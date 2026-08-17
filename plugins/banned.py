from pyrogram import Client, filters
from pyrogram.types import Message

from database.users_chats_db import db
from utils import temp


async def banned_users(_, __, message: Message):
    return bool(
        message.from_user
        and message.from_user.id in temp.BANNED_USERS
    )


banned_user = filters.create(banned_users)


@Client.on_message(filters.private & banned_user & filters.incoming)
async def ban_reply(bot, message):
    ban = await db.get_ban_status(message.from_user.id)
    await message.reply(
        f'Sorry Dude, You are Banned to use Me.\nBan Reason: {ban["ban_reason"]}'
    )
