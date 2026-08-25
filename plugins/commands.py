import os
import logging
import asyncio
import json
from datetime import datetime, timedelta
from Script import script
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ChatJoinRequest, ChatMemberUpdated
from pyrogram.errors import FloodWait, MessageNotModified
from database.ia_filterdb import Media, get_file_details, unpack_new_file_id, get_bad_files
from database.users_chats_db import db
from info import CHANNELS, OWNER, LOG_CHANNEL, PICS, CUSTOM_FILE_CAPTION, CHNL_LNK, PREMIUM_GROUP_ID, PREMIUM_PERMANENT_LINK, PREMIUM_LOG
from utils import get_size, temp
from pymongo.errors import PyMongoError
import re, sys, base64

logger = logging.getLogger(__name__)
BATCH_FILES = {}

def fmt_date(dt: datetime) -> str:
    return (dt + timedelta(hours=5, minutes=30)).strftime('%d %b, %Y') if isinstance(dt, datetime) else "N/A"

def get_col():
    try:
        return db.premium_users if hasattr(db, 'premium_users') and db.premium_users is not None else (db.db.premium_users if hasattr(db, 'db') else db.get_collection('premium_users'))
    except Exception:
        return None

def get_db_collection(col_name: str):
    try:
        if hasattr(db, col_name) and getattr(db, col_name) is not None:
            return getattr(db, col_name)
        if hasattr(db, 'db') and hasattr(db.db, col_name):
            return getattr(db.db, col_name)
        return db.get_collection(col_name)
    except Exception:
        return None

async def fetch_user_name(client, uid: int) -> str:
    try:
        user = await client.get_users(uid)
        return user.first_name or "User"
    except Exception:
        return "User"

def user_link(name: str, uid: int) -> str:
    return f"<b>👤 User: <a href='tg://user?id={uid}'>{name}</a></b> (<code>{uid}</code>)"

async def get_user_display(client, uid: int, fallback_name: str = "User") -> str:
    name = await fetch_user_name(client, uid)
    if name == "User" and fallback_name != "User":
        name = fallback_name
    return user_link(name, uid)

def get_plan_keyboard(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1 Month - ₹40", callback_data=f"selplan_{uid}_30d_40"), InlineKeyboardButton("2 Months - ₹80", callback_data=f"selplan_{uid}_60d_80")],
        [InlineKeyboardButton("6 Months - ₹240", callback_data=f"selplan_{uid}_180d_240"), InlineKeyboardButton("1 Year - ₹480", callback_data=f"selplan_{uid}_365d_480")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"min_rej_{uid}")]
    ])

def parse_plan_duration(duration_str: str):
    if duration_str == "30d":
        return timedelta(days=30), "1 Month"
    elif duration_str == "60d":
        return timedelta(days=60), "2 Months"
    elif duration_str == "180d":
        return timedelta(days=180), "6 Months"
    elif duration_str == "365d":
        return timedelta(days=365), "1 Year"
    else:
        raise ValueError("Invalid or expired plan duration selected.")

async def safe_edit_message(message, text, reply_markup=None):
    try:
        await message.edit_caption(text, reply_markup=reply_markup, parse_mode=enums.ParseMode.HTML)
    except MessageNotModified:
        pass
    except Exception:
        try:
            await message.edit_text(text, reply_markup=reply_markup, parse_mode=enums.ParseMode.HTML)
        except MessageNotModified:
            pass

async def notify_owner(client: Client, text: str):
    try:
        await client.send_message(int(OWNER), text, disable_web_page_preview=True, parse_mode=enums.ParseMode.HTML)
    except Exception:
        pass

async def safe_premium_log(client: Client, text: str):
    global PREMIUM_LOG
    if PREMIUM_LOG:
        try:
            log_id = int(PREMIUM_LOG)
            try:
                await client.get_chat(log_id)
            except Exception:
                await client.resolve_peer(log_id)
            
            await client.send_message(
                log_id,
                text,
                parse_mode=enums.ParseMode.HTML,
                disable_web_page_preview=True
            )
            return
        except Exception as e:
            logger.warning(f"PREMIUM_LOG failed ({e}), falling back to owner DM.")
    
    await notify_owner(client, text)

async def safe_kick(client: Client, chat_id, user_id) -> bool:
    if not chat_id: 
        return True
    
    try:
        cid = int(chat_id)
    except ValueError:
        return True

    u_link = await get_user_display(client, user_id)
    
    try:
        await client.resolve_peer(cid)
    except Exception:
        try:
            await client.get_chat(cid)
        except Exception:
            pass

    try:
        await client.ban_chat_member(cid, user_id)
        await asyncio.sleep(0.3)
        await client.unban_chat_member(cid, user_id)
        return True
    except Exception as e:
        err_str = str(e)
        if "USER_NOT_PARTICIPANT" in err_str or "PEER_ID_INVALID" in err_str:
            return True

        await safe_premium_log(client, f"<b>⚠️ Expired User Kick Failed (1)</b>\n\n{u_link}\n<b>❓ Reason: {e}</b>\n\n")

    await asyncio.sleep(60)

    try:
        try: 
            await client.resolve_peer(cid)
        except Exception: 
            try: await client.get_chat(cid)
            except Exception: pass
            
        await client.ban_chat_member(cid, user_id)
        await asyncio.sleep(0.3)
        await client.unban_chat_member(cid, user_id)
        await safe_premium_log(client, f"<b>✅ Expired User Kick Successful</b>\n{u_link}")
        return True
    except Exception as retry_err:
        await safe_premium_log(client, f"<b>⚠️ Expired User Kick Failed (2)</b>\n{u_link}\n<b>❓ Reason: {retry_err}\n♻ Retrying in Next Loop</b>")
        return False

async def premium_expiry_reminder_loop(client: Client):
    await asyncio.sleep(10)
    try:
        now = datetime.utcnow()
        col = get_col()
        if col:
            async for doc in col.find({"active": True, "expires_at": {"$lte": now}}):
                uid = doc.get("user_id")
                name = doc.get("username", "User")
                exp = doc.get("expires_at")
                user_display = user_link(name, uid)
                
                if PREMIUM_GROUP_ID: 
                    kicked = await safe_kick(client, PREMIUM_GROUP_ID, uid)
                    if not kicked:
                        continue
                
                await col.delete_one({"user_id": uid})
                    
                await safe_premium_log(client, f"<b>❌ Missed Expiry Catch-Up & Ejected</b>\n\n{user_display}\n<b>• Plan: {doc.get('plan', 'N/A')}</b>\n<b>• Expired On: {fmt_date(exp)}</b>")
                try:
                    await client.send_message(
                        uid, 
                        "<b>⚠️ Premium Membership Expired!</b>", 
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Renew Plan", callback_data="buy_premium_start")]]), 
                        parse_mode=enums.ParseMode.HTML
                    )
                except Exception: 
                    pass
    except Exception as e:
        logger.error(f"Startup expiry check error: {e}")

    while True:
        try:
            now = datetime.utcnow()
            col = get_col()
            if col:
                async for doc in col.find({"active": True}):
                    uid, exp = doc.get("user_id"), doc.get("expires_at")
                    name = doc.get("username", "User")
                    user_display = user_link(name, uid)
                    
                    if not isinstance(exp, datetime): continue
                    
                    reminders = doc.get("reminders", {})
                    if not reminders.get("1_day") and timedelta(seconds=0) < (exp - now) <= timedelta(days=1):
                        try:
                            await client.send_message(
                                uid, 
                                "<b>⚠️ Your Premium Membership is expiring in 1 day!\n\nRenew now to maintain uninterrupted access.</b>", 
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Renew Now", callback_data="buy_premium_start")]]), 
                                parse_mode=enums.ParseMode.HTML
                            )
                            await col.update_one({"user_id": uid}, {"$set": {"reminders.1_day": True}})
                        except Exception: 
                            pass

                    if now >= exp:
                        if PREMIUM_GROUP_ID: 
                            kicked = await safe_kick(client, PREMIUM_GROUP_ID, uid)
                            if not kicked:
                                continue
                        
                        await col.delete_one({"user_id": uid})
                        
                        await safe_premium_log(client, f"<b>❌ Premium Membership Expired & Ejected</b>\n\n{user_display}\n<b>• Plan: {doc.get('plan', 'N/A')}</b>\n<b>• Expired On: {fmt_date(exp)}</b>")
                        try:
                            await client.send_message(uid, "<b>⚠️ Premium Membership Expired!\n\nRenew your plan to restore your premium status.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Renew Plan", callback_data="buy_premium_start")]]), parse_mode=enums.ParseMode.HTML)
                        except Exception: pass
        except Exception as e:
            logger.error(f"Expiry loop error: {e}")
            
        await asyncio.sleep(3600)

@Client.on_message(filters.command("approve") & filters.user(OWNER))
async def approve_command(client, message):
    if len(message.command) < 2:
        return await message.reply_text("<b>⚠️ Usage: /approve [user_id]</b>", parse_mode=enums.ParseMode.HTML)
    try:
        uid = int(message.command[1])
        u_link = await get_user_display(client, uid)
        
        col_ses = get_db_collection('admin_approval_sessions')
        if col_ses is not None:
            await col_ses.update_one({"admin_id": message.from_user.id}, {"$set": {"target_user_id": uid}}, upsert=True)

        kb = get_plan_keyboard(uid)
        await message.reply_text(f"<b>💎 Select Plan Package for</b>\n{u_link}", reply_markup=kb, parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        await message.reply_text(f"<b>❌ Error: {e}</b>", parse_mode=enums.ParseMode.HTML)

@Client.on_message(filters.command("revoke") & filters.user(OWNER))
async def revoke_command(client, message):
    if len(message.command) < 2:
        return await message.reply_text("<b>⚠️ Usage: /revoke [user_id]</b>", parse_mode=enums.ParseMode.HTML)
    try:
        uid = int(message.command[1])
        u_link = await get_user_display(client, uid)
        
        if PREMIUM_GROUP_ID:
            kicked = await safe_kick(client, PREMIUM_GROUP_ID, uid)
            if not kicked:
                return await message.reply_text(
                    f"<b>❌ Revocation Halted</b>\n\n{u_link}\n<b>• Automated kick failed. Database record retained for safety.</b>",
                    parse_mode=enums.ParseMode.HTML
                )
        
        col = get_col()
        if col:
            await col.delete_one({"user_id": uid})
            
        try:
            await client.send_message(uid, "<b>❌ Your Premium Membership has been revoked by administration.</b>", parse_mode=enums.ParseMode.HTML)
        except Exception: pass
        await message.reply_text(f"<b>✅ Successfully revoked premium for</b>\n{u_link}", parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        await message.reply_text(f"<b>❌ Error: {e}</b>", parse_mode=enums.ParseMode.HTML)

@Client.on_message(filters.command("premiums") & filters.user(OWNER))
async def premiums_command(client, message):
    col = get_col()
    if not col:
        return await message.reply_text("<b>❌ Database collection unavailable.</b>", parse_mode=enums.ParseMode.HTML)
    text = "<b>💎 Active Premium Members List:</b>\n\n"
    count = 0
    async for doc in col.find({"active": True}):
        count += 1
        uid = doc.get("user_id")
        name = doc.get("username", "User")
        plan = doc.get("plan")
        exp = fmt_date(doc.get("expires_at"))
        text += f"<b>{count}.</b> {user_link(name, uid)}\n<b>   • Plan: {plan}</b>\n<b>   • Expires: {exp}</b>\n\n"
    if count == 0:
        text = "<b>❌ No active premium users found.</b>"
    if len(text) > 4096:
        file = 'premium_users.txt'
        with open(file, 'w', encoding='utf-8') as f: f.write(text)
        await message.reply_document(file)
        os.remove(file)
    else:
        await message.reply_text(text, parse_mode=enums.ParseMode.HTML)

@Client.on_message(filters.command("start") & filters.incoming)
async def start(client, message):
    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        await message.reply(script.START_TXT.format(message.from_user.mention if message.from_user else message.chat.title, temp.U_NAME, temp.B_NAME), disable_web_page_preview=True)
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
    
    if len(message.command) == 2 and message.command[1] == "i_paid":
        try:
            col_intent = get_db_collection('user_payment_intents')
            if col_intent is not None:
                await col_intent.update_one({"user_id": message.from_user.id}, {"$set": {"action": "i_paid_clicked", "timestamp": datetime.utcnow()}}, upsert=True)
        except Exception: pass
        return await message.reply_text("<b>📸 Send Payment Proof!\n\nPlease upload your transaction screenshot to verify!</b>", parse_mode=enums.ParseMode.HTML)

    data = message.command[1]

    user_id = message.from_user.id
    is_admin = (user_id == OWNER)
    col = get_col()
    is_premium = is_admin or (col and await col.find_one({"user_id": user_id, "active": True}))
    
    if not is_premium:
        return await message.reply_text(
            "<b>🔒 This file is exclusive to Premium members. Upgrade your plan to access.</b>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🌟 Buy Premium", callback_data="buy_premium_start")]]),
            parse_mode=enums.ParseMode.HTML
        )

    try: pre, file_id = data.split('_', 1)
    except: file_id, pre = data, ""

    files_ = await get_file_details(file_id)            
    if not files_:
        try:
            pre, file_id = ((base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))).decode("ascii")).split("_", 1)
            msg = await client.send_cached_media(
                chat_id=message.from_user.id,
                file_id=file_id,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔆彡⟨ HEROFLiX ⟩彡🔆', url=f'https://telegram.me/{CHNL_LNK}')]])
            )
            filetype = msg.media
            file = getattr(msg, filetype.value)
            title = ' '.join(filter(lambda x: not x.startswith('www.') and not x.startswith('@'), file.file_name.split()))
            size = get_size(file.file_size)
            f_caption = f"{title}"
            if CUSTOM_FILE_CAPTION:
                try:
                    f_caption = CUSTOM_FILE_CAPTION.format(file_name=title, file_size=size, file_caption='')
                except:
                    pass
            await msg.edit_caption(f_caption)
            return
        except Exception:
            return await message.reply('No such file exist.')

    files = files_[0]
    title = ' '.join(filter(lambda x: not x.startswith('www.') and not x.startswith('@'), files.file_name.split()))
    size = get_size(files.file_size)
    f_caption = files.caption
    if CUSTOM_FILE_CAPTION:
        try:
            f_caption = CUSTOM_FILE_CAPTION.format(file_name=title, file_size=size, file_caption=f_caption or '')
        except Exception as e:
            logger.exception(e)
    if f_caption is None:
        f_caption = title

    await client.send_cached_media(
        chat_id=message.from_user.id,
        file_id=file_id,
        caption=f_caption,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔆彡⟨ HEROFLiX ⟩彡🔆', url=f'https://telegram.me/{CHNL_LNK}')]])
    )
    return

@Client.on_message(filters.command("myplan") & filters.private)
async def check_my_plan(client, message):
    user_id = message.from_user.id
    col = get_col()
    doc = await col.find_one({"user_id": user_id, "active": True}) if col else None
    if not doc:
        return await message.reply_text("<b>❌ No active Premium subscription.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🌟 Buy Premium", callback_data="buy_premium_start")]]), parse_mode=enums.ParseMode.HTML)
    plan, expires_at, price = doc.get("plan"), doc.get("expires_at"), doc.get("price", "40")
    now = datetime.utcnow()
    rem = expires_at - now if expires_at and expires_at > now else None
    left_str = f"{rem.days} Days" if rem and rem.days > 0 else (f"{rem.seconds // 3600} Hours {(rem.seconds % 3600) // 60} Minutes" if rem else "Expired")
    await message.reply_text(
        f"<b>🌟 Premium Membership Active ✅</b>\n\n"
        f"{user_link(message.from_user.first_name, user_id)}\n"
        f"<b>💰 Plan: {plan} | ₹{price}</b>\n"
        f"<b>⌛ Expiry: {fmt_date(expires_at)}</b>\n"
        f"<b>⏳ Remaining: {left_str}</b>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Renew Plan", callback_data="buy_premium_start")]]),
        parse_mode=enums.ParseMode.HTML
    )

@Client.on_message(filters.command("premium") & filters.private)
@Client.on_callback_query(filters.regex("^buy_premium_start$"))
async def premium_menu(client, update):
    message = update.message if isinstance(update, CallbackQuery) else update
    if isinstance(update, CallbackQuery): await update.answer()
    text = (
        "<b>🌟 Premium Plans:-\n\n"
        "✨ 1 Month: ₹40\n"
        "✨ 2 Months: ₹80\n"
        "✨ 6 Months: ₹240\n"
        "✨ 1 Year: ₹480</b>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Click Here To Pay", callback_data="click_here_to_pay")]
    ])
    if isinstance(update, CallbackQuery):
        try: await message.delete()
        except Exception: pass
        await client.send_message(message.chat.id, text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)
    else:
        await message.reply_text(text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex("^click_here_to_pay$"))
async def click_here_to_pay_cb(client, callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    qr_caption = "<b>📸 Scan QR CODE or use UPI ID to Pay:\n\nUPI ID:</b> <code>karthik.slice@ibl</code>"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I Paid", callback_data="minimal_send_proof")]
    ])
    await client.send_photo(
        chat_id=callback.message.chat.id,
        photo="https://ibb.co/KHqPKqg",
        caption=qr_caption,
        reply_markup=kb,
        parse_mode=enums.ParseMode.HTML
    )

@Client.on_callback_query(filters.regex("^minimal_send_proof$"))
async def send_proof_cb(client, callback: CallbackQuery):
    try:
        col_intent = get_db_collection('user_payment_intents')
        if col_intent is not None:
            await col_intent.update_one({"user_id": callback.from_user.id}, {"$set": {"action": "i_paid_clicked", "timestamp": datetime.utcnow()}}, upsert=True)
    except Exception: pass
    await callback.answer()
    try: await callback.message.delete()
    except Exception: pass
    await client.send_message(callback.message.chat.id, "<b>📸 Send Payment Proof!\n\nPlease upload your transaction screenshot to verify!</b>", parse_mode=enums.ParseMode.HTML)

async def update_user_payment_intent(client, user_id: int, action: str, file_id: str = None):
    col_intent = get_db_collection('user_payment_intents')
    if col_intent is not None:
        old_doc = await col_intent.find_one({"user_id": user_id})
        
        if old_doc and old_doc.get("admin_msg_ids"):
            for admin_id, msg_id in old_doc["admin_msg_ids"].items():
                try:
                    await client.delete_messages(chat_id=int(admin_id), message_ids=int(msg_id))
                except Exception:
                    pass

        data = {
            "user_id": user_id,
            "action": action,
            "file_id": file_id,
            "timestamp": datetime.utcnow(),
            "admin_msg_ids": {}
        }
        await col_intent.update_one({"user_id": user_id}, {"$set": data}, upsert=True)

@Client.on_message(filters.private & (filters.photo | filters.document) & ~filters.command(["start", "premium"]))
async def screenshot_handler(client, message):
    user_id = message.from_user.id
    is_valid_intent = False
    
    try:
        col_intent = get_db_collection('user_payment_intents')
        if col_intent is not None:
            doc = await col_intent.find_one({"user_id": user_id})
            if doc:
                is_valid_intent = True
                if doc.get("admin_msg_ids"):
                    for admin_id, msg_id in doc["admin_msg_ids"].items():
                        try:
                            await client.delete_messages(chat_id=int(admin_id), message_ids=int(msg_id))
                        except Exception:
                            pass
    except Exception: 
        pass

    if not is_valid_intent:
        return

    await message.reply_text("<b>✅ Your screenshot has been submitted for verification, please wait!</b>", parse_mode=enums.ParseMode.HTML)
    
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"min_app_{user_id}"), InlineKeyboardButton("❌ Reject", callback_data=f"min_rej_{user_id}")]])
    text = (
        f"<b>🔔 New Payment Verification</b>\n\n"
        f"{user_link(message.from_user.first_name, user_id)}"
    )
    
    fid = message.photo.file_id if message.photo else message.document.file_id
    admin_msg_ids = {}

    try:
        sent_msg = None
        if message.photo: 
            sent_msg = await client.send_photo(int(OWNER), fid, caption=text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)
        else: 
            sent_msg = await client.send_document(int(OWNER), fid, caption=text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)
        
        if sent_msg:
            admin_msg_ids[str(OWNER)] = sent_msg.id
    except Exception: 
        pass

    try:
        col_intent = get_db_collection('user_payment_intents')
        if col_intent is not None:
            await col_intent.update_one(
                {"user_id": user_id}, 
                {"$set": {"admin_msg_ids": admin_msg_ids, "action": "screenshot_sent", "timestamp": datetime.utcnow()}}, 
                upsert=True
            )
    except Exception:
        pass

@Client.on_callback_query(filters.regex("^min_app_"))
async def admin_app_cb(client, callback: CallbackQuery):
    if callback.from_user.id != OWNER: return await callback.answer("Unauthorized.", show_alert=True)
    uid = int(callback.data.split("_")[2])
    
    try:
        col_ses = get_db_collection('admin_approval_sessions')
        if col_ses is not None:
            await col_ses.update_one({"admin_id": callback.from_user.id}, {"$set": {"target_user_id": uid}}, upsert=True)
    except Exception: pass

    kb = get_plan_keyboard(uid)
    await callback.answer()
    text = "<b>💎 Select Plan Package</b>"
    await safe_edit_message(callback.message, text, reply_markup=kb)

@Client.on_callback_query(filters.regex("^selplan_"))
async def select_plan_cb(client, callback: CallbackQuery):
    if callback.from_user.id != OWNER: return await callback.answer("Unauthorized.", show_alert=True)
    _, uid_str, duration_str, price = callback.data.split("_")
    uid = int(uid_str)
    
    now = datetime.utcnow()
    delta, plan_name = parse_plan_duration(duration_str)

    col = get_col()
    existing = await col.find_one({"user_id": uid, "active": True}) if col else None
    start = existing.get("expires_at") if existing and isinstance(existing.get("expires_at"), datetime) and existing.get("expires_at") > now else now
    exp = start + delta

    u_link = await get_user_display(client, uid)
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data=f"confact_{uid}_{duration_str}_{price}"), InlineKeyboardButton("◀ Back", callback_data=f"min_app_{uid}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"min_rej_{uid}")]
    ])
    text = (
        f"<b>💎 Preview Panel</b>\n\n"
        f"{u_link}\n"
        f"<b>✨ Plan: {plan_name} | ₹{price}</b>\n"
        f"<b>📆 Expiry: {fmt_date(exp)}</b>"
    )
    await callback.answer()
    await safe_edit_message(callback.message, text, reply_markup=kb)

@Client.on_callback_query(filters.regex("^confact_"))
async def conf_act_cb(client, callback: CallbackQuery):
    if callback.from_user.id != OWNER: return await callback.answer("Unauthorized.", show_alert=True)
    _, uid_str, duration_str, price = callback.data.split("_")
    uid = int(uid_str)
    
    now = datetime.utcnow()
    delta, plan = parse_plan_duration(duration_str)

    name = await fetch_user_name(client, uid)
    u_link = user_link(name, uid)
    await callback.answer("Activating...")
    
    col = get_col()
    existing = await col.find_one({"user_id": uid, "active": True}) if col else None
    is_renewal = existing is not None
    start = existing.get("expires_at") if existing and isinstance(existing.get("expires_at"), datetime) and existing.get("expires_at") > now else now
    exp = start + delta
    
    if PREMIUM_GROUP_ID:
        try: 
            cid = int(PREMIUM_GROUP_ID)
            await client.unban_chat_member(cid, uid)
            await client.approve_chat_join_request(chat_id=cid, user_id=uid)
        except Exception: 
            pass

    data = {"user_id": uid, "username": name, "plan": plan, "price": price, "purchased_at": now, "expires_at": exp, "active": True, "reminders": {"1_day": False}}
    if col: await col.update_one({"user_id": uid}, {"$set": data}, upsert=True)
    
    try:
        col_intent = get_db_collection('user_payment_intents')
        col_ses = get_db_collection('admin_approval_sessions')
        if col_intent is not None: await col_intent.delete_many({"user_id": uid})
        if col_ses is not None: await col_ses.delete_many({"admin_id": callback.from_user.id})
    except Exception: pass

    link = PREMIUM_PERMANENT_LINK or "https://t.me/your_group_link"
    title_msg = "<b>🌟 Premium Membership Renewed ✅</b>" if is_renewal else "<b>🌟 Premium Membership Active ✅</b>"
    try:
        await client.send_message(
            uid, 
            f"{title_msg}\n\n"
            f"<b>💰 Plan: {plan} | ₹{price}</b>\n"
            f"<b>⌛ Expiry: {fmt_date(exp)}</b>\n\n"
            f"<b>✨ Join Premium Group:</b>", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🧤 Click Here To Join", url=link)]]), 
            parse_mode=enums.ParseMode.HTML
        )
    except Exception: pass
    
    log_title = "<b>🌟 Premium Renewed ✅</b>" if is_renewal else "<b>🌟 Premium Activated ✅</b>"
    await safe_premium_log(client, f"{log_title}\n\n{u_link}\n<b>• 💰 Plan: {plan} | ₹{price}</b>\n<b>• ⌛ Expiry: {fmt_date(exp)}</b>")
    
    success_text = f"<b>✅ Activated Successfully</b>\n{u_link}"
    await safe_edit_message(callback.message, success_text, reply_markup=None)

@Client.on_chat_join_request()
async def auto_accept(client, req: ChatJoinRequest):
    if PREMIUM_GROUP_ID and req.chat.id == int(PREMIUM_GROUP_ID):
        col = get_col()
        if col and await col.find_one({"user_id": req.from_user.id, "active": True}):
            try: await client.approve_chat_join_request(req.chat.id, req.from_user.id)
            except Exception: pass

@Client.on_chat_member_updated()
async def member_update(client, update: ChatMemberUpdated):
    if not PREMIUM_GROUP_ID: return
    try:
        if update.chat.id != int(PREMIUM_GROUP_ID): return
    except ValueError: return
    old, new = (update.old_chat_member.status if update.old_chat_member else enums.ChatMemberStatus.LEFT), (update.new_chat_member.status if update.new_chat_member else enums.ChatMemberStatus.LEFT)
    if old in [enums.ChatMemberStatus.LEFT, enums.ChatMemberStatus.BANNED] and new in [enums.ChatMemberStatus.MEMBER, enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
        user = update.new_chat_member.user
        if not user or user.is_bot: return
        col = get_col()
        if col:
            doc = await col.find_one({"user_id": user.id, "active": True})
            if not doc: return
            link = PREMIUM_PERMANENT_LINK or "https://t.me/your_group_link"
            text = (
                f"<b>🌟 Premium Activated ✅</b>\n\n"
                f"{user_link(user.first_name, user.id)}\n"
                f"<b>💰 Plan: {doc.get('plan')} | ₹{doc.get('price')}</b>\n"
                f"<b>⌛ Expiry: {fmt_date(doc.get('expires_at'))}</b>"
            )
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("✨ Premium Group", url=link)]])
            try: await client.send_message(user.id, text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)
            except Exception: pass

@Client.on_callback_query(filters.regex("^min_rej_"))
async def admin_reject_cb(client, callback: CallbackQuery):
    if callback.from_user.id != OWNER: return await callback.answer("Unauthorized.", show_alert=True)
    uid = int(callback.data.split("_")[-1])
    try:
        col_intent = get_db_collection('user_payment_intents')
        col_ses = get_db_collection('admin_approval_sessions')
        if col_intent is not None: await col_intent.delete_many({"user_id": uid})
        if col_ses is not None: await col_ses.delete_many({"admin_id": callback.from_user.id})
    except Exception: pass
    await callback.answer("Rejected.")
    try:
        await client.send_message(uid, "<b>⚠️ Payment Verification Failed.\n\nPlease Pay and Send a Valid Screenshot.</b>", parse_mode=enums.ParseMode.HTML)
    except Exception: pass
    rej_text = "<b>❌ Status: REJECTED</b>"
    await safe_edit_message(callback.message, rej_text, reply_markup=None)

@Client.on_message(filters.command('channel') & filters.user(OWNER))
async def channel_info(bot, message):
    channels = [CHANNELS] if isinstance(CHANNELS, (int, str)) else CHANNELS
    text = '<b>📑 Indexed channels/groups\n'
    for channel in channels:
        chat = await bot.get_chat(channel)
        text += ('\n@' + chat.username) if chat.username else ('\n' + (chat.title or chat.first_name))
    text += f'\n\nTotal: {len(channels)}</b>'
    if len(text) < 4096:
        await message.reply(text, parse_mode=enums.ParseMode.HTML)
    else:
        file = 'Indexed channels.txt'
        with open(file, 'w', encoding='utf-8') as f: f.write(text)
        await message.reply_document(file)
        os.remove(file)

@Client.on_message(filters.command('logs') & filters.user(OWNER))
async def log_file(bot, message):
    try: await message.reply_document('TelegramBot.log')
    except Exception as e: await message.reply(str(e))

@Client.on_message(filters.command('delete') & filters.user(OWNER))
async def delete(bot, message):
    reply = message.reply_to_message
    if not reply or not reply.media: return await message.reply('Reply to file with /delete', quote=True)
    msg = await message.reply("Processing...⏳", quote=True)
    media = next((getattr(reply, ft, None) for ft in ("document", "video", "audio") if getattr(reply, ft, None) is not None), None)
    if not media: return await msg.edit('Unsupported file format')
    file_id, _ = unpack_new_file_id(media.file_id)
    try:
        res = await Media.collection.delete_one({'_id': file_id})
        if not res.deleted_count:
            fn = re.sub(r"(_|\-|\.|\+)", " ", str(media.file_name))
            res = await Media.collection.delete_many({'file_name': fn, 'file_size': media.file_size, 'mime_type': media.mime_type})
        await msg.edit('🛃 Deleted File!' if res.deleted_count else 'File not found')
    except PyMongoError as e: await msg.edit(f'DB error: {e}')

@Client.on_message(filters.command('deleteall') & filters.user(OWNER))
async def delete_all_index(bot, message):
    await message.reply_text('Delete all indexed files?', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛃 Delete", callback_data="autofilter_delete")], [InlineKeyboardButton("💢 Cancel", callback_data="close_data")]]), quote=True)

@Client.on_callback_query(filters.regex(r'^autofilter_delete'))
async def delete_all_index_confirm(bot, callback):
    try:
        await Media.collection.drop()
        await callback.answer('Done')
        try: 
            await callback.message.edit('Successfully Deleted All Indexed Files.')
        except MessageNotModified: 
            pass
    except PyMongoError as e: await callback.answer(f'Error: {e}')

@Client.on_message(filters.command("deletefiles") & filters.user(OWNER))
async def deletemultiplefiles(bot, message):
    if message.chat.type != enums.ChatType.PRIVATE: return await message.reply_text("<b>Only Works in PM !</b>")
    try: kw = message.text.split(" ", 1)[1]
    except Exception: return await message.reply_text("<b>Give me a keyword!</b>")
    k = await bot.send_message(message.chat.id, "<b>Please Wait...</b>")
    _, total = await get_bad_files(kw)
    await k.delete()
    await message.reply_text(f"<b>{total} Files ➠ {kw}</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛃 Delete", callback_data=f"killfilesdq#{kw}")], [InlineKeyboardButton("💢 Cancel", callback_data="close_data")]]), parse_mode=enums.ParseMode.HTML)

@Client.on_message(filters.command("restart") & filters.user(OWNER))
async def restart_bot(bot, message):
    msg = await message.reply("<b>🔄 RESTARTING...</b>")
    await asyncio.sleep(1)
    try: 
        await msg.edit("<b>✅ RESTARTED!</b>")
    except MessageNotModified: 
        pass
    await asyncio.sleep(1)
    os.execl(sys.executable, sys.executable, *sys.argv)
