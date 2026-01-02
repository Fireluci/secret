import logging
import re
import base64
from struct import pack

from pyrogram.file_id import FileId
from pymongo.errors import DuplicateKeyError
from umongo import Instance, Document, fields
from motor.motor_asyncio import AsyncIOMotorClient
from marshmallow.exceptions import ValidationError

from info import DATABASE_URI, DATABASE_NAME, COLLECTION_NAME, USE_CAPTION_FILTER, MAX_B_TN
from utils import get_settings, save_group_settings

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

client = AsyncIOMotorClient(DATABASE_URI)
db = client[DATABASE_NAME]
instance = Instance.from_db(db)

# =========================================================
# NORMALIZATION (CORE FIX)
# =========================================================

def normalize(text: str) -> list[str]:
    text = text.lower()
    text = re.sub(r"[()\[\]{}]", " ", text)      # remove brackets, keep content
    text = re.sub(r"[^a-z0-9\s]", " ", text)     # remove symbols
    text = re.sub(r"\s+", " ", text).strip()     # collapse spaces
    return text.split()

# =========================================================
# DATABASE MODEL
# =========================================================

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

# =========================================================
# SAVE FILE (CLEAN INDEXING)
# =========================================================

async def save_file(media):
    file_id, file_ref = unpack_new_file_id(media.file_id)

    # normalize filename ONCE at index time
    file_name = " ".join(normalize(str(media.file_name)))

    try:
        file = Media(
            file_id=file_id,
            file_ref=file_ref,
            file_name=file_name,
            file_size=media.file_size,
            file_type=media.file_type,
            mime_type=media.mime_type,
            caption=media.caption.html if media.caption else None,
        )
    except ValidationError:
        logger.exception("Validation error while saving file")
        return False, 2

    try:
        await file.commit()
    except DuplicateKeyError:
        logger.warning(f"{media.file_name} already exists")
        return False, 0

    logger.info(f"{media.file_name} indexed")
    return True, 1

# =========================================================
# SEARCH (FAST, BACKWARD-COMPATIBLE)
# =========================================================

async def get_search_results(
    chat_id,
    query,
    file_type=None,
    max_results=10,
    offset=0,
    filter=False,     # <-- legacy arg (IGNORED)
    **kwargs          # <-- catch any future bullshit safely
):
    if chat_id is not None:
        settings = await get_settings(int(chat_id))
        try:
            max_results = 10 if settings.get("max_btn") else int(MAX_B_TN)
        except Exception:
            await save_group_settings(int(chat_id), "max_btn", False)
            max_results = int(MAX_B_TN)

    words = normalize(query)

    if not words:
        mongo_filter = {}
    else:
        mongo_filter = {
            "$and": [
                {"file_name": {"$regex": rf"\b{re.escape(w)}\b", "$options": "i"}}
                for w in words
            ]
        }

    if USE_CAPTION_FILTER:
        mongo_filter = {
            "$or": [
                mongo_filter,
                {"caption": mongo_filter.get("$and")}
            ]
        }

    if file_type:
        mongo_filter["file_type"] = file_type

    cursor = Media.find(mongo_filter)
    cursor.sort("$natural", -1)
    cursor.skip(offset).limit(max_results)

    files = await cursor.to_list(length=max_results)
    next_offset = offset + max_results if len(files) == max_results else ""

    return files, next_offset, None

# =========================================================
# BAD FILE SEARCH (ADMIN)
# =========================================================

async def get_bad_files(query, file_type=None, filter=False, **kwargs):
    words = normalize(query)

    if not words:
        mongo_filter = {}
    else:
        mongo_filter = {
            "$and": [
                {"file_name": {"$regex": rf"\b{re.escape(w)}\b", "$options": "i"}}
                for w in words
            ]
        }

    if file_type:
        mongo_filter["file_type"] = file_type

    cursor = Media.find(mongo_filter)
    cursor.sort("$natural", -1)

    files = await cursor.to_list(length=None)
    return files, len(files)

# =========================================================
# FILE DETAILS
# =========================================================

async def get_file_details(file_id):
    cursor = Media.find({"_id": file_id})
    return await cursor.to_list(length=1)

# =========================================================
# FILE ID UTILS (UNCHANGED)
# =========================================================

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
            decoded.access_hash
        )
    )
    file_ref = encode_file_ref(decoded.file_reference)
    return file_id, file_ref
