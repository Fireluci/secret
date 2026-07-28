import os
import logging
import random
import asyncio
from datetime import datetime, timedelta
from urllib.parse import quote
from Script import script
from pyrogram import Client, filters, enums
from pyrogram.errors import ChatAdminRequired, FloodWait, RPCError
from pyrogram.types import *
from database.ia_filterdb import Media, get_file_details, unpack_new_file_id, get_bad_files
from database.users_chats_db import db
from info import CHANNELS, ADMINS, AUTH_CHANNEL, LOG_CHANNEL, PICS, BATCH_FILE_CAPTION, CUSTOM_FILE_CAPTION, PROTECT_CONTENT, CHNL_LNK, FORCE, GRP_LNK, REQST_CHANNEL, SUPPORT_CHAT_ID, SUPPORT_CHAT, MAX_B_TN, SHORTLINK_API, SHORTLINK_URL, TUTORIAL, IS_TUTORIAL, PREMIUM_USER, UPI_ID, PREMIUM_GROUP_ID
from utils import get_settings, get_size, is_subscribed, save_group_settings, temp, get_shortlink, get_tutorial
from database.connections_mdb import active_connection
import re, sys
import json
import base64
logger = logging.getLogger(__name__)

BATCH_FILES = {}

MINIMAL_PENDING_FLOW = {}

# ==========================================
# BACKGROUND LIFECYCLE & EXPIRY CHECKER LOOP
# ==========================================
async def premium_expiry_reminder_loop(client: Client):
    """Background loop running every hour to handle 1-day reminders and automated expiry group kicks."""
    await asyncio.sleep(10)  # Initial delay after bot start
    while True:
        try:
            now = datetime.utcnow()
            
            # Target collections
            col = None
            if 'db' in globals() and hasattr(db, 'premium_users'):
                col = db.premium_users
            elif 'users_col' in globals():
                col = users_col
                
            if col is not None:
                async for user_doc in col.find({"active": True}):
                    user_id = user_doc.get("user_id")
                    expires_at = user_doc.get("expires_at") or user_doc.get("expiry_date")
                    
                    if not expires_at or not isinstance(expires_at, datetime):
                        continue
                        
                    reminders = user_doc.get("reminders", {})
                    
                    # 1. On Expiry Check
                    if now >= expires_at:
                        # Automatically remove user from Premium group if configured
                        if PREMIUM_GROUP_ID:
                            try:
                                await client.ban_chat_member(chat_id=PREMIUM_GROUP_ID, user_id=user_id)
                                # Immediately unban so they can rejoin via a new invite link later if they renew
                                await client.unban_chat_member(chat_id=PREMIUM_GROUP_ID, user_id=user_id)
                            except Exception as e:
                                logger.error(f"Failed to kick user {user_id} from premium group: {e}")
                                
                        # Send expiry DM with Renew button
                        expiry_kb = InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 Renew Premium", callback_data="buy_premium_start")]
                        ])
                        expiry_msg = (
                            "❌ **HeroFlix Premium Expired**\n\n"
                            "Your Premium Membership has expired.\n\n"
                            "Tap below to renew."
                        )
                        try:
                            await client.send_message(user_id, expiry_msg, reply_markup=expiry_kb)
                        except Exception as e:
                            logger.error(f"Failed to send expiry DM to user {user_id}: {e}")
                            
                        # Delete the premium record from database
                        await col.delete_one({"user_id": user_id})
                        logger.info(f"🔄 Expired and removed premium record for user {user_id}")
                        
                    # 2. 1 Day Before Expiry Reminder Check
                    elif expires_at - now <= timedelta(days=1) and not reminders.get("1_day", False):
                        reminder_kb = InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 Renew Premium", callback_data="buy_premium_start")]
                        ])
                        reminder_text = (
                            "⚠ **HeroFlix Premium**\n\n"
                            "Your Premium expires tomorrow.\n\n"
                            "Renew now to continue enjoying Premium without interruption."
                        )
                        try:
                            await client.send_message(user_id, reminder_text, reply_markup=reminder_kb)
                            # Update reminder flag (simplified to only 1_day)
                            await col.update_one(
                                {"user_id": user_id},
                                {"$set": {"reminders.1_day": True}}
                            )
                            logger.info(f"📧 Sent 1-day expiry reminder to user {user_id}")
                        except Exception as e:
                            logger.error(f"Failed to send 1-day reminder to user {user_id}: {e}")
                            
        except Exception as e:
            logger.error(f"Error in premium expiry background task: {e}")
            
        await asyncio.sleep(3600)  # Check every hour

# Automatically start the background task when any client starts up
@Client.on_start()
async def start_background_tasks(client, *args):
    asyncio.create_task(premium_expiry_reminder_loop(client))


@Client.on_message(filters.command("start") & filters.incoming)
async def start(client, message):
    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        buttons = [
            [
                InlineKeyboardButton('❓How To Use Me❓', url=f'https://telegram.me/{TUTORIAL}')
            ]
               ]
        reply_markup = InlineKeyboardMarkup(buttons)
        await message.reply(script.START_TXT.format(message.from_user.mention if message.from_user else message.chat.title, temp.U_NAME, temp.B_NAME), reply_markup=reply_markup, disable_web_page_preview=True)
        await asyncio.sleep(2) # 😢 https://github.com/EvamariaTG/EvaMaria/blob/master/plugins/p_ttishow.py#L17 😬 wait a bit, before checking.
        if not await db.get_chat(message.chat.id):
            total=await client.get_chat_members_count(message.chat.id)
            await client.send_message(LOG_CHANNEL, script.LOG_TEXT_G.format(message.chat.title, message.chat.id, total, "Unknown"))       
            await db.add_chat(message.chat.id, message.chat.title)
        return 
    if not await db.is_user_exist(message.from_user.id):
        await db.add_user(message.from_user.id, message.from_user.first_name)
        await client.send_message(LOG_CHANNEL, script.LOG_TEXT_P.format(message.from_user.id, message.from_user.mention))
    if len(message.command) != 2:
        buttons = [
            [InlineKeyboardButton("🌟 Paid (No Ads)", url="https://telegram.me/HeroFlixx/49"),
             InlineKeyboardButton("🍿 Free (With Ads)", url="https://telegram.me/addlist/X5k2lnJLIGAyZjQ1")],
            [InlineKeyboardButton("👤 Admin", url=f"https://telegram.me/{SUPPORT_CHAT}"),
             InlineKeyboardButton("⚜ Updates", url=FORCE)]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        await message.reply_photo(
            photo=PICS,
            caption=script.START_TXT.format(message.from_user.mention, temp.U_NAME, temp.B_NAME),
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
        return
    if AUTH_CHANNEL and not await is_subscribed(client, message):
        payload = message.text.split(" ", 1)[1] if " " in message.text else "subscribe"
        retry = f"https://telegram.me/{temp.U_NAME}?start={payload}"

        btn = [
            [InlineKeyboardButton("🏮 Main Channel ⟨Click Here⟩ 🏮", url=FORCE)],
            [InlineKeyboardButton("🔄 Try Again", url=retry)]
        ]

        await client.send_message(
            message.from_user.id,
            "**🔆 First Join Our Main Channel & Then Click Try Again ♻\n\n"
            "🔆 पहले हमारे मैन चैनल से जुड़ें और फिर Try Again दबाएँ ♻**",
            reply_markup=InlineKeyboardMarkup(btn),
            parse_mode=enums.ParseMode.MARKDOWN
        )
        return

    if len(message.command) == 2 and message.command[1] in ["subscribe", "error", "okay", "help"]:
        buttons = [
            [InlineKeyboardButton("🌟 Paid (No Ads)", url="https://telegram.me/HeroFlixx/49"),
             InlineKeyboardButton("🍿 Free (With Ads)", url="https://telegram.me/addlist/X5k2lnJLIGAyZjQ1")],
            [InlineKeyboardButton("👤 Admin", url=f"https://telegram.me/{SUPPORT_CHAT}"),
             InlineKeyboardButton("⚜ Updates", url=FORCE)]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)      
        await message.reply_photo(
            photo=PICS,
            caption=script.START_TXT.format(message.from_user.mention, temp.U_NAME, temp.B_NAME),
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
        return
    data = message.command[1]
    try:
        pre, file_id = data.split('_', 1)
    except:
        file_id = data
        pre = ""
    if data.split("-", 1)[0] == "BATCH":
        sts = await message.reply("<b>Please wait...</b>")
        file_id = data.split("-", 1)[1]
        msgs = BATCH_FILES.get(file_id)
        if not msgs:
            file = await client.download_media(file_id)
            try: 
                with open(file) as file_data:
                    msgs=json.loads(file_data.read())
            except:
                await sts.edit("FAILED")
                return await client.send_message(LOG_CHANNEL, "UNABLE TO OPEN FILE.")
            os.remove(file)
            BATCH_FILES[file_id] = msgs
        for msg in msgs:
            title = msg.get("title")
            size=get_size(int(msg.get("size", 0)))
            f_caption=msg.get("caption", "")
            if BATCH_FILE_CAPTION:
                try:
                    f_caption=BATCH_FILE_CAPTION.format(file_name= '' if title is None else title, file_size='' if size is None else size, file_caption='' if f_caption is None else f_caption)
                except Exception as e:
                    logger.exception(e)
                    f_caption=f_caption
            if f_caption is None:
                f_caption = f"{title}"
            try:
                await client.send_cached_media(
                    chat_id=message.from_user.id,
                    file_id=msg.get("file_id"),
                    caption=f_caption,
                    protect_content=msg.get('protect', False),
                    reply_markup=InlineKeyboardMarkup(
                        [
                         [
                          InlineKeyboardButton('🔆彡⟨ HEROFLiX ⟩彡🔆', url=f'https://telegram.me/{CHNL_LNK}'),
                         ]
                        ]
                    )
                )
            except FloodWait as e:
                await asyncio.sleep(e.x)
                logger.warning(f"Floodwait of {e.x} sec.")
                await client.send_cached_media(
                    chat_id=message.from_user.id,
                    file_id=msg.get("file_id"),
                    caption=f_caption,
                    protect_content=msg.get('protect', False),
                    reply_markup=InlineKeyboardMarkup(
                        [
                         [
                          InlineKeyboardButton('🔆彡⟨ HEROFLiX ⟩彡🔆', url=f'https://telegram.me/{CHNL_LNK}'),
                         ]
                        ]
                    )
                )
            except Exception as e:
                logger.warning(e, exc_info=True)
                continue
            await asyncio.sleep(1) 
        await sts.delete()
        return
    
    elif data.split("-", 1)[0] == "DSTORE":
        sts = await message.reply("<b>Please wait...</b>")
        b_string = data.split("-", 1)[1]
        decoded = (base64.urlsafe_b64decode(b_string + "=" * (-len(b_string) % 4))).decode("ascii")
        try:
            f_msg_id, l_msg_id, f_chat_id, protect = decoded.split("_", 3)
        except:
            f_msg_id, l_msg_id, f_chat_id = decoded.split("_", 2)
            protect = "/pbatch" if PROTECT_CONTENT else "batch"
        diff = int(l_msg_id) - int(f_msg_id)
        async for msg in client.iter_messages(int(f_chat_id), int(l_msg_id), int(f_msg_id)):
            if msg.media:
                media = getattr(msg, msg.media.value)
                if BATCH_FILE_CAPTION:
                    try:
                        f_caption=BATCH_FILE_CAPTION.format(file_name=getattr(media, 'file_name', ''), file_size=getattr(media, 'file_size', ''), file_caption=getattr(msg, 'caption', ''))
                    except Exception as e:
                        logger.exception(e)
                        f_caption = getattr(msg, 'caption', '')
                else:
                    media = getattr(msg, msg.media.value)
                    file_name = getattr(media, 'file_name', '')
                    f_caption = getattr(msg, 'caption', file_name)
                try:
                    await msg.copy(message.chat.id, caption=f_caption, protect_content=True if protect == "/pbatch" else False)
                except FloodWait as e:
                    await asyncio.sleep(e.x)
                    await msg.copy(message.chat.id, caption=f_caption, protect_content=True if protect == "/pbatch" else False)
                except Exception as e:
                    logger.exception(e)
                    continue
            elif msg.empty:
                continue
            else:
                try:
                    await msg.copy(message.chat.id, protect_content=True if protect == "/pbatch" else False)
                except FloodWait as e:
                    await asyncio.sleep(e.x)
                    await msg.copy(message.chat.id, protect_content=True if protect == "/pbatch" else False)
                except Exception as e:
                    logger.exception(e)
                    continue
            await asyncio.sleep(1) 
        return await sts.delete()

    if data.startswith("sendfiles"):
        chat_id = int("-" + file_id.split("-")[1])
        userid = message.from_user.id if message.from_user else None
        st = await client.get_chat_member(chat_id, userid)
        if (
                st.status != enums.ChatMemberStatus.ADMINISTRATOR
                and st.status != enums.ChatMemberStatus.OWNER
        ):
            g = await get_shortlink(chat_id, f"https://telegram.me/{temp.U_NAME}?start=allfiles_{file_id}", True)
        else:
            g = await get_shortlink(chat_id, f"https://telegram.me/{temp.U_NAME}?start=allfiles_{file_id}", False)
        k = await client.send_message(chat_id=message.from_user.id,text=f"<b>Get All Files in a Single Click!!!\n\n♻️ ʟɪɴᴋ ➠ {g}</b>", reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton('♻️ Download Link ♻️', url=g)
                    ], [
                        InlineKeyboardButton('❓ How To Download ❓', url=f'https://telegram.me/{TUTORIAL}')
                    ]
                ]
            )
        )
        await asyncio.sleep(900)
        await k.edit("<b>Link Deleted!</b>")
        return
        
    elif data.startswith("short"):
        user = message.from_user.id
        chat_id = temp.SHORT.get(user)
        files_ = await get_file_details(file_id)
        files = files_[0]
        cleaned_file_name = f"{' '.join(filter(lambda x: not x.startswith('www.') and not x.startswith('@'), files.file_name.split()))}"
        g = await get_shortlink(chat_id, f"https://telegram.me/{temp.U_NAME}?start=file_{file_id}")
        k = await client.send_message(chat_id=user,text=f'<b>[ {get_size(files.file_size)} ] <a href="https://telegram.me/HEROFLiX">{cleaned_file_name}</a> \n\n📗 Download Link ➔ {g} {g}</b>', reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton('♻️ Download Link ♻️', url=g)
                    ], [
                        InlineKeyboardButton('❓ How To Download ❓', url=f'https://telegram.me/{TUTORIAL}')
                    ], [
                        InlineKeyboardButton('🌟 Direct Download 🌟', url="https://telegram.me/HeroFlixx/49")
                    ]
                ]
            )
        )
        await asyncio.sleep(900)
        await k.edit("<b>Link Deleted!</b>")
        return
        
    elif data.startswith("all"):
        files = temp.GETALL.get(file_id)
        if not files:
            return await message.reply('<b><i>No such file exist.</b></i>')
        filesarr = []
        for file in files:
            file_id = file.file_id
            files_ = await get_file_details(file_id)
            files1 = files_[0]
            title = ' '.join(filter(lambda x: not x.startswith('www.') and not x.startswith('@'), files1.file_name.split()))
            size=get_size(files1.file_size)
            f_caption=files1.caption
            if CUSTOM_FILE_CAPTION:
                try:
                    f_caption=CUSTOM_FILE_CAPTION.format(file_name= '' if title is None else title, file_size='' if size is None else size, file_caption='' if f_caption is None else f_caption)
                except Exception as e:
                    logger.exception(e)
                    f_caption=f_caption
            if f_caption is None:
                f_caption = f"{' '.join(filter(lambda x: not x.startswith('www.') and not x.startswith('@'), files1.file_name.split()))}"

            msg = await client.send_cached_media(
                chat_id=message.from_user.id,
                file_id=file_id,
                caption=f_caption,
                protect_content=True if pre == 'filep' else False,
                reply_markup=InlineKeyboardMarkup(
                    [
                     [
                      InlineKeyboardButton('🔆彡⟨ HEROFLiX ⟩彡🔆', url=f'https://telegram.me/{CHNL_LNK}'),
                     ]
                    ]
                )
            )
            filesarr.append(msg)
        await k.edit_text("<b>File Deleted!</b>")
        return    
        
    elif data.startswith("files"):
        user = message.from_user.id
        if temp.SHORT.get(user)==None:
            await message.reply_text(text="<b>Link Expired, Search Again in Group!</b>")
            return
        else:
            chat_id = temp.SHORT.get(user)
        settings = await get_settings(chat_id)
        if settings['is_shortlink'] and user not in PREMIUM_USER:
            files_ = await get_file_details(file_id)
            files = files_[0]
            g = await get_shortlink(chat_id, f"https://telegram.me/{temp.U_NAME}?start=file_{file_id}")
            cleaned_file_name = f"{' '.join(filter(lambda x: not x.startswith('www.') and not x.startswith('@'), files.file_name.split()))}"
            k = await client.send_message(chat_id=message.from_user.id,text=f'<b>[ {get_size(files.file_size)} ] <a href="https://telegram.me/HEROFLiX">{cleaned_file_name}</a> \n\n📗 Download Link ➠ {g} {g}</b>', reply_markup=InlineKeyboardMarkup(
                [
                        [
                            InlineKeyboardButton('♻️ Download Link ♻️', url=g)
                        ], [
                            InlineKeyboardButton('❓ How To Download ❓', url=f"https://telegram.me/{TUTORIAL}")
                        ], [
                            InlineKeyboardButton('🌟 Direct Download 🌟', url="https://telegram.me/HeroFlixx/49")
                        ]
                    ]
                )
            )
            await asyncio.sleep(900)
            try:
                await k.edit_text("Link Deleted!")
            except Exception:
                pass
            return
    user = message.from_user.id
    files_ = await get_file_details(file_id)           
    if not files_:
        pre, file_id = ((base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))).decode("ascii")).split("_", 1)
        try:

            msg = await client.send_cached_media(
                chat_id=message.from_user.id,
                file_id=file_id,
                protect_content=True if pre == 'filep' else False,
                reply_markup=InlineKeyboardMarkup(
                    [
                     [
                      InlineKeyboardButton('🔆彡⟨ HEROFLiX ⟩彡🔆', url=f'https://telegram.me/{CHNL_LNK}'),
                     ]
                    ]
                )
            )
            filetype = msg.media
            file = getattr(msg, filetype.value)
            title = '' + ' '.join(filter(lambda x: not x.startswith('www.') and not x.startswith('@'), file.file_name.split()))
            size=get_size(file.file_size)
            f_caption = f"<code>{title}</code>"
            if CUSTOM_FILE_CAPTION:
                try:
                    f_caption=CUSTOM_FILE_CAPTION.format(file_name= '' if title is None else title, file_size='' if size is None else size, file_caption='')
                except:
                    return
            await msg.edit_caption(f_caption)
            btn = [[
                InlineKeyboardButton("Get File Again", callback_data=f'delfile#{file_id}')
            ]]
            await k.edit_text("<b>Your File/Video is deleted!!!\n\nClick below button to get your deleted file 👇</b>",reply_markup=InlineKeyboardMarkup(btn))
            return
        except:
            pass
        return await message.reply('No such file exist.')
    files = files_[0]
    title = '' + ' '.join(filter(lambda x: not x.startswith('www.') and not x.startswith('@'), files.file_name.split()))
    size=get_size(files.file_size)
    f_caption=files.caption
    if CUSTOM_FILE_CAPTION:
        try:
            f_caption=CUSTOM_FILE_CAPTION.format(file_name= '' if title is None else title, file_size='' if size is None else size, file_caption='' if f_caption is None else f_caption)
        except Exception as e:
            logger.exception(e)
            f_caption=f_caption
    if f_caption is None:
        f_caption = f"{' '.join(filter(lambda x: not x.startswith('www.') and not x.startswith('@'), files.file_name.split()))}"

    msg = await client.send_cached_media(
        chat_id=message.from_user.id,
        file_id=file_id,
        caption=f_caption,
        protect_content=True if pre == 'filep' else False,
        reply_markup=InlineKeyboardMarkup(
            [
             [
              InlineKeyboardButton('🔆彡⟨ HEROFLiX ⟩彡🔆', url=f'https://telegram.me/{CHNL_LNK}'),
             ]
            ]
        )
    )
    return   

@Client.on_message(filters.command('channel') & filters.user(ADMINS))
async def channel_info(bot, message):
           
    """Send basic information of channel"""
    if isinstance(CHANNELS, (int, str)):
        channels = [CHANNELS]
    elif isinstance(CHANNELS, list):
        channels = CHANNELS
    else:
        raise ValueError("Unexpected type of CHANNELS")

    text = '📑 **Indexed channels/groups**\n'
    for channel in channels:
        chat = await bot.get_chat(channel)
        if chat.username:
            text += '\n@' + chat.username
        else:
            text += '\n' + chat.title or chat.first_name

    text += f'\n\n**Total:** {len(CHANNELS)}'

    if len(text) < 4096:
        await message.reply(text)
    else:
        file = 'Indexed channels.txt'
        with open(file, 'w') as f:
            f.write(text)
        await message.reply_document(file)
        os.remove(file)

@Client.on_message(filters.command('logs') & filters.user(ADMINS))
async def log_file(bot, message):
    """Send log file"""
    try:
        await message.reply_document('TelegramBot.log')
    except Exception as e:
        await message.reply(str(e))

@Client.on_message(filters.command('delete') & filters.user(ADMINS))
async def delete(bot, message):
    """Delete file from database"""
    reply = message.reply_to_message
    if reply and reply.media:
        msg = await message.reply("Processing...⏳", quote=True)
    else:
        await message.reply('Reply to file with /delete which you want to delete', quote=True)
        return

    for file_type in ("document", "video", "audio"):
        media = getattr(reply, file_type, None)
        if media is not None:
            break
    else:
        await msg.edit('This is not supported file format')
        return
    
    file_id, file_ref = unpack_new_file_id(media.file_id)

    result = await Media.collection.delete_one({
        '_id': file_id,
    })
    if result.deleted_count:
        await msg.edit('🛃 Deleted File!')
    else:
        file_name = re.sub(r"(_|\-|\.|\+)", " ", str(media.file_name))
        result = await Media.collection.delete_many({
            'file_name': file_name,
            'file_size': media.file_size,
            'mime_type': media.mime_type
            })
        if result.deleted_count:
            await msg.edit('🛃 Deleted File!')
        else:
            # files indexed before https://github.com/EvamariaTG/EvaMaria/commit/f3d2a1bcb155faf44178e5d7a685a1b533e714bf#diff-86b613edf1748372103e94cacff3b578b36b698ef9c16817bb98fe9ef22fb669R39 
            # have original file name.
            result = await Media.collection.delete_many({
                'file_name': media.file_name,
                'file_size': media.file_size,
                'mime_type': media.mime_type
            })
            if result.deleted_count:
                await msg.edit('🛃 Deleted File!')
            else:
                await msg.edit('File not found in database')

@Client.on_message(filters.command('deleteall') & filters.user(ADMINS))
async def delete_all_index(bot, message):
    await message.reply_text(
        'This will delete all indexed files.\nDo you want to continue??',
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text="🛃 Delete Files!", callback_data="autofilter_delete"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="💢 Cancel 💢", callback_data="close_data"
                    )
                ],
            ]
        ),
        quote=True,
    )

@Client.on_callback_query(filters.regex(r'^autofilter_delete'))
async def delete_all_index_confirm(bot, message):
    await Media.collection.drop()
    await message.answer('Piracy Is Crime')
    await message.message.edit('Succesfully Deleted All The Indexed Files.')

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
            except:
                await message.reply_text("Make sure I'm present in your group!!", quote=True)
                return
        else:
            await message.reply_text("I'm not connected to any groups!", quote=True)
            return

    elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        grp_id = message.chat.id
        title = message.chat.title

    else:
        return

    st = await client.get_chat_member(grp_id, userid)
    if (
            st.status != enums.ChatMemberStatus.ADMINISTRATOR
            and st.status != enums.ChatMemberStatus.OWNER
            and str(userid) not in ADMINS
    ):
        return
    
    settings = await get_settings(grp_id)

    try:
        if settings['max_btn']:
            settings = await get_settings(grp_id)
    except KeyError:
        await save_group_settings(grp_id, 'max_btn', False)
        settings = await get_settings(grp_id)
    if 'is_shortlink' not in settings.keys():
        await save_group_settings(grp_id, 'is_shortlink', False)
    else:
        pass

    if settings is not None:
        buttons = [
            [
                InlineKeyboardButton(
                    'Rᴇsᴜʟᴛ Pᴀɢᴇ',
                    callback_data=f'setgs#button#{settings["button"]}#{grp_id}',
                ),
                InlineKeyboardButton(
                    'Bᴜᴛᴛᴏɴ' if settings["button"] else 'Tᴇxᴛ',
                    callback_data=f'setgs#button#{settings["button"]}#{grp_id}',
                ),
            ],
            [
                InlineKeyboardButton(
                    'Fɪʟᴇ Sᴇɴᴅ Mᴏᴅᴇ',
                    callback_data=f'setgs#botpm#{settings["botpm"]}#{grp_id}',
                ),
                InlineKeyboardButton(
                    'Mᴀɴᴜᴀʟ Sᴛᴀʀᴛ' if settings["botpm"] else 'Aᴜᴛᴏ Sᴇɴᴅ',
                    callback_data=f'setgs#botpm#{settings["botpm"]}#{grp_id}',
                ),
            ],
            [
                InlineKeyboardButton(
                    'Pʀᴏᴛᴇᴄᴛ Cᴏɴᴛᴇɴᴛ',
                    callback_data=f'setgs#file_secure#{settings["file_secure"]}#{grp_id}',
                ),
                InlineKeyboardButton(
                    '✔ Oɴ' if settings["file_secure"] else '✘ Oғғ',
                    callback_data=f'setgs#file_secure#{settings["file_secure"]}#{grp_id}',
                ),
            ],
            [
                InlineKeyboardButton(
                    'Sᴘᴇʟʟ Cʜᴇᴄᴋ',
                    callback_data=f'setgs#spell_check#{settings["spell_check"]}#{grp_id}',
                ),
                InlineKeyboardButton(
                    '✔ Oɴ' if settings["spell_check"] else '✘ Oғғ',
                    callback_data=f'setgs#spell_check#{settings["spell_check"]}#{grp_id}',
                ),
            ],
            [
                InlineKeyboardButton(
                    'Wᴇʟᴄᴏᴍᴇ Msɢ',
                    callback_data=f'setgs#welcome#{settings["welcome"]}#{grp_id}',
                ),
                InlineKeyboardButton(
                    '✔ Oɴ' if settings["welcome"] else '✘ Oғғ',
                    callback_data=f'setgs#welcome#{settings["welcome"]}#{grp_id}',
                ),
            ],
            [
                InlineKeyboardButton(
                    'Aᴜᴛᴏ-Dᴇʟᴇᴛᴇ',
                    callback_data=f'setgs#auto_delete#{settings["auto_delete"]}#{grp_id}',
                ),
                InlineKeyboardButton(
                    '10 Mɪns' if settings["auto_delete"] else '✘ Oғғ',
                    callback_data=f'setgs#auto_delete#{settings["auto_delete"]}#{grp_id}',
                ),
            ],
            [
                InlineKeyboardButton(
                    'Aᴜᴛᴏ-Fɪʟᴛᴇʀ',
                    callback_data=f'setgs#auto_ffilter#{settings["auto_ffilter"]}#{grp_id}',
                ),
                InlineKeyboardButton(
                    '✔ Oɴ' if settings["auto_ffilter"] else '✘ Oғғ',
                    callback_data=f'setgs#auto_ffilter#{settings["auto_ffilter"]}#{grp_id}',
                ),
            ],
            [
                InlineKeyboardButton(
                    'Mᴀx Bᴜᴛᴛᴏɴs',
                    callback_data=f'setgs#max_btn#{settings["max_btn"]}#{grp_id}',
                ),
                InlineKeyboardButton(
                    '10' if settings["max_btn"] else f'{MAX_B_TN}',
                    callback_data=f'setgs#max_btn#{settings["max_btn"]}#{grp_id}',
                ),
            ],
            [
                InlineKeyboardButton(
                    'ShortLink',
                    callback_data=f'setgs#is_shortlink#{settings["is_shortlink"]}#{grp_id}',
                ),
                InlineKeyboardButton(
                    '✔ Oɴ' if settings["is_shortlink"] else '✘ Oғғ',
                    callback_data=f'setgs#is_shortlink#{settings["is_shortlink"]}#{grp_id}',
                ),
            ],
        ]

        btn = [[
                InlineKeyboardButton("Oᴘᴇɴ Hᴇʀᴇ ↓", callback_data=f"opnsetgrp#{grp_id}"),
                InlineKeyboardButton("Oᴘᴇɴ Iɴ PM ⇲", callback_data=f"opnsetpm#{grp_id}")
              ]]

        reply_markup = InlineKeyboardMarkup(buttons)
        if chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
            await message.reply_text(
                text="<b>Dᴏ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴏᴘᴇɴ sᴇᴛᴛɪɴɢs ʜᴇʀᴇ ?</b>",
                reply_markup=InlineKeyboardMarkup(btn),
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML,
                reply_to_message_id=message.id
            )
        else:
            await message.reply_text(
                text=f"<b>Sᴇᴛᴛɪɴɢs Fᴏʀ {title}</b>",
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML,
                reply_to_message_id=message.id
            )

@Client.on_message(filters.command("deletefiles") & filters.user(ADMINS))
async def deletemultiplefiles(bot, message):
    chat_type = message.chat.type
    if chat_type != enums.ChatType.PRIVATE:
        return await message.reply_text(f"<b>Only Works in PM !</b>")
    else:
        pass
    try:
        keyword = message.text.split(" ", 1)[1]
    except:
        return await message.reply_text(f"<b>Hey {message.from_user.mention}, Give me a keyword along with the command to delete files.</b>")
    k = await bot.send_message(chat_id=message.chat.id, text=f"<b>♻️ Please Wait!</b>")
    files, total = await get_bad_files(keyword)
    await k.delete()
    btn = [[
       InlineKeyboardButton("🛃 Delete Files!", callback_data=f"killfilesdq#{keyword}")
       ],[
       InlineKeyboardButton("💢 Cancel 💢", callback_data="close_data")
    ]]
    await message.reply_text(
        text=f"<b>{total} Files ➠ {keyword}</b>",
        reply_markup=InlineKeyboardMarkup(btn),
        parse_mode=enums.ParseMode.HTML
    )

@Client.on_message(filters.command("shortlink"))
async def shortlink(bot, message):
    userid = message.from_user.id if message.from_user else None
    if not userid:
        return await message.reply(f"You are anonymous admin. Turn off anonymous admin and try again this command")
    chat_type = message.chat.type
    if chat_type == enums.ChatType.PRIVATE:
        return await message.reply_text(f"<b>Only works in groups !</b>")
    elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        grpid = message.chat.id
        title = message.chat.title
    else:
        return
    data = message.text
    userid = message.from_user.id
    user = await bot.get_chat_member(grpid, userid)
    if user.status != enums.ChatMemberStatus.ADMINISTRATOR and user.status != enums.ChatMemberStatus.OWNER and str(userid) not in ADMINS:
        return await message.reply_text("<b>You don't have access to use this command!\n\nAdd Me to Your Own Group as Admin and Try This Command\n\nFor More PM Me With This Command</b>")
    else:
        pass
    try:
        command, shortlink_url, api = data.split(" ")
    except:
        return await message.reply_text("<b>Wrong Format. Example - /shortlink omnifly.in 1f1da5c9df9a58058672ac8d8134e203b03426a1</b>")
    reply = await message.reply_text("<b>Please Wait...</b>")
    shortlink_url = re.sub(r"https?://?", "", shortlink_url)
    shortlink_url = re.sub(r"[:/]", "", shortlink_url)
    await save_group_settings(grpid, 'shortlink', shortlink_url)
    await save_group_settings(grpid, 'shortlink_api', api)
    await save_group_settings(grpid, 'is_shortlink', True)
    await reply.edit_text(f"<b>Successfully added shortlink API for {title}.\n\nCurrent Shortlink Website: <code>{shortlink_url}</code>\nCurrent API: <code>{api}</code></b>")
    
@Client.on_message(filters.command("restart") & filters.user(ADMINS))
async def stop_button(bot, message):
    msg = await bot.send_message(text="**🔄 𝙱𝙾𝚃 𝙸𝚂 𝚁𝙴𝚂𝚃𝙰𝚁𝚃𝙸𝙽𝙶**", chat_id=message.chat.id)       
    await asyncio.sleep(3)
    await msg.edit("**✅️ 𝙱𝙾𝚃 𝙸𝚂 𝚁𝙴𝚂𝚃𝙰𝚁𝚃𝙴𝙳**")
    os.execl(sys.executable, sys.executable, *sys.argv)

# ==========================================
# MINIMAL INTEGRATED PREMIUM SYSTEM & WORKFLOW
# ==========================================
@Client.on_message(filters.command("premium") & filters.private)
@Client.on_callback_query(filters.regex("^buy_premium_start$"))
async def minimal_premium_command(client, update):
    message = update.message if isinstance(update, CallbackQuery) else update
    if isinstance(update, CallbackQuery):
        await update.answer()

    plan_name = "30 Days"
    price = "39"
    
    upi_link = (
        f"upi://pay?"
        f"pa={quote(UPI_ID)}"
        f"&pn={quote('HeroFlix')}"
        f"&am={price}"
        f"&cu=INR"
        f"&tn={quote(f'HeroFlix Premium | {plan_name} | ₹{price}')}"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Pay Now", url="https://fireluci.github.io/pay/")],
        [InlineKeyboardButton("✅ I Have Paid (Send Screenshot)", callback_data="minimal_send_proof")]
    ])
    
    text = (
        f"🛒 **Plan:** {plan_name}\n"
        f"💰 **Price:** ₹{price}\n\n"
        f"📱 **UPI ID:** `{UPI_ID}`\n\n"
        f"Tap **Pay Now** to complete your payment, then click **I Have Paid** below to send your screenshot."
    )
    
    if isinstance(update, CallbackQuery):
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.reply_text(text, reply_markup=kb)

@Client.on_callback_query(filters.regex("^minimal_send_proof$"))
async def minimal_send_proof_cb(client, callback: CallbackQuery):
    user_id = callback.from_user.id
    MINIMAL_PENDING_FLOW[user_id] = {
        "plan": "30 Days",
        "price": "39"
    }
    await callback.answer()
    await callback.message.edit_text(
        "📸 **Please send your payment screenshot now in this chat.**\n\n"
        "Your request will be forwarded to the admin immediately after you upload the image."
    )

@Client.on_message(filters.private & filters.photo & ~filters.command(["start", "premium"]))
async def minimal_screenshot_handler(client, message):
    user_id = message.from_user.id
    if user_id not in MINIMAL_PENDING_FLOW:
        return
    
    flow = MINIMAL_PENDING_FLOW.pop(user_id)
    plan = flow["plan"]
    price = flow["price"]
    
    await message.reply_text("✅ Payment proof submitted! Please wait for admin verification.")
    
    user_name = message.from_user.first_name or "Unknown"
    username = f"@{message.from_user.username}" if message.from_user.username else "None"
    
    admin_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"min_app_{user_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"min_rej_{user_id}")
        ]
    ])
    
    admin_text = (
        f"🔔 **New Payment Verification**\n\n"
        f"👤 Name: {user_name}\n"
        f"🆔 User ID: `{user_id}`\n"
        f"📦 Plan: {plan}\n"
        f"💰 Amount: ₹{price}"
    )
    
    for admin_id in ADMINS:
        try:
            await client.send_photo(admin_id, message.photo.file_id, caption=admin_text, reply_markup=admin_kb)
        except Exception as e:
            logger.error(f"Failed to send minimal payment proof to admin {admin_id}: {e}")

@Client.on_callback_query(filters.regex("^min_app_"))
async def minimal_admin_action_cb(client, callback: CallbackQuery):
    if str(callback.from_user.id) not in map(str, ADMINS):
        return await callback.answer("Unauthorized.", show_alert=True)
    
    parts = callback.data.split("_")
    target_user_str = parts[2] if len(parts) > 2 else parts[-1]
    target_user_id = int(target_user_str)
    
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟣 30 Days (₹39)", callback_data=f"selplan_{target_user_id}_30_39"),
            InlineKeyboardButton("🟣 90 Days (₹99)", callback_data=f"selplan_{target_user_id}_90_99")
        ],
        [
            InlineKeyboardButton("🟣 180 Days (₹179)", callback_data=f"selplan_{target_user_id}_180_179"),
            InlineKeyboardButton("🟣 365 Days (₹299)", callback_data=f"selplan_{target_user_id}_365_299")
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data=f"min_rej_{target_user_id}")
        ]
    ])
    
    await callback.answer()
    try:
        await callback.message.edit_caption(
            "💎 **Select Premium Plan**\n\nChoose the subscription to activate.",
            reply_markup=kb,
            parse_mode=enums.ParseMode.MARKDOWN
        )
    except Exception:
        await callback.message.edit_text(
            "💎 **Select Premium Plan**\n\nChoose the subscription to activate.",
            reply_markup=kb,
            parse_mode=enums.ParseMode.MARKDOWN
        )

@Client.on_callback_query(filters.regex("^selplan_"))
async def select_plan_cb(client, callback: CallbackQuery):
    if str(callback.from_user.id) not in map(str, ADMINS):
        return await callback.answer("Unauthorized.", show_alert=True)
    
    _, target_user_str, days_str, price_str = callback.data.split("_")
    target_user_id = int(target_user_str)
    days = int(days_str)
    price = price_str
    
    now = datetime.utcnow()
    
    existing_user = None
    if 'users_col' in globals():
        existing_user = await users_col.find_one({"user_id": target_user_id})
    elif 'db' in globals() and hasattr(db, 'premium_users'):
        existing_user = await db.premium_users.find_one({"user_id": target_user_id})
        
    current_expiry = None
    if existing_user:
        current_expiry = existing_user.get("expires_at") or existing_user.get("expiry_date")
        
    is_active_renewal = False
    if current_expiry and isinstance(current_expiry, datetime) and current_expiry > now:
        start_date = current_expiry
        is_active_renewal = True
    else:
        start_date = now
        
    expiry_date = start_date + timedelta(days=days)
    
    if is_active_renewal:
        mode_text = "🔄 Extend Existing"
    else:
        mode_text = "🟢 Fresh Activation"
    
    try:
        target_user = await client.get_users(target_user_id)
        username = f"@{target_user.username}" if target_user.username else str(target_user_id)
    except Exception:
        username = str(target_user_id)
    
    pending_state = {
        "user_id": target_user_id,
        "username": username,
        "plan": f"{days} Days",
        "price": price,
        "days": days,
        "start_date": start_date,
        "expiry_date": expiry_date,
        "is_active_renewal": is_active_renewal,
        "current_expiry": current_expiry,
        "updated_at": now
    }
    
    if 'db' in globals() and hasattr(db, 'premium_pending'):
        await db.premium_pending.update_one({"user_id": target_user_id}, {"$set": pending_state}, upsert=True)
    elif 'users_col' in globals():
        db_ref = users_col.database
        await db_ref.premium_pending.update_one({"user_id": target_user_id}, {"$set": pending_state}, upsert=True)
    
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm", callback_data=f"confact_{target_user_id}"),
            InlineKeyboardButton("◀ Back", callback_data=f"min_app_{target_user_id}")
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data=f"min_rej_{target_user_id}")
        ]
    ])
    
    preview_text = (
        f"💎 **Premium Activation Preview**\n\n"
        f"👤 **User**: {username}\n"
        f"🆔 **User ID**: `{target_user_id}`\n"
        f"📦 **New Plan**: {days} Days\n"
        f"💰 **Amount**: ₹{price}\n"
        f"⚙️ **Mode**: {mode_text}\n"
    )
    
    if is_active_renewal and current_expiry:
        preview_text += (
            f"📅 **Current Expiry**: {current_expiry.strftime('%d %b %Y')}\n"
            f"⌛ **Result Expiry**: {expiry_date.strftime('%d %b %Y')}\n"
        )
    else:
        preview_text += (
            f"📅 **Current Expiry**: Expired\n"
            f"⌛ **Result Expiry**: {expiry_date.strftime('%d %b %Y')}\n"
        )
        
    preview_text += "\nProceed with activation?"
    
    await callback.answer()
    try:
        await callback.message.edit_caption(preview_text, reply_markup=kb, parse_mode=enums.ParseMode.MARKDOWN)
    except Exception:
        await callback.message.edit_text(preview_text, reply_markup=kb, parse_mode=enums.ParseMode.MARKDOWN)

@Client.on_callback_query(filters.regex("^confact_"))
async def confirm_activation_cb(client, callback: CallbackQuery):
    if str(callback.from_user.id) not in map(str, ADMINS):
        return await callback.answer("Unauthorized.", show_alert=True)
    
    _, target_user_str = callback.data.split("_")
    target_user_id = int(target_user_str)
    
    flow = None
    if 'db' in globals() and hasattr(db, 'premium_pending'):
        flow = await db.premium_pending.find_one({"user_id": target_user_id})
    elif 'users_col' in globals():
        db_ref = users_col.database
        flow = await db_ref.premium_pending.find_one({"user_id": target_user_id})
        
    if not flow:
        return await callback.answer("Activation session expired or already processed.", show_alert=True)
        
    plan = flow["plan"]
    price = flow["price"]
    days = flow["days"]
    start_date = flow["start_date"]
    expiry_date = flow["expiry_date"]
    username = flow["username"]
    
    await callback.answer("Processing activation...")
    now = datetime.utcnow()
    
    # Simplified reminder state containing only the 1_day flag
    reminders_state = {
        "1_day": False
    }
    
    activation_data = {
        "user_id": target_user_id,
        "username": username,
        "plan": plan,
        "plan_days": days,
        "price": price,
        "purchased_at": now,
        "start_date": start_date,
        "expires_at": expiry_date,
        "expiry_date": expiry_date,
        "active": True,
        "status": "active",
        "approved_by": callback.from_user.id,
        "approved_at": now,
        "reminders": reminders_state
    }
    
    if 'users_col' in globals():
        await users_col.update_one({"user_id": target_user_id}, {"$set": activation_data}, upsert=True)
        db_ref = users_col.database
        await db_ref.premium_pending.delete_one({"user_id": target_user_id})
    elif 'db' in globals() and hasattr(db, 'premium_users'):
        await db.premium_users.update_one({"user_id": target_user_id}, {"$set": activation_data}, upsert=True)
        await db.premium_pending.delete_one({"user_id": target_user_id})
        
    invite_link = None
    if PREMIUM_GROUP_ID:
        try:
            link_obj = await client.create_chat_invite_link(
                chat_id=PREMIUM_GROUP_ID,
                member_limit=1,
                expire_date=now + timedelta(hours=24)
            )
            invite_link = link_obj.invite_link
        except Exception as e:
            logger.error(f"Failed to create invite link for {target_user_id}: {e}")
            
    user_msg = (
        f"🎉 **HeroFlix Premium Activated**\n\n"
        f"📦 **Plan**: {plan}\n"
        f"📅 **Start**: {start_date.strftime('%d %b %Y')}\n"
        f"⌛ **Expires**: {expiry_date.strftime('%d %b %Y')}\n\n"
    )
    if invite_link:
        user_msg += f"👇 **Join Premium Group**\n{invite_link}\n\n"
    user_msg += "Enjoy your Premium Membership."
    
    try:
        await client.send_message(target_user_id, user_msg, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Failed to notify user {target_user_id}: {e}")
        
    success_admin_text = (
        f"✅ **Premium Activated**\n\n"
        f"• **User**: {username} (`{target_user_id}`)\n"
        f"• **Plan**: {plan} (₹{price})\n"
        f"• **Started**: {start_date.strftime('%d %b %Y')}\n"
        f"• **Expires**: {expiry_date.strftime('%d %b %Y')}\n"
        f"• **Admin ID**: `{callback.from_user.id}`\n"
        f"• **Activation Time**: {now.strftime('%d %b %Y, %H:%M:%S UTC')}\n"
        f"• **Invite Link**: Generated\n"
        f"• **Database**: Updated\n"
        f"• **Notification**: Sent"
    )
    
    try:
        await callback.message.edit_caption(success_admin_text, reply_markup=None, parse_mode=enums.ParseMode.MARKDOWN)
    except Exception:
        await callback.message.edit_text(success_admin_text, reply_markup=None, parse_mode=enums.ParseMode.MARKDOWN)
        
    logger.info(
        f"✅ Premium Activated | User: {target_user_id} ({username}) | Plan: {plan} | "
        f"Price: ₹{price} | Start: {start_date.strftime('%Y-%m-%d')} | "
        f"Expiry: {expiry_date.strftime('%Y-%m-%d')} | Admin: {callback.from_user.id} | Time: {now.strftime('%Y-%m-%d %H:%M:%S')}"
    )

@Client.on_callback_query(filters.regex("^min_rej_"))
async def minimal_admin_reject_cb(client, callback: CallbackQuery):
    if str(callback.from_user.id) not in map(str, ADMINS):
        return await callback.answer("Unauthorized.", show_alert=True)
    
    parts = callback.data.split("_")
    target_user_str = parts[2] if len(parts) > 2 else parts[-1]
    target_user_id = int(target_user_str)
    
    if 'db' in globals() and hasattr(db, 'premium_pending'):
        await db.premium_pending.delete_one({"user_id": target_user_id})
    elif 'users_col' in globals():
        db_ref = users_col.database
        await db_ref.premium_pending.delete_one({"user_id": target_user_id})
    
    await callback.answer("Rejected.")
    try:
        await callback.message.edit_caption(f"{callback.message.caption or ''}\n\n❌ **Status:** REJECTED", reply_markup=None, parse_mode=enums.ParseMode.MARKDOWN)
    except Exception:
        try:
            await callback.message.edit_text(f"{callback.message.text or ''}\n\n❌ **Status:** REJECTED", reply_markup=None, parse_mode=enums.ParseMode.MARKDOWN)
        except Exception:
            pass
            
    try:
        await client.send_message(target_user_id, "Payment could not be verified. Please contact the admin.")
    except Exception:
        pass
