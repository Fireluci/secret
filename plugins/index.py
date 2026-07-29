import asyncio
import logging
import re
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait
from pyrogram.errors.exceptions.bad_request_400 import ChannelInvalid, ChatAdminRequired, UsernameInvalid, UsernameNotModified
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from info import ADMINS
from database.ia_filterdb import save_file, db
from utils import temp

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
lock = asyncio.Lock()

index_state_col = db["index_state"]

async def get_index_state():
    return await index_state_col.find_one({"_id": "active_index"})

async def save_index_state(chat_id, lst_msg_id, current, total_files, duplicate, deleted):
    await index_state_col.update_one(
        {"_id": "active_index"},
        {
            "$set": {
                "chat_id": chat_id,
                "lst_msg_id": lst_msg_id,
                "current": current,
                "total_files": total_files,
                "duplicate": duplicate,
                "deleted": deleted
            }
        },
        upsert=True
    )

async def clear_index_state():
    await index_state_col.delete_one({"_id": "active_index"})


@Client.on_callback_query(filters.regex(r'^index'))
async def index_files(bot, query):
    if query.data.startswith('index_cancel'):
        temp.CANCEL = True
        await clear_index_state()
        return await query.answer("Cancelling Indexing")
    
    if query.data == 'index_status':
        current_progress = getattr(temp, 'CURRENT', 0)
        total_saved = getattr(temp, 'SAVED', 0)
        total_dup = getattr(temp, 'DUP', 0)
        total_del = getattr(temp, 'DEL', 0)
        return await query.answer(
            f"📊 Live Index Status:\n"
            f"● Processed: {current_progress}\n"
            f"● Saved: {total_saved}\n"
            f"● Duplicates: {total_dup}\n"
            f"● Deleted: {total_del}",
            show_alert=True
        )

    _, raju, chat, lst_msg_id = query.data.split("#")
    if raju == 'reject':
        await query.message.delete()
        return
    if lock.locked():
        return await query.answer('Wait Until Previous Index is Finished', show_alert=True)
    msg = query.message
    await query.answer('Processing...⏳', show_alert=True)
    await msg.edit(
        "Starting Indexing",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton('📊 Check Live Status', callback_data='index_status')],
             [InlineKeyboardButton('❌ Cancel ❌', callback_data='index_cancel')]]
        )
    )
    try:
        chat = int(chat)
    except:
        pass
    await index_files_to_db(int(lst_msg_id), chat, msg, bot)

@Client.on_message(
    (filters.forwarded | (filters.regex(
        "(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$"
    )) & filters.text) & filters.private & filters.incoming
)
async def send_for_index(bot, message):
    if message.from_user.id not in ADMINS:
        return

    if message.text:
        regex = re.compile(
            "(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$"
        )
        match = regex.match(message.text)
        if not match:
            return await message.reply('Invalid link')
        chat_id = match.group(4)
        last_msg_id = int(match.group(5))
        if chat_id.isnumeric():
            chat_id = int("-100" + chat_id)
    elif message.forward_from_chat and message.forward_from_chat.type == enums.ChatType.CHANNEL:
        last_msg_id = message.forward_from_message_id
        chat_id = message.forward_from_chat.username or message.forward_from_chat.id
    else:
        return

    try:
        await bot.get_chat(chat_id)
    except ChannelInvalid:
        return await message.reply(
            '📮This Channel Is Private, Make Me Admin In The Channel To Index The Files'
        )
    except (UsernameInvalid, UsernameNotModified):
        return await message.reply('Invalid Link specified.')
    except Exception as e:
        logger.exception(e)
        return await message.reply(f'Errors - {e}')

    try:
        k = await bot.get_messages(chat_id, last_msg_id)
    except:
        return await message.reply(
            'Make Sure That I am An Admin In The Channel, if channel is private'
        )

    if k.empty:
        return await message.reply(
            'This may be a group and I am not an admin of the group.'
        )
    buttons = [[
        InlineKeyboardButton(
            '✅ Accept',
            callback_data=f'index#accept#{chat_id}#{last_msg_id}'
        ),
        InlineKeyboardButton('❌ Reject', callback_data='close_data')
    ]]

    return await message.reply(
        f'<b>❓ Index This Channel Files ❓</b>\n\n'
        f'🗳 <b>Chat ID/Username ›</b> <code>{chat_id}</code>',
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@Client.on_message(filters.command('setskip') & filters.user(ADMINS))
async def set_skip_number(bot, message):
    if ' ' in message.text:
        _, skip = message.text.split(" ")
        try:
            skip = int(skip)
        except:
            return await message.reply("Skip number should be an integer.")
        await message.reply(f"📲 SKIP Number set: {skip}")
        temp.CURRENT = int(skip)
    else:
        await message.reply("Give me a skip number.")

async def index_files_to_db(lst_msg_id, chat, msg, bot, resume_current=0, resume_saved=0, resume_dup=0, resume_del=0):
    total_files = resume_saved
    duplicate = resume_dup
    deleted = resume_del

    temp.SAVED = total_files
    temp.DUP = duplicate
    temp.DEL = deleted
    temp.CURRENT = resume_current

    async with lock:
        try:
            current = temp.CURRENT
            last_edit = current
            temp.CANCEL = False
            
            async for message in bot.iter_messages(chat, lst_msg_id, temp.CURRENT):
                if temp.CANCEL:
                    try:
                        await msg.edit(
                            f"<b>Cancelled Index</b> 🚫\n\n"
                            f"● Saved Files: {total_files}\n"
                            f"● Duplicate Files: {duplicate}\n"
                            f"● Deleted Messages: {deleted}"
                        )
                    except FloodWait as e:
                        logger.warning(f"FloodWait while cancelling: {e.value} seconds.")
                    await clear_index_state()
                    break

                current += 1
                temp.CURRENT = current

                if current % 50 == 0:
                    await save_index_state(chat, lst_msg_id, current, total_files, duplicate, deleted)

                if (current >= 10 and last_edit == temp.CURRENT) or (current - last_edit >= 2000):
                    last_edit = current
                    await save_index_state(chat, lst_msg_id, current, total_files, duplicate, deleted)
                    try:
                        await msg.edit_text(
                            text=f"● Total Messages Fetched: {current}\n"
                                 f"● Saved: {total_files}\n"
                                 f"● Duplicates: {duplicate}\n"
                                 f"● Deleted: {deleted}",
                            reply_markup=InlineKeyboardMarkup(
                                [[InlineKeyboardButton('📊 Check Live Status', callback_data='index_status')],
                                 [InlineKeyboardButton('Cancel', callback_data='index_cancel')]]
                            )
                        )
                    except FloodWait as e:
                        logger.warning(f"FloodWait while updating progress: {e.value} seconds.")

                if message.empty:
                    deleted += 1
                    temp.DEL = deleted
                    continue
                elif not message.media:
                    continue
                elif message.media not in [
                    enums.MessageMediaType.VIDEO,
                    enums.MessageMediaType.DOCUMENT
                ]:
                    continue

                media = getattr(message, message.media.value, None)
                if not media:
                    continue

                media.file_type = message.media.value
                media.caption = message.caption
                media.chat_id = message.chat.id
                aynav, vnay = await save_file(media)

                if aynav:
                    total_files += 1
                    temp.SAVED = total_files
                elif vnay == 0:
                    duplicate += 1
                    temp.DUP = duplicate

        except Exception as e:
            logger.exception(e)
            try:
                await msg.edit(f'Error: {e}')
            except FloodWait as e:
                logger.warning(f"FloodWait while sending error: {e.value} seconds.")
        else:
            temp.CURRENT = 0
            await clear_index_state()
            try:
                await msg.edit(
                    f'<b>🔆 Saved "{total_files}" Files!</b>\n\n'
                    f'● Duplicates: {duplicate}\n'
                    f'● Deleted: {deleted}'
                )
            except FloodWait as e:
                logger.warning(f"FloodWait while sending final result: {e.value} seconds.")

# Helper function to auto-resume when your bot starts up
async def check_pending_index_on_startup(client):
    state = await get_index_state()
    if state:
        chat_id = state.get("chat_id")
        lst_msg_id = state.get("lst_msg_id")
        current = state.get("current", 0)
        saved = state.get("total_files", 0)
        dup = state.get("duplicate", 0)
        deleted = state.get("deleted", 0)
        
        logger.info(f"Found pending indexing task! Resuming from message count: {current}")
        
        for admin_id in ADMINS:
            try:
                msg = await client.send_message(
                    admin_id, 
                    f"🔄 **Resuming Interrupted Indexing Task**\n● Processed: {current}\n● Saved: {saved}",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton('📊 Check Live Status', callback_data='index_status')],
                         [InlineKeyboardButton('Cancel', callback_data='index_cancel')]]
                    )
                )
                asyncio.create_task(index_files_to_db(lst_msg_id, chat_id, msg, client, current, saved, dup, deleted))
                break
            except Exception:
                continue
