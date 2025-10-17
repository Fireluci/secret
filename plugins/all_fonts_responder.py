# liz/plugins/all_fonts_responder.py
from pyrogram import Client, filters
from normalize_text import normalize_fancy_text

@Client.on_message(filters.text & ~filters.edited)
async def reply_to_any_font(_, message):
    text = message.text
    plain = normalize_fancy_text(text)

    # Example responses — change them as you like
    if "hello" in plain:
        await message.reply_text("👋 Hi there! (I understood your fancy font!)")
    elif "help" in plain:
        await message.reply_text("🛠 Send me any text — I’ll understand all fonts.")
    else:
        await message.reply_text(f"You said: {plain}")
