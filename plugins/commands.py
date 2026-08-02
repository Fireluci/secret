import os
import logging
import asyncio
from datetime import datetime
from Script import script
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait
from pyrogram.types import *
from database.ia_filterdb import Media, get_file_details, unpack_new_file_id, get_bad_files
from database.users_chats_db import db
from info import CHANNELS, ADMINS, AUTH_CHANNEL, LOG_CHANNEL, PICS, BATCH_FILE_CAPTION, CUSTOM_FILE_CAPTION, PROTECT_CONTENT, CHNL_LNK, FORCE, MAX_B_TN, TUTORIAL, PREMIUM_USER
from utils import get_settings, get_size, is_subscribed, save_group_settings, temp, get_shortlink
from database.connections_mdb import active_connection
from pymongo.errors import PyMongoError
import re, sys, json, base64

logger = logging.getLogger(__name__)

BATCH_FILES = {}

@Client.on_message(filters.command("start") & filters.incoming)
async def start(client, message):
    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        await message.reply(script.START_TXT.format(message.from_user.mention if message.from_user else message.chat.title, temp.U_NAME, temp.B_NAME), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❓How To Use Me❓', url=f'https://telegram.me/{TUTORIAL}')]]), disable_web_page_preview=True)
        await asyncio.sleep(2)
        if not await db.get_chat(message.chat.id):
            total = await client.get_chat_members_count(message.chat.id)
            await client.send_message(LOG_CHANNEL, script.LOG_TEXT_G.format(message.chat.title, message.chat.id, total, "Unknown"))       
            await db.add_chat(message.chat.id, message.chat.title)
        return 
    if not await db.is_user_exist(message.from_user.id):
        await db.add_user(message.from_user.id, message.from_user.first_name)
        await client.send_message(LOG_CHANNEL, script.LOG_TEXT_P.format(message.from_user.id, message.from_user.mention))
    if len(message.command) != 2:
        return await message.reply_photo(photo=PICS, caption=script.START_TXT.format(message.from_user.mention, temp.U_NAME, temp.B_NAME), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 Buy Premium", callback_data="buy_premium_start")]]), parse_mode=enums.ParseMode.HTML)
    if AUTH_CHANNEL and not await is_subscribed(client, message):
        payload = message.text.split(" ", 1)[1] if " " in message.text else "subscribe"
        return await client.send_message(message.from_user.id, "<b>🔆 First Join Our Main Channel & Then Click Try Again ♻</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏮 Main Channel", url=FORCE)], [InlineKeyboardButton("🔄 Try Again", url=f"https://telegram.me/{temp.U_NAME}?start={payload}")]], parse_mode=enums.ParseMode.HTML)

    if len(message.command) == 2 and message.command[1] in ["subscribe", "error", "okay", "help"]:
        return await message.reply_photo(photo=PICS, caption=script.START_TXT.format(message.from_user.mention, temp.U_NAME, temp.B_NAME), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 Buy Premium", callback_data="buy_premium_start")]]), parse_mode=enums.ParseMode.HTML)

    data = message.command[1]
    try:
        pre, file_id = data.split('_', 1)
    except:
        file_id, pre = data, ""

    if data.split("-", 1)[0] == "BATCH":
        sts = await message.reply("<b>Please wait...</b>")
        file_id = data.split("-", 1)[1]
        msgs = BATCH_FILES.get(file_id)
        if not msgs:
            file = await client.download_media(file_id)
            try:
                with open(file) as f:
                    msgs = json.loads(f.read())
            except:
                await sts.edit("FAILED")
                return await client.send_message(LOG_CHANNEL, "UNABLE TO OPEN FILE.")
            os.remove(file)
            BATCH_FILES[file_id] = msgs
        for msg in msgs:
            title, size = msg.get("title"), get_size(int(msg.get("size", 0)))
            f_caption = BATCH_FILE_CAPTION.format(file_name=title or '', file_size=size or '', file_caption=msg.get("caption", "")) if BATCH_FILE_CAPTION else (msg.get("caption") or title)
            try:
                await client.send_cached_media(chat_id=message.from_user.id, file_id=msg.get("file_id"), caption=f_caption, protect_content=msg.get('protect', False), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔆彡⟨ HEROFLiX ⟩彡🔆', url=f'https://telegram.me/{CHNL_LNK}')]]))
            except FloodWait as e:
                await asyncio.sleep(e.x)
                await client.send_cached_media(chat_id=message.from_user.id, file_id=msg.get("file_id"), caption=f_caption, protect_content=msg.get('protect', False), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔆彡⟨ HEROFLiX ⟩彡🔆', url=f'https://telegram.me/{CHNL_LNK}')]]))
            except Exception:
                continue
            await asyncio.sleep(1)
        return await sts.delete()
    
    elif data.split("-", 1)[0] == "DSTORE":
        sts = await message.reply("<b>Please wait...</b>")
        b_string = data.split("-", 1)[1]
        try:
            decoded = base64.urlsafe_b64decode(b_string + "=" * (-len(b_string) % 4)).decode("utf-8")
        except (base64.binascii.Error, UnicodeDecodeError, ValueError):
            return await sts.edit("<b>❌ Invalid or corrupted store link!</b>")
        try:
            f_msg_id, l_msg_id, f_chat_id, protect = decoded.split("_", 3)
        except:
            f_msg_id, l_msg_id, f_chat_id = decoded.split("_", 2)
            protect = "/pbatch" if PROTECT_CONTENT else "batch"
        async for msg in client.iter_messages(int(f_chat_id), int(l_msg_id), int(f_msg_id)):
            if msg.media:
                media = getattr(msg, msg.media.value)
                f_caption = BATCH_FILE_CAPTION.format(file_name=getattr(media, 'file_name', ''), file_size=getattr(media, 'file_size', ''), file_caption=getattr(msg, 'caption', '')) if BATCH_FILE_CAPTION else getattr(msg, 'caption', getattr(media, 'file_name', ''))
                try:
                    await msg.copy(message.chat.id, caption=f_caption, protect_content=(protect == "/pbatch"))
                except FloodWait as e:
                    await asyncio.sleep(e.x)
                    await msg.copy(message.chat.id, caption=f_caption, protect_content=(protect == "/pbatch"))
                except Exception:
                    continue
            elif not msg.empty:
                try:
                    await msg.copy(message.chat.id, protect_content=(protect == "/pbatch"))
                except FloodWait as e:
                    await asyncio.sleep(e.x)
                    await msg.copy(message.chat.id, protect_content=(protect == "/pbatch"))
                except Exception:
                    continue
            await asyncio.sleep(1)
        return await sts.delete()

    if data.startswith("sendfiles"):
        chat_id = int("-" + file_id.split("-")[1])
        userid = message.from_user.id if message.from_user else None
        st = await client.get_chat_member(chat_id, userid)
        is_admin = st.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]
        g = await get_shortlink(chat_id, f"https://telegram.me/{temp.U_NAME}?start=allfiles_{file_id}", not is_admin)
        k = await client.send_message(chat_id=message.from_user.id, text=f"<b>Get All Files in a Single Click!!!\n\n♻️ ʟɪɴᴋ ➠ {g}</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('♻️ Download Link ♻️', url=g)], [InlineKeyboardButton('❓ How To Download ❓', url=f'https://telegram.me/{TUTORIAL}')]]))
        await asyncio.sleep(900)
        return await k.edit("<b>Link Deleted!</b>")
        
    elif data.startswith("short"):
        user = message.from_user.id
        files = (await get_file_details(file_id))[0]
        cleaned_file_name = ' '.join(filter(lambda x: not x.startswith(('www.', '@')), files.file_name.split()))
        g = await get_shortlink(temp.SHORT.get(user), f"https://telegram.me/{temp.U_NAME}?start=file_{file_id}")
        k = await client.send_message(chat_id=user, text=f'<b>[ {get_size(files.file_size)} ] <a href="https://telegram.me/HEROFLiX">{cleaned_file_name}</a> \n\n📗 Download Link ➔ {g}</b>', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('♻️ Download Link ♻️', url=g)], [InlineKeyboardButton('❓ How To Download ❓', url=f'https://telegram.me/{TUTORIAL}')], [InlineKeyboardButton('💎 Buy Premium', callback_data="buy_premium_start")]]))
        await asyncio.sleep(900)
        return await k.edit("<b>Link Deleted!</b>")
        
    elif data.startswith("all"):
        files = temp.GETALL.get(file_id)
        if not files:
            return await message.reply('<b><i>No such file exist.</b></i>')
        for file in files:
            files1 = (await get_file_details(file.file_id))[0]
            title = ' '.join(filter(lambda x: not x.startswith(('www.', '@')), files1.file_name.split()))
            f_caption = CUSTOM_FILE_CAPTION.format(file_name=title or '', file_size=get_size(files1.file_size) or '', file_caption=files1.caption or '') if CUSTOM_FILE_CAPTION else (files1.caption or title)
            await client.send_cached_media(chat_id=message.from_user.id, file_id=file.file_id, caption=f_caption, protect_content=(pre == 'filep'), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔆彡⟨ HEROFLiX ⟩彡🔆', url=f'https://telegram.me/{CHNL_LNK}')]]))
        return
        
    elif data.startswith("files"):
        user = message.from_user.id
        chat_id = temp.SHORT.get(user)
        if not chat_id:
            return await message.reply_text(text="<b>Link Expired, Search Again in Group!</b>")
        settings = await get_settings(chat_id)
        if settings['is_shortlink'] and user not in PREMIUM_USER:
            files = (await get_file_details(file_id))[0]
            g = await get_shortlink(chat_id, f"https://telegram.me/{temp.U_NAME}?start=file_{file_id}")
            cleaned_file_name = ' '.join(filter(lambda x: not x.startswith(('www.', '@')), files.file_name.split()))
            k = await client.send_message(chat_id=message.from_user.id, text=f'<b>[ {get_size(files.file_size)} ] <a href="https://telegram.me/HEROFLiX">{cleaned_file_name}</a> \n\n📗 Download Link ➠ {g}</b>', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('♻️ Download Link ♻️', url=g)], [InlineKeyboardButton('❓ How To Download ❓', url=f"https://telegram.me/{TUTORIAL}")], [InlineKeyboardButton('💎 Buy Premium', callback_data="buy_premium_start")]]))
            await asyncio.sleep(900)
            try:
                await k.edit_text("Link Deleted!")
            except Exception:
                pass
            return

    files_ = await get_file_details(file_id)
    if not files_:
        try:
            decoded_string = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8")
            pre, file_id = decoded_string.split("_", 1)
        except (base64.binascii.Error, UnicodeDecodeError, ValueError):
            return await message.reply('<b>❌ Invalid or corrupted file link!</b>')
        try:
            msg = await client.send_cached_media(chat_id=message.from_user.id, file_id=file_id, protect_content=(pre == 'filep'), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔆彡⟨ HEROFLiX ⟩彡🔆', url=f'https://telegram.me/{CHNL_LNK}')]]))
            file = getattr(msg, msg.media.value)
            title = ' '.join(filter(lambda x: not x.startswith(('www.', '@')), file.file_name.split()))
            f_caption = CUSTOM_FILE_CAPTION.format(file_name=title or '', file_size=get_size(file.file_size) or '', file_caption='') if CUSTOM_FILE_CAPTION else f"<code>{title}</code>"
            await msg.edit_caption(f_caption)
            return await message.reply_text("<b>Your File/Video is deleted!!!\n\nClick below button to get your deleted file 👇</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Get File Again", callback_data=f'delfile#{file_id}')]]))
        except Exception:
            pass
        return await message.reply('No such file exist.')
        
    files = files_[0]
    title = ' '.join(filter(lambda x: not x.startswith(('www.', '@')), files.file_name.split()))
    f_caption = CUSTOM_FILE_CAPTION.format(file_name=title or '', file_size=get_size(files.file_size) or '', file_caption=files.caption or '') if CUSTOM_FILE_CAPTION else (files.caption or title)
    await client.send_cached_media(chat_id=message.from_user.id, file_id=file_id, caption=f_caption, protect_content=(pre == 'filep'), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔆彡⟨ HEROFLiX ⟩彡🔆', url=f'https://telegram.me/{CHNL_LNK}')]]))

@Client.on_message(filters.command('channel') & filters.user(ADMINS))
async def channel_info(bot, message):
    channels = [CHANNELS] if isinstance(CHANNELS, (int, str)) else CHANNELS
    if not isinstance(channels, list):
        raise ValueError("Unexpected type of CHANNELS")
    text = '<b>📑 Indexed channels/groups</b>\n'
    for channel in channels:
        chat = await bot.get_chat(channel)
        text += ('\n@' + chat.username) if chat.username else ('\n' + (chat.title or chat.first_name))
    text += f'\n\n<b>Total:</b> {len(channels)}'
    if len(text) < 4096:
        await message.reply(text, parse_mode=enums.ParseMode.HTML)
    else:
        file = 'Indexed channels.txt'
        with open(file, 'w') as f:
            f.write(text)
        await message.reply_document(file)
        os.remove(file)

@Client.on_message(filters.command('logs') & filters.user(ADMINS))
async def log_file(bot, message):
    try:
        await message.reply_document('TelegramBot.log')
    except Exception as e:
        await message.reply(str(e))

@Client.on_message(filters.command('delete') & filters.user(ADMINS))
async def delete(bot, message):
    reply = message.reply_to_message
    if not reply or not reply.media:
        return await message.reply('Reply to file with /delete which you want to delete', quote=True)
    msg = await message.reply("Processing...⏳", quote=True)
    media = next((getattr(reply, ft, None) for ft in ("document", "video", "audio") if getattr(reply, ft, None) is not None), None)
    if not media:
        return await msg.edit('This is not supported file format')
    file_id, _ = unpack_new_file_id(media.file_id)
    try:
        result = await Media.collection.delete_one({'_id': file_id})
        if not result.deleted_count:
            file_name = re.sub(r"(_|\-|\.|\+)", " ", str(media.file_name))
            result = await Media.collection.delete_many({'file_name': file_name, 'file_size': media.file_size, 'mime_type': media.mime_type})
        if not result.deleted_count:
            result = await Media.collection.delete_many({'file_name': media.file_name, 'file_size': media.file_size, 'mime_type': media.mime_type})
        await msg.edit('🛃 Deleted File!' if result.deleted_count else 'File not found in database')
    except PyMongoError as e:
        await msg.edit(f'Database error: {e}')

@Client.on_message(filters.command('deleteall') & filters.user(ADMINS))
async def delete_all_index(bot, message):
    await message.reply_text('This will delete all indexed files.\nDo you want to continue??', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(text="🛃 Delete Files!", callback_data="autofilter_delete")], [InlineKeyboardButton(text="💢 Cancel 💢", callback_data="close_data")]]), quote=True)

@Client.on_callback_query(filters.regex(r'^autofilter_delete'))
async def delete_all_index_confirm(bot, callback):
    try:
        await Media.collection.drop()
        await callback.answer('Piracy Is Crime')
        await callback.message.edit('Succesfully Deleted All The Indexed Files.')
    except PyMongoError as e:
        await callback.answer(f'Database error: {e}')

@Client.on_message(filters.command('settings'))
async def settings(client, message):
    userid = message.from_user.id if message.from_user else None
    if not userid:
        return await message.reply(f"You are anonymous admin. Use /connect {message.chat.id} in PM")
    chat_type = message.chat.type
    if chat_type == enums.ChatType.PRIVATE:
        grpid = await active_connection(str(userid))
        if grpid is not None:
            grp_id = grpid
            try:
                chat = await client.get_chat(grpid)
                title = chat.title
            except Exception:
                return await message.reply_text("Make sure I'm present in your group!!", quote=True)
        else:
            return await message.reply_text("I'm not connected to any groups!", quote=True)
    elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        grp_id, title = message.chat.id, message.chat.title
    else:
        return

    st = await client.get_chat_member(grp_id, userid)
    if st.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] and str(userid) not in ADMINS:
        return
    
    settings = await get_settings(grp_id)
    if 'max_btn' not in settings:
        await save_group_settings(grp_id, 'max_btn', False)
        settings = await get_settings(grp_id)
    if 'is_shortlink' not in settings:
        await save_group_settings(grp_id, 'is_shortlink', False)
        settings = await get_settings(grp_id)

    buttons = [
        [InlineKeyboardButton('Rᴇsᴜʟᴛ Pᴀɢᴇ', callback_data=f'setgs#button#{settings["button"]}#{grp_id}'), InlineKeyboardButton('Bᴜᴛᴛᴏɴ' if settings["button"] else 'Tᴇxᴛ', callback_data=f'setgs#button#{settings["button"]}#{grp_id}')],
        [InlineKeyboardButton('Fɪʟᴇ Sᴇɴᴅ Mᴏᴅᴇ', callback_data=f'setgs#botpm#{settings["botpm"]}#{grp_id}'), InlineKeyboardButton('Mᴀɴᴜᴀʟ Sᴛᴀʀᴛ' if settings["botpm"] else 'Aᴜᴛᴏ Sᴇɴᴅ', callback_data=f'setgs#botpm#{settings["botpm"]}#{grp_id}')],
        [InlineKeyboardButton('Pʀᴏᴛᴇᴄᴛ Cᴏɴᴛᴇɴᴛ', callback_data=f'setgs#file_secure#{settings["file_secure"]}#{grp_id}'), InlineKeyboardButton('✔ Oɴ' if settings["file_secure"] else '✘ Oғғ', callback_data=f'setgs#file_secure#{settings["file_secure"]}#{grp_id}')],
        [InlineKeyboardButton('Sᴘᴇʟʟ Cʜᴇᴄᴋ', callback_data=f'setgs#spell_check#{settings["spell_check"]}#{grp_id}'), InlineKeyboardButton('✔ Oɴ' if settings["spell_check"] else '✘ Oғғ', callback_data=f'setgs#spell_check#{settings["spell_check"]}#{grp_id}')],
        [InlineKeyboardButton('Wᴇʟᴄᴏᴍᴇ Msɢ', callback_data=f'setgs#welcome#{settings["welcome"]}#{grp_id}'), InlineKeyboardButton('✔ Oɴ' if settings["welcome"] else '✘ Oғғ', callback_data=f'setgs#welcome#{settings["welcome"]}#{grp_id}')],
        [InlineKeyboardButton('Aᴜᴛᴏ-Dᴇʟᴇᴛᴇ', callback_data=f'setgs#auto_delete#{settings["auto_delete"]}#{grp_id}'), InlineKeyboardButton('10 Mɪns' if settings["auto_delete"] else '✘ Oғғ', callback_data=f'setgs#auto_delete#{settings["auto_delete"]}#{grp_id}')],
        [InlineKeyboardButton('Aᴜᴛᴏ-Fɪʟᴛᴇʀ', callback_data=f'setgs#auto_ffilter#{settings["auto_ffilter"]}#{grp_id}'), InlineKeyboardButton('✔ Oɴ' if settings["auto_ffilter"] else '✘ Oғғ', callback_data=f'setgs#auto_ffilter#{settings["auto_ffilter"]}#{grp_id}')],
        [InlineKeyboardButton('Mᴀx Bᴜᴛᴛᴏns', callback_data=f'setgs#max_btn#{settings["max_btn"]}#{grp_id}'), InlineKeyboardButton('10' if settings["max_btn"] else f'{MAX_B_TN}', callback_data=f'setgs#max_btn#{settings["max_btn"]}#{grp_id}')],
        [InlineKeyboardButton('ShortLink', callback_data=f'setgs#is_shortlink#{settings["is_shortlink"]}#{grp_id}'), InlineKeyboardButton('✔ Oɴ' if settings["is_shortlink"] else '✘ Oғғ', callback_data=f'setgs#is_shortlink#{settings["is_shortlink"]}#{grp_id}')],
    ]
    btn = [
        [InlineKeyboardButton("Oᴘᴇɴ Hᴇʀᴇ ↓", callback_data=f"opnsetgrp#{grp_id}"), InlineKeyboardButton("Oᴘᴇɴ Iɴ PM ⇲", callback_data=f"opnsetpm#{grp_id}")]
    ]
    
    if chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        await message.reply_text(text="<b>Dᴏ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴏᴘᴇɴ sᴇᴛᴛɪɴɢs ʜᴇʀᴇ ?</b>", reply_markup=InlineKeyboardMarkup(btn), disable_web_page_preview=True, parse_mode=enums.ParseMode.HTML, reply_to_message_id=message.id)
    else:
        await message.reply_text(text=f"<b>Sᴇᴛᴛɪɴɢs Fᴏʀ {title}</b>", reply_markup=InlineKeyboardMarkup(buttons), disable_web_page_preview=True, parse_mode=enums.ParseMode.HTML, reply_to_message_id=message.id)

@Client.on_message(filters.command("deletefiles") & filters.user(ADMINS))
async def deletemultiplefiles(bot, message):
    if message.chat.type != enums.ChatType.PRIVATE:
        return await message.reply_text("<b>Only Works in PM !</b>")
    try:
        keyword = message.text.split(" ", 1)[1]
    except Exception:
        return await message.reply_text(f"<b>Hey {message.from_user.mention}, Give me a keyword along with the command to delete files.</b>")
    k = await bot.send_message(chat_id=message.chat.id, text="<b>♻️ Please Wait!</b>")
    _, total = await get_bad_files(keyword)
    await k.delete()
    await message.reply_text(text=f"<b>{total} Files ➠ {keyword}</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛃 Delete Files!", callback_data=f"killfilesdq#{keyword}")], [InlineKeyboardButton("💢 Cancel 💢", callback_data="close_data")]]), parse_mode=enums.ParseMode.HTML)

@Client.on_message(filters.command("shortlink"))
async def shortlink_cmd(bot, message):
    userid = message.from_user.id if message.from_user else None
    if not userid:
        return await message.reply("You are anonymous admin.")
    if message.chat.type == enums.ChatType.PRIVATE:
        return await message.reply_text("<b>Only works in groups !</b>")
    grpid, title = message.chat.id, message.chat.title
    user = await bot.get_chat_member(grpid, userid)
    if user.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] and str(userid) not in ADMINS:
        return await message.reply_text("<b>You don't have access to use this command!</b>")
    try:
        _, shortlink_url, api = message.text.split(" ")
    except Exception:
        return await message.reply_text("<b>Wrong Format. Example - /shortlink omnifly.in api_key</b>")
    reply = await message.reply_text("<b>Please Wait...</b>")
    shortlink_url = re.sub(r"[:/]", "", re.sub(r"https?://?", "", shortlink_url))
    await save_group_settings(grpid, 'shortlink', shortlink_url)
    await save_group_settings(grpid, 'shortlink_api', api)
    await save_group_settings(grpid, 'is_shortlink', True)
    await reply.edit_text(f"<b>Successfully added shortlink API for {title}.\n\nWebsite: <code>{shortlink_url}</code></b>")
    
@Client.on_message(filters.command("restart") & filters.user(ADMINS))
async def stop_button(bot, message):
    msg = await bot.send_message(text="<b>🔄 𝙱𝙾𝚃 𝙸𝚂 𝚁𝙴𝚂𝚃𝙰𝚁𝚃𝙸𝙽𝙶</b>", chat_id=message.chat.id, parse_mode=enums.ParseMode.HTML)        
    await asyncio.sleep(3)
    await msg.edit("<b>✅️ 𝙱𝙾𝚃 𝙸𝚂 𝚁𝙴𝚂𝚃𝙰𝚁𝚃𝙴𝙳</b>", parse_mode=enums.ParseMode.HTML)
    os.execl(sys.executable, sys.executable, *sys.argv)
