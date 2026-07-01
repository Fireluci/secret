from pyrogram import Client, filters

from info import CAPTION_INDEX_CHANNEL

from database.ia_filterdb import (
    Media,
    normalize,
    normalize_basic_episode,
    unpack_new_file_id
)

import logging

logger = logging.getLogger(__name__)


@Client.on_edited_message(filters.chat(CAPTION_INDEX_CHANNEL))
async def caption_edit_handler(client, message):

    media = (
        message.document
        or message.video
        or message.audio
    )

    if not media:
        return

    # caption removed -> fallback filename
    source_text = (
        message.caption
        if message.caption
        else media.file_name
    )

    source_text = source_text[:1000]

    # searchable normalized text
    tmp = normalize_basic_episode(source_text)

    normalized_name = " ".join(normalize(tmp))

    # display normalized text
    display_name = " ".join(
        word.capitalize()
        for word in normalize(tmp)
    )

    try:

        file_id, _ = unpack_new_file_id(media.file_id)

        await Media.collection.update_one(
            {"_id": file_id},
            {
                "$set": {
                    "file_name": normalized_name,
                    "display_name": display_name,
                    "caption": message.caption if message.caption else None
                }
            }
        )

        logger.info(f"Caption updated for {file_id}")

    except Exception:
        logger.exception("Failed updating caption edit")

