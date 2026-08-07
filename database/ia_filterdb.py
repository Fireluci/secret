import logging
import re
import base64
from struct import pack
from pyrogram import Client, filters
from pyrogram.file_id import FileId
from pymongo.errors import DuplicateKeyError
from umongo import Instance, Document, fields
from motor.motor_asyncio import AsyncIOMotorClient
from marshmallow.exceptions import ValidationError
from info import DATABASE_URI, DATABASE_NAME, COLLECTION_NAME, CAPTION_INDEX_CHANNEL
from utils import extract_v2

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

client = AsyncIOMotorClient(DATABASE_URI)
db = client[DATABASE_NAME]
instance = Instance.from_db(db)

def normalize(text: str) -> list:
    text = text.lower()
    text = re.sub(r'@[^\s\.-]+', ' ', text)
    text = re.sub(r"[()\[\]{}]", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.split()

def normalize_basic_episode(text: str) -> str:
    text = text.lower()
    text = re.sub(r'\bs(\d{2})\s*e(\d{2})\b', r's\1e\2', text)
    text = re.sub(r'\bs(\d{2})\s*ep(\d{2})\b', r's\1e\2', text)
    text = re.sub(r'\bs(\d{2})\s*ep\s*(\d{2})\b', r's\1e\2', text)
    return text

@instance.register
class Media(Document):
    file_id = fields.StrField(attribute="_id")
    file_ref = fields.StrField(allow_none=True)
    file_name = fields.StrField(required=True)
    file_size = fields.IntField(required=True)
    file_type = fields.StrField(allow_none=True)
    mime_type = fields.StrField(allow_none=True)
    caption = fields.StrField(allow_none=True)

    class Meta:
        collection_name = COLLECTION_NAME
        indexes = ["$file_name"]

async def save_file(media):
    file_id, file_ref = unpack_new_file_id(media.file_id)
    original_name = str(media.file_name)
    source_text = original_name
    try:
        if hasattr(media, "chat_id") and media.chat_id == CAPTION_INDEX_CHANNEL and media.caption:
            source_text = media.caption
    except Exception:
        pass
    source_text = source_text[:1000]
    tmp = normalize_basic_episode(source_text)
    normalized_name = " ".join(normalize(tmp))
    try:
        file = Media(
            file_id=file_id,
            file_ref=file_ref,
            file_name=normalized_name,
            file_size=media.file_size,
            file_type=media.file_type,
            mime_type=media.mime_type,
            caption=media.caption if media.caption else None,
        )
    except ValidationError:
        logger.exception("Validation error while saving file")
        return False, 2
    try:
        await file.commit()
    except DuplicateKeyError:
        try:
            if hasattr(media, "chat_id") and media.chat_id == CAPTION_INDEX_CHANNEL and media.caption:
                await Media.collection.update_one(
                    {"_id": file_id},
                    {"$set": {"file_name": normalized_name, "caption": media.caption}}
                )
                logger.info(f"{original_name} updated using caption indexing")
                return True, 1
        except Exception:
            logger.exception("Failed updating duplicate file")
        logger.warning(f"{original_name} already exists")
        return False, 0
    logger.info(f"{original_name} indexed")
    return True, 1

async def get_search_results(chat_id, query, file_type=None, max_results=10, offset=0, filter=False, **kwargs):
    max_results = 10

    query = await extract_v2(query)
    query = query.strip()
    words = normalize(query)

    if not words:
        strict_filter = {}
        loose_filter = {}
    else:
        strict_conditions = [{"file_name": {"$regex": rf"\b{re.escape(w)}\b", "$options": "i"}} for w in words]
        strict_filter = {"$and": strict_conditions}

        loose_conditions = [{"file_name": {"$regex": re.escape(w), "$options": "i"}} for w in words]
        loose_filter = {"$and": loose_conditions}

    if file_type:
        if words:
            strict_filter["file_type"] = file_type
            loose_filter["file_type"] = file_type
        else:
            strict_filter = {"file_type": file_type}
            loose_filter = {"file_type": file_type}

    strict_count = await Media.collection.count_documents(strict_filter)
    strict_ids = await Media.collection.distinct("_id", strict_filter)

    loose_filter_with_exclude = dict(loose_filter)
    if strict_ids:
        loose_filter_with_exclude["_id"] = {"$nin": strict_ids}

    loose_count = await Media.collection.count_documents(loose_filter_with_exclude)
    total_results = strict_count + loose_count

    try:
        offset = int(offset)
    except (TypeError, ValueError):
        offset = 0

    files = []
    if offset < strict_count:
        cursor = Media.find(strict_filter).sort("$natural", -1).skip(offset).limit(max_results)
        files = await cursor.to_list(length=max_results)
    else:
        strict_pages = (strict_count + max_results - 1) // max_results if strict_count > 0 else 0
        page_idx = offset // max_results
        loose_page_idx = max(0, page_idx - strict_pages)
        loose_skip = loose_page_idx * max_results

        cursor = Media.find(loose_filter_with_exclude).sort("$natural", -1).skip(loose_skip).limit(max_results)
        files = await cursor.to_list(length=max_results)

    next_offset = offset + max_results
    if next_offset >= total_results:
        next_offset = ""

    return files, next_offset, total_results

async def get_bad_files(query, file_type=None, filter=False, **kwargs):
    words = normalize(query)
    if words:
        mongo_filter = {"$and": [{"file_name": {"$regex": re.escape(w), "$options": "i"}} for w in words]}
    else:
        mongo_filter = {}
    if file_type:
        mongo_filter["file_type"] = file_type
    cursor = Media.find(mongo_filter).sort("$natural", -1)
    files = await cursor.to_list(length=100)
    return files, len(files)

async def get_file_details(file_id):
    cursor = Media.find({"_id": file_id})
    return await cursor.to_list(length=1)

async def ensure_indexes():
    try:
        # Creates a text index shortcut on the 'file_name' field
        await Media.collection.create_index([("file_name", "text")])
    except Exception as e:
        print(f"Index creation error: {e}")

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
    file_id = encode_file_id(pack("<iiqq", int(decoded.file_type), decoded.dc_id, decoded.media_id, decoded.access_hash))
    file_ref = encode_file_ref(decoded.file_reference)
    return file_id, file_ref
