import asyncio
import logging
import re
import base64
from struct import pack

from pymongo.errors import DuplicateKeyError
from umongo import Instance, Document, fields
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram.file_id import FileId
from marshmallow.exceptions import ValidationError

from info import DATABASE_URI, DATABASE_NAME, COLLECTION_NAME, CAPTION_INDEX_CHANNEL
from utils import extract_v2

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

client = AsyncIOMotorClient(DATABASE_URI)
db = client[DATABASE_NAME]
instance = Instance.from_db(db)


def normalize(text: str) -> list:
    text = text.casefold()
    text = re.sub(r"@[^\s.-]+", " ", text)
    text = re.sub(r"[_]+", " ", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text.split()


def normalize_basic_episode(text: str) -> str:
    text = text.casefold()
    text = re.sub(r'\bs(\d{2})\s*e(\d{2})\b', r's\1e\2', text)
    text = re.sub(r'\bs(\d{2})\s*ep(\d{2})\b', r's\1e\2', text)
    text = re.sub(r'\bs(\d{2})\s*ep\s*(\d{2})\b', r's\1e\2', text)
    return text


async def normalize_for_search(text: str) -> str:
    # Saving/indexing uses basic episode normalization + normalize().
    # extract_v2() is reserved for user search queries.
    text = normalize_basic_episode(str(text or ""))
    return " ".join(normalize(text))


@instance.register
class Media(Document):
    file_id = fields.StrField(attribute="_id")
    file_ref = fields.StrField(allow_none=True)
    file_name = fields.StrField(required=True)
    file_size = fields.IntField(required=True)
    file_type = fields.StrField(allow_none=True)
    mime_type = fields.StrField(allow_none=True)

    class Meta:
        collection_name = COLLECTION_NAME
        indexes = ["$file_name"]


async def save_file(media):
    file_id, file_ref = unpack_new_file_id(media.file_id)

    original_name = str(media.file_name or "")
    source_text = original_name

    if (
        getattr(media, "chat_id", None) == CAPTION_INDEX_CHANNEL
        and getattr(media, "caption", None)
    ):
        source_text = media.caption

    source_text = str(source_text)[:1000]
    normalized_name = await normalize_for_search(source_text)

    try:
        file = Media(
            file_id=file_id,
            file_ref=file_ref,
            file_name=normalized_name,
            file_size=media.file_size,
            file_type=media.file_type,
            mime_type=media.mime_type,
        )
        await file.commit()
    except ValidationError:
        logger.exception("Validation error while saving file")
        return False, 2
    except DuplicateKeyError:
        if getattr(media, "chat_id", None) == CAPTION_INDEX_CHANNEL and getattr(media, "caption", None):
            try:
                await Media.collection.update_one(
                    {"_id": file_id},
                    {"$set": {"file_name": normalized_name}},
                )
                logger.info("%s updated using caption indexing", original_name)
                return True, 1
            except Exception:
                logger.exception("Failed updating duplicate file")
        return False, 0

    logger.info("%s indexed", original_name)
    return True, 1


async def get_search_results(
    chat_id,
    query,
    file_type=None,
    max_results=10,
    offset=0,
    **kwargs,
):
    max_results = 10

    try:
        offset = int(offset)
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, offset)

    query = (await extract_v2(query)).strip()
    words = normalize(query)

    if not words:
        return [], "", 0

    base_filter = {}
    if file_type:
        base_filter["file_type"] = file_type

    # Strict: every search term must exist as a complete filename word.
    strict_conditions = [
        {
            "file_name": {
                "$regex": rf"\b{re.escape(word)}\b",
                "$options": "i",
            }
        }
        for word in words
    ]
    strict_filter = {**base_filter, "$and": strict_conditions}

    # Fuzzy: every search term may occur anywhere inside the filename.
    # Strict matches are excluded here so a file is never shown twice.
    fuzzy_conditions = [
        {
            "file_name": {
                "$regex": re.escape(word),
                "$options": "i",
            }
        }
        for word in words
    ]
    fuzzy_filter = {
        **base_filter,
        "$and": fuzzy_conditions,
        "$nor": [{"$and": strict_conditions}],
    }

    # Get the sizes of both sections concurrently. We need the exact total
    # because the existing UI displays Pages X/Y and uses next_offset.
    strict_count_task = Media.count_documents(strict_filter)
    fuzzy_count_task = Media.count_documents(fuzzy_filter)
    strict_total, fuzzy_total = await asyncio.gather(
        strict_count_task,
        fuzzy_count_task,
    )

    total_results = strict_total + fuzzy_total

    if total_results == 0 or offset >= total_results:
        return [], "", total_results

    # The result list is logically:
    #   [all strict matches] + [all fuzzy-only matches]
    # Fetch only the 10 records needed for this page.
    if offset < strict_total:
        strict_cursor = (
            Media.find(strict_filter)
            .sort("$natural", -1)
            .skip(offset)
            .limit(max_results)
        )
        files = await strict_cursor.to_list(length=max_results)

        # If the page crosses the strict/fuzzy boundary, fill the remaining
        # slots from the beginning of the fuzzy-only section.
        if len(files) < max_results and offset + len(files) < total_results:
            remaining = max_results - len(files)
            fuzzy_cursor = (
                Media.find(fuzzy_filter)
                .sort("$natural", -1)
                .skip(0)
                .limit(remaining)
            )
            fuzzy_files = await fuzzy_cursor.to_list(length=remaining)
            files.extend(fuzzy_files)
    else:
        fuzzy_offset = offset - strict_total
        fuzzy_cursor = (
            Media.find(fuzzy_filter)
            .sort("$natural", -1)
            .skip(fuzzy_offset)
            .limit(max_results)
        )
        files = await fuzzy_cursor.to_list(length=max_results)

    next_offset = offset + len(files)
    if next_offset >= total_results:
        next_offset = ""

    return files, next_offset, total_results


async def get_bad_files(query, file_type=None, **kwargs):
    words = normalize(query)
    mongo_filter = (
        {"$and": [{"file_name": {"$regex": re.escape(word), "$options": "i"}} for word in words]}
        if words else {}
    )
    if file_type:
        mongo_filter["file_type"] = file_type

    cursor = Media.find(mongo_filter).sort("$natural", -1)
    files = await cursor.to_list(length=100)
    return files, len(files)


async def get_file_details(file_id):
    return await Media.find({"_id": file_id}).to_list(length=1)


def encode_file_id(s: bytes) -> str:
    r = b""
    n = 0
    for i in s + bytes([22]) + bytes([4]):
        if i == 0:
            n += 1
        else:
            if n:
                r += b"\x00" + bytes([n])
                n = 0
            r += bytes([i])
    return base64.urlsafe_b64encode(r).decode().rstrip("=")


def encode_file_ref(file_ref: bytes) -> str:
    return base64.urlsafe_b64encode(file_ref).decode().rstrip("=")


def unpack_new_file_id(new_file_id):
    decoded = FileId.decode(new_file_id)
    file_id = encode_file_id(
        pack(
            "<iiqq",
            int(decoded.file_type),
            decoded.dc_id,
            decoded.media_id,
            decoded.access_hash,
        )
    )
    file_ref = encode_file_ref(decoded.file_reference)
    return file_id, file_ref
