import asyncio
import logging
import re

from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait
from pyrogram.errors.exceptions.bad_request_400 import (
    ChannelInvalid,
    ChatAdminRequired,
    UsernameInvalid,
    UsernameNotModified
)
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from info import ADMINS
from info import INDEX_REQ_CHANNEL as LOG_CHANNEL
from database.ia_filterdb import Media
from utils import temp

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

lock = asyncio.Lock()


# =========================
# BULK SAVE (FAST)
# =========================
async def save_files_bulk(media_list):
    if not media_list:
        return 0, 0, 0  # saved, duplicate, error

    docs = []
    file_ids = set()

    for media in media_list:
        fid = media.file_id
        if fid in file_ids:
            continue
        file_ids.add(fid)

        docs.append({
            "file_id": fid,
            "file_name": media.file_name,
            "file_size": media.file_size,
            "file_type": media.file_type,
            "caption": media.caption
        })

    existing = await Media.find(
        {"file_id": {"$in": list(file_ids)}},
        {"file_id": 1}
    ).to_list(length=None)

    existing_ids = {x["file_id"] for x in existing}
    new_docs = [d for d in docs if d["file_id"] not in existing_ids]

    if not new_docs:
        return 0, len(existing_ids), 0

    try:
        await Media.insert_many(new_docs, ordered=False)
        return len(new_docs), len(existing_ids), 0
    except Exception:
        return 0, 0, len(new_docs)


# =========================
# CALLBACK HANDLER
# =========================
@Client.on_callback_query(filters.regex(r'^index'))
async def index_files(bot, query):
    if query.data.startswith('index_cancel'):
        temp.CANCEL = True
        return await query.answer("Cancelling Indexing")

    _, action, chat, lst_msg_id, from_user = query.data.split("#")

    if action == 'reject':
        await query.message.delete()
        await bot.send_message(
            int(from_user),
            f'Your submission for indexing {chat} was declined.',
            reply_to_message_id=int(lst_msg_id)
        )
        return

    if lock.locked():
        return await query.answer(
            'Wait until previous indexing finishes',
            show_alert=True
        )

    await query.answer('Processing... ⏳', show_alert=True)

    if int(from_user) not in ADMINS:
        await bot.send_message(
            int(from_user),
            f'Your submission for indexing {chat} has been accepted.',
            reply_to_message_id=int(lst_msg_id)
        )

    await query.message.edit(
        "Starting Indexing…",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Cancel ❌", callback_data="index_cancel")]]
        )
    )

    try:
        chat = int(chat)
    except ValueError:
        pass

    await index_files_to_db(int(lst_msg_id), chat, query.message, bot)


# =========================
# SEND FOR INDEX
# =========================
@Client.on_message(
    (filters.forwarded |
     filters.regex(r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$"))
    & filters.text & filters.private
)
async def send_for_index(bot, message):
    if message.text:
        regex = re.compile(
            r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$"
        )
        match = regex.match(message.text)
        if not match:
            return await message.reply("Invalid link")

        chat_id = match.group(4)
        last_msg_id = int(match.group(5))

        if chat_id.isnumeric():
            chat_id = int("-100" + chat_id)

    elif message.forward_from_chat and message.forward_from_chat.type == enums.ChatType.CHANNEL:
        chat_id = message.forward_from_chat.username or message.forward_from_chat.id
        last_msg_id = message.forward_from_message_id
    else:
        return

    try:
        await bot.get_chat(chat_id)
    except ChannelInvalid:
        return await message.reply(
            "📮 Channel is private. Make me admin to index."
        )
    except (UsernameInvalid, UsernameNotModified):
        return await message.reply("Invalid link.")
    except Exception as e:
        logger.exception(e)
        return await message.reply(str(e))

    try:
        k = await bot.get_messages(chat_id, last_msg_id)
    except Exception:
        return await message.reply(
            "Make sure I am admin in the channel."
        )

    if k.empty:
        return await message.reply("This may be a group or inaccessible.")

    if message.from_user.id in ADMINS:
        return await message.reply(
            "<b>❓ Index This Channel Files ❓</b>",
            reply_markup=InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "✅ Accept",
                        callback_data=f"index#accept#{chat_id}#{last_msg_id}#{message.from_user.id}"
                    ),
                    InlineKeyboardButton("❌ Reject", callback_data="close_data")
                ]]
            )
        )

    try:
        link = (
            await bot.create_chat_invite_link(chat_id)
        ).invite_link if isinstance(chat_id, int) else f"@{chat_id}"
    except ChatAdminRequired:
        return await message.reply(
            "I need admin rights to create invite links."
        )

    await bot.send_message(
        LOG_CHANNEL,
        f"<b>#IndexRequest</b>\n\n"
        f"👤 User: {message.from_user.mention} "
        f"[<code>{message.from_user.id}</code>]\n"
        f"📺 Channel: {link}",
        reply_markup=InlineKeyboardMarkup(
            [[
                InlineKeyboardButton(
                    "✅ Accept",
                    callback_data=f"index#accept#{chat_id}#{last_msg_id}#{message.from_user.id}"
                ),
                InlineKeyboardButton(
                    "❌ Reject",
                    callback_data=f"index#reject#{chat_id}#{message.id}#{message.from_user.id}"
                )
            ]]
        )
    )

    await message.reply(
        "Thank you for the contribution. Waiting for approval."
    )


# =========================
# SET SKIP
# =========================
@Client.on_message(filters.command("setskip") & filters.user(ADMINS))
async def set_skip_number(_, message):
    if len(message.command) != 2:
        return await message.reply("Usage: /setskip <number>")

    try:
        temp.CURRENT = int(message.command[1])
    except ValueError:
        return await message.reply("Skip must be an integer.")

    await message.reply(f"📲 Skip set to {temp.CURRENT}")


# =========================
# INDEX CORE (FAST)
# =========================
async def index_files_to_db(lst_msg_id, chat, msg, bot):
    total = duplicate = errors = deleted = no_media = unsupported = 0
    buffer = []
    BATCH_SIZE = 50
    processed = 0
    temp.CANCEL = False

    async with lock:
        try:
            async for message in bot.iter_messages(
                chat_id=chat,
                offset_id=lst_msg_id,
                min_id=temp.CURRENT
            ):
                if temp.CANCEL:
                    break

                processed += 1

                if message.empty:
                    deleted += 1
                    continue

                if not message.media:
                    no_media += 1
                    continue

                if message.media not in (
                    enums.MessageMediaType.VIDEO,
                    enums.MessageMediaType.AUDIO,
                    enums.MessageMediaType.DOCUMENT
                ):
                    unsupported += 1
                    continue

                media = getattr(message, message.media.value, None)
                if not media:
                    unsupported += 1
                    continue

                media.file_type = message.media.value
                media.caption = message.caption

                buffer.append(media)

                if len(buffer) >= BATCH_SIZE:
                    s, d, e = await save_files_bulk(buffer)
                    total += s
                    duplicate += d
                    errors += e
                    buffer.clear()

                if processed % 100 == 0:
                    try:
                        await msg.edit_text(
                            f"📦 Saved: {total}\n"
                            f"♻ Duplicates: {duplicate}\n"
                            f"🗑 Deleted: {deleted}\n"
                            f"🚫 Non-Media: {no_media + unsupported}\n"
                            f"❌ Errors: {errors}",
                            reply_markup=InlineKeyboardMarkup(
                                [[InlineKeyboardButton("❌ Cancel", callback_data="index_cancel")]]
                            )
                        )
                    except FloodWait:
                        pass

            if buffer:
                s, d, e = await save_files_bulk(buffer)
                total += s
                duplicate += d
                errors += e

        except Exception as e:
            logger.exception(e)
            try:
                await msg.edit(f"❌ Error: {e}")
            except FloodWait:
                pass
        else:
            try:
                await msg.edit(
                    f"<b>✅ Index Completed</b>\n\n"
                    f"🔆 Saved: {total}\n"
                    f"♻ Duplicates: {duplicate}\n"
                    f"🗑 Deleted: {deleted}\n"
                    f"🚫 Non-Media: {no_media + unsupported}\n"
                    f"❌ Errors: {errors}"
                )
            except FloodWait:
                pass
