import asyncio
from datetime import datetime, timedelta
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from info import DATABASE_URI, DATABASE_NAME, UPI_ID, PREMIUM_GROUP_ID, ADMINS

logger = logging.getLogger(__name__)

db_client = AsyncIOMotorClient(DATABASE_URI)
db = db_client[DATABASE_NAME]

users_col = db.premium_users
pending_col = db.premium_pending
flow_col = db.premium_payment_flow

PLANS = {
    "plan_30": {"days": 30, "price": 39, "name": "30 Days"},
    "plan_60": {"days": 60, "price": 78, "name": "60 Days"},
    "plan_180": {"days": 180, "price": 234, "name": "180 Days"},
    "plan_360": {"days": 360, "price": 468, "name": "360 Days"},
}

_background_task = None
_cooldowns = {}

def init_premium_plugin(client: Client):
    global _background_task
    if _background_task is None or _background_task.done():
        _background_task = asyncio.create_task(run_background_tasks(client))

async def create_indexes():
    try:
        await users_col.create_index("user_id", unique=True)
        await pending_col.create_index("user_id")
        await flow_col.create_index("user_id")
    except Exception as e:
        logger.error(f"Failed to create MongoDB indexes: {e}")

async def run_background_tasks(client: Client):
    await create_indexes()
    await startup_recovery(client)
    while True:
        try:
            cutoff = datetime.utcnow() - timedelta(hours=24)
            await flow_col.delete_many({"updated_at": {"$lt": cutoff}})
            await check_expiries_and_reminders(client)
        except Exception as e:
            logger.error(f"Error in premium background tasks: {e}")
        await asyncio.sleep(3600)

async def startup_recovery(client: Client):
    now = datetime.utcnow()
    async for user in users_col.find({"active": True, "expires_at": {"$lte": now}}):
        user_id = user["user_id"]
        try:
            if PREMIUM_GROUP_ID:
                await client.ban_chat_member(PREMIUM_GROUP_ID, user_id)
                await client.unban_chat_member(PREMIUM_GROUP_ID, user_id)
            logger.info(f"Premium Expired (Startup Recovery) - User: {user_id}")
        except Exception as e:
            logger.warning(f"Startup recovery kick failed for {user_id}: {e}")
        await users_col.update_one({"user_id": user_id}, {"$set": {"active": False, "invite_link": None}})

async def check_expiries_and_reminders(client: Client):
    now = datetime.utcnow()
    async for user in users_col.find({"active": True, "expires_at": {"$lte": now}}):
        user_id = user["user_id"]
        try:
            if PREMIUM_GROUP_ID:
                await client.ban_chat_member(PREMIUM_GROUP_ID, user_id)
                await client.unban_chat_member(PREMIUM_GROUP_ID, user_id)
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Renew Membership", callback_data="premium_menu")]])
            await client.send_message(user_id, "⚠️ **Your Premium Membership has expired.**", reply_markup=kb)
            logger.info(f"Premium Expired - User: {user_id}")
        except Exception:
            pass
        await users_col.update_one({"user_id": user_id}, {"$set": {"active": False, "invite_link": None}})

    window_start = now + timedelta(hours=23)
    window_end = now + timedelta(hours=25)
    async for user in users_col.find({"active": True, "reminder_sent": {"$ne": True}, "expires_at": {"$gte": window_start, "$lte": window_end}}):
        user_id = user["user_id"]
        try:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Renew Membership", callback_data="premium_menu")]])
            await client.send_message(user_id, "⏳ Your Premium Membership expires tomorrow!\n\nRenew now to avoid interruption.", reply_markup=kb)
            await users_col.update_one({"user_id": user_id}, {"$set": {"reminder_sent": True}})
        except Exception as e:
            logger.error(f"Reminder error for {user_id}: {e}")

@Client.on_chat_member_updated()
async def member_join_handler(client: Client, member):
    if not PREMIUM_GROUP_ID or member.chat.id != PREMIUM_GROUP_ID:
        return
    if member.new_chat_member and member.new_chat_member.user:
        user_id = member.new_chat_member.user.id
        user_doc = await users_col.find_one({"user_id": user_id, "active": True})
        if user_doc and user_doc.get("invite_link"):
            try:
                await client.revoke_chat_invite_link(PREMIUM_GROUP_ID, user_doc["invite_link"])
                await users_col.update_one({"user_id": user_id}, {"$set": {"invite_link": None}})
            except Exception as e:
                logger.error(f"Failed to revoke invite link for {user_id}: {e}")

# Raw command logic functions (decorators removed here, handled in commands.py)
async def premium_command(client: Client, message: Message):
    user_id = message.from_user.id
    now_ts = datetime.utcnow().timestamp()
    if user_id in _cooldowns and now_ts - _cooldowns[user_id] < 4:
        return await message.reply_text("⏳ Please wait a few seconds before trying again.")
    _cooldowns[user_id] = now_ts

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("30 Days — ₹39", callback_data="buy_plan_30"), InlineKeyboardButton("60 Days — ₹78", callback_data="buy_plan_60")],
        [InlineKeyboardButton("180 Days — ₹234", callback_data="buy_plan_180"), InlineKeyboardButton("360 Days — ₹468", callback_data="buy_plan_360")]
    ])
    await message.reply_text("💎 **Upgrade to Premium**\n\nSelect a plan below to proceed:", reply_markup=kb)

async def my_premium_command(client: Client, message: Message):
    user_id = message.from_user.id
    user_doc = await users_col.find_one({"user_id": user_id})
    if not user_doc or not user_doc.get("active") or user_doc["expires_at"] <= datetime.utcnow():
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Renew Membership", callback_data="premium_menu")]])
        await message.reply_text("❌ You do not have an active premium membership.", reply_markup=kb)
        return
    rem = user_doc["expires_at"] - datetime.utcnow()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Renew Membership", callback_data="premium_menu")]])
    await message.reply_text(
        f"💎 **Your Premium Status**\n\n"
        f"• Plan: {user_doc.get('plan')}\n"
        f"• Remaining: {rem.days} days, {rem.seconds // 3600} hours\n"
        f"• Expiry: {user_doc['expires_at'].strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
        f"• Status: Active ✅",
        reply_markup=kb
    )

@Client.on_callback_query(filters.regex("^premium_menu$"))
async def premium_menu_cb(client: Client, callback: CallbackQuery):
    await callback.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("30 Days — ₹39", callback_data="buy_plan_30"), InlineKeyboardButton("60 Days — ₹78", callback_data="buy_plan_60")],
        [InlineKeyboardButton("180 Days — ₹234", callback_data="buy_plan_180"), InlineKeyboardButton("360 Days — ₹468", callback_data="buy_plan_360")]
    ])
    await callback.message.edit_text("💎 **Upgrade to Premium**\n\nSelect a plan below to proceed:", reply_markup=kb)

@Client.on_callback_query(filters.regex("^buy_plan_"))
async def buy_plan_cb(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    plan_key = callback.data.replace("buy_plan_", "")
    if plan_key not in PLANS:
        return await callback.answer("Invalid plan.", show_alert=True)
    if await pending_col.find_one({"user_id": user_id}):
        return await callback.answer("You already have a pending payment request.", show_alert=True)

    plan = PLANS[plan_key]
    await flow_col.update_one({"user_id": user_id}, {"$set": {"plan_key": plan_key, "updated_at": datetime.utcnow()}}, upsert=True)
    await callback.answer()

    upi_link = f"upi://pay?pa={UPI_ID}&pn=HeroFlix&am={plan['price']}&cu=INR&tn=HeroFlix Premium"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("💳 Pay Now", url=upi_link)]])

    await callback.message.edit_text(
        f"🛒 Plan: {plan['name']}\n"
        f"💰 Amount: ₹{plan['price']}\n\n"
        f"UPI ID:\n`{UPI_ID}`\n\n"
        f"Tap the button below to pay.\n\n"
        f"After paying, send your **UTR number** or **payment screenshot** here.",
        reply_markup=kb
    )

@Client.on_message(filters.private & (filters.text | filters.photo | filters.document) & ~filters.command(["start", "premium", "mypremium"]))
async def payment_proof_handler(client: Client, message: Message):
    user_id = message.from_user.id
    flow = await flow_col.find_one({"user_id": user_id})
    if not flow:
        return

    plan = PLANS.get(flow["plan_key"])
    await flow_col.delete_one({"user_id": user_id})
    if await pending_col.find_one({"user_id": user_id}):
        return await message.reply_text("You already have a pending approval request.")

    proof_type = "photo" if message.photo else ("document" if message.document else "text")
    proof_val = message.photo.file_id if message.photo else (message.document.file_id if message.document else (message.text or message.caption))

    req = await pending_col.insert_one({
        "user_id": user_id, "plan_key": flow["plan_key"], "plan_name": plan["name"],
        "price": plan["price"], "proof_type": proof_type, "proof_value": proof_val, "date": datetime.utcnow()
    })
    req_id = str(req.inserted_id)

    await message.reply_text("✅ Payment proof submitted! Please wait for admin verification.")

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"prem_app_{req_id}"), InlineKeyboardButton("❌ Reject", callback_data=f"prem_rej_{req_id}")]])
    text = f"🔔 **New Payment Request**\n\n• User ID: `{user_id}`\n• Plan: {plan['name']}\n• Price: ₹{plan['price']}"

    for admin_id in ADMINS:
        try:
            if proof_type == "photo":
                await client.send_photo(admin_id, proof_val, caption=text, reply_markup=kb)
            elif proof_type == "document":
                await client.send_document(admin_id, proof_val, caption=text, reply_markup=kb)
            else:
                await client.send_message(admin_id, f"{text}\n• UTR: {proof_val}", reply_markup=kb)
        except Exception as e:
            logger.error(f"Failed sending to admin {admin_id}: {e}")

@Client.on_callback_query(filters.regex("^prem_(app|rej)_"))
async def admin_action_cb(client: Client, callback: CallbackQuery):
    if callback.from_user.id not in ADMINS:
        return await callback.answer("Unauthorized.", show_alert=True)

    _, action, req_id = callback.data.split("_")
    from bson.ObjectId import ObjectId
    try:
        pending = await pending_col.find_one({"_id": ObjectId(req_id)})
    except Exception:
        pending = None

    if not pending:
        return await callback.answer("Request already processed.", show_alert=True)

    user_id = pending["user_id"]
    plan = PLANS[pending["plan_key"]]

    if action == "rej":
        await pending_col.delete_one({"_id": ObjectId(req_id)})
        await callback.answer("Rejected.")
        try:
            await callback.message.edit_caption("❌ Rejected")
        except Exception:
            await callback.message.edit_text("❌ Rejected")
        await client.send_message(user_id, "❌ Your payment verification was rejected.")
        logger.info(f"Premium Rejected - User: {user_id}, Plan: {plan['name']}, Rejected by: {callback.from_user.id}")
        return

    await pending_col.delete_one({"_id": ObjectId(req_id)})
    now = datetime.utcnow()
    existing = await users_col.find_one({"user_id": user_id})

    if existing and existing.get("active") and existing.get("expires_at", now) > now:
        new_expiry = existing["expires_at"] + timedelta(days=plan["days"])
    else:
        new_expiry = now + timedelta(days=plan["days"])

    invite_link = None
    if PREMIUM_GROUP_ID:
        try:
            link = await client.create_chat_invite_link(chat_id=PREMIUM_GROUP_ID, member_limit=1, expire_date=now + timedelta(hours=24))
            invite_link = link.invite_link
        except Exception as e:
            logger.error(f"Link creation failed for {user_id}: {e}")

    await users_col.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "plan": plan["name"], "purchased_at": now, "expires_at": new_expiry, "active": True, "reminder_sent": False, "invite_link": invite_link}},
        upsert=True
    )

    await callback.answer("Approved!")
    try:
        await callback.message.edit_caption("✅ Approved")
    except Exception:
        await callback.message.edit_text("✅ Approved")

    msg = f"🎉 **Payment Approved!**\n\n• Plan: {plan['name']}\n• Expiry: {new_expiry.strftime('%Y-%m-%d %H:%M:%S')} UTC"
    if invite_link:
        msg += f"\n\n👉 [Click Here to Join Premium Group]({invite_link})"
    await client.send_message(user_id, msg, disable_web_page_preview=True)

    logger.info(
        f"✅ Premium Approved | User: {user_id} | Plan: {plan['name']} | Expires: {new_expiry.strftime('%d %b %Y')} | Approved by: {callback.from_user.id}"
    )
