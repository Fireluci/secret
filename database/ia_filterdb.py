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
    words = fields.ListField(fields.StrField())
    file_size = fields.IntField(required=True)
    file_type = fields.StrField(allow_none=True)
    mime_type = fields.StrField(allow_none=True)

    class Meta:
        collection_name = COLLECTION_NAME
        indexes = ["words"]


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
    normalized_words = normalized_name.split()

    try:
        file = Media(
            file_id=file_id,
            file_ref=file_ref,
            file_name=normalized_name,
            words=normalized_words,
            file_size=media.file_size,
            file_type=media.file_type,
            mime_type=media.mime_type,
        )
        await file.commit()
    except ValidationError:
        logger.exception("Validation error while saving file")
        return False, 2
    except DuplicateKeyError:
        if (
            getattr(media, "chat_id", None) == CAPTION_INDEX_CHANNEL
            and getattr(media, "caption", None)
        ):
            try:
                await Media.collection.update_one(
                    {"_id": file_id},
                    {"$set": {"file_name": normalized_name, "words": normalized_words}},
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

    # Exact matches: every query word must exist as an exact word.
    exact_filter = {
        **base_filter,
        "words": {"$all": words},
    }

    # Prefix matches: every query word must prefix-match a word.
    # Exact matches are excluded so they only appear in the exact section.
    prefix_filter = {
        **base_filter,
        "$and": [
            {"words": {"$regex": f"^{re.escape(word)}"}}
            for word in words
        ],
        "$nor": [exact_filter],
    }

    exact_total, prefix_total = await asyncio.gather(
        Media.count_documents(exact_filter),
        Media.count_documents(prefix_filter),
    )

    total_results = exact_total + prefix_total
    if total_results == 0:
        return [], "", 0

    # Exact results always come first. If the requested page reaches the
    # end of exact results, fill the rest of the page from prefix results.
    files = []

    if offset < exact_total:
        exact_cursor = (
            Media.find(exact_filter)
            .sort("$natural", -1)
            .skip(offset)
            .limit(max_results)
        )
        files = await exact_cursor.to_list(length=max_results)

        remaining = max_results - len(files)
        if remaining > 0 and offset + len(files) >= exact_total:
            prefix_cursor = (
                Media.find(prefix_filter)
                .sort("$natural", -1)
                .limit(remaining)
            )
            files.extend(await prefix_cursor.to_list(length=remaining))
    else:
        prefix_offset = offset - exact_total
        prefix_cursor = (
            Media.find(prefix_filter)
            .sort("$natural", -1)
            .skip(prefix_offset)
            .limit(max_results)
        )
        files = await prefix_cursor.to_list(length=max_results)

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
