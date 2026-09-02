import os
import logging
import asyncio
from datetime import datetime, timedelta

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ChatJoinRequest, ChatMemberUpdated
from pyrogram.errors import MessageNotModified

from database.users_chats_db import db
from info import *

logger = logging.getLogger(__name__)


def premium_col():
    return db.db.premium_users


def aux_col(name):
    return db.db[name]


def fmt_date(dt):
    return (
        (dt + timedelta(hours=5, minutes=30)).strftime("%d %b, %Y")
        if isinstance(dt, datetime)
        else "N/A"
    )


async def fetch_user_name(client, uid):
    try:
        user = await client.get_users(uid)
        return user.first_name or "User"
    except Exception:
        return "User"


def user_link(name, uid):
    return f"<b>👤 User: <a href='tg://user?id={uid}'>{name}</a></b> (<code>{uid}</code>)"


async def get_user_display(client, uid, fallback_name="User"):
    name = await fetch_user_name(client, uid)
    if name == "User" and fallback_name != "User":
        name = fallback_name
    return user_link(name, uid)


async def is_premium_user(client, user_id):
    if int(user_id) in {int(x) for x in OWNER}:
        return True

    return bool(
        await premium_col().find_one(
            {
                "user_id": int(user_id),
                "active": True,
                "expires_at": {"$gt": datetime.utcnow()},
            }
        )
    )


def get_plan_keyboard(uid):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1 Month - ₹40", callback_data=f"selplan_{uid}_30d_40"),
            InlineKeyboardButton("2 Months - ₹80", callback_data=f"selplan_{uid}_60d_80"),
        ],
        [
            InlineKeyboardButton("6 Months - ₹240", callback_data=f"selplan_{uid}_180d_240"),
            InlineKeyboardButton("1 Year - ₹480", callback_data=f"selplan_{uid}_365d_480"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"min_rej_{uid}")],
    ])


def parse_plan_duration(duration_str):
    plans = {
        "30d": (30, "1 Month"),
        "60d": (60, "2 Months"),
        "180d": (180, "6 Months"),
        "365d": (365, "1 Year"),
    }

    if duration_str not in plans:
        raise ValueError("Invalid or expired plan duration selected.")

    days, name = plans[duration_str]
    return timedelta(days=days), name


async def safe_edit_message(message, text, reply_markup=None):
    try:
        await message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML,
        )
        return
    except MessageNotModified:
        return
    except Exception:
        pass

    try:
        await message.edit_caption(
            text,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML,
        )
    except MessageNotModified:
        pass
    except Exception:
        logger.exception("Premium message edit failed")


async def notify_owner(client, text):
    try:
        await client.send_message(
            int(OWNER),
            text,
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        logger.exception("Failed notifying owner")


async def safe_premium_log(client, text):
    if PREMIUM_LOG:
        try:
            log_id = int(PREMIUM_LOG)
            await client.get_chat(log_id)
            await client.send_message(
                log_id,
                text,
                parse_mode=enums.ParseMode.HTML,
                disable_web_page_preview=True,
            )
            return True
        except Exception:
            logger.exception("PREMIUM_LOG text delivery failed")

    await notify_owner(client, text)
    return False


async def safe_premium_proof(client, message, caption, keyboard):
    """Send the actual payment proof to PREMIUM_LOG, with OWNER fallback."""
    file_id = message.photo.file_id if message.photo else message.document.file_id

    if PREMIUM_LOG:
        try:
            log_id = int(PREMIUM_LOG)
            await client.get_chat(log_id)

            if message.photo:
                sent = await client.send_photo(
                    log_id, file_id, caption=caption,
                    reply_markup=keyboard, parse_mode=enums.ParseMode.HTML
                )
            else:
                sent = await client.send_document(
                    log_id, file_id, caption=caption,
                    reply_markup=keyboard, parse_mode=enums.ParseMode.HTML
                )
            return {str(log_id): sent.id}
        except Exception:
            logger.exception("PREMIUM_LOG payment proof delivery failed")

    # PREMIUM_LOG failed: preserve the original working OWNER fallback.
    try:
        if message.photo:
            sent = await client.send_photo(
                int(OWNER), file_id, caption=caption,
                reply_markup=keyboard, parse_mode=enums.ParseMode.HTML
            )
        else:
            sent = await client.send_document(
                int(OWNER), file_id, caption=caption,
                reply_markup=keyboard, parse_mode=enums.ParseMode.HTML
            )
        return {str(OWNER): sent.id}
    except Exception:
        logger.exception("OWNER payment proof fallback delivery failed")
        return {}


async def safe_kick(client, user_id):
    if not PREMIUM_GROUP_ID:
        return True

    try:
        cid = int(PREMIUM_GROUP_ID)
        await client.ban_chat_member(cid, int(user_id))
        await asyncio.sleep(0.3)
        await client.unban_chat_member(cid, int(user_id))
        return True
    except Exception as exc:
        if "USER_NOT_PARTICIPANT" in str(exc) or "PEER_ID_INVALID" in str(exc):
            return True

        user_display = await get_user_display(client, user_id)
        await safe_premium_log(
            client,
            f"<b>⚠️ Premium member removal failed</b>\n"
            f"{user_display}\n"
            f"<b>Reason:</b> {exc}",
        )
        return False


@Client.on_message(filters.command("premium") & filters.private)
async def premium_command(client, message):
    await message.reply_text(
        "<b>🌟 Premium Plans</b>\n\n"
        "✨ 1 Month: ₹40\n"
        "✨ 2 Months: ₹80\n"
        "✨ 6 Months: ₹240\n"
        "✨ 1 Year: ₹480",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Continue", callback_data="buy_premium_start")]
        ]),
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_callback_query(filters.regex(r"^buy_premium_start$"))
async def premium_menu_callback(client, callback):
    await callback.answer()
    await safe_edit_message(
        callback.message,
        "<b>🌟 Premium Plans</b>\n\n"
        "✨ 1 Month: ₹40\n"
        "✨ 2 Months: ₹80\n"
        "✨ 6 Months: ₹240\n"
        "✨ 1 Year: ₹480",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Click Here To Pay", callback_data="click_here_to_pay")]
        ]),
    )


@Client.on_callback_query(filters.regex(r"^click_here_to_pay$"))
async def click_here_to_pay_cb(client, callback):
    await callback.answer()

    try:
        await callback.message.delete()
    except Exception:
        pass

    qr_caption = (
        "<b>📸 Scan QR CODE or use UPI ID to Pay:\n\n"
        "UPI ID:</b> <code>karthik.slice@ibl</code>"
    )

    await client.send_photo(
        chat_id=callback.message.chat.id,
        photo="https://ibb.co/KHqPKqg",
        caption=qr_caption,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ I Paid", callback_data="minimal_send_proof")]
        ]),
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_callback_query(filters.regex(r"^minimal_send_proof$"))
async def send_proof_cb(client, callback):
    await aux_col("user_payment_intents").update_one(
        {"user_id": callback.from_user.id},
        {
            "$set": {
                "action": "i_paid_clicked",
                "timestamp": datetime.utcnow(),
            }
        },
        upsert=True,
    )

    await callback.answer()

    try:
        await callback.message.delete()
    except Exception:
        pass

    await client.send_message(
        callback.message.chat.id,
        "<b>📸 Send Payment Proof!\n\n"
        "Please upload your transaction screenshot to verify!</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(
    filters.private
    & (filters.photo | filters.document)
    & ~filters.command(["start", "premium"])
)
async def screenshot_handler(client, message):
    user_id = message.from_user.id
    intent_col = aux_col("user_payment_intents")

    try:
        intent = await intent_col.find_one({"user_id": user_id})
    except Exception:
        logger.exception("Failed reading payment intent for user %s", user_id)
        return

    if not intent or intent.get("action") not in {"i_paid_clicked", "screenshot_sent"}:
        return

    for admin_id, msg_id in (intent.get("admin_msg_ids") or {}).items():
        try:
            await client.delete_messages(int(admin_id), int(msg_id))
        except Exception:
            logger.exception("Failed deleting previous payment proof message %s for %s", msg_id, user_id)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"min_app_{user_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"min_rej_{user_id}"),
    ]])

    caption = (
        f"<b>🔔 New Payment Verification</b>\n\n"
        f"{user_link(message.from_user.first_name, user_id)}"
    )

    try:
        admin_msg_ids = await safe_premium_proof(client, message, caption, keyboard)

        await intent_col.update_one(
            {"user_id": user_id},
            {"$set": {
                "admin_msg_ids": admin_msg_ids,
                "action": "screenshot_sent",
                "timestamp": datetime.utcnow(),
            }},
            upsert=True,
        )

        await message.reply_text(
            "<b>✅ Payment proof submitted for verification.</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        logger.exception("Payment screenshot workflow failed for user %s", user_id)


@Client.on_message(filters.command("approve") & filters.user(OWNER))
async def approve_command(client, message):
    if len(message.command) < 2:
        return await message.reply_text(
            "<b>⚠️ Usage: /approve [user_id]</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    try:
        uid = int(message.command[1])
        await aux_col("admin_approval_sessions").update_one(
            {"admin_id": message.from_user.id},
            {"$set": {"target_user_id": uid}},
            upsert=True,
        )

        await message.reply_text(
            f"<b>💎 Select Premium Plan</b>\n\n"
            f"{await get_user_display(client, uid)}",
            reply_markup=get_plan_keyboard(uid),
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception as exc:
        await message.reply_text(
            f"<b>❌ Error: {exc}</b>",
            parse_mode=enums.ParseMode.HTML,
        )


@Client.on_callback_query(filters.regex(r"^min_app_"))
async def approve_button(client, callback):
    if callback.from_user.id != int(OWNER):
        return await callback.answer("Unauthorized.", show_alert=True)

    uid = int(callback.data.split("_")[-1])

    await aux_col("admin_approval_sessions").update_one(
        {"admin_id": callback.from_user.id},
        {"$set": {"target_user_id": uid}},
        upsert=True,
    )

    await callback.answer()
    await safe_edit_message(
        callback.message,
        "<b>💎 Select Premium Plan</b>",
        get_plan_keyboard(uid),
    )


@Client.on_callback_query(filters.regex(r"^selplan_"))
async def select_plan(client, callback):
    if callback.from_user.id != int(OWNER):
        return await callback.answer("Unauthorized.", show_alert=True)

    _, uid_text, duration, price = callback.data.split("_")
    uid = int(uid_text)
    delta, plan = parse_plan_duration(duration)
    now = datetime.utcnow()
    existing = await premium_col().find_one({"user_id": uid, "active": True})

    start = (
        existing.get("expires_at")
        if existing
        and isinstance(existing.get("expires_at"), datetime)
        and existing.get("expires_at") > now
        else now
    )
    exp = start + delta

    await callback.answer()
    await safe_edit_message(
        callback.message,
        f"<b>💎 Preview Panel</b>\n\n"
        f"{await get_user_display(client, uid)}\n"
        f"<b>✨ Plan:</b> {plan} | ₹{price}\n"
        f"<b>📆 Expiry:</b> {fmt_date(exp)}",
        InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Confirm", callback_data=f"confact_{uid}_{duration}_{price}"),
                InlineKeyboardButton("◀ Back", callback_data=f"min_app_{uid}"),
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"min_rej_{uid}")],
        ]),
    )


@Client.on_callback_query(filters.regex(r"^confact_"))
async def confirm_activation(client, callback):
    if callback.from_user.id != int(OWNER):
        return await callback.answer("Unauthorized.", show_alert=True)

    _, uid_text, duration, price = callback.data.split("_")
    uid = int(uid_text)
    delta, plan = parse_plan_duration(duration)
    now = datetime.utcnow()
    col = premium_col()
    existing = await col.find_one({"user_id": uid, "active": True})

    start = (
        existing.get("expires_at")
        if existing
        and isinstance(existing.get("expires_at"), datetime)
        and existing.get("expires_at") > now
        else now
    )
    exp = start + delta

    if PREMIUM_GROUP_ID:
        try:
            cid = int(PREMIUM_GROUP_ID)
            await client.unban_chat_member(cid, uid)
            await client.approve_chat_join_request(cid, uid)
        except Exception:
            pass

    name = await fetch_user_name(client, uid)
    data = {
        "user_id": uid,
        "username": name,
        "plan": plan,
        "price": price,
        "purchased_at": now,
        "expires_at": exp,
        "active": True,
        "reminders": {"1_day": False},
    }

    await col.update_one(
        {"user_id": uid},
        {"$set": data},
        upsert=True,
    )

    await aux_col("admin_approval_sessions").delete_one(
        {"admin_id": callback.from_user.id}
    )
    await aux_col("user_payment_intents").delete_one(
        {"user_id": uid}
    )

    markup = (
        InlineKeyboardMarkup([
            [InlineKeyboardButton("✨ Premium Group", url=PREMIUM_PERMANENT_LINK)]
        ])
        if PREMIUM_PERMANENT_LINK
        else None
    )

    try:
        await client.send_message(
            uid,
            f"<b>{'🌟 Premium Membership Renewed ✅' if existing else '🌟 Premium Membership Active ✅'}</b>\n\n"
            f"<b>💰 Plan:</b> {plan} | ₹{price}\n"
            f"<b>⌛ Expiry:</b> {fmt_date(exp)}",
            reply_markup=markup,
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass

    await notify_owner(
        client,
        f"<b>{'🌟 Premium Renewed ✅' if existing else '🌟 Premium Activated ✅'}</b>\n\n"
        f"{user_link(name, uid)}\n"
        f"<b>• Plan:</b> {plan} | ₹{price}\n"
        f"<b>• Expiry:</b> {fmt_date(exp)}",
    )

    await callback.answer("Activated")
    await safe_edit_message(
        callback.message,
        f"<b>✅ Activated Successfully</b>\n{user_link(name, uid)}",
    )


@Client.on_callback_query(filters.regex(r"^min_rej_"))
async def reject_payment(client, callback):
    if callback.from_user.id != int(OWNER):
        return await callback.answer("Unauthorized.", show_alert=True)

    uid = int(callback.data.split("_")[-1])
    await aux_col("user_payment_intents").delete_one({"user_id": uid})
    await aux_col("admin_approval_sessions").delete_one({"admin_id": callback.from_user.id})
    await callback.answer("Rejected.")

    try:
        await client.send_message(
            uid,
            "<b>⚠️ Payment Verification Failed.</b>\n\n"
            "Please pay again and send a valid screenshot.",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass

    await safe_edit_message(
        callback.message,
        "<b>❌ Status: REJECTED</b>",
    )


@Client.on_message(filters.command("revoke") & filters.user(OWNER))
async def revoke_premium(client, message):
    if len(message.command) < 2:
        return await message.reply_text(
            "<b>⚠️ Usage: /revoke [user_id]</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    uid = int(message.command[1])

    if PREMIUM_GROUP_ID and not await safe_kick(client, uid):
        return await message.reply_text(
            "<b>❌ Revocation halted because group removal failed.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    await premium_col().delete_one({"user_id": uid})

    try:
        await client.send_message(
            uid,
            "<b>❌ Your Premium Membership has been revoked by administration.</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass

    await message.reply_text(
        f"<b>✅ Premium revoked</b>\n{await get_user_display(client, uid)}",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("premiums") & filters.user(OWNER))
async def premiums_list(client, message):
    lines = ["<b>💎 Active Premium Members</b>", ""]
    count = 0

    async for doc in premium_col().find({"active": True}):
        count += 1
        uid = doc.get("user_id")
        lines.extend([
            f"<b>{count}.</b> {user_link(doc.get('username', 'User'), uid)}",
            f"<b>• Plan:</b> {doc.get('plan', 'N/A')}",
            f"<b>• Expires:</b> {fmt_date(doc.get('expires_at'))}",
            "",
        ])

    if not count:
        lines = ["<b>❌ No active premium users found.</b>"]

    text = "\n".join(lines)

    if len(text) > 4096:
        with open("premium_users.txt", "w", encoding="utf-8") as f:
            f.write(text)
        try:
            await message.reply_document("premium_users.txt")
        finally:
            try:
                os.remove("premium_users.txt")
            except OSError:
                pass
    else:
        await message.reply_text(text, parse_mode=enums.ParseMode.HTML)


@Client.on_message(filters.command("myplan") & filters.private)
async def my_plan(client, message):
    uid = message.from_user.id
    doc = await premium_col().find_one({"user_id": uid, "active": True})

    if not doc or not await is_premium_user(client, uid):
        return await message.reply_text(
            "<b>❌ No active Premium subscription.</b>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 Buy Premium", callback_data="buy_premium_start")]
            ]),
            parse_mode=enums.ParseMode.HTML,
        )

    exp = doc.get("expires_at")
    rem = exp - datetime.utcnow() if isinstance(exp, datetime) else None
    remaining = (
        f"{rem.days} Days"
        if rem and rem.days > 0
        else (f"{rem.seconds // 3600} Hours" if rem else "Expired")
    )

    await message.reply_text(
        f"<b>🌟 Premium Membership Active ✅</b>\n\n"
        f"{user_link(message.from_user.first_name, uid)}\n"
        f"<b>💰 Plan:</b> {doc.get('plan')} | ₹{doc.get('price')}\n"
        f"<b>⌛ Expiry:</b> {fmt_date(exp)}\n"
        f"<b>⏳ Remaining:</b> {remaining}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Renew Now", callback_data="buy_premium_start")]
        ]),
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_chat_join_request()
async def premium_join_request(client, request: ChatJoinRequest):
    if not PREMIUM_GROUP_ID:
        return

    try:
        if request.chat.id != int(PREMIUM_GROUP_ID):
            return
    except (TypeError, ValueError):
        return

    if await is_premium_user(client, request.from_user.id):
        try:
            await client.approve_chat_join_request(
                request.chat.id,
                request.from_user.id,
            )
        except Exception:
            logger.exception("Failed approving premium join request")


@Client.on_chat_member_updated()
async def premium_member_update(client, update: ChatMemberUpdated):
    if not PREMIUM_GROUP_ID:
        return

    try:
        if update.chat.id != int(PREMIUM_GROUP_ID):
            return
    except (TypeError, ValueError):
        return

    new_member = update.new_chat_member.user if update.new_chat_member else None
    if not new_member or new_member.is_bot:
        return

    if await is_premium_user(client, new_member.id):
        return

    if update.new_chat_member.status in {
        enums.ChatMemberStatus.MEMBER,
        enums.ChatMemberStatus.ADMINISTRATOR,
        enums.ChatMemberStatus.OWNER,
    }:
        await safe_kick(client, new_member.id)


async def premium_expiry_loop(client):
    await asyncio.sleep(10)

    while True:
        try:
            now = datetime.utcnow()
            col = premium_col()

            async for doc in col.find({"active": True}):
                uid = doc.get("user_id")
                exp = doc.get("expires_at")

                if not uid or not isinstance(exp, datetime):
                    continue

                if now >= exp:
                    if PREMIUM_GROUP_ID and not await safe_kick(client, uid):
                        continue

                    await col.delete_one({"user_id": uid})

                    try:
                        await client.send_message(
                            uid,
                            "<b>⚠️ Premium Membership Expired.</b>\n\n"
                            "Renew your plan to restore access.",
                            parse_mode=enums.ParseMode.HTML,
                        )
                    except Exception:
                        pass

                elif (
                    not doc.get("reminders", {}).get("1_day")
                    and timedelta(0) < (exp - now) <= timedelta(days=1)
                ):
                    try:
                        await client.send_message(
                            uid,
                            "<b>⚠️ Your Premium Membership expires in 1 day.</b>\n\n"
                            "Renew now to keep access.",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("🔄 Renew Now", callback_data="buy_premium_start")]
                            ]),
                            parse_mode=enums.ParseMode.HTML,
                        )
                        await col.update_one(
                            {"user_id": uid},
                            {"$set": {"reminders.1_day": True}},
                        )
                    except Exception:
                        pass

        except Exception:
            logger.exception("Premium expiry loop error")

        await asyncio.sleep(3600)


async def start_premium_tasks(client):
    asyncio.create_task(premium_expiry_loop(client))
