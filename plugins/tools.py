import asyncio
import time
import datetime
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database.users_chats_db import db
from info import ADMINS
from utils import broadcast_messages, broadcast_messages_group, connected_group
import logging
from pyrogram import Client, filters, enums
from pyrogram.errors.exceptions.bad_request_400 import MessageTooLong, PeerIdInvalid
from database.ia_filterdb import Media
from info import *
from utils import connected_group, get_size
import os
import re
import sys
from pyrogram.errors import FloodWait
from database.ia_filterdb import Media, get_file_details, unpack_new_file_id, get_bad_files
from utils import get_settings, get_size, is_subscribed, save_group_settings, temp, get_shortlink, is_group_connected

# ==================== BROADCAST.PY ====================

BROADCAST_CANCEL = set()

@Client.on_message(
    filters.command("broadcast") & filters.user(ADMINS) & filters.reply & connected_group
)
async def broadcast_users(bot, message):
    b_msg = message.reply_to_message
    total_users = await db.total_users_count()
    admin_id = message.from_user.id
    BROADCAST_CANCEL.discard(admin_id)

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel Broadcast", callback_data=f"cancel_broadcast#{admin_id}")]
    ])

    sts = await message.reply_text(
        f"📢 <b>Broadcast Started</b>\n\n"
        f"👥 Total Users: {total_users}",
        reply_markup=markup,
    )

    success = 0
    async for user in db.get_all_users():
        if admin_id in BROADCAST_CANCEL:
            break

        sent, _ = await broadcast_messages(int(user["id"]), b_msg)
        if sent:
            success += 1

        if success and success % 20 == 0:
            await sts.edit_text(
                f"📢 <b>Broadcasting...</b>\n\n"
                f"👥 Total Users: {total_users}\n"
                f"✅ Sent: {success}",
                reply_markup=markup,
            )

    cancelled = admin_id in BROADCAST_CANCEL
    BROADCAST_CANCEL.discard(admin_id)

    if cancelled:
        await sts.edit_text(
            f"🛑 <b>Broadcast Cancelled</b>\n\n"
            f"👥 Total Users: {total_users}\n"
            f"✅ Successful: {success}"
        )
    else:
        await sts.edit_text(
            f"✅ <b>Broadcast Completed</b>\n\n"
            f"👥 Total Users: {total_users}\n"
            f"✅ Successful: {success}"
        )

@Client.on_message(
    filters.command("grp_broadcast") & filters.user(ADMINS) & filters.reply & connected_group
)
async def broadcast_groups(bot, message):
    b_msg = message.reply_to_message
    total_groups = await db.total_chat_count()
    admin_id = message.from_user.id
    BROADCAST_CANCEL.discard(admin_id)

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel Broadcast", callback_data=f"cancel_group_broadcast#{admin_id}")]
    ])

    sts = await message.reply_text(
        f"📢 <b>Group Broadcast Started</b>\n\n"
        f"👥 Total Groups: {total_groups}",
        reply_markup=markup,
    )

    success = 0
    async for group in db.get_all_chats():
        if admin_id in BROADCAST_CANCEL:
            break

        sent, _ = await broadcast_messages_group(int(group["id"]), b_msg)
        if sent:
            success += 1

        if success and success % 20 == 0:
            await sts.edit_text(
                f"📢 <b>Broadcasting...</b>\n\n"
                f"👥 Total Groups: {total_groups}\n"
                f"✅ Sent: {success}",
                reply_markup=markup,
            )

    cancelled = admin_id in BROADCAST_CANCEL
    BROADCAST_CANCEL.discard(admin_id)

    if cancelled:
        await sts.edit_text(
            f"🛑 <b>Group Broadcast Cancelled</b>\n\n"
            f"👥 Total Groups: {total_groups}\n"
            f"✅ Successful: {success}"
        )
    else:
        await sts.edit_text(
            f"✅ <b>Group Broadcast Completed</b>\n\n"
            f"👥 Total Groups: {total_groups}\n"
            f"✅ Successful: {success}"
        )

@Client.on_callback_query(filters.regex(r"^cancel_broadcast#"))
async def cancel_broadcast(bot, query):
    try:
        _, admin_id = query.data.split("#", 1)
        admin_id = int(admin_id)
    except ValueError:
        return await query.answer("Invalid request.", show_alert=True)

    if query.from_user.id != admin_id:
        return await query.answer("This is not your broadcast.", show_alert=True)

    BROADCAST_CANCEL.add(admin_id)
    await query.answer("🛑 Broadcast cancelling...")

@Client.on_callback_query(filters.regex(r"^cancel_group_broadcast#"))
async def cancel_group_broadcast(bot, query):
    try:
        _, admin_id = query.data.split("#", 1)
        admin_id = int(admin_id)
    except ValueError:
        return await query.answer("Invalid request.", show_alert=True)

    if query.from_user.id != admin_id:
        return await query.answer("This is not your broadcast.", show_alert=True)

    BROADCAST_CANCEL.add(admin_id)
    await query.answer("🛑 Broadcast cancelling...")

# ==================== P_TTISHOW.PY ====================

@Client.on_message(filters.command("stats") & filters.incoming & filters.user(ADMINS) & connected_group)
async def get_stats(bot, message):
    reply = await message.reply("Fetching stats...")
    total_users = await db.total_users_count()
    total_chats = await db.total_chat_count()
    files = await Media.count_documents()
    size = await db.get_db_size()
    await reply.edit(
        STATUS_TXT.format(
            files,
            total_users,
            total_chats,
            get_size(size),
            get_size(max(0, 536870912 - size)),
        )
    )

@Client.on_message(filters.command("ban") & filters.user(ADMINS) & connected_group)
async def ban_user(bot, message):
    if len(message.command) == 1:
        return await message.reply("Give me a user id / username")

    target = message.command[1]
    reason = message.text.split(None, 2)[2] if len(message.text.split(None, 2)) > 2 else "No reason provided"

    try:
        user = await bot.get_users(int(target) if target.lstrip("-").isdigit() else target)
    except PeerIdInvalid:
        return await message.reply("Invalid user.")
    except Exception as e:
        return await message.reply(f"Error - {e}")

    status = await db.get_ban_status(user.id)
    if status["is_banned"]:
        return await message.reply(f"{user.mention} is already banned.")

    await db.ban_user(user.id, reason)
    try:
        await message.reply(f"Successfully banned {user.mention}")
    except Exception:
        pass

@Client.on_message(filters.command("unban") & filters.user(ADMINS) & connected_group)
async def unban_user(bot, message):
    if len(message.command) == 1:
        return await message.reply("Give me a user id / username")

    target = message.command[1]
    try:
        user = await bot.get_users(int(target) if target.lstrip("-").isdigit() else target)
    except Exception as e:
        return await message.reply(f"Error - {e}")

    status = await db.get_ban_status(user.id)
    if not status["is_banned"]:
        return await message.reply(f"{user.mention} is not banned.")

    await db.remove_ban(user.id)
    await message.reply(f"Successfully unbanned {user.mention}")

@Client.on_message(filters.command("users") & filters.user(ADMINS) & connected_group)
async def list_users(bot, message):
    reply = await message.reply("Getting user list...")
    out = "Users Saved In DB Are:\n\n"

    users = await db.get_all_users()
    async for user in users:
        out += f'<a href="tg://user?id={user["id"]}">{user["name"]}</a>'
        if user.get("ban_status", {}).get("is_banned"):
            out += " (Banned User)"
        out += "\n"

    try:
        await reply.edit_text(out)
    except MessageTooLong:
        with open("users.txt", "w", encoding="utf-8") as outfile:
            outfile.write(out)
        await message.reply_document("users.txt", caption="List Of Users")

@Client.on_message(filters.command("chats") & filters.user(ADMINS) & connected_group)
async def list_chats(bot, message):
    reply = await message.reply("Getting list of chats...")
    out = "Connected Chats:\n\n"

    chats = await db.get_all_chats()
    async for chat in chats:
        out += f'**Title:** `{chat.get("title", "Unknown")}`\n**ID:** `{chat["id"]}`\n\n'

    try:
        await reply.edit_text(out)
    except MessageTooLong:
        with open("chats.txt", "w", encoding="utf-8") as outfile:
            outfile.write(out)
        await message.reply_document("chats.txt", caption="Connected Chats")

# ==================== COMMANDS.PY (MOVED) ====================

@Client.on_message(filters.command('channel') & filters.user(ADMINS))
async def channel_info(bot, message):
    channels = CHANNELS if isinstance(CHANNELS, list) else [CHANNELS]
    text = '📑 **Indexed channels/groups**\n'
    for channel in channels:
        try:
            chat = await bot.get_chat(channel)
            text += '\n@' + chat.username if chat.username else '\n' + (chat.title or chat.first_name)
        except Exception:
            continue
    text += f'\n\n**Total:** {len(channels)}'
    await message.reply(text)

@Client.on_message(filters.command('delete') & filters.user(ADMINS))
async def delete(bot, message):
    reply = message.reply_to_message
    if not reply or not reply.media:
        return await message.reply('Reply to file with /delete which you want to delete', quote=True)

    msg = await message.reply("Processing...⏳", quote=True)
    for file_type in ("document", "video", "audio"):
        media = getattr(reply, file_type, None)
        if media is not None:
            break
    else:
        return await msg.edit('This is not supported file format')

    file_id, _ = unpack_new_file_id(media.file_id)
    result = await Media.collection.delete_one({'_id': file_id})
    if result.deleted_count:
        return await msg.edit('🛃 Deleted File!')

    file_name = re.sub(r"(_|\-|\.|\+)", " ", str(media.file_name))
    result = await Media.collection.delete_many({'file_name': file_name, 'file_size': media.file_size, 'mime_type': media.mime_type})
    if result.deleted_count:
        return await msg.edit('🛃 Deleted File!')

    result = await Media.collection.delete_many({'file_name': media.file_name, 'file_size': media.file_size, 'mime_type': media.mime_type})
    await msg.edit('🛃 Deleted File!' if result.deleted_count else 'File not found in database')

@Client.on_message(filters.command("deletefiles") & filters.user(ADMINS))
async def deletemultiplefiles(bot, message):
    if message.chat.type != enums.ChatType.PRIVATE:
        return await message.reply_text("<b>Only Works in PM !</b>")
    try:
        keyword = message.text.split(" ", 1)[1]
    except Exception:
        return await message.reply_text(f"<b>Hey {message.from_user.mention}, Give me a keyword along with the command to delete files.</b>")
    k = await bot.send_message(chat_id=message.chat.id, text="<b>♻️ Please Wait!</b>")
    files, total = await get_bad_files(keyword)
    await k.delete()
    await message.reply_text(
        text=f"<b>{total} Files ➠ {keyword}</b>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛃 Delete Files!", callback_data=f"killfilesdq#{keyword}")],
            [InlineKeyboardButton("💢 Cancel 💢", callback_data="close_data")],
        ]),
        parse_mode=enums.ParseMode.HTML,
    )
