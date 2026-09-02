from pyrogram import Client, enums, filters

from database.users_chats_db import db
from info import *
from utils import connected_group, temp


def is_bot_admin_status(status):
    return status in (
        enums.ChatMemberStatus.ADMINISTRATOR,
        enums.ChatMemberStatus.OWNER,
    )


@Client.on_message(
    filters.group
    & filters.command("connect")
    & filters.user(OWNER)
)
async def connect_group(client, message):
    bot_member = await client.get_chat_member(message.chat.id, "me")
    if not is_bot_admin_status(bot_member.status):
        return await message.reply("Make me an admin in this group first.")

    await db.connect_group(message.chat.id, message.chat.title)
    temp.GROUP_ACCESS[message.chat.id] = True

    await message.reply(
        f"Connected: <b>{message.chat.title}</b>\nThe bot is now active in this group."
    )


@Client.on_message(
    filters.group
    & filters.command("disconnect")
    & filters.user(OWNER)
    & connected_group
)
async def disconnect_group(client, message):
    await db.disconnect_group(message.chat.id)
    temp.GROUP_ACCESS[message.chat.id] = False
    await message.reply("Disconnected. The bot is now silent in this group.")
