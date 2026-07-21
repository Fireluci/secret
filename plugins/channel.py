from pyrogram import Client, filters
from info import CHANNELS, CAPTION_INDEX_CHANNEL
from database.ia_filterdb import save_file
from plugins.caption_edit import clean_caption

media_filter = filters.document | filters.video  

@Client.on_message(filters.chat(CHANNELS) & media_filter)
async def media(bot, message):
    for file_type in ("document", "video"):
        media = getattr(message, file_type, None)
        if media:
            break
    else:
        return

    if message.chat.id == CAPTION_INDEX_CHANNEL:
        new_caption = clean_caption(message.caption or media.file_name)
        if new_caption != (message.caption or ""):
            try:
                await message.edit_caption(new_caption)
                message.caption = new_caption
            except Exception:
                pass

    media.file_type = file_type
    media.caption = message.caption
    media.chat_id = message.chat.id

    await save_file(media)
