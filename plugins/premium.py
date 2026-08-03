import os
import logging
import asyncio
from datetime import datetime, timedelta
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ChatJoinRequest, ChatMemberUpdated
from pyrogram.errors import ChatAdminRequired, FloodWait
from database.users_chats_db import db
from info import ADMINS, PREMIUM_GROUP_ID, PREMIUM_LOG_CHANNEL, PREMIUM_PERMANENT_LINK, TUTORIAL
from pymongo.errors import PyMongoError
from utils import temp

logger = logging.getLogger(__name__)

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
    
    # 1. Force Pyrogram/Pyrofork to fetch and resolve peer cache to prevent PEER_ID_INVALID
    try:
        await client.get_chat(chat_id_int)
    except Exception:
        pass
        
    try:
        await client.resolve_peer(chat_id_int)
    except Exception:
        pass

    # 2. Attempt delivery to the channel
    try:
        await client.send_message(
            chat_id=chat_id_int, 
            text=text, 
            disable_web_page_preview=True, 
            parse_mode=enums.ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Failed to send log to PREMIUM_LOG_CHANNEL: {e}")
        
        # Fallback: Send to all ADMINS if channel broadcast completely fails
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
@Client.on_callback_query(filters.regex("^buy_premium_start$"))
async def minimal_premium_command(client, update):
    message = update.message if isinstance(update, CallbackQuery) else update
    if isinstance(update, CallbackQuery):
        await update.answer()
    text = "<b>💎 HeroFlix Premium Plans</b>\n\n• <b>1 Month</b>: ₹40\n• <b>2 Months</b>: ₹80\n• <b>6 Months</b>: ₹240\n• <b>1 Year</b>: ₹480\n\n1. Tap <b>Click Here To Buy</b> to pay.\n2. Click <b>I Have Paid</b> to send screenshot."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Click Here To Buy", url="https://fireluci.github.io/pay/")], [InlineKeyboardButton("✅ I Have Paid (Send Screenshot)", callback_data="minimal_send_proof")]])
    
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

    for admin_id in ADMINS:
        try:
            if message.photo:
                await client.send_photo(int(admin_id), file_id, caption=admin_text, reply_markup=admin_kb, parse_mode=enums.ParseMode.HTML)
            else:
                await client.send_document(int(admin_id), file_id, caption=admin_text, reply_markup=admin_kb, parse_mode=enums.ParseMode.HTML)
        except Exception as e:
            logger.error(f"Failed to send proof to admin {admin_id}: {e}")

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
