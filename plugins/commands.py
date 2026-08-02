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
from info import CHANNELS, ADMINS, AUTH_CHANNEL, LOG_CHANNEL, PICS, BATCH_FILE_CAPTION, CUSTOM_FILE_CAPTION, PROTECT_CONTENT, CHNL_LNK, FORCE, GRP_LNK, REQST_CHANNEL, SUPPORT_CHAT_ID, SUPPORT_CHAT, MAX_B_TN, SHORTLINK_API, SHORTLINK_URL, TUTORIAL, IS_TUTORIAL, PREMIUM_USER, UPI_ID, PREMIUM_GROUP_ID, PREMIUM_LOG_CHANNEL, PREMIUM_PERMANENT_LINK
from utils import get_settings, get_size, is_subscribed, save_group_settings, temp, get_shortlink, get_tutorial
from database.connections_mdb import active_connection
from pymongo.errors import PyMongoError
import re, sys
import json
import base64

logger = logging.getLogger(__name__)

BATCH_FILES = {}
MINIMAL_PENDING_FLOW = {}

# ==========================================
# HELPER: FORMAT IST TIME (12-Hour, No Seconds)
# ==========================================
def format_ist_time(dt: datetime) -> str:
    if not isinstance(dt, datetime):
        return "N/A"
    ist_offset = timedelta(hours=5, minutes=30)
    ist_dt = dt + ist_offset
    return ist_dt.strftime('%d %b, %Y | %I:%M %p')

# ==========================================
# UNIFIED DATABASE COLLECTION HELPER
# ==========================================
def get_premium_collection():
    """Safely retrieves the premium users collection regardless of DB structure initialization."""
    try:
        if hasattr(db, 'premium_users') and db.premium_users is not None:
            return db.premium_users
        if hasattr(db, 'db') and hasattr(db.db, 'premium_users'):
            return db.db.premium_users
        if hasattr(db, 'get_collection'):
            return db.get_collection('premium_users')
    except Exception as e:
        logger.error(f"Error fetching premium collection: {e}")
    
    if 'users_col' in globals() and hasattr(users_col, 'database'):
        return users_col.database.premium_users
    return None

# ==========================================
# PREMIUM LOGGING HELPER (With Admin DM Fallback)
# ==========================================
async def log_premium_action(client: Client, text: str):
    """Helper to send important premium events to the dedicated premium log channel with admin fallback."""
    if not PREMIUM_LOG_CHANNEL:
        return
    try:
        await client.send_message(int(PREMIUM_LOG_CHANNEL), text, disable_web_page_preview=True, parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        if "PEER_ID_INVALID" in str(e) or "CHANNEL_INVALID" in str(e) or "CHAT_ADMIN_REQUIRED" in str(e):
            for admin_id in ADMINS:
                try:
                    await client.send_message(
                        int(admin_id), 
                        f"<b>⚠️ Log Channel Error Fallback</b>\n\nFailed to send log to <code>PREMIUM_LOG_CHANNEL</code> (<code>{PREMIUM_LOG_CHANNEL}</code>). Error: <code>{e}</code>\n\n--- Original Log ---\n\n{text}", 
                        disable_web_page_preview=True, 
                        parse_mode=enums.ParseMode.HTML
                    )
                except Exception as admin_err:
                    logger.error(f"Failed to send fallback log to admin {admin_id}: {admin_err}")
        else:
            logger.error(f"Failed to send log to PREMIUM_LOG_CHANNEL: {e}")

# ==========================================
# ROBUST EJECTION HELPER (Handles Ex-Admins & Non-Participants)
# ==========================================
async def safe_kick_user(client: Client, chat_id, user_id):
    if not chat_id:
        return
    try:
        chat_id_int = int(chat_id)
        try:
            peer = await client.resolve_peer(chat_id_int)
        except Exception:
            pass

        try:
            await client.promote_chat_member(
                chat_id=chat_id_int,
                user_id=user_id,
                is_anonymous=False,
                can_manage_chat=False,
                can_delete_messages=False,
                can_manage_video_chats=False,
                can_restrict_members=False,
                can_promote_members=False,
                can_change_info=False,
                can_invite_users=False,
                can_pin_messages=False
            )
        except Exception:
            pass

        await client.ban_chat_member(chat_id=chat_id_int, user_id=user_id)
        await asyncio.sleep(0.5)
        await client.unban_chat_member(chat_id=chat_id_int, user_id=user_id)
        
        try:
            user_obj = await client.get_users(user_id)
            p_name = user_obj.first_name or "User"
        except Exception:
            p_name = "User"
        logger.info(f"Successfully ejected user {p_name} (ID: {user_id}) from premium group {chat_id_int}")
    except Exception as e:
        if "USER_NOT_PARTICIPANT" in str(e) or "PEER_ID_INVALID" in str(e):
            logger.info(f"User ID {user_id} was not in the premium group.")
        else:
            logger.error(f"Failed to kick user ID {user_id} from premium group: {e}")
            await log_premium_action(
                client, 
                f"<b>⚠️ Warning: Failed to Kick User</b>\n\n"
                f"• <b>User ID</b>: <code>{user_id}</code>\n"
                f"• <b>Group ID</b>: <code>{chat_id}</code>\n"
                f"• <b>Error</b>: <code>{e}</code>"
            )

# ==========================================
# BACKGROUND LIFECYCLE & EXPIRY CHECKER LOOP
# ==========================================
async def premium_expiry_reminder_loop(client: Client):
    """Background loop checking expirations, running checks on boot and every interval."""
    await asyncio.sleep(5)
    while True:
        try:
            now = datetime.utcnow()
            col = get_premium_collection()
                
            if col is not None:
                try:
                    cursor = col.find({"active": True})
                    async for user_doc in cursor:
                        user_id = user_doc.get("user_id")
                        expires_at = user_doc.get("expires_at") or user_doc.get("expiry_date")
                        
                        if not expires_at or not isinstance(expires_at, datetime):
                            continue
                            
                        reminders = user_doc.get("reminders", {})
                        
                        if now >= expires_at:
                            await col.delete_one({"user_id": user_id})
                            
                            try:
                                u_obj = await client.get_users(user_id)
                                u_name = u_obj.first_name or "User"
                            except Exception:
                                u_name = "User"
                                
                            logger.info(f"🔄 Expired and removed premium record for {u_name} (ID: {user_id})")

                            if PREMIUM_GROUP_ID:
                                await safe_kick_user(client, PREMIUM_GROUP_ID, user_id)
                                
                            ist_expiry = format_ist_time(expires_at)
                            log_text = (
                                f"<b>❌ HeroFlix Premium Expired & Ejected</b>\n\n"
                                f"👤 <b>User</b>: <a href=\"tg://user?id={user_id}\">{u_name}</a> (<code>{user_id}</code>)\n"
                                f"⌛ <b>Expired At</b>: {ist_expiry} IST\n"
                                f"🚪 <b>Action</b>: Removed from database and kicked from group."
                            )
                            await log_premium_action(client, log_text)

                            expiry_kb = InlineKeyboardMarkup([
                                [InlineKeyboardButton("🔄 Renew Premium", callback_data="buy_premium_start")]
                            ])
                            expiry_msg = (
                                "<b>❌ HeroFlix Premium Expired</b>\n\n"
                                "Your Premium Membership has expired.\n\n"
                                "Tap below to renew."
                            )
                            try:
                                await client.send_message(user_id, expiry_msg, reply_markup=expiry_kb, parse_mode=enums.ParseMode.HTML)
                            except Exception as e:
                                logger.error(f"Failed to send expiry DM to user {user_id}: {e}")
                                
                        elif expires_at - now <= timedelta(days=1) and not reminders.get("1_day", False):
                            reminder_kb = InlineKeyboardMarkup([
                                [InlineKeyboardButton("🔄 Renew Premium", callback_data="buy_premium_start")]
                            ])
                            reminder_text = (
                                "<b>⚠ HeroFlix Premium</b>\n\n"
                                "Your Premium expires tomorrow.\n\n"
                                "Renew now to continue enjoying Premium without interruption."
                            )
                            try:
                                await client.send_message(user_id, reminder_text, reply_markup=reminder_kb, parse_mode=enums.ParseMode.HTML)
                                await col.update_one(
                                    {"user_id": user_id},
                                    {"$set": {"reminders.1_day": True}}
                                )
                            except Exception as e:
                                logger.error(f"Failed to send 1-day reminder to user {user_id}: {e}")
                except PyMongoError as db_err:
                    logger.error(f"Database error in expiry loop: {db_err}")
                    
        except Exception as e:
            logger.error(f"Error in premium expiry background task: {e}")
            
        await asyncio.sleep(30)

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
        buttons = [
            [InlineKeyboardButton("💎 Buy Premium", callback_data="buy_premium_start")]
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
            "<b>🔆 First Join Our Main Channel & Then Click Try Again ♻\n\n"
            "🔆 पहले हमारे मैन चैनल से जुड़ें और फिर Try Again दबाएँ ♻</b>",
            reply_markup=InlineKeyboardMarkup(btn),
            parse_mode=enums.ParseMode.HTML
        )
        return

    # === WEB-PAGE "I PAID" REDIRECT HANDLER ===
    if len(message.command) == 2 and message.command[1] == "i_paid":
        user_id = message.from_user.id
        MINIMAL_PENDING_FLOW[user_id] = {"status": "waiting_screenshot"}
        
        return await message.reply_text(
            "<b>📸 Please send your payment screenshot now in this chat.</b>\n\n"
            "Your request will be forwarded to the admin immediately.",
            parse_mode=enums.ParseMode.HTML
        )

    if len(message.command) == 2 and message.command[1] in ["subscribe", "error", "okay", "help"]:
        buttons = [
            [InlineKeyboardButton("💎 Buy Premium", callback_data="buy_premium_start")]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)      
        await message.reply_photo(
            photo=PICS,
            caption=script.START_TXT.format(message.from_user.mention, temp.U_NAME, temp.B_NAME),
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
        return
        
    # === PREMIUM ENFORCEMENT CHECK FOR FILES ===
    if len(message.command) == 2 and any(message.command[1].startswith(prefix) for prefix in ["file_", "allfiles_", "BATCH", "DSTORE"]):
        user_id = message.from_user.id
        if user_id not in ADMINS and user_id not in PREMIUM_USER:
            col = get_premium_collection()
            p_doc = None
            if col is not None:
                try:
                    p_doc = await col.find_one({"user_id": user_id, "active": True})
                except PyMongoError:
                    p_doc = None
            
            now = datetime.utcnow()
            is_active_premium = False
            if p_doc:
                exp = p_doc.get("expires_at") or p_doc.get("expiry_date")
                if exp and isinstance(exp, datetime) and exp > now:
                    is_active_premium = True
            
            if not is_active_premium:
                locked_kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("💎 Buy Premium to Access Files", callback_data="buy_premium_start")]
                ])
                return await message.reply_text(
                    "<b>🔒 Premium Required</b>\n\n"
                    "File downloading is restricted to <b>Premium Members</b> only.\n\n"
                    "Tap below to check plans and upgrade your account!",
                    reply_markup=locked_kb,
                    parse_mode=enums.ParseMode.HTML
                )

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
                    msgs = json.loads(file_data.read())
            except:
                await sts.edit("FAILED")
                return await client.send_message(LOG_CHANNEL, "UNABLE TO OPEN FILE.")
            os.remove(file)
            BATCH_FILES[file_id] = msgs
        for msg in msgs:
            title = msg.get("title")
            size = get_size(int(msg.get("size", 0)))
            f_caption = msg.get("caption", "")
            if BATCH_FILE_CAPTION:
                try:
                    f_caption = BATCH_FILE_CAPTION.format(file_name='' if title is None else title, file_size='' if size is None else size, file_caption='' if f_caption is None else f_caption)
                except Exception as e:
                    logger.exception(e)
                    f_caption = f_caption
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
        try:
            decoded_bytes = base64.urlsafe_b64decode(b_string + "=" * (-len(b_string) % 4))
            decoded = decoded_bytes.decode("utf-8")
        except (base64.binascii.Error, UnicodeDecodeError, ValueError):
            await sts.edit("<b>❌ Invalid or corrupted store link!</b>")
            return
            
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
                        InlineKeyboardButton('💎 Buy Premium', callback_data="buy_premium_start")
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
                                InlineKeyboardButton('💎 Buy Premium', callback_data="buy_premium_start")
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
        try:
            decoded_bytes = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
            decoded_string = decoded_bytes.decode("utf-8")
            pre, file_id = decoded_string.split("_", 1)
        except (base64.binascii.Error, UnicodeDecodeError, ValueError):
            return await message.reply('<b>❌ Invalid or corrupted file link!</b>')
            
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
            await message.reply_text("<b>Your File/Video is deleted!!!\n\nClick below button to get your deleted file 👇</b>",reply_markup=InlineKeyboardMarkup(btn))
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

    text = '<b>📑 Indexed channels/groups</b>\n'
    for channel in channels:
        chat = await bot.get_chat(channel)
        if chat.username:
            text += '\n@' + chat.username
        else:
            text += '\n' + (chat.title or chat.first_name)

    text += f'\n\n<b>Total:</b> {len(CHANNELS)}'

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

    try:
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
                result = await Media.collection.delete_many({
                    'file_name': media.file_name,
                    'file_size': media.file_size,
                    'mime_type': media.mime_type
                })
                if result.deleted_count:
                    await msg.edit('🛃 Deleted File!')
                else:
                    await msg.edit('File not found in database')
    except PyMongoError as e:
        await msg.edit(f'Database error during deletion: {e}')

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
    try:
        await Media.collection.drop()
        await message.answer('Piracy Is Crime')
        await message.message.edit('Succesfully Deleted All The Indexed Files.')
    except PyMongoError as e:
        await message.answer(f'Database error: {e}')

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
                    'Mᴀx Bᴜᴛᴛᴏns',
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
    msg = await bot.send_message(text="<b>🔄 𝙱𝙾𝚃 𝙸𝚂 𝚁𝙴𝚂𝚃𝙰𝚁𝚃𝙸𝙽𝙶</b>", chat_id=message.chat.id, parse_mode=enums.ParseMode.HTML)        
    await asyncio.sleep(3)
    await msg.edit("<b>✅️ 𝙱𝙾𝚃 𝙸𝚂 𝚁𝙴𝚂𝚃𝙰𝚁𝚃𝙴𝙳</b>", parse_mode=enums.ParseMode.HTML)
    os.execl(sys.executable, sys.executable, *sys.argv)

# ==========================================
# ADMIN TEXT COMMAND (/text userid message)
# ==========================================
@Client.on_message(filters.command("text") & filters.user(ADMINS))
async def admin_send_text_command(client, message):
    if len(message.command) < 3:
        return await message.reply_text(
            "<b>Usage:</b> /text <code>user_id</code> <code>message</code>",
            parse_mode=enums.ParseMode.HTML
        )
    
    try:
        target_user_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("<b>Invalid User ID format.</b>", parse_mode=enums.ParseMode.HTML)
    
    text_to_send = message.text.split(None, 2)[2]
    
    try:
        await client.send_message(target_user_id, text_to_send, parse_mode=enums.ParseMode.HTML)
        await message.reply_text(f"<b>✅ Message successfully sent to user <code>{target_user_id}</code>.</b>", parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        await message.reply_text(f"<b>❌ Failed to send message to user <code>{target_user_id}</code>:</b>\n<code>{e}</code>", parse_mode=enums.ParseMode.HTML)

# ==========================================
# USER /MYPLAN COMMAND (Unified Lookup)
# ==========================================
@Client.on_message(filters.command("myplan") & filters.private)
async def check_my_plan(client, message):
    user_id = message.from_user.id
    now = datetime.utcnow()
    
    col = get_premium_collection()
    user_doc = None
    if col is not None:
        try:
            user_doc = await col.find_one({"user_id": user_id, "active": True})
        except PyMongoError:
            user_doc = None
        
    if not user_doc:
        await message.reply_text(
            "<b>❌ You do not have an active Premium subscription.</b>\n\n"
            "Use /premium to check plans and upgrade!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🌟 Buy Premium", callback_data="buy_premium_start")]
            ]),
            parse_mode=enums.ParseMode.HTML
        )
        return

    plan = user_doc.get("plan", "N/A")
    expires_at = user_doc.get("expires_at") or user_doc.get("expiry_date")
    
    if expires_at and isinstance(expires_at, datetime):
        if expires_at > now:
            remaining = expires_at - now
            days_left = remaining.days
            hours_left = remaining.seconds // 3600
            minutes_left = (remaining.seconds % 3600) // 60
            expiry_str = format_ist_time(expires_at)
            time_left_str = f"{days_left}d, {hours_left}h, {minutes_left}m"
        else:
            expiry_str = "Expired"
            time_left_str = "0 days"
    else:
        expiry_str = "Unknown"
        time_left_str = "N/A"

    plan_text = (
        f"<b>✨ Your Premium Status ✨</b>\n\n"
        f"📦 <b>Plan</b>: {plan}\n"
        f"🟢 <b>Status</b>: [██████████] Active\n"
        f"⏳ <b>Expires On</b>: {expiry_str} IST\n"
        f"⏱️ <b>Remaining Time</b>: {time_left_str}\n\n"
        f"Enjoy your ad-free experience!"
    )
    
    renew_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Extend / Renew", callback_data="buy_premium_start")]
    ])
    
    await message.reply_text(plan_text, reply_markup=renew_kb, parse_mode=enums.ParseMode.HTML)

# ==========================================
# ADMIN REVOKE PREMIUM COMMAND (Replaces /removepremium)
# ==========================================
@Client.on_message(filters.command("revoke") & filters.user(ADMINS))
async def revoke_premium_command(client, message):
    if len(message.command) != 2:
        return await message.reply_text("<b>Usage:</b> /revoke <code>user_id</code>", parse_mode=enums.ParseMode.HTML)
    
    try:
        target_user_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("<b>Invalid User ID format.</b>", parse_mode=enums.ParseMode.HTML)
    
    col = get_premium_collection()
    if col is None:
        return await message.reply_text("<b>Database collection not found.</b>", parse_mode=enums.ParseMode.HTML)
        
    try:
        result = await col.delete_one({"user_id": target_user_id})
    except PyMongoError as e:
        return await message.reply_text(f"<b>Database error:</b> <code>{e}</code>", parse_mode=enums.ParseMode.HTML)
    
    try:
        t_user = await client.get_users(target_user_id)
        t_name = t_user.first_name or "User"
    except Exception:
        t_name = "User"

    try:
        a_user = message.from_user
        a_name = a_user.first_name or "Admin"
    except Exception:
        a_name = "Admin"
    
    if result.deleted_count > 0:
        if PREMIUM_GROUP_ID:
            await safe_kick_user(client, PREMIUM_GROUP_ID, target_user_id)
                
        log_revocation_text = (
            f"<b>⚠️ HeroFlix Premium Manually Revoked</b>\n\n"
            f"👤 <b>Target User</b>: <a href=\"tg://user?id={target_user_id}\">{t_name}</a> (<code>{target_user_id}</code>)\n"
            f"🛡️ <b>Revoked By Admin</b>: <a href=\"tg://user?id={message.from_user.id}\">{a_name}</a> (<code>{message.from_user.id}</code>)\n"
            f"🚪 <b>Action</b>: Record deleted and user ejected from group."
        )
        await log_premium_action(client, log_revocation_text)

        try:
            revocation_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Renew Premium", callback_data="buy_premium_start")]
            ])
            await client.send_message(
                target_user_id,
                "<b>❌ HeroFlix Premium Revoked</b>\n\nYour Premium Membership has been manually removed by an administrator.\n\nTap below to renew.",
                reply_markup=revocation_kb,
                parse_mode=enums.ParseMode.HTML
            )
        except Exception:
            pass
            
        await message.reply_text(f"<b>Successfully removed premium status for <a href=\"tg://user?id={target_user_id}\">{t_name}</a> (<code>{target_user_id}</code>), ejected them from the group, and sent renewal DM.</b>", parse_mode=enums.ParseMode.HTML)
    else:
        await message.reply_text(f"<b>No active premium record found for <a href=\"tg://user?id={target_user_id}\">{t_name}</a> (<code>{target_user_id}</code>).</b>", parse_mode=enums.ParseMode.HTML)

# ==========================================
# ADMIN LIST ACTIVE PREMIUM USERS COMMAND (/premiums)
# ==========================================
@Client.on_message(filters.command("premiums") & filters.user(ADMINS))
async def list_premiums_command(client, message):
    col = get_premium_collection()
    if col is None:
        return await message.reply_text("<b>Database collection not found.</b>", parse_mode=enums.ParseMode.HTML)
    
    now = datetime.utcnow()
    active_users = []
    try:
        async for doc in col.find({"active": True}):
            expires_at = doc.get("expires_at") or doc.get("expiry_date")
            if expires_at and isinstance(expires_at, datetime) and expires_at > now:
                active_users.append(doc)
    except PyMongoError as e:
        return await message.reply_text(f"<b>Database error:</b> <code>{e}</code>", parse_mode=enums.ParseMode.HTML)
        
    if not active_users:
        return await message.reply_text("<b>No active premium users found at the moment.</b>", parse_mode=enums.ParseMode.HTML)
        
    text = f"<b>💎 Active Premium Users List</b> ({len(active_users)})\n\n"
    for idx, doc in enumerate(active_users, 1):
        uid = doc.get("user_id")
        plan = doc.get("plan", "Standard")
        expires = doc.get("expires_at") or doc.get("expiry_date")
        exp_str = format_ist_time(expires) if expires else "N/A"
        
        try:
            u_obj = await client.get_users(uid)
            u_name = u_obj.first_name or "User"
        except Exception:
            u_name = doc.get("username", "User")
            
        text += f"{idx}. <a href=\"tg://user?id={uid}\">{u_name}</a> (<code>{uid}</code>) | 📦 {plan} | ⏳ {exp_str}\n"
        
        if len(text) > 3800:
            await message.reply_text(text, parse_mode=enums.ParseMode.HTML)
            text = ""
            
    if text:
        await message.reply_text(text, parse_mode=enums.ParseMode.HTML)

# ==========================================
# ADMIN INVITE LINK GENERATOR COMMAND
# ==========================================
@Client.on_message(filters.command("invite") & filters.user(ADMINS))
async def generate_invite_command(client, message):
    if len(message.command) < 2:
        return await message.reply_text(
            "<b>Usage:</b> /invite <code>chat_id</code> [expire_hours] [usage_limit]\n\n"
            "<b>Example:</b> /invite <code>-1001234567890</code> 24 1\n"
            "<i>expire_hours</i> defaults to 24 (0 = never expires).\n"
            "<i>usage_limit</i> defaults to 1 (0 = unlimited).",
            parse_mode=enums.ParseMode.HTML
        )

    try:
        target_chat_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("<b>Invalid chat ID format.</b>", parse_mode=enums.ParseMode.HTML)

    try:
        expire_hours = int(message.command[2]) if len(message.command) > 2 else 24
    except ValueError:
        return await message.reply_text("<b>Invalid expire_hours value.</b>", parse_mode=enums.ParseMode.HTML)

    try:
        usage_limit = int(message.command[3]) if len(message.command) > 3 else 1
    except ValueError:
        return await message.reply_text("<b>Invalid usage_limit value.</b>", parse_mode=enums.ParseMode.HTML)

    status_msg = await message.reply_text("<b>Generating invite link...</b>", parse_mode=enums.ParseMode.HTML)

    try:
        try:
            await client.resolve_peer(target_chat_id)
        except Exception:
            await client.get_chat(target_chat_id)
            await client.resolve_peer(target_chat_id)

        chat_obj = await client.get_chat(target_chat_id)

        link = await client.create_chat_invite_link(
            chat_id=target_chat_id,
            expire_date=(datetime.utcnow() + timedelta(hours=expire_hours)) if expire_hours > 0 else None,
            member_limit=usage_limit if usage_limit > 0 else None
        )

        await status_msg.edit_text(
            f"✅ <b>Invite link generated!</b>\n\n"
            f"<b>Chat:</b> {chat_obj.title or target_chat_id} (<code>{target_chat_id}</code>)\n"
            f"<b>Expires:</b> {'Never' if expire_hours == 0 else f'{expire_hours}h'}\n"
            f"<b>Usage limit:</b> {'Unlimited' if usage_limit == 0 else usage_limit}\n\n"
            f"🔗 {link.invite_link}",
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True
        )
    except ChatAdminRequired:
        await status_msg.edit_text(
            "❌ <b>Failed to generate invite link.</b>\n\n"
            "The bot is not an admin in that chat, or lacks the "
            "<b>Invite Users via Link</b> permission.",
            parse_mode=enums.ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"/invite command failed for chat {target_chat_id}: {e}")
        try:
            chat_obj = await client.get_chat(target_chat_id)
            if chat_obj.invite_link:
                return await status_msg.edit_text(
                    f"✅ <b>Permanent invite link (fallback):</b>\n\n{chat_obj.invite_link}",
                    parse_mode=enums.ParseMode.HTML,
                    disable_web_page_preview=True
                )
        except Exception:
            pass
        await status_msg.edit_text(f"❌ <b>Failed to generate invite link:</b>\n<code>{e}</code>", parse_mode=enums.ParseMode.HTML)

# ==========================================
# MULTI-PLAN /PREMIUM COMMAND & WORKFLOW
# ==========================================
@Client.on_message(filters.command("premium") & filters.private)
@Client.on_callback_query(filters.regex("^buy_premium_start$"))
async def minimal_premium_command(client, update):
    message = update.message if isinstance(update, CallbackQuery) else update
    if isinstance(update, CallbackQuery):
        await update.answer()

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔗 Click Here To Buy", url="https://fireluci.github.io/pay/")
        ],
        [
            InlineKeyboardButton("✅ I Have Paid (Send Screenshot)", callback_data="minimal_send_proof")
        ]
    ])
    
    text = (
        "<b>💎 HeroFlix Premium Plans</b>\n\n"
        "• <b>1 Month</b>: ₹40\n"
        "• <b>2 Months</b>: ₹80\n"
        "• <b>6 Months</b>: ₹240\n"
        "• <b>1 Year</b>: ₹480\n\n"
        "1. Tap <b>Click Here To Buy</b> to complete payment.\n"
        "2. Click <b>I Have Paid</b> below to send your screenshot."
    )
    
    if isinstance(update, CallbackQuery):
        try:
            await message.delete()
        except Exception:
            pass
        await client.send_message(message.chat.id, text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)
    else:
        await message.reply_text(text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex("^minimal_send_proof$"))
async def minimal_send_proof_cb(client, callback: CallbackQuery):
    user_id = callback.from_user.id
    MINIMAL_PENDING_FLOW[user_id] = {"status": "waiting_screenshot"}
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await client.send_message(
        callback.message.chat.id,
        "<b>📸 Please send your payment screenshot now in this chat.</b>\n\n"
        "Your request will be forwarded to the admin immediately.",
        parse_mode=enums.ParseMode.HTML
    )

@Client.on_message(filters.private & filters.photo & ~filters.command(["start", "premium"]))
async def minimal_screenshot_handler(client, message):
    user_id = message.from_user.id
    if user_id not in MINIMAL_PENDING_FLOW:
        return
    
    MINIMAL_PENDING_FLOW.pop(user_id, None)
    await message.reply_text("✅ Payment proof submitted! Please wait for admin verification.")
    
    user_name = message.from_user.first_name or "Unknown"
    admin_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"min_app_{user_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"min_rej_{user_id}")
        ]
    ])
    
    admin_text = (
        f"<b>🔔 New Payment Verification</b>\n\n"
        f"👤 User: <a href=\"tg://user?id={user_id}\">{user_name}</a>\n"
        f"🆔 User ID: <code>{user_id}</code>"
    )
    
    for admin_id in ADMINS:
        try:
            await client.send_photo(admin_id, message.photo.file_id, caption=admin_text, reply_markup=admin_kb, parse_mode=enums.ParseMode.HTML)
        except Exception as e:
            logger.error(f"Failed to send minimal payment proof to admin {admin_id}: {e}")

@Client.on_callback_query(filters.regex("^min_app_"))
async def minimal_admin_action_cb(client, callback: CallbackQuery):
    if str(callback.from_user.id) not in map(str, ADMINS):
        return await callback.answer("Unauthorized.", show_alert=True)
    
    parts = callback.data.split("_")
    target_user_id = int(parts[2] if len(parts) > 2 else parts[-1])
    
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1 Month (Test 2 Min) - ₹40", callback_data=f"selplan_{target_user_id}_30_40"),
            InlineKeyboardButton("2 Months - ₹80", callback_data=f"selplan_{target_user_id}_60_80")
        ],
        [
            InlineKeyboardButton("6 Months - ₹240", callback_data=f"selplan_{target_user_id}_180_240"),
            InlineKeyboardButton("1 Year - ₹480", callback_data=f"selplan_{target_user_id}_365_480")
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data=f"min_rej_{target_user_id}")
        ]
    ])
    
    await callback.answer()
    try:
        await callback.message.edit_caption(
            "<b>💎 Select Premium Plan</b>\n\nChoose the subscription to activate.",
            reply_markup=kb,
            parse_mode=enums.ParseMode.HTML
        )
    except Exception:
        await callback.message.edit_text(
            "<b>💎 Select Premium Plan</b>\n\nChoose the subscription to activate.",
            reply_markup=kb,
            parse_mode=enums.ParseMode.HTML
        )

@Client.on_callback_query(filters.regex("^selplan_"))
async def select_plan_cb(client, callback: CallbackQuery):
    if str(callback.from_user.id) not in map(str, ADMINS):
        return await callback.answer("Unauthorized.", show_alert=True)
    
    _, target_user_str, days_str, price_str = callback.data.split("_")
    target_user_id = int(target_user_str)
    days = int(days_str)
    price = price_str
    
    is_test_minute = (days == 30)
    plan_label = "1 Month (1 Min Test)" if is_test_minute else f"{days} Days"

    now = datetime.utcnow()
    expiry_date = now + timedelta(minutes=2) if is_test_minute else now + timedelta(days=days)
    
    try:
        target_user = await client.get_users(target_user_id)
        username = target_user.first_name or "User"
    except Exception:
        username = "User"
    
    pending_state = {
        "user_id": target_user_id,
        "username": username,
        "plan": plan_label,
        "price": price,
        "days": days,
        "start_date": now,
        "expiry_date": expiry_date,
        "updated_at": now
    }
    
    try:
        if 'db' in globals() and hasattr(db, 'premium_pending'):
            await db.premium_pending.update_one({"user_id": target_user_id}, {"$set": pending_state}, upsert=True)
        else:
            if not hasattr(client, 'fallback_pending'):
                client.fallback_pending = {}
            client.fallback_pending[target_user_id] = pending_state
    except PyMongoError:
        if not hasattr(client, 'fallback_pending'):
            client.fallback_pending = {}
        client.fallback_pending[target_user_id] = pending_state

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm & Activate", callback_data=f"confact_{target_user_id}"),
            InlineKeyboardButton("◀ Back", callback_data=f"min_app_{target_user_id}")
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data=f"min_rej_{target_user_id}")
        ]
    ])
    
    preview_text = (
        f"<b>💎 Premium Activation Preview</b>\n\n"
        f"👤 <b>User</b>: <a href=\"tg://user?id={target_user_id}\">{username}</a>\n"
        f"🆔 <b>User ID</b>: <code>{target_user_id}</code>\n"
        f"📦 <b>New Plan</b>: {plan_label}\n"
        f"💰 <b>Amount</b>: ₹{price}\n"
        f"⌛ <b>Result Expiry</b>: {format_ist_time(expiry_date)} IST\n\n"
        f"Proceed with activation?"
    )
    
    await callback.answer()
    try:
        await callback.message.edit_caption(preview_text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)
    except Exception:
        await callback.message.edit_text(preview_text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex("^confact_"))
async def confirm_activation_cb(client, callback: CallbackQuery):
    if str(callback.from_user.id) not in map(str, ADMINS):
        return await callback.answer("Unauthorized.", show_alert=True)
    
    _, target_user_str = callback.data.split("_")
    target_user_id = int(target_user_str)
    
    flow = None
    try:
        if 'db' in globals() and hasattr(db, 'premium_pending'):
            flow = await db.premium_pending.find_one({"user_id": target_user_id})
    except PyMongoError:
        flow = None
        
    if not flow and hasattr(client, 'fallback_pending') and target_user_id in client.fallback_pending:
        flow = client.fallback_pending.get(target_user_id)
        
    if not flow:
        return await callback.answer("Activation session expired or already processed.", show_alert=True)
        
    plan = flow.get("plan", "1 Month")
    price = flow.get("price", "40")
    days = flow.get("days", 30)
    
    try:
        t_usr = await client.get_users(target_user_id)
        username = t_usr.first_name or "User"
    except Exception:
        username = flow.get("username", "User")
    
    await callback.answer("Processing activation/renewal...")
    now = datetime.utcnow()
    
    # ==========================================
    # CUMULATIVE EXPIRY & START DATE CONTINUITY
    # ==========================================
    col = get_premium_collection()
    existing_user_doc = None
    if col is not None:
        try:
            existing_user_doc = await col.find_one({"user_id": target_user_id, "active": True})
        except PyMongoError:
            existing_user_doc = None
        
    is_test_minute = (days == 30 and "Test" in plan)
    
    if existing_user_doc:
        old_expiry = existing_user_doc.get("expires_at") or existing_user_doc.get("expiry_date")
        if old_expiry and isinstance(old_expiry, datetime) and old_expiry > now:
            start_date = old_expiry
            if is_test_minute:
                expiry_date = start_date + timedelta(minutes=2)
            else:
                expiry_date = start_date + timedelta(days=days)
        else:
            start_date = now
            if is_test_minute:
                expiry_date = start_date + timedelta(minutes=2)
            else:
                expiry_date = start_date + timedelta(days=days)
    else:
        start_date = now
        if is_test_minute:
            expiry_date = start_date + timedelta(minutes=2)
        else:
            expiry_date = start_date + timedelta(days=days)

    # ==========================================
    # CHECK IF ALREADY IN GROUP & AUTO-APPROVE
    # ==========================================
    already_joined = False
    if PREMIUM_GROUP_ID:
        try:
            member = await client.get_chat_member(int(PREMIUM_GROUP_ID), target_user_id)
            already_joined = member.status in [
                enums.ChatMemberStatus.MEMBER,
                enums.ChatMemberStatus.ADMINISTRATOR,
                enums.ChatMemberStatus.OWNER
            ]
        except Exception:
            already_joined = False

        try:
            await client.approve_chat_join_request(chat_id=int(PREMIUM_GROUP_ID), user_id=target_user_id)
            already_joined = True
        except Exception:
            pass

    if hasattr(client, 'fallback_pending') and target_user_id in client.fallback_pending:
        client.fallback_pending.pop(target_user_id, None)

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
        "welcomed": already_joined,
        "reminders": {"1_day": False}
    }
    
    if col is not None:
        try:
            await col.update_one({"user_id": target_user_id}, {"$set": activation_data}, upsert=True)
            if hasattr(db, 'premium_pending'):
                await db.premium_pending.delete_one({"user_id": target_user_id})
        except PyMongoError as db_err:
            logger.error(f"Failed to update premium collection for user {target_user_id}: {db_err}")
        
    ist_start_str = format_ist_time(start_date)
    ist_expiry_str = format_ist_time(expiry_date)

    perm_link = PREMIUM_PERMANENT_LINK if 'PREMIUM_PERMANENT_LINK' in globals() and PREMIUM_PERMANENT_LINK else "https://t.me/your_group_link"

    user_msg_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Click Here To Join", url=perm_link)]
    ])

    user_msg_text = (
        f"<b>🎉 HeroFlix Premium Activated</b>\n\n"
        f"📦 <b>Plan</b>: {plan}\n"
        f"📅 <b>Start</b>: {ist_start_str} IST\n"
        f"⌛ <b>Expires</b>: {ist_expiry_str} IST\n\n"
        f"👇 <b>Tap below to join the Premium Group</b>:"
    )
    
    user_msg_sent = None
    try:
        user_msg_sent = await client.send_message(target_user_id, user_msg_text, reply_markup=user_msg_kb, disable_web_page_preview=True, parse_mode=enums.ParseMode.HTML)
        if not already_joined and col is not None and user_msg_sent:
            try:
                await col.update_one({"user_id": target_user_id}, {"$set": {"dm_msg_id": user_msg_sent.id}})
            except PyMongoError:
                pass
    except Exception as e:
        logger.error(f"Failed to notify user {target_user_id}: {e}")
        
    success_admin_text = (
        f"<b>✅ Premium Updated Successfully</b>\n\n"
        f"• <b>User</b>: <a href=\"tg://user?id={target_user_id}\">{username}</a> (<code>{target_user_id}</code>)\n"
        f"• <b>Plan</b>: {plan} (₹{price})\n"
        f"• <b>New Start</b>: {ist_start_str} IST\n"
        f"• <b>New Expiry</b>: {ist_expiry_str} IST\n"
        f"• <b>Auto-Approved Join Request</b>: Yes"
    )

    action_type = "Renewal" if existing_user_doc else "New Activation"
    log_event_text = (
        f"<b>💎 HeroFlix Premium {action_type}</b>\n\n"
        f"👤 <b>User</b>: <a href=\"tg://user?id={target_user_id}\">{username}</a> (<code>{target_user_id}</code>)\n"
        f"📦 <b>Plan</b>: {plan} (₹{price})\n"
        f"📅 <b>Start</b>: {ist_start_str} IST\n"
        f"⌛ <b>New Expiry</b>: {ist_expiry_str} IST\n"
        f"🛡️ <b>Approved By Admin ID</b>: <code>{callback.from_user.id}</code>\n"
        f"🟢 <b>Join Request Auto-Approved</b>: Yes"
    )
    await log_premium_action(client, log_event_text)
    
    try:
        await callback.message.edit_caption(success_admin_text, reply_markup=None, parse_mode=enums.ParseMode.HTML)
    except Exception:
        await callback.message.edit_text(success_admin_text, reply_markup=None, parse_mode=enums.ParseMode.HTML)

# ==========================================
# AUTO JOIN REQUEST HANDLER & WELCOME LISTENER
# ==========================================
@Client.on_chat_join_request()
async def auto_accept_join_request(client, join_request: ChatJoinRequest):
    if PREMIUM_GROUP_ID and join_request.chat.id == int(PREMIUM_GROUP_ID):
        try:
            col = get_premium_collection()
            is_active = False
            if col is not None:
                is_active = await col.find_one({"user_id": join_request.from_user.id, "active": True})
            if is_active:
                await client.approve_chat_join_request(chat_id=join_request.chat.id, user_id=join_request.from_user.id)
                u_name = join_request.from_user.first_name or "User"
                logger.info(f"Auto-approved join request for active premium user {u_name} (ID: {join_request.from_user.id})")
        except Exception as e:
            logger.error(f"Failed to auto-approve join request for {join_request.from_user.id}: {e}")

@Client.on_chat_member_updated()
async def welcome_premium_user_handler(client, member_update: ChatMemberUpdated):
    if not PREMIUM_GROUP_ID:
        return
        
    try:
        if member_update.chat.id != int(PREMIUM_GROUP_ID):
            return
    except ValueError:
        return
        
    old_status = member_update.old_chat_member.status if member_update.old_chat_member else enums.ChatMemberStatus.LEFT
    new_status = member_update.new_chat_member.status if member_update.new_chat_member else enums.ChatMemberStatus.LEFT
    
    joined_statuses = [enums.ChatMemberStatus.MEMBER, enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]
    left_statuses = [enums.ChatMemberStatus.LEFT, enums.ChatMemberStatus.BANNED]
    
    if old_status in left_statuses and new_status in joined_statuses:
        user = member_update.new_chat_member.user
        if not user or user.is_bot:
            return
            
        user_id = user.id
        col = get_premium_collection()
        if col is not None:
            try:
                user_doc = await col.find_one({"user_id": user_id, "active": True})
            except PyMongoError:
                user_doc = None
            if not user_doc:
                return
                
            dm_msg_id = user_doc.get("dm_msg_id")
            plan = user_doc.get("plan", "Standard")
            expires_at = user_doc.get("expires_at") or user_doc.get("expiry_date")
            exp_str = format_ist_time(expires_at) if expires_at else "N/A"
            
            perm_link = PREMIUM_PERMANENT_LINK if 'PREMIUM_PERMANENT_LINK' in globals() and PREMIUM_PERMANENT_LINK else "https://t.me/your_group_link"
            
            joined_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 Open Premium Group", url=perm_link)]
            ])
            
            joined_text = (
                f"<b>🎉 Welcome to HeroFlix Premium!</b>\n\n"
                f"✅ You have successfully joined the Premium Group.\n\n"
                f"✨ <b>Your Active Plan Details</b>:\n"
                f"• <b>Plan</b>: {plan}\n"
                f"• <b>Expires On</b>: {exp_str} IST\n"
                f"• <b>Status</b>: Active"
            )
            
            if dm_msg_id:
                try:
                    await client.edit_message_text(
                        chat_id=user_id,
                        message_id=dm_msg_id,
                        text=joined_text,
                        reply_markup=joined_kb,
                        parse_mode=enums.ParseMode.HTML,
                        disable_web_page_preview=True
                    )
                    return
                except Exception:
                    pass
            
            try:
                await client.send_message(
                    user_id,
                    joined_text,
                    reply_markup=joined_kb,
                    disable_web_page_preview=True,
                    parse_mode=enums.ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Failed to send join confirmation DM to {user_id}: {e}")

@Client.on_callback_query(filters.regex("^min_rej_"))
async def minimal_admin_reject_cb(client, callback: CallbackQuery):
    if str(callback.from_user.id) not in map(str, ADMINS):
        return await callback.answer("Unauthorized.", show_alert=True)
    
    parts = callback.data.split("_")
    target_user_id = int(parts[2] if len(parts) > 2 else parts[-1])
    
    try:
        if 'db' in globals() and hasattr(db, 'premium_pending'):
            await db.premium_pending.delete_one({"user_id": target_user_id})
    except PyMongoError:
        pass
    
    await callback.answer("Rejected.")
    try:
        await callback.message.edit_caption("<b>❌ Status:</b> REJECTED", reply_markup=None, parse_mode=enums.ParseMode.HTML)
    except Exception:
        await callback.message.edit_text("<b>❌ Status:</b> REJECTED", reply_markup=None, parse_mode=enums.ParseMode.HTML)
