import logging

from pyrogram import Client, filters, enums
from pyrogram.errors.exceptions.bad_request_400 import MessageTooLong, PeerIdInvalid

from database.users_chats_db import db
from database.ia_filterdb import Media
from info import ADMINS, LOG_CHANNEL, SUPPORT_CHAT, STATUS_TXT
from utils import connected_group, get_size


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
