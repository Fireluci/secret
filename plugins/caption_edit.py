from pyrogram import Client, filters

from info import CAPTION_INDEX_CHANNEL
from database.ia_filterdb import Media, normalize_for_search, unpack_new_file_id

import logging

logger = logging.getLogger(__name__)


@Client.on_edited_message(filters.chat(CAPTION_INDEX_CHANNEL))
async def caption_edit_handler(client, message):
    media = message.document or message.video or message.audio
    if not media:
        return

    source_text = (message.caption or getattr(media, "file_name", "") or "")[:1000]

    try:
        file_id, _ = unpack_new_file_id(media.file_id)
        normalized_name = await normalize_for_search(source_text)

        result = await Media.collection.update_one(
            {"_id": file_id},
            {"$set": {"file_name": normalized_name}},
        )

        if result.matched_count:
            logger.info("Caption index updated for %s", file_id)
    except Exception:
        logger.exception("Failed updating caption index")
