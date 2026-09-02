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


async def normalize_for_search(text: str) -> str:
    return " ".join(normalize(await extract_v2(text)))


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
        return [], 0, 0

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

    # Fuzzy: every search term only needs to occur somewhere inside the filename.
    fuzzy_conditions = [
        {
            "file_name": {
                "$regex": re.escape(word),
                "$options": "i",
            }
        }
        for word in words
    ]
    fuzzy_filter = {**base_filter, "$and": fuzzy_conditions}

    # Run both searches independently, then prioritize strict matches.
    strict_cursor = Media.find(strict_filter).sort("$natural", -1)
    fuzzy_cursor = Media.find(fuzzy_filter).sort("$natural", -1)
    strict_files, fuzzy_files = await asyncio.gather(
        strict_cursor.to_list(length=100),
        fuzzy_cursor.to_list(length=100),
    )

    seen_ids = set()
    combined_files = []

    for file in strict_files + fuzzy_files:
        file_id = getattr(file, "file_id", None)
        if not file_id:
            file_id = str(getattr(file, "_id", ""))
        if file_id and file_id not in seen_ids:
            seen_ids.add(file_id)
            combined_files.append(file)

    total_results = len(combined_files)
    if total_results == 0:
        return [], 0, 0

    paginated_files = combined_files[offset:offset + max_results]
    next_offset = offset + len(paginated_files)
    if next_offset >= total_results:
        next_offset = ""

    return paginated_files, next_offset, total_results


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
