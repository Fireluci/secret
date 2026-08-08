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
from info import CHANNELS, ADMINS, LOG_CHANNEL, PICS, CUSTOM_FILE_CAPTION, CHNL_LNK, PREMIUM_GROUP_ID, PREMIUM_PERMANENT_LINK
from utils import get_size, temp
from pymongo.errors import PyMongoError
import re, sys, json, base64

logger = logging.getLogger(__name__)
BATCH_FILES = {}

def fmt_date(dt: datetime) -> str:
    return (dt + timedelta(hours=5, minutes=30)).strftime('%d %b, %Y at %I:%M %p') if isinstance(dt, datetime) else "N/A"

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

def get_plan_keyboard(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("2 Min Test", callback_data=f"selplan_{uid}_2m_80"), InlineKeyboardButton("5 Min Test", callback_data=f"selplan_{uid}_5m_80")],
        [InlineKeyboardButton("1 Month - ₹40", callback_data=f"selplan_{uid}_30d_40"), InlineKeyboardButton("2 Months - ₹80", callback_data=f"selplan_{uid}_60d_80")],
        [InlineKeyboardButton("6 Months - ₹240", callback_data=f"selplan_{uid}_180d_240"), InlineKeyboardButton("1 Year - ₹480", callback_data=f"selplan_{uid}_365d_480")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"min_rej_{uid}")]
    ])

def parse_plan_duration(duration_str: str):
    if duration_str.endswith("m"):
        mins = int(duration_str[:-1])
        return timedelta(minutes=mins), f"{mins} Min Test"
    else:
        days = int(duration_str[:-1])
        return timedelta(days=days), f"{days} Days Plan"

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

async def notify_admins(client: Client, text: str):
    for admin_id in ADMINS:
        try:
            await client.send_message(int(admin_id), text, disable_web_page_preview=True, parse_mode=enums.ParseMode.HTML)
        except Exception:
            pass

async def safe_kick(client: Client, chat_id, user_id):
    if not chat_id: 
        return
    try:
        cid = int(chat_id)
        await client.ban_chat_member(cid, user_id)
        await asyncio.sleep(0.3)
        await client.unban_chat_member(cid, user_id)
    except Exception as e:
        if "USER_NOT_PARTICIPANT" not in str(e) and "PEER_ID_INVALID" not in str(e):
            await notify_admins(client, f"<b>⚠️ Automated Kick Failed (Attempt 1)\n\n• User ID: {user_id}\n• Reason: {e}\n\n<i>Retrying in 1 minute...</i></b>")
            await asyncio.sleep(60)
            try:
                if hasattr(client, "get_chat"):
                    try: await client.get_chat(cid)
                    except Exception: pass
                await client.ban_chat_member(cid, user_id)
                await asyncio.sleep(0.3)
                await client.unban_chat_member(cid, user_id)
                await notify_admins(client, f"<b>✅ Automated Kick Succeeded on Retry (Attempt 2)\n• User ID: {user_id}</b>")
            except Exception as retry_err:
                await notify_admins(client, f"<b>❌ Automated Kick Permanently Failed (Attempt 2)\n• User ID: {user_id}\n• Final Error: {retry_err}</b>")

async def premium_expiry_reminder_loop(client: Client):
    await asyncio.sleep(5)
    try:
        now = datetime.utcnow()
        col = get_col()
        if col:
            async for doc in col.find({"active": True, "expires_at": {"$lte": now}}):
                uid = doc.get("user_id")
                name = doc.get("username", "User")
                exp = doc.get("expires_at")
                user_display = f"<a href='tg://user?id={uid}'>{name}</a> (<code>{uid}</code>)"
                
                await col.delete_one({"user_id": uid})
                if PREMIUM_GROUP_ID: 
                    await safe_kick(client, PREMIUM_GROUP_ID, uid)
                    
                await notify_admins(client, f"<b>❌ Missed Expiry Catch-Up & Ejected\n\n• 👤 User: {user_display}\n• Plan: <code>{doc.get('plan', 'N/A')}</code>\n• Expired On: <code>{fmt_date(exp)}</code></b>")
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
                    uid, exp = doc.get("user_id"), doc.get("expires_at") or doc.get("expiry_date")
                    name = doc.get("username", "User")
                    user_display = f"<a href='tg://user?id={uid}'>{name}</a> (<code>{uid}</code>)"
                    
                    if not isinstance(exp, datetime): continue
                    
                    reminders = doc.get("reminders", {})
                    if not reminders.get("30_sec") and timedelta(seconds=0) < (exp - now) <= timedelta(seconds=60):
                        try:
                            await client.send_message(
                                uid, 
                                "<b>⚠️ Your Premium Membership is expiring in less than a minute!\n\nRenew now to avoid getting ejected.</b>", 
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Renew Now", callback_data="buy_premium_start")]]), 
                                parse_mode=enums.ParseMode.HTML
                            )
                            await col.update_one({"user_id": uid}, {"$set": {"reminders.30_sec": True}})
                        except Exception: 
                            pass

                    if now >= exp:
                        await col.delete_one({"user_id": uid})
                        if PREMIUM_GROUP_ID: await safe_kick(client, PREMIUM_GROUP_ID, uid)
                        
                        await notify_admins(client, f"<b>❌ Premium Membership Expired & Ejected\n\n• 👤 User: {user_display}\n• Plan: <code>{doc.get('plan', 'N/A')}</code>\n• Expired On: <code>{fmt_date(exp)}</code></b>")
                        try:
                            await client.send_message(uid, "<b>⚠️ Premium Membership Expired!\n\nRenew your plan to restore your premium status.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Renew Plan", callback_data="buy_premium_start")]]), parse_mode=enums.ParseMode.HTML)
                        except Exception: pass
        except Exception as e:
            logger.error(f"Expiry loop error: {e}")
            
        await asyncio.sleep(30)

@Client.on_message(filters.command("approve") & filters.user(ADMINS))
async def approve_command(client, message):
    if len(message.command) < 2:
        return await message.reply_text("<b>⚠️ Usage: /approve [user_id]</b>", parse_mode=enums.ParseMode.HTML)
    try:
        uid = int(message.command[1])
        name = await fetch_user_name(client, uid)
        
        col_ses = get_db_collection('admin_approval_sessions')
        if col_ses is not None:
            await col_ses.update_one({"admin_id": message.from_user.id}, {"$set": {"target_user_id": uid}}, upsert=True)

        kb = get_plan_keyboard(uid)
        await message.reply_text(f"<b>💎 Select Plan Package for <a href='tg://user?id={uid}'>{name}</a> (<code>{uid}</code>)</b>", reply_markup=kb, parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        await message.reply_text(f"<b>❌ Error: {e}</b>", parse_mode=enums.ParseMode.HTML)

@Client.on_message(filters.command("revoke") & filters.user(ADMINS))
async def revoke_command(client, message):
    if len(message.command) < 2:
        return await message.reply_text("<b>⚠️ Usage: /revoke [user_id]</b>", parse_mode=enums.ParseMode.HTML)
    try:
        uid = int(message.command[1])
        col = get_col()
        if col:
            await col.delete_one({"user_id": uid})
        if PREMIUM_GROUP_ID:
            await safe_kick(client, PREMIUM_GROUP_ID, uid)
        try:
            await client.send_message(uid, "<b>❌ Your Premium Membership has been revoked by administration.</b>", parse_mode=enums.ParseMode.HTML)
        except Exception: pass
        await message.reply_text(f"<b>✅ Successfully revoked premium for user {uid}</b>", parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        await message.reply_text(f"<b>❌ Error: {e}</b>", parse_mode=enums.ParseMode.HTML)

@Client.on_message(filters.command("premiums") & filters.user(ADMINS))
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
        text += f"<b>{count}.</b> <a href='tg://user?id={uid}'>{name}</a> (<code>{uid}</code>)\n   • <b>Plan:</b> {plan}\n   • <b>Expires:</b> {exp}\n\n"
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
    is_admin = str(user_id) in map(str, ADMINS)
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
    plan, expires_at, price = doc.get("plan"), doc.get("expires_at") or doc.get("expiry_date"), doc.get("price", "40")
    now = datetime.utcnow()
    rem = expires_at - now if expires_at and expires_at > now else None
    left_str = f"{rem.days} Days" if rem and rem.days > 0 else (f"{rem.seconds // 60} Minutes {rem.seconds % 60} Seconds" if rem else "Expired")
    await message.reply_text(
        f"<b>🌟 Premium Membership Active ✅\n\n"
        f"• 👤 User: <a href='tg://user?id={user_id}'>{message.from_user.first_name}</a> ({user_id})\n"
        f"• 💰 Plan: {plan} | ₹{price}\n"
        f"• ⌛ Expiry: {fmt_date(expires_at)}\n"
        f"• ⏳ Remaining: {left_str}</b>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Renew Plan", callback_data="buy_premium_start")]]),
        parse_mode=enums.ParseMode.HTML
    )

@Client.on_message(filters.command("premium") & filters.private)
@Client.on_callback_query(filters.regex("^buy_premium_start$"))
async def premium_menu(client, update):
    message = update.message if isinstance(update, CallbackQuery) else update
    if isinstance(update, CallbackQuery): await update.answer()
    text = (
        "<b>🌟 Premium Plans:-</b>\n\n"
        "<b>• ✨ 1 Month: ₹40\n"
        "• ✨ 2 Months: ₹80\n"
        "• ✨ 6 Months: ₹240\n"
        "• ✨ 1 Year: ₹480</b>\n\n"
        "<b>1. Pay via Button below.\n"
        "2. Click ‘Click Here To Pay’</b>"
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
    qr_caption = "<b>📸 Scan QR or use UPI ID below to pay:\n\nUPI ID: <code>karthik.slice@ybl</code></b>"
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
                await col_intent.delete_one({"user_id": user_id})
    except Exception: pass

    if not is_valid_intent:
        return

    await message.reply_text("<b>✅ Your screenshot has been submitted for verification, please wait!</b>", parse_mode=enums.ParseMode.HTML)
    
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"min_app_{user_id}"), InlineKeyboardButton("❌ Reject", callback_data=f"min_rej_{user_id}")]])
    text = (
        f"<b>🔔 New Payment Verification\n\n"
        f"• 👤 User: <a href='tg://user?id={user_id}'>{message.from_user.first_name}</a> ({user_id})</b>"
    )
    
    fid = message.photo.file_id if message.photo else message.document.file_id
    for admin_id in ADMINS:
        try:
            if message.photo: await client.send_photo(int(admin_id), fid, caption=text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)
            else: await client.send_document(int(admin_id), fid, caption=text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)
        except Exception: pass

@Client.on_callback_query(filters.regex("^min_app_"))
async def admin_app_cb(client, callback: CallbackQuery):
    if str(callback.from_user.id) not in map(str, ADMINS): return await callback.answer("Unauthorized.", show_alert=True)
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
    if str(callback.from_user.id) not in map(str, ADMINS): return await callback.answer("Unauthorized.", show_alert=True)
    _, uid_str, duration_str, price = callback.data.split("_")
    uid = int(uid_str)
    
    now = datetime.utcnow()
    delta, plan_name = parse_plan_duration(duration_str)

    col = get_col()
    existing = await col.find_one({"user_id": uid, "active": True}) if col else None
    start = existing.get("expires_at") or existing.get("expiry_date") if existing and isinstance(existing.get("expires_at"), datetime) and existing.get("expires_at") > now else now
    exp = start + delta

    name = await fetch_user_name(client, uid)
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data=f"confact_{uid}_{duration_str}_{price}"), InlineKeyboardButton("◀ Back", callback_data=f"min_app_{uid}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"min_rej_{uid}")]
    ])
    text = (
        f"<b>💎 Preview Panel\n\n"
        f"• 👤 User: <a href='tg://user?id={uid}'>{name}</a> (<code>{uid}</code>)\n"
        f"• ✨ Plan: {plan_name} | ₹{price}\n"
        f"• 📆 Expiry: {fmt_date(exp)}</b>"
    )
    await callback.answer()
    await safe_edit_message(callback.message, text, reply_markup=kb)

@Client.on_callback_query(filters.regex("^confact_"))
async def conf_act_cb(client, callback: CallbackQuery):
    if str(callback.from_user.id) not in map(str, ADMINS): return await callback.answer("Unauthorized.", show_alert=True)
    _, uid_str, duration_str, price = callback.data.split("_")
    uid = int(uid_str)
    
    now = datetime.utcnow()
    delta, plan = parse_plan_duration(duration_str)

    name = await fetch_user_name(client, uid)
    await callback.answer("Activating...")
    
    col = get_col()
    existing = await col.find_one({"user_id": uid, "active": True}) if col else None
    is_renewal = existing is not None
    start = existing.get("expires_at") or existing.get("expiry_date") if existing and isinstance(existing.get("expires_at"), datetime) and existing.get("expires_at") > now else now
    exp = start + delta
    
    joined = False
    if PREMIUM_GROUP_ID:
        try:
            m = await client.get_chat_member(int(PREMIUM_GROUP_ID), uid)
            joined = m.status in [enums.ChatMemberStatus.MEMBER, enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]
        except Exception: pass
        try: await client.approve_chat_join_request(chat_id=int(PREMIUM_GROUP_ID), user_id=uid); joined = True
        except Exception: pass

    data = {"user_id": uid, "username": name, "plan": plan, "price": price, "purchased_at": now, "expires_at": exp, "expiry_date": exp, "active": True, "welcomed": joined, "reminders": {"30_sec": False}}
    if col: await col.update_one({"user_id": uid}, {"$set": data}, upsert=True)
    
    try:
        col_ses = get_db_collection('admin_approval_sessions')
        if col_ses is not None:
            await col_ses.delete_one({"admin_id": callback.from_user.id})
    except Exception: pass

    link = PREMIUM_PERMANENT_LINK or "https://t.me/your_group_link"
    title_msg = "<b>🌟 Premium Membership Renewed ✅</b>" if is_renewal else "<b>🌟 Premium Membership Active ✅</b>"
    try:
        msg = await client.send_message(
            uid, 
            f"{title_msg}\n\n"
            f"• 💰 Plan: {plan} | ₹{price}\n"
            f"• ⌛ Expiry: {fmt_date(exp)}\n\n"
            f"<b>✨ Join Premium Group:</b>", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🧤 click here to join", url=link)]]), 
            parse_mode=enums.ParseMode.HTML
        )
        if not joined and col and msg: await col.update_one({"user_id": uid}, {"$set": {"dm_msg_id": msg.id}})
    except Exception: pass
    
    log_title = "<b>🌟 Premium Renewed ✅</b>" if is_renewal else "<b>🌟 Premium Activated ✅</b>"
    await notify_admins(client, f"{log_title}\n\n• <b>👤 User:</b> <a href='tg://user?id={uid}'>{name}</a> (<code>{uid}</code>)\n• <b>💰 Plan:</b> {plan} | ₹{price}\n• <b>⌛ Expiry:</b> {fmt_date(exp)}")
    success_text = f"<b>✅ Activated Successfully\n• 👤 User:</b> <a href='tg://user?id={uid}'>{name}</a> (<code>{uid}</code>)"
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
                f"<b>🌟 Premium Activated ✅\n\n"
                f"• 👤 User: <a href='tg://user?id={user.id}'>{user.first_name}</a> ({user.id})\n"
                f"• 💰 Plan: {doc.get('plan')} | ₹{doc.get('price')}\n"
                f"• ⌛ Expiry: {fmt_date(doc.get('expires_at'))}</b>"
            )
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("✨ Premium Group", url=link)]])
            if doc.get("dm_msg_id"):
                try: return await client.edit_message_text(user.id, doc.get("dm_msg_id"), text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)
                except Exception: pass
            try: await client.send_message(user.id, text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)
            except Exception: pass

@Client.on_callback_query(filters.regex("^min_rej_"))
async def admin_reject_cb(client, callback: CallbackQuery):
    if str(callback.from_user.id) not in map(str, ADMINS): return await callback.answer("Unauthorized.", show_alert=True)
    uid = int(callback.data.split("_")[-1])
    try:
        col_intent = get_db_collection('user_payment_intents')
        col_ses = get_db_collection('admin_approval_sessions')
        if col_intent is not None: await col_intent.delete_one({"user_id": uid})
        if col_ses is not None: await col_ses.delete_one({"admin_id": callback.from_user.id})
    except Exception: pass
    await callback.answer("Rejected.")
    try:
        await client.send_message(uid, "<b>⚠️ Payment Verification Failed.\n\nPlease pay and send a valid screenshot.</b>", parse_mode=enums.ParseMode.HTML)
    except Exception: pass
    rej_text = "<b>❌ Status: REJECTED</b>"
    await safe_edit_message(callback.message, rej_text, reply_markup=None)

@Client.on_message(filters.command('channel') & filters.user(ADMINS))
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

@Client.on_message(filters.command('logs') & filters.user(ADMINS))
async def log_file(bot, message):
    try: await message.reply_document('TelegramBot.log')
    except Exception as e: await message.reply(str(e))

@Client.on_message(filters.command('delete') & filters.user(ADMINS))
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

@Client.on_message(filters.command('deleteall') & filters.user(ADMINS))
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

@Client.on_message(filters.command("deletefiles") & filters.user(ADMINS))
async def deletemultiplefiles(bot, message):
    if message.chat.type != enums.ChatType.PRIVATE: return await message.reply_text("<b>Only Works in PM !</b>")
    try: kw = message.text.split(" ", 1)[1]
    except Exception: return await message.reply_text("<b>Give me a keyword!</b>")
    k = await bot.send_message(message.chat.id, "<b>Please Wait...</b>")
    _, total = await get_bad_files(kw)
    await k.delete()
    await message.reply_text(f"<b>{total} Files ➠ {kw}</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛃 Delete", callback_data=f"killfilesdq#{kw}")], [InlineKeyboardButton("💢 Cancel", callback_data="close_data")]]), parse_mode=enums.ParseMode.HTML)

@Client.on_message(filters.command("restart") & filters.user(ADMINS))
async def restart_bot(bot, message):
    msg = await message.reply("<b>🔄 RESTARTING...</b>")
    await asyncio.sleep(1)
    try: 
        await msg.edit("<b>✅ RESTARTED!</b>")
    except MessageNotModified: 
        pass
    await asyncio.sleep(1)
    os.execl(sys.executable, sys.executable, *sys.argv)

API_ID = 20354559
API_HASH = "bbdf772b35141fa8b661740dddb840bf"
SESSION_STRING = "BQE2lf8AKLqlyjLoygEnyioQKt-iyJKQi6IxqUvpSIk5FCVW259dcZoUbYnath0zqwqRvf66o1IvsOyJL7-PI8gPiGlAHijRl25aa1Verk1bdd7s1y5Am4V7QtqY1k5jL1mu4-_beBdfWt5BmvLz4uKmQ4I8ERtQuPwGzLF7xqOVY2OMdAMaYGn5hpVKIWWU1iNa4ZYcUlHfqh6Ws1SNdYM6a13SxcFRMzIRtX0f41GXYG_ISuTxbR-G8jZH0i5XnE-IYx0F2Lev9fe_MbklaP5OlyzARvbIHmPdnc-DDeFuFw_c3-pNiKTROTtYCXbHjWGG4Hr3oayjHOq3h_964mHZmwHCSQAAAAGF3NwSAA"

INVITE_LINKS = [
    "https://t.me/+7QAPG4ERY0lhZWQ1", # 1. BACKUP 4
    "https://t.me/+-VyxToFvkA0wNmVl", # 2. BACKUP 3
    "https://t.me/+57sOfi_NiZwxYmNl", # 3. BackUp K
    "https://t.me/+tREA7LOsFaFhY2Fl"  # 4. BACKUP 2
]

STATE_FILE = "cleaner_state.json"
SAFE_DELAY = 0.8  # Slow, safe delay to completely protect against rate limits and overheating

async def run_cleaner_background(bot_client):
    async with Client("cleaner_worker", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING) as app:
        print("🤖 Safe Cleaner worker connected successfully!")

        start_channel_index = 0
        offset_id = 0
        scanned_count = 0
        deleted_count = 0
        seen_file_ids = set()

        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r") as f:
                    data = json.load(f)
                    start_channel_index = data.get("channel_index", 0)
                    offset_id = data.get("offset_id", 0)
                    scanned_count = data.get("scanned_count", 0)
                    deleted_count = data.get("deleted_count", 0)
                    seen_file_ids = set(data.get("seen_file_ids", []))
                print(f"📂 Resumed state loaded: Channel index {start_channel_index}, Scanned {scanned_count}, Deleted {deleted_count}.")
            except Exception as e:
                print(f"⚠️ Could not load state file, starting fresh: {e}")

        for idx in range(start_channel_index, len(INVITE_LINKS)):
            link = INVITE_LINKS[idx]
            print(f"\n🔗 Processing Channel {idx + 1} of {len(INVITE_LINKS)}: {link}")

            try:
                chat = await app.join_chat(link)
                target_chat_id = chat.id
            except Exception:
                try:
                    chat = await app.get_chat(link)
                    target_chat_id = chat.id
                except Exception as e:
                    print(f"❌ Could not access channel {link}: {e}")
                    continue

            kwargs = {}
            if offset_id:
                kwargs["offset_id"] = offset_id
                offset_id = 0  # Reset after resume usage

            async for msg in app.get_chat_history(target_chat_id, **kwargs):
                scanned_count += 1
                
                # Rule 1: Delete text-only or empty messages safely with a delay
                if msg.empty or not msg.media:
                    try:
                        await app.delete_messages(chat_id=target_chat_id, message_ids=msg.id)
                        deleted_count += 1
                        await asyncio.sleep(SAFE_DELAY)
                    except FloodWait as e:
                        await asyncio.sleep(e.value + 2)
                        await app.delete_messages(chat_id=target_chat_id, message_ids=msg.id)
                        deleted_count += 1
                    except Exception:
                        pass
                    continue
                
                # Rule 2: Keep only Video and Document. Delete photos, stickers, audio, GIFs, etc.
                if msg.media not in [enums.MessageMediaType.VIDEO, enums.MessageMediaType.DOCUMENT]:
                    try:
                        await app.delete_messages(chat_id=target_chat_id, message_ids=msg.id)
                        deleted_count += 1
                        await asyncio.sleep(SAFE_DELAY)
                    except FloodWait as e:
                        await asyncio.sleep(e.value + 2)
                        await app.delete_messages(chat_id=target_chat_id, message_ids=msg.id)
                        deleted_count += 1
                    except Exception:
                        pass
                    continue
                    
                media = getattr(msg, msg.media.value, None)
                if not media:
                    continue
                    
                # Rule 3: Check document extensions (.srt, .txt, .rar, .zip) and delete them
                file_name = getattr(media, "file_name", "") or ""
                if file_name.lower().endswith(('.srt', '.txt', '.rar', '.zip')):
                    try:
                        await app.delete_messages(chat_id=target_chat_id, message_ids=msg.id)
                        deleted_count += 1
                        await asyncio.sleep(SAFE_DELAY)
                    except FloodWait as e:
                        await asyncio.sleep(e.value + 2)
                        await app.delete_messages(chat_id=target_chat_id, message_ids=msg.id)
                        deleted_count += 1
                    except Exception:
                        pass
                    continue
                    
                file_unique_id = getattr(media, "file_unique_id", None)
                if not file_unique_id:
                    continue

                # Rule 4: Handle cross-channel duplicates for valid videos/documents
                if file_unique_id in seen_file_ids:
                    try:
                        await app.delete_messages(chat_id=target_chat_id, message_ids=msg.id)
                        deleted_count += 1
                        await asyncio.sleep(SAFE_DELAY)
                    except FloodWait as e:
                        await asyncio.sleep(e.value + 2)
                        await app.delete_messages(chat_id=target_chat_id, message_ids=msg.id)
                        deleted_count += 1
                    except Exception:
                        pass
                else:
                    seen_file_ids.add(file_unique_id)

                # Save state checkpoint every 50 messages to ensure zero data loss on restarts
                if scanned_count % 50 == 0:
                    state_data = {
                        "channel_index": idx,
                        "offset_id": msg.id,
                        "scanned_count": scanned_count,
                        "deleted_count": deleted_count,
                        "seen_file_ids": list(seen_file_ids)
                    }
                    with open(STATE_FILE, "w") as f:
                        json.dump(state_data, f)

        print(f"\n✅ All Channels Cleaned Successfully!\n● Total Scanned: {scanned_count}\n● Total Deleted: {deleted_count}")

# 1. Manual trigger command
@Client.on_message(filters.command("clean") & filters.private)
async def trigger_cleaner_command(client, message):
    asyncio.create_task(run_cleaner_background(client))
    await message.reply("🧹 **Safe Cleaner started!** Running slowly with built-in delays to protect your hardware and rate limits.")

# 2. Auto-resume on boot: Automatically starts up the background task as soon as your main bot launches/restarts
@Client.on_start()
async def auto_resume_cleaner(client):
    if os.path.exists(STATE_FILE):
        print("🔄 Detected existing cleaner state file on boot. Auto-resuming background cleaner...")
        asyncio.create_task(run_cleaner_background(client))
