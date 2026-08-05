import logging
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait
from database.users_chats_db import db
from info import ADMINS

logger = logging.getLogger(__name__)

@Client.on_message(filters.command('stats') & filters.user(ADMINS))
async def get_stats(client, message):
    r_msg = await message.reply_text("<b>⚡ Fetching database statistics...</b>")
    total_users = await db.total_users_count()
    total_chats = await db.total_chat_count()
    try:
        db_size = await db.get_db_size()
        free_space = 524288000 - db_size  # 500MB free tier standard baseline
        if free_space < 0:
            free_space = 0
        db_size_mb = f"{db_size / 1024 / 1024:.2f} MB"
        free_space_mb = f"{free_space / 1024 / 1024:.2f} MB"
    except Exception:
        db_size_mb = "N/A"
        free_space_mb = "N/A"

    text = (
        f"<b>📊 Bot Statistics Status:\n\n"
        f"• 👤 Total Users: <code>{total_users}</code>\n"
        f"• 👥 Total Connected Chats: <code>{total_chats}</code>\n"
        f"• 💾 Database Storage Used: <code>{db_size_mb}</code>\n"
        f"• 🗄️ Database Free Space: <code>{free_space_mb}</code></b>"
    )
    await r_msg.edit_text(text)

@Client.on_message(filters.command('ban') & filters.user(ADMINS))
async def ban_user_handler(client, message):
    if len(message.command) < 2:
        return await message.reply_text("<b>⚠️ Usage: /ban [user_id] [reason]</b>")
    try:
        user_id = int(message.command[1])
        reason = " ".join(message.command[2:]) if len(message.command) > 2 else "No Reason Provided"
        await db.ban_user(user_id, reason)
        await message.reply_text(f"<b>✅ Successfully banned user <code>{user_id}</code>\n• Reason: {reason}</b>")
    except Exception as e:
        await message.reply_text(f"<b>❌ Error: <code>{e}</code></b>")

@Client.on_message(filters.command('unban') & filters.user(ADMINS))
async def unban_user_handler(client, message):
    if len(message.command) < 2:
        return await message.reply_text("<b>⚠️ Usage: /unban [user_id]</b>")
    try:
        user_id = int(message.command[1])
        await db.remove_ban(user_id)
        await message.reply_text(f"<b>✅ Successfully unbanned user <code>{user_id}</code></b>")
    except Exception as e:
        await message.reply_text(f"<b>❌ Error: <code>{e}</code></b>")

@Client.on_message(filters.command('chats') & filters.user(ADMINS))
async def get_chats_handler(client, message):
    r_msg = await message.reply_text("<b>⚡ Fetching connected chats list...</b>")
    chats = await db.get_all_chats()
    text = "<b>👥 Connected Chats List:\n\n</b>"
    count = 0
    async for chat in chats:
        count += 1
        title = chat.get('title', 'Unknown')
        cid = chat.get('id', 'N/A')
        status = chat.get('chat_status', {})
        disabled = status.get('is_disabled', False)
        state = "🔴 Disabled" if disabled else "🟢 Active"
        text += f"<b>{count}. {title}</b>\n   • ID: <code>{cid}</code>\n   • Status: {state}\n\n"
    
    if count == 0:
        text = "<b>❌ No connected chats found.</b>"
        
    if len(text) > 4096:
        file = 'connected_chats.txt'
        with open(file, 'w', encoding='utf-8') as f:
            f.write(text)
        await message.reply_document(file)
        await r_msg.delete()
    else:
        await r_msg.edit_text(text)
