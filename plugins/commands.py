import os
import logging
import asyncio
from datetime import datetime, timedelta
from Script import script
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ChatJoinRequest, ChatMemberUpdated
from pyrogram.errors import FloodWait
from database.ia_filterdb import Media, get_file_details, unpack_new_file_id, get_bad_files
from database.users_chats_db import db
from info import CHANNELS, ADMINS, AUTH_CHANNEL, LOG_CHANNEL, PICS, BATCH_FILE_CAPTION, CUSTOM_FILE_CAPTION, PROTECT_CONTENT, CHNL_LNK, FORCE, MAX_B_TN, TUTORIAL, PREMIUM_USER, PREMIUM_GROUP_ID, PREMIUM_LOG_CHANNEL, PREMIUM_PERMANENT_LINK
from utils import get_settings, get_size, is_subscribed, save_group_settings, temp, get_shortlink
from database.connections_mdb import active_connection
from pymongo.errors import PyMongoError
import re, sys, json, base64

logger = logging.getLogger(__name__)

BATCH_FILES = {}

def format_date_only(dt: datetime) -> str:
    if not isinstance(dt, datetime):
        return "N/A"
    return (dt + timedelta(hours=5, minutes=30)).strftime('%d %b, %Y')

def get_premium_collection():
    try:
        if hasattr(db, 'premium_users') and db.premium_users is not None:
            return db.premium_users
        if hasattr(db, 'db') and hasattr(db.db, 'premium_users'):
            return db.db.premium_users
        if hasattr(db, 'get_collection'):
            return db.get_collection('premium_users')
    except Exception as e:
        logger.error(f"Error fetching premium collection: {e}")
    return None

async def log_premium_action(client: Client, text: str):
    """Foolproof logger for PREMIUM_LOG_CHANNEL with internal cache resolution and admin fallback."""
    if not PREMIUM_LOG_CHANNEL:
        return
    
    chat_id_int = int(PREMIUM_LOG_CHANNEL)
    try:
        await client.get_chat(chat_id_int)
    except Exception:
        pass
        
    try:
        await client.resolve_peer(chat_id_int)
    except Exception:
        pass

    try:
        await client.send_message(
            chat_id=chat_id_int, 
            text=text, 
            disable_web_page_preview=True, 
            parse_mode=enums.ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Failed to send log to PREMIUM_LOG_CHANNEL: {e}")
        for admin_id in ADMINS:
            try:
                await client.send_message(
                    int(admin_id), 
                    f"<b>⚠️ Log Channel Error ({e})</b>\n\n{text}", 
                    disable_web_page_preview=True, 
                    parse_mode=enums.ParseMode.HTML
                )
            except Exception:
                pass

async def safe_kick_user(client: Client, chat_id, user_id):
    if not chat_id:
        return
    try:
        chat_id_int = int(chat_id)
        try:
            await client.get_chat(chat_id_int)
            await client.resolve_peer(chat_id_int)
        except Exception:
            pass

        try:
            await client.promote_chat_member(
                chat_id=chat_id_int, user_id=user_id, is_anonymous=False, can_manage_chat=False,
                can_delete_messages=False, can_manage_video_chats=False, can_restrict_members=False,
                can_promote_members=False, can_change_info=False, can_invite_users=False, can_pin_messages=False
            )
        except Exception:
            pass
        await client.ban_chat_member(chat_id=chat_id_int, user_id=user_id)
        await asyncio.sleep(0.5)
        await client.unban_chat_member(chat_id=chat_id_int, user_id=user_id)
    except Exception as e:
        if "USER_NOT_PARTICIPANT" not in str(e) and "PEER_ID_INVALID" not in str(e):
            logger.error(f"Failed to kick user ID {user_id}: {e}")
            await log_premium_action(client, f"<b>⚠️ Warning: Failed to Kick User</b>\n\n• <b>User ID</b>: <code>{user_id}</code>\n• <b>Group ID</b>: <code>{chat_id}</code>\n• <b>Error</b>: <code>{e}</code>")

# ==========================================
# BACKGROUND EXPIRY LOOP
# ==========================================
async def premium_expiry_reminder_loop(client: Client):
    await asyncio.sleep(5)
    while True:
        try:
            now = datetime.utcnow()
            col = get_premium_collection()
            if col is not None:
                async for user_doc in col.find({"active": True}):
                    user_id = user_doc.get("user_id")
                    expires_at = user_doc.get("expires_at") or user_doc.get("expiry_date")
                    if not isinstance(expires_at, datetime):
                        continue
                    reminders = user_doc.get("reminders", {})
                    if now >= expires_at:
                        await col.delete_one({"user_id": user_id})
                        if PREMIUM_GROUP_ID:
                            await safe_kick_user(client, PREMIUM_GROUP_ID, user_id)
                        exp_str = format_date_only(expires_at)
                        await log_premium_action(client, f"<b>❌ HeroFlix Premium Expired & Ejected</b>\n\n👤 User ID: <code>{user_id}</code>\n⌛ Expired: {exp_str}")
                        try:
                            await client.send_message(user_id, "<b>❌ HeroFlix Premium Expired</b>\n\nYour membership has expired. Tap below to renew.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Renew Premium", callback_data="buy_premium_start")]]), parse_mode=enums.ParseMode.HTML)
                        except Exception:
                            pass
                    elif expires_at - now <= timedelta(days=1) and not reminders.get("1_day", False):
                        try:
                            await client.send_message(user_id, "<b>⚠ HeroFlix Premium</b>\n\nYour Premium expires tomorrow. Renew now to avoid interruption.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Renew", callback_data="buy_premium_start")]]), parse_mode=enums.ParseMode.HTML)
                            await col.update_one({"user_id": user_id}, {"$set": {"reminders.1_day": True}})
                        except Exception:
                            pass
        except Exception as e:
            logger.error(f"Error in expiry loop: {e}")
        await asyncio.sleep(30)

# ==========================================
# START & FILE HANDLERS
# ==========================================
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
        return await client.send_message(message.from_user.id, "<b>🔆 First Join Our Main Channel & Then Click Try Again ♻</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏮 Main Channel", url=FORCE)], [InlineKeyboardButton("🔄 Try Again", url=f"https://telegram.me/{temp.U_NAME}?start={payload}")]]), parse_mode=enums.ParseMode.HTML)

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

# ==========================================
# PREMIUM COMMANDS & WORKFLOW
# ==========================================
@Client.on_message(filters.command("myplan") & filters.private)
async def check_my_plan(client, message):
    user_id = message.from_user.id
    col = get_premium_collection()
    user_doc = await col.find_one({"user_id": user_id, "active": True}) if col is not None else None
    
    if not user_doc:
        return await message.reply_text("<b>❌ You do not have an active Premium subscription.</b>\n\nUse /premium to check plans and upgrade!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🌟 Buy Premium", callback_data="buy_premium_start")]]), parse_mode=enums.ParseMode.HTML)

    plan, expires_at = user_doc.get("plan", "N/A"), user_doc.get("expires_at") or user_doc.get("expiry_date")
    price = user_doc.get("price", "40")
    now = datetime.utcnow()
    
    if expires_at and isinstance(expires_at, datetime) and expires_at > now:
        remaining = expires_at - now
        days_left = remaining.days
        time_left_str = f"{days_left} Days" if days_left > 0 else f"{remaining.seconds // 3600} Hours"
        expiry_str = format_date_only(expires_at)
    else:
        expiry_str, time_left_str = "Expired", "0 Days"

    await message.reply_text(f"<b>✨ Your Premium Status ✨</b>\n\n💰 <b>Plan</b>: {plan} | ₹{price}\n🟢 <b>Status</b>: Active\n⏳ <b>Expires On</b>: {expiry_str}\n⏱️ <b>Remaining Time</b>: {time_left_str}\n\nEnjoy your ad-free experience!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Extend / Renew", callback_data="buy_premium_start")]]), parse_mode=enums.ParseMode.HTML)

@Client.on_message(filters.command("premium") & filters.private)
async def minimal_premium_command_msg(client, message):
    text = "<b>💎 HeroFlix Premium Plans</b>\n\n• <b>1 Month</b>: ₹40\n• <b>2 Months</b>: ₹80\n• <b>6 Months</b>: ₹240\n• <b>1 Year</b>: ₹480\n\n1. Tap <b>Click Here To Buy</b> to pay.\n2. Click <b>I Have Paid</b> to send screenshot."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Click Here To Buy", url="https://fireluci.github.io/pay/")], [InlineKeyboardButton("✅ I Have Paid (Send Screenshot)", callback_data="minimal_send_proof")]])
    await message.reply_text(text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex("^buy_premium_start$"))
async def minimal_premium_command_cb(client, callback: CallbackQuery):
    await callback.answer()
    text = "<b>💎 HeroFlix Premium Plans</b>\n\n• <b>1 Month</b>: ₹40\n• <b>2 Months</b>: ₹80\n• <b>6 Months</b>: ₹240\n• <b>1 Year</b>: ₹480\n\n1. Tap <b>Click Here To Buy</b> to pay.\n2. Click <b>I Have Paid</b> to send screenshot."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Click Here To Buy", url="https://fireluci.github.io/pay/")], [InlineKeyboardButton("✅ I Have Paid (Send Screenshot)", callback_data="minimal_send_proof")]])
    try:
        await callback.message.delete()
    except Exception:
        pass
    await client.send_message(callback.message.chat.id, text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex("^minimal_send_proof$"))
async def minimal_send_proof_cb(client, callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await client.send_message(callback.message.chat.id, "<b>📸 Please send your payment screenshot now in this chat.</b>", parse_mode=enums.ParseMode.HTML)

@Client.on_message(filters.private & (filters.photo | filters.document) & ~filters.command(["start", "premium"]))
async def minimal_screenshot_handler(client, message):
    user_id = message.from_user.id
    await message.reply_text("<b>✅ Payment proof submitted! Please wait for admin verification.</b>", parse_mode=enums.ParseMode.HTML)
    
    admin_kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"min_app_{user_id}"), InlineKeyboardButton("❌ Reject", callback_data=f"min_rej_{user_id}")]])
    admin_text = f"<b>🔔 New Payment Verification</b>\n\n👤 User: <a href='tg://user?id={user_id}'>{message.from_user.first_name or 'Unknown'}</a>\n🆔 ID: <code>{user_id}</code>"
    file_id = message.photo.file_id if message.photo else message.document.file_id

    if PREMIUM_LOG_CHANNEL:
        chat_id_int = int(PREMIUM_LOG_CHANNEL)
        try:
            await client.get_chat(chat_id_int)
            await client.resolve_peer(chat_id_int)
        except Exception:
            pass
            
        try:
            if message.photo:
                await client.send_photo(chat_id_int, file_id, caption=admin_text, reply_markup=admin_kb, parse_mode=enums.ParseMode.HTML)
            else:
                await client.send_document(chat_id_int, file_id, caption=admin_text, reply_markup=admin_kb, parse_mode=enums.ParseMode.HTML)
        except Exception as e:
            logger.error(f"Failed to send proof to PREMIUM_LOG_CHANNEL: {e}")
            for admin_id in ADMINS:
                try:
                    if message.photo:
                        await client.send_photo(int(admin_id), file_id, caption=admin_text, reply_markup=admin_kb, parse_mode=enums.ParseMode.HTML)
                    else:
                        await client.send_document(int(admin_id), file_id, caption=admin_text, reply_markup=admin_kb, parse_mode=enums.ParseMode.HTML)
                except Exception:
                    pass

@Client.on_callback_query(filters.regex("^min_app_"))
async def minimal_admin_action_cb(client, callback: CallbackQuery):
    if str(callback.from_user.id) not in map(str, ADMINS):
        return await callback.answer("Unauthorized.", show_alert=True)
    target_user_id = int(callback.data.split("_")[2])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("1 Month (Test 2 Mins) - ₹40", callback_data=f"selplan_{target_user_id}_30_40"), InlineKeyboardButton("2 Months - ₹80", callback_data=f"selplan_{target_user_id}_60_80")],
        [InlineKeyboardButton("6 Months - ₹240", callback_data=f"selplan_{target_user_id}_180_240"), InlineKeyboardButton("1 Year - ₹480", callback_data=f"selplan_{target_user_id}_365_480")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"min_rej_{target_user_id}")]
    ])
    await callback.answer()
    try:
        await callback.message.edit_caption("<b>💎 Select Premium Plan</b>", reply_markup=kb, parse_mode=enums.ParseMode.HTML)
    except Exception:
        await callback.message.edit_text("<b>💎 Select Premium Plan</b>", reply_markup=kb, parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex("^selplan_"))
async def select_plan_cb(client, callback: CallbackQuery):
    if str(callback.from_user.id) not in map(str, ADMINS):
        return await callback.answer("Unauthorized.", show_alert=True)
    
    _, target_user_str, days_str, price = callback.data.split("_")
    target_user_id, days = int(target_user_str), int(days_str)
    
    is_test = (days == 30)
    plan_label = "1 Month (2 Mins Test)" if is_test else (f"2 Months" if days == 60 else (f"6 Months" if days == 180 else "1 Year"))
    now = datetime.utcnow()
    expiry_date = (now + timedelta(minutes=2)) if is_test else (now + timedelta(days=days))
    
    try:
        username = (await client.get_users(target_user_id)).first_name or "User"
    except Exception:
        username = "User"
    
    conf_callback_data = f"confact_{target_user_id}_{days}_{price}"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm & Activate", callback_data=conf_callback_data), InlineKeyboardButton("◀ Back", callback_data=f"min_app_{target_user_id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"min_rej_{target_user_id}")]
    ])
    
    preview_text = f"<b>💎 Preview</b>\n\n👤 User: <a href='tg://user?id={target_user_id}'>{username}</a> (<code>{target_user_id}</code>)\n💰 Plan: {plan_label} | ₹{price}\n⌛ Expiry: {format_date_only(expiry_date)}"
    await callback.answer()
    try:
        await callback.message.edit_caption(preview_text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)
    except Exception:
        await callback.message.edit_text(preview_text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex("^confact_"))
async def confirm_activation_cb(client, callback: CallbackQuery):
    if str(callback.from_user.id) not in map(str, ADMINS):
        return await callback.answer("Unauthorized.", show_alert=True)
    
    _, target_user_str, days_str, price = callback.data.split("_")
    target_user_id, days = int(target_user_str), int(days_str)
    
    is_test = (days == 30)
    plan = "1 Month" if is_test else (f"2 Months" if days == 60 else (f"6 Months" if days == 180 else "1 Year"))

    try:
        username = (await client.get_users(target_user_id)).first_name or "User"
    except Exception:
        username = "User"
    
    await callback.answer("Activating...")
    now = datetime.utcnow()
    col = get_premium_collection()
    existing = await col.find_one({"user_id": target_user_id, "active": True}) if col is not None else None
            
    old_expiry = existing.get("expires_at") or existing.get("expiry_date") if existing else None
    start_date = old_expiry if old_expiry and isinstance(old_expiry, datetime) and old_expiry > now else now
    expiry_date = (start_date + timedelta(minutes=2)) if is_test else (start_date + timedelta(days=days))

    already_joined = False
    if PREMIUM_GROUP_ID:
        try:
            member = await client.get_chat_member(int(PREMIUM_GROUP_ID), target_user_id)
            already_joined = member.status in [enums.ChatMemberStatus.MEMBER, enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]
        except Exception:
            pass
        try:
            await client.approve_chat_join_request(chat_id=int(PREMIUM_GROUP_ID), user_id=target_user_id)
            already_joined = True
        except Exception:
            pass

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
        await col.update_one({"user_id": target_user_id}, {"$set": activation_data}, upsert=True)
        
    perm_link = PREMIUM_PERMANENT_LINK if PREMIUM_PERMANENT_LINK else "https://t.me/your_group_link"
    user_msg_sent = None
    try:
        user_msg_sent = await client.send_message(
            target_user_id, 
            f"<b>🎉 HeroFlix Premium Activated</b>\n\n📦 <b>Plan</b>: {plan} | ₹{price}\n📅 <b>Start</b>: {format_date_only(start_date)}\n⌛ <b>Expires</b>: {format_date_only(expiry_date)}\n\n👇 Tap below to join:", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Click Here To Join", url=perm_link)]]), 
            disable_web_page_preview=True, 
            parse_mode=enums.ParseMode.HTML
        )
        if not already_joined and col is not None and user_msg_sent:
            await col.update_one({"user_id": target_user_id}, {"$set": {"dm_msg_id": user_msg_sent.id}})
    except Exception as e:
        logger.error(f"Failed to notify user: {e}")
        
    await log_premium_action(client, f"<b>💎 HeroFlix Premium {'Renewal' if existing else 'Activation'}</b>\n\n👤 User: <a href='tg://user?id={target_user_id}'>{username}</a> (<code>{target_user_id}</code>)\n📦 Plan: {plan} | ₹{price}\n⌛ Expiry: {format_date_only(expiry_date)}")
    
    success_text = f"<b>✅ Premium Activated Successfully</b>\n\n👤 User: <a href='tg://user?id={target_user_id}'>{username}</a> (<code>{target_user_id}</code>)\n💰 Plan: {plan} | ₹{price}\n⌛ Expiry: {format_date_only(expiry_date)}"
    try:
        await callback.message.edit_caption(success_text, reply_markup=None, parse_mode=enums.ParseMode.HTML)
    except Exception:
        await callback.message.edit_text(success_text, reply_markup=None, parse_mode=enums.ParseMode.HTML)

@Client.on_chat_join_request()
async def auto_accept_join_request(client, join_request: ChatJoinRequest):
    if PREMIUM_GROUP_ID and join_request.chat.id == int(PREMIUM_GROUP_ID):
        try:
            col = get_premium_collection()
            if col is not None and await col.find_one({"user_id": join_request.from_user.id, "active": True}):
                await client.approve_chat_join_request(chat_id=join_request.chat.id, user_id=join_request.from_user.id)
        except Exception:
            pass

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
    if old_status in [enums.ChatMemberStatus.LEFT, enums.ChatMemberStatus.BANNED] and new_status in [enums.ChatMemberStatus.MEMBER, enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
        user = member_update.new_chat_member.user
        if not user or user.is_bot:
            return
        user_id = user.id
        col = get_premium_collection()
        if col is not None:
            user_doc = await col.find_one({"user_id": user_id, "active": True})
            if not user_doc:
                return
            dm_msg_id, plan, price, exp_str = user_doc.get("dm_msg_id"), user_doc.get("plan", "Standard"), user_doc.get("price", "40"), format_date_only(user_doc.get("expires_at") or user_doc.get("expiry_date"))
            perm_link = PREMIUM_PERMANENT_LINK if PREMIUM_PERMANENT_LINK else "https://t.me/your_group_link"
            joined_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Open Premium Group", url=perm_link)]])
            joined_text = f"<b>🎉 Welcome to HeroFlix Premium!</b>\n\n✅ You have successfully joined the Premium Group.\n\n✨ <b>Your Active Plan Details</b>:\n• <b>Plan</b>: {plan} | ₹{price}\n• <b>Expires On</b>: {exp_str}\n• <b>Status</b>: Active"
            
            if dm_msg_id:
                try:
                    return await client.edit_message_text(chat_id=user_id, message_id=dm_msg_id, text=joined_text, reply_markup=joined_kb, disable_web_page_preview=True, parse_mode=enums.ParseMode.HTML)
                except Exception:
                    pass
            try:
                await client.send_message(user_id, joined_text, reply_markup=joined_kb, disable_web_page_preview=True, parse_mode=enums.ParseMode.HTML)
            except Exception:
                pass

@Client.on_callback_query(filters.regex("^min_rej_"))
async def minimal_admin_reject_cb(client, callback: CallbackQuery):
    if str(callback.from_user.id) not in map(str, ADMINS):
        return await callback.answer("Unauthorized.", show_alert=True)
    parts = callback.data.split("_")
    target_user_id = int(parts[2] if len(parts) > 2 else parts[-1])
    try:
        if hasattr(db, 'premium_pending'):
            await db.premium_pending.delete_one({"user_id": target_user_id})
    except PyMongoError:
        pass
    await callback.answer("Rejected.")
    try:
        await callback.message.edit_caption("<b>❌ Status:</b> REJECTED", reply_markup=None, parse_mode=enums.ParseMode.HTML)
    except Exception:
        await callback.message.edit_text("<b>❌ Status:</b> REJECTED", reply_markup=None, parse_mode=enums.ParseMode.HTML)

# ==========================================
# ADMIN & UTILITY COMMANDS
# ==========================================
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

# ==========================================
# SETTINGS HELPER & KEYBOARD BUILDER
# ==========================================
def get_settings_keyboard(settings: dict, grp_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('Rᴇsᴜʟᴛ Pᴀɢᴇ', callback_data=f'setgs#button#{settings.get("button", False)}#{grp_id}'), InlineKeyboardButton('Bᴜᴛᴛᴏɴ' if settings.get("button", False) else 'Tᴇxᴛ', callback_data=f'setgs#button#{settings.get("button", False)}#{grp_id}')],
        [InlineKeyboardButton('Fɪʟᴇ Sᴇɴᴅ Mᴏᴅᴇ', callback_data=f'setgs#botpm#{settings.get("botpm", False)}#{grp_id}'), InlineKeyboardButton('Mᴀɴᴜᴀʟ Sᴛᴀʀᴛ' if settings.get("botpm", False) else 'Aᴜᴛᴏ Sᴇɴᴅ', callback_data=f'setgs#botpm#{settings.get("botpm", False)}#{grp_id}')],
        [InlineKeyboardButton('Pʀᴏᴛᴇᴄᴛ Cᴏɴᴛᴇɴᴛ', callback_data=f'setgs#file_secure#{settings.get("file_secure", False)}#{grp_id}'), InlineKeyboardButton('✔ Oɴ' if settings.get("file_secure", False) else '✘ Oғғ', callback_data=f'setgs#file_secure#{settings.get("file_secure", False)}#{grp_id}')],
        [InlineKeyboardButton('Sᴘᴇʟʟ Cʜᴇᴄᴋ', callback_data=f'setgs#spell_check#{settings.get("spell_check", True)}#{grp_id}'), InlineKeyboardButton('✔ Oɴ' if settings.get("spell_check", True) else '✘ Oғғ', callback_data=f'setgs#spell_check#{settings.get("spell_check", True)}#{grp_id}')],
        [InlineKeyboardButton('Wᴇʟᴄᴏᴍᴇ Msɢ', callback_data=f'setgs#welcome#{settings.get("welcome", True)}#{grp_id}'), InlineKeyboardButton('✔ Oɴ' if settings.get("welcome", True) else '✘ Oғғ', callback_data=f'setgs#welcome#{settings.get("welcome", True)}#{grp_id}')],
        [InlineKeyboardButton('Aᴜᴛᴏ-Dᴇʟᴇᴛᴇ', callback_data=f'setgs#auto_delete#{settings.get("auto_delete", False)}#{grp_id}'), InlineKeyboardButton('10 Mɪns' if settings.get("auto_delete", False) else '✘ Oғғ', callback_data=f'setgs#auto_delete#{settings.get("auto_delete", False)}#{grp_id}')],
        [InlineKeyboardButton('Aᴜᴛᴏ-Fɪʟᴛᴇʀ', callback_data=f'setgs#auto_ffilter#{settings.get("auto_ffilter", True)}#{grp_id}'), InlineKeyboardButton('✔ Oɴ' if settings.get("auto_ffilter", True) else '✘ Oғғ', callback_data=f'setgs#auto_ffilter#{settings.get("auto_ffilter", True)}#{grp_id}')],
        [InlineKeyboardButton('Mᴀx Bᴜᴛᴛᴏns', callback_data=f'setgs#max_btn#{settings.get("max_btn", False)}#{grp_id}'), InlineKeyboardButton('10' if settings.get("max_btn", False) else f'{MAX_B_TN}', callback_data=f'setgs#max_btn#{settings.get("max_btn", False)}#{grp_id}')],
        [InlineKeyboardButton('ShortLink', callback_data=f'setgs#is_shortlink#{settings.get("is_shortlink", False)}#{grp_id}'), InlineKeyboardButton('✔ Oɴ' if settings.get("is_shortlink", False) else '✘ Oғғ', callback_data=f'setgs#is_shortlink#{settings.get("is_shortlink", False)}#{grp_id}')],
    ])

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

    if chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        btn = [[InlineKeyboardButton("Oᴘᴇɴ Hᴇʀᴇ ↓", callback_data=f"opnsetgrp#{grp_id}"), InlineKeyboardButton("Oᴘᴇɴ Iɴ PM ⇲", callback_data=f"opnsetpm#{grp_id}")]]
        await message.reply_text(text="<b>Dᴏ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴏᴘᴇɴ sᴇᴛᴛɪɴɢs ʜᴇʀᴇ ?</b>", reply_markup=InlineKeyboardMarkup(btn), disable_web_page_preview=True, parse_mode=enums.ParseMode.HTML, reply_to_message_id=message.id)
    else:
        await message.reply_text(text=f"<b>Sᴇᴛᴛɪɴɢs Fᴏʀ {title}</b>", reply_markup=get_settings_keyboard(settings, grp_id), disable_web_page_preview=True, parse_mode=enums.ParseMode.HTML, reply_to_message_id=message.id)

@Client.on_callback_query(filters.regex(r'^setgs#'))
async def settings_callback(client, callback: CallbackQuery):
    data = callback.data.split("#")
    if len(data) < 4:
        return await callback.answer("Invalid settings data!", show_alert=True)
    
    _, key, value, grp_id = data[0], data[1], data[2], int(data[3])
    
    current_val = True if value.lower() == "true" else False
    new_val = not current_val
    
    await save_group_settings(grp_id, key, new_val)
    
    settings = await get_settings(grp_id)
    if not settings:
        return await callback.answer("Error fetching settings!", show_alert=True)

    try:
        await callback.message.edit_reply_markup(reply_markup=get_settings_keyboard(settings, grp_id))
    except Exception:
        pass
    await callback.answer("Settings Updated!")
