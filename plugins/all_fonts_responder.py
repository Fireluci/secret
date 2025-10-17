from pyrogram import Client, filters
from normalize_text import normalize_fancy_text  # ✅ your existing normalize_text.py

@Client.on_message(filters.text)
async def all_fonts_responder(_, message):
    # Convert fancy text to normal
    plain = normalize_fancy_text(message.text)
    
    # Reply to the message, always
    await message.reply_text(f"🗣 {plain}")
