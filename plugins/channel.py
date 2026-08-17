from pyrogram import Client, filters

from info import CHANNELS, CAPTION_INDEX_CHANNEL
from database.ia_filterdb import save_file

media_filter = filters.document | filters.video | filters.audio
index_channels = list(dict.fromkeys([*CHANNELS, CAPTION_INDEX_CHANNEL]))


@Client.on_message(filters.chat(index_channels) & media_filter)
async def media(bot, message):
    """Index media from configured channels."""
    for file_type in ("document", "video", "audio"):
        media = getattr(message, file_type, None)
        if media is not None:
            break
    else:
        return

    media.file_type = file_type
    media.caption = message.caption
    media.chat_id = message.chat.id
    await save_file(media)
