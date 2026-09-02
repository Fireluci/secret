import os
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ChatJoinRequest, ChatMemberUpdated
from pyrogram.errors import MessageNotModified
from database.users_chats_db import db
from info import *

logger = logging.getLogger(__name__)
OWNER_ID = int(OWNER)
PREMIUM_LOG_ID = int(PREMIUM_LOG) if PREMIUM_LOG else None

def premium_col():
    return db.db.premium_users

def aux_col(name):
    return db.db[name]

def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def fmt_date(dt):
    return (dt + timedelta(hours=5, minutes=30)).strftime("%d %b, %Y") if isinstance(dt, datetime) else "N/A"

async def fetch_user_name(client, uid):
    try:
        user = await client.get_users(int(uid))
        return user.first_name or user.username or "User"
    except Exception:
        logger.exception("Failed to fetch user %s", uid)
        return "User"

def user_link(name, uid):
    return f"<b>👤 User: <a href='tg://user?id={uid}'>{name}</a></b> (<code>{uid}</code>)"

async def get_user_display(client, uid, fallback_name="User"):
    name = await fetch_user_name(client, uid)
    if name == "User" and fallback_name != "User":
        name = fallback_name
    return user_link(name, uid)

async def is_premium_user(client, user_id):
    if int(user_id) == OWNER_ID:
        return True
    return bool(await premium_col().find_one({
        "user_id": int(user_id),
        "active": True,
        "expires_at": {"$gt": now_utc()},
    }))

def get_plan_keyboard(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1 Month - ₹40", callback_data=f"selplan_{uid}_30d_40"),
         InlineKeyboardButton("2 Months - ₹80", callback_data=f"selplan_{uid}_60d_80")],
        [InlineKeyboardButton("6 Months - ₹240", callback_data=f"selplan_{uid}_180d_240"),
         InlineKeyboardButton("1 Year - ₹480", callback_data=f"selplan_{uid}_365d_480")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"min_rej_{uid}")],
    ])

def parse_plan_duration(duration_str):
    plans = {"30d": (30, "1 Month"), "60d": (60, "2 Months"), "180d": (180, "6 Months"), "365d": (365, "1 Year")}
    if duration_str not in plans:
        raise ValueError("Invalid or expired plan duration selected.")
    days, name = plans[duration_str]
    return timedelta(days=days), name

def premium_admin_chat(_, __, message):
    return bool(message.from_user and message.from_user.id == OWNER_ID and (
        message.chat.type == enums.ChatType.PRIVATE or
        (PREMIUM_LOG_ID is not None and message.chat.id == PREMIUM_LOG_ID)
    ))

def premium_admin_callback(callback):
    return bool(callback.from_user and callback.from_user.id == OWNER_ID and (
        callback.message and (
            callback.message.chat.type == enums.ChatType.PRIVATE or
            (PREMIUM_LOG_ID is not None and callback.message.chat.id == PREMIUM_LOG_ID)
        )
    ))

async def safe_edit_message(message, text, reply_markup=None):
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=enums.ParseMode.HTML)
        return True
    except MessageNotModified:
        return True
    except Exception:
        logger.exception("Premium text edit failed")
    try:
        await message.edit_caption(text, reply_markup=reply_markup, parse_mode=enums.ParseMode.HTML)
        return True
    except MessageNotModified:
        return True
    except Exception:
        logger.exception("Premium caption edit failed")
        return False

async def notify_owner(client, text):
    try:
        sent = await client.send_message(OWNER_ID, text, disable_web_page_preview=True, parse_mode=enums.ParseMode.HTML)
        return sent
    except Exception:
        logger.exception("Failed notifying OWNER")
        return None

async def resolve_log_peer(client):
    try:
        await client.get_chat(PREMIUM_LOG_ID)
        return True
    except Exception:
        logger.exception("Failed to resolve PREMIUM_LOG %s", PREMIUM_LOG_ID)
        return False

async def safe_premium_log(client, text):
    if PREMIUM_LOG_ID is not None:
        try:
            await client.get_chat(PREMIUM_LOG_ID)
        except Exception:
            pass
            
        try:
            return await client.send_message(
                PREMIUM_LOG_ID, 
                text, 
                parse_mode=enums.ParseMode.HTML, 
                disable_web_page_preview=True
            )
        except Exception:
            logger.exception("PREMIUM_LOG text delivery failed to %s", PREMIUM_LOG_ID)
    
    return await notify_owner(client, text)

async def safe_premium_proof(client, message, caption, keyboard):
    # Extract raw file_id to strip forward headers and bypass privacy restrictions
    is_doc = bool(message.document)
    fid = message.document.file_id if is_doc else message.photo.file_id
        
    if PREMIUM_LOG_ID and await resolve_log_peer(client):
        try:
            if is_doc:
                sent = await client.send_document(PREMIUM_LOG_ID, fid, caption=caption, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
            else:
                sent = await client.send_photo(PREMIUM_LOG_ID, fid, caption=caption, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
            return {str(PREMIUM_LOG_ID): sent.id}
        except Exception:
            logger.exception("PREMIUM_LOG screenshot delivery failed")

    # Fallback to OWNER_ID
    try:
        if is_doc:
            sent = await client.send_document(OWNER_ID, fid, caption=caption, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        else:
            sent = await client.send_photo(OWNER_ID, fid, caption=caption, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        return {str(OWNER_ID): sent.id}
    except Exception:
        logger.exception("OWNER screenshot fallback failed")
        return {}

async def safe_kick(client, user_id):
    if not PREMIUM_GROUP_ID:
        return True
        
    cid = int(PREMIUM_GROUP_ID)
    user_disp = await get_user_display(client, user_id)
    
    try:
        await client.get_chat(cid)
    except Exception:
        pass

    try:
        await client.ban_chat_member(cid, int(user_id))
        await asyncio.sleep(0.3)
        await client.unban_chat_member(cid, int(user_id))
        return True
    except Exception as exc:
        err_str = str(exc)
        if "USER_NOT_PARTICIPANT" in err_str or "PEER_ID_INVALID" in err_str:
            return True
            
        logger.exception("Premium member removal failed (1) for %s: %s", user_id, exc)
        await safe_premium_log(client, f"<b>⚠️ Expired User Kick Failed (1)</b>\n\n{user_disp}\n<b>❓ Reason:</b> {exc}")

    await asyncio.sleep(60)

    try:
        try:
            await client.get_chat(cid)
        except Exception:
            pass
            
        await client.ban_chat_member(cid, int(user_id))
        await asyncio.sleep(0.3)
        await client.unban_chat_member(cid, int(user_id))
        
        await safe_premium_log(client, f"<b>✅ Expired User Kick Successful</b>\n{user_disp}")
        return True
    except Exception as retry_err:
        logger.exception("Premium member removal failed (2) for %s: %s", user_id, retry_err)
        await safe_premium_log(client, f"<b>⚠️ Expired User Kick Failed (2)</b>\n\n{user_disp}\n<b>❓ Reason:</b> {retry_err}\n<b>♻ Retrying in Next Loop</b>")
        return False

PREMIUM_MENU_TEXT = (
    "<b>🌟 Choose Your Plan:-\n\n"
    "🔹 ₹40   – 1 Month\n"
    "🔸 ₹80   – 2 Months\n"
    "🔹 ₹240 – 6 Months\n"
    "🔸 ₹480 – 1 Year</b>"
)

def premium_menu_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Click Here To Pay", callback_data="click_here_to_pay")]])

@Client.on_message(filters.command("premium") & filters.private)
@Client.on_callback_query(filters.regex(r"^buy_premium_start$"))
async def premium_menu(client, update):
    try:
        if isinstance(update, CallbackQuery):
            await update.answer()
            await update.message.edit_text(PREMIUM_MENU_TEXT, reply_markup=premium_menu_markup(), parse_mode=enums.ParseMode.HTML)
        else:
            await update.reply_text(PREMIUM_MENU_TEXT, reply_markup=premium_menu_markup(), parse_mode=enums.ParseMode.HTML)
    except Exception:
        logger.exception("Premium menu failed")

@Client.on_callback_query(filters.regex(r"^buy_premium_start2$"))
async def premium_try_again(client, callback):
    try:
        await callback.answer()
        await callback.message.edit_text(PREMIUM_MENU_TEXT, reply_markup=premium_menu_markup(), parse_mode=enums.ParseMode.HTML)
    except Exception:
        logger.exception("Premium Try Again failed for user %s", callback.from_user.id)

@Client.on_callback_query(filters.regex(r"^click_here_to_pay$"))
async def click_here_to_pay_cb(client, callback):
    try:
        await callback.answer()
        try:
            await callback.message.delete()
        except Exception:
            logger.exception("Failed deleting premium payment menu for user %s", callback.from_user.id)
        await client.send_photo(
            callback.message.chat.id,
            photo="https://ibb.co/KHqPKqg",
            caption="<b>📸 Scan QR CODE or use UPI ID to Pay:\n\nUPI ID:</b> <code>karthik.slice@ibl</code>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ I Paid", callback_data="minimal_send_proof")]]),
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        logger.exception("Premium payment page failed for user %s", callback.from_user.id)

@Client.on_callback_query(filters.regex(r"^minimal_send_proof$"))
async def send_proof_cb(client, callback):
    try:
        await aux_col("user_payment_intents").update_one(
            {"user_id": callback.from_user.id},
            {"$set": {"action": "i_paid_clicked", "timestamp": now_utc(), "admin_msg_ids": {}}},
            upsert=True,
        )
        await callback.answer()
        try:
            await callback.message.delete()
        except Exception:
            logger.exception("Failed deleting payment page for user %s", callback.from_user.id)
        await client.send_message(
            callback.message.chat.id,
            "<b>📸 Send Payment Proof!\n\nPlease upload your transaction screenshot to verify!</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        logger.exception("Failed starting payment proof flow for user %s", callback.from_user.id)

@Client.on_message(filters.private & (filters.photo | filters.document) & ~filters.command(["start", "premium"]))
async def screenshot_handler(client, message):
    user_id = message.chat.id
    intent_col = aux_col("user_payment_intents")
    try:
        intent = await intent_col.find_one({"user_id": user_id})
        if not intent:
            return
        timestamp = intent.get("timestamp")
        if not isinstance(timestamp, datetime) or now_utc() - timestamp > timedelta(days=1):
            await intent_col.delete_one({"user_id": user_id})
            await message.reply_text(
                "<b>⚠️ Payment Verification Failed.</b>\n\nPlease pay again and send a valid screenshot.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Try Again", callback_data="buy_premium_start2")]]),
                parse_mode=enums.ParseMode.HTML,
            )
            return
        if intent.get("action") not in {"i_paid_clicked", "screenshot_sent"}:
            return
        for admin_id, msg_id in (intent.get("admin_msg_ids") or {}).items():
            try:
                await client.delete_messages(int(admin_id), int(msg_id))
            except Exception:
                logger.exception("Failed deleting previous payment proof %s for user %s", msg_id, user_id)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"min_app_{user_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"min_rej_{user_id}")
        ]])
        name = message.from_user.first_name if message.from_user else "User"
        caption = f"<b>🔔 New Payment Verification</b>\n\n{user_link(name, user_id)}"
        admin_msg_ids = await safe_premium_proof(client, message, caption, keyboard)
        if not admin_msg_ids:
            logger.error("Payment proof could not be delivered to PREMIUM_LOG or OWNER for user %s", user_id)
            await message.reply_text(
                "<b>⚠️ Payment Verification Failed.</b>\n\nPlease try again.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Try Again", callback_data="buy_premium_start2")]]),
                parse_mode=enums.ParseMode.HTML,
            )
            return
        await intent_col.update_one(
            {"user_id": user_id},
            {"$set": {"admin_msg_ids": admin_msg_ids, "action": "screenshot_sent", "timestamp": now_utc()}},
            upsert=True,
        )
        await message.reply_text("<b>✅ Payment proof submitted for verification.</b>", parse_mode=enums.ParseMode.HTML)
    except Exception:
        logger.exception("Payment screenshot workflow failed for user %s", user_id)
        try:
            await message.reply_text(
                "<b>⚠️ Payment Verification Failed.</b>\n\nPlease try again.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Try Again", callback_data="buy_premium_start2")]]),
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            logger.exception("Failed sending screenshot failure message to user %s", user_id)

@Client.on_message(filters.command("approve") & filters.create(premium_admin_chat))
async def approve_command(client, message):
    try:
        if len(message.command) < 2:
            return await message.reply_text("<b>⚠️ Usage: /approve [user_id]</b>", parse_mode=enums.ParseMode.HTML)
        uid = int(message.command[1])
        await aux_col("admin_approval_sessions").update_one({"admin_id": OWNER_ID}, {"$set": {"target_user_id": uid}}, upsert=True)
        await message.reply_text(f"<b>💎 Select Premium Plan</b>\n\n{await get_user_display(client, uid)}", reply_markup=get_plan_keyboard(uid), parse_mode=enums.ParseMode.HTML)
    except Exception:
        logger.exception("Premium /approve failed")
        await message.reply_text("<b>❌ Error processing approval command.</b>", parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex(r"^min_app_"))
async def approve_button(client, callback):
    if not premium_admin_callback(callback):
        return await callback.answer("Unauthorized.", show_alert=True)
    try:
        uid = int(callback.data.split("_")[-1])
        await aux_col("admin_approval_sessions").update_one({"admin_id": OWNER_ID}, {"$set": {"target_user_id": uid}}, upsert=True)
        await callback.answer()
        await safe_edit_message(callback.message, "<b>💎 Select Premium Plan</b>", get_plan_keyboard(uid))
    except Exception:
        logger.exception("Premium approval button failed for user %s", callback.from_user.id)

@Client.on_callback_query(filters.regex(r"^selplan_"))
async def select_plan(client, callback):
    if not premium_admin_callback(callback):
        return await callback.answer("Unauthorized.", show_alert=True)
    try:
        _, uid_text, duration, price = callback.data.split("_")
        uid = int(uid_text)
        delta, plan = parse_plan_duration(duration)
        now = now_utc()
        existing = await premium_col().find_one({"user_id": uid, "active": True})
        start = existing.get("expires_at") if existing and isinstance(existing.get("expires_at"), datetime) and existing.get("expires_at") > now else now
        exp = start + delta
        await callback.answer()
        await safe_edit_message(callback.message, f"<b>💎 Preview Panel</b>\n\n{await get_user_display(client, uid)}\n<b>✨ Plan:</b> {plan} | ₹{price}\n<b>📆 Expiry:</b> {fmt_date(exp)}", InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirm", callback_data=f"confact_{uid}_{duration}_{price}"), InlineKeyboardButton("◀ Back", callback_data=f"min_app_{uid}")],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"min_rej_{uid}")]
        ]))
    except Exception:
        logger.exception("Premium plan selection failed")

@Client.on_callback_query(filters.regex(r"^confact_"))
async def confirm_activation(client, callback):
    if not premium_admin_callback(callback):
        return await callback.answer("Unauthorized.", show_alert=True)
    try:
        _, uid_text, duration, price = callback.data.split("_")
        uid = int(uid_text)
        delta, plan = parse_plan_duration(duration)
        now = now_utc()
        col = premium_col()
        existing = await col.find_one({"user_id": uid, "active": True})
        start = existing.get("expires_at") if existing and isinstance(existing.get("expires_at"), datetime) and existing.get("expires_at") > now else now
        exp = start + delta
        name = await fetch_user_name(client, uid)

        # 1. Update Database FIRST to prevent group-join race conditions
        await col.update_one({"user_id": uid}, {"$set": {
            "user_id": uid, "username": name, "plan": plan, "price": price,
            "purchased_at": now, "expires_at": exp, "active": True,
            "reminders": {"1_day": False}
        }}, upsert=True)

        # 2. Unban and approve join request
        if PREMIUM_GROUP_ID:
            try:
                cid = int(PREMIUM_GROUP_ID)
                await client.unban_chat_member(cid, uid)
                await client.approve_chat_join_request(cid, uid)
            except Exception:
                logger.exception("Premium group activation failed for user %s", uid)
        
        await aux_col("admin_approval_sessions").delete_one({"admin_id": OWNER_ID})
        await aux_col("user_payment_intents").delete_one({"user_id": uid})
        
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("✨ Premium Group", url=PREMIUM_PERMANENT_LINK)]]) if PREMIUM_PERMANENT_LINK else None
        try:
            await client.send_message(uid, f"<b>{'🌟 Premium Membership Renewed ✅' if existing else '🌟 Premium Membership Active ✅'}</b>\n\n<b>💰 Plan:</b> {plan} | ₹{price}\n<b>⌛ Expiry:</b> {fmt_date(exp)}", reply_markup=markup, parse_mode=enums.ParseMode.HTML)
        except Exception:
            logger.exception("Failed notifying premium user %s about activation", uid)
            
        await safe_premium_log(client, f"<b>{'🌟 Premium Renewed ✅' if existing else '🌟 Premium Activated ✅'}</b>\n\n{user_link(name, uid)}\n<b>• Plan:</b> {plan} | ₹{price}\n<b>• Expiry:</b> {fmt_date(exp)}")
        await callback.answer("Activated")
        await safe_edit_message(callback.message, f"<b>✅ Activated Successfully</b>\n{user_link(name, uid)}")
    except Exception:
        logger.exception("Premium activation failed")
        await callback.answer("Activation failed. Check logs.", show_alert=True)

@Client.on_callback_query(filters.regex(r"^min_rej_"))
async def reject_payment(client, callback):
    if not premium_admin_callback(callback):
        return await callback.answer("Unauthorized.", show_alert=True)
    try:
        uid = int(callback.data.split("_")[-1])
        await aux_col("user_payment_intents").delete_one({"user_id": uid})
        await aux_col("admin_approval_sessions").delete_one({"admin_id": OWNER_ID})
        await callback.answer("Rejected.")
        try:
            await client.send_message(uid, "<b>⚠️ Payment Verification Failed.</b>\n\nPlease pay again and send a valid screenshot.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Try Again", callback_data="buy_premium_start2")]]), parse_mode=enums.ParseMode.HTML)
        except Exception:
            logger.exception("Failed notifying rejected premium payment for user %s", uid)
        await safe_edit_message(callback.message, f"<b>❌ Status: REJECTED</b>\n\n{await get_user_display(client, uid)}")
    except Exception:
        logger.exception("Premium rejection failed")

@Client.on_message(filters.command("revoke") & filters.create(premium_admin_chat))
async def revoke_premium(client, message):
    try:
        if len(message.command) < 2:
            return await message.reply_text("<b>⚠️ Usage: /revoke [user_id]</b>", parse_mode=enums.ParseMode.HTML)
        uid = int(message.command[1])
        if PREMIUM_GROUP_ID and not await safe_kick(client, uid):
            return await message.reply_text("<b>❌ Revocation halted because group removal failed.</b>", parse_mode=enums.ParseMode.HTML)
        await premium_col().delete_one({"user_id": uid})
        try:
            await client.send_message(uid, "<b>❌ Your Premium Membership has been revoked by administration.</b>", parse_mode=enums.ParseMode.HTML)
        except Exception:
            logger.exception("Failed notifying revoked premium user %s", uid)
        await safe_premium_log(client, f"<b>❌ Premium Revoked</b>\n\n{await get_user_display(client, uid)}")
        await message.reply_text(f"<b>✅ Premium revoked</b>\n{await get_user_display(client, uid)}", parse_mode=enums.ParseMode.HTML)
    except Exception:
        logger.exception("Premium /revoke failed")
        await message.reply_text("<b>❌ Error processing revoke command.</b>", parse_mode=enums.ParseMode.HTML)

@Client.on_message(filters.command("premiums") & filters.create(premium_admin_chat))
async def premiums_list(client, message):
    try:
        lines = ["<b>💎 Active Premium Members</b>", ""]
        count = 0
        async for doc in premium_col().find({"active": True}):
            count += 1
            uid = doc.get("user_id")
            lines += [f"<b>{count}.</b> {user_link(doc.get('username', 'User'), uid)}", f"<b>• Plan:</b> {doc.get('plan', 'N/A')}", f"<b>• Expires:</b> {fmt_date(doc.get('expires_at'))}", ""]
        text = "\n".join(lines) if count else "<b>❌ No active premium users found.</b>"
        if len(text) > 4096:
            path = "premium_users.txt"
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            try:
                await message.reply_document(path)
            finally:
                try:
                    os.remove(path)
                except OSError:
                    logger.exception("Failed removing temporary premium list")
        else:
            await message.reply_text(text, parse_mode=enums.ParseMode.HTML)
    except Exception:
        logger.exception("Premium /premiums failed")

@Client.on_message(filters.command("myplan") & filters.private)
async def my_plan(client, message):
    try:
        uid = message.from_user.id
        doc = await premium_col().find_one({"user_id": uid, "active": True})
        if not doc or not await is_premium_user(client, uid):
            return await message.reply_text("<b>❌ No active Premium subscription.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 Buy Premium", callback_data="buy_premium_start")]]), parse_mode=enums.ParseMode.HTML)
        exp = doc.get("expires_at")
        rem = exp - now_utc() if isinstance(exp, datetime) else None
        remaining = f"{rem.days} Days" if rem and rem.days > 0 else (f"{rem.seconds // 3600} Hours" if rem and rem.total_seconds() > 0 else "Expired")
        await message.reply_text(f"<b>🌟 Premium Membership Active ✅</b>\n\n{user_link(message.from_user.first_name, uid)}\n<b>💰 Plan:</b> {doc.get('plan')} | ₹{doc.get('price')}\n<b>⌛ Expiry:</b> {fmt_date(exp)}\n<b>⏳ Remaining:</b> {remaining}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Renew Now", callback_data="buy_premium_start")]]), parse_mode=enums.ParseMode.HTML)
    except Exception:
        logger.exception("Premium /myplan failed")

@Client.on_message(filters.command("text") & filters.create(premium_admin_chat))
async def send_text_to_user(client: Client, message):
    if len(message.command) < 3:
        return await message.reply_text("<b>⚠️ Usage: /text [user_id] [message]</b>", parse_mode=enums.ParseMode.HTML)
    
    try:
        target_uid = int(message.command[1])
        text_to_send = message.text.split(None, 2)[2]
        
        await client.send_message(
            chat_id=target_uid,
            text=f"<b>📩 Message from Administration:</b>\n\n{text_to_send}",
            parse_mode=enums.ParseMode.HTML
        )
        await message.reply_text(f"<b>✅ Message sent to <code>{target_uid}</code>!</b>", parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        await message.reply_text(f"<b>❌ Failed: {e}</b>", parse_mode=enums.ParseMode.HTML)

@Client.on_chat_join_request()
async def premium_join_request(client, request: ChatJoinRequest):
    if not PREMIUM_GROUP_ID:
        return
    try:
        if request.chat.id != int(PREMIUM_GROUP_ID):
            return
        if await is_premium_user(client, request.from_user.id):
            await client.approve_chat_join_request(request.chat.id, request.from_user.id)
    except Exception:
        logger.exception("Failed processing premium join request for %s", request.from_user.id)

@Client.on_chat_member_updated()
async def premium_member_update(client, update: ChatMemberUpdated):
    if not PREMIUM_GROUP_ID:
        return
    try:
        if update.chat.id != int(PREMIUM_GROUP_ID):
            return
            
        new_member = update.new_chat_member.user if update.new_chat_member else None
        if not new_member or new_member.is_bot:
            return

        new_status = update.new_chat_member.status if update.new_chat_member else None
        old_status = update.old_chat_member.status if update.old_chat_member else None

        if new_status == enums.ChatMemberStatus.MEMBER and old_status != enums.ChatMemberStatus.MEMBER:
            
            doc = await premium_col().find_one({"user_id": new_member.id, "active": True})
            
            if doc:
                exp = doc.get("expires_at")
                rem = exp - now_utc() if isinstance(exp, datetime) else None
                remaining = f"{rem.days} Days" if rem and rem.days > 0 else (f"{rem.seconds // 3600} Hours" if rem and rem.total_seconds() > 0 else "Expired")
                
                welcome_text = (
                    f"<b>🎉 Welcome to the Premium Group!</b>\n\n"
                    f"{user_link(new_member.first_name, new_member.id)}\n"
                    f"<b>💰 Plan:</b> {doc.get('plan')} | ₹{doc.get('price')}\n"
                    f"<b>⌛ Expiry:</b> {fmt_date(exp)}\n"
                    f"<b>⏳ Remaining:</b> {remaining}"
                )
                
                try:
                    # Delay to allow the user's UI to load the group chat
                    await asyncio.sleep(2)
                    await client.send_message(update.chat.id, welcome_text, parse_mode=enums.ParseMode.HTML)
                except Exception:
                    logger.exception("Failed to send welcome message to group for %s", new_member.id)
            else:
                if new_member.id != OWNER_ID:
                    await safe_kick(client, new_member.id)
                
    except Exception:
        logger.exception("Premium member update processing failed")

async def premium_expiry_loop(client):
    await asyncio.sleep(10)
    while True:
        try:
            now = now_utc()
            col = premium_col()
            intent_cutoff = now - timedelta(days=1)
            result = await aux_col("user_payment_intents").delete_many({"timestamp": {"$lt": intent_cutoff}})
            if result.deleted_count:
                logger.info("Removed %s expired payment intents", result.deleted_count)
            async for doc in col.find({"active": True}):
                uid, exp = doc.get("user_id"), doc.get("expires_at")
                if not uid or not isinstance(exp, datetime):
                    continue
                if now >= exp:
                    if PREMIUM_GROUP_ID and not await safe_kick(client, uid):
                        continue
                    await col.delete_one({"user_id": uid})
                    try:
                        await client.send_message(uid, "<b>⚠️ Premium Membership Expired.</b>\n\nRenew your plan to restore access.", parse_mode=enums.ParseMode.HTML)
                    except Exception:
                        logger.exception("Failed notifying expired premium user %s", uid)
                    await safe_premium_log(client, f"<b>⚠️ Premium Expired</b>\n\n{await get_user_display(client, uid)}")
                elif not doc.get("reminders", {}).get("1_day") and timedelta(0) < exp - now <= timedelta(days=1):
                    try:
                        await client.send_message(uid, "<b>⚠️ Your Premium Membership expires in 1 day.</b>\n\nRenew now to keep access.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Renew Now", callback_data="buy_premium_start")]]), parse_mode=enums.ParseMode.HTML)
                        await col.update_one({"user_id": uid}, {"$set": {"reminders.1_day": True}})
                    except Exception:
                        logger.exception("Failed sending premium expiry reminder to %s", uid)
        except Exception:
            logger.exception("Premium expiry loop error")
        await asyncio.sleep(3600)

async def start_premium_tasks(client):
    asyncio.create_task(premium_expiry_loop(client))
