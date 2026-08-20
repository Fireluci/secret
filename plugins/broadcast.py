import asyncio
import time
import datetime

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database.users_chats_db import db
from info import ADMINS
from utils import broadcast_messages, broadcast_messages_group, connected_group

BROADCAST_CANCEL = set()


# ==================== USER BROADCAST ====================

@Client.on_message(
    filters.command("broadcast") & filters.user(ADMINS) & filters.reply & connected_group
)
async def broadcast_users(bot, message):
    b_msg = message.reply_to_message
    total_users = await db.total_users_count()
    admin_id = message.from_user.id
    BROADCAST_CANCEL.discard(admin_id)

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel Broadcast", callback_data=f"cancel_broadcast#{admin_id}")]
    ])

    sts = await message.reply_text(
        f"📢 <b>Broadcast Started</b>\n\n"
        f"👥 Total Users: {total_users}",
        reply_markup=markup,
    )

    success = 0
    async for user in db.get_all_users():
        if admin_id in BROADCAST_CANCEL:
            break

        sent, _ = await broadcast_messages(int(user["id"]), b_msg)
        if sent:
            success += 1

        if success and success % 20 == 0:
            await sts.edit_text(
                f"📢 <b>Broadcasting...</b>\n\n"
                f"👥 Total Users: {total_users}\n"
                f"✅ Sent: {success}",
                reply_markup=markup,
            )

    cancelled = admin_id in BROADCAST_CANCEL
    BROADCAST_CANCEL.discard(admin_id)

    if cancelled:
        await sts.edit_text(
            f"🛑 <b>Broadcast Cancelled</b>\n\n"
            f"👥 Total Users: {total_users}\n"
            f"✅ Successful: {success}"
        )
    else:
        await sts.edit_text(
            f"✅ <b>Broadcast Completed</b>\n\n"
            f"👥 Total Users: {total_users}\n"
            f"✅ Successful: {success}"
        )


# ==================== GROUP BROADCAST ====================

@Client.on_message(
    filters.command("grp_broadcast") & filters.user(ADMINS) & filters.reply & connected_group
)
async def broadcast_groups(bot, message):
    b_msg = message.reply_to_message
    total_groups = await db.total_chat_count()
    admin_id = message.from_user.id
    BROADCAST_CANCEL.discard(admin_id)

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel Broadcast", callback_data=f"cancel_group_broadcast#{admin_id}")]
    ])

    sts = await message.reply_text(
        f"📢 <b>Group Broadcast Started</b>\n\n"
        f"👥 Total Groups: {total_groups}",
        reply_markup=markup,
    )

    success = 0
    async for group in db.get_all_chats():
        if admin_id in BROADCAST_CANCEL:
            break

        sent, _ = await broadcast_messages_group(int(group["id"]), b_msg)
        if sent:
            success += 1

        if success and success % 20 == 0:
            await sts.edit_text(
                f"📢 <b>Broadcasting...</b>\n\n"
                f"👥 Total Groups: {total_groups}\n"
                f"✅ Sent: {success}",
                reply_markup=markup,
            )

    cancelled = admin_id in BROADCAST_CANCEL
    BROADCAST_CANCEL.discard(admin_id)

    if cancelled:
        await sts.edit_text(
            f"🛑 <b>Group Broadcast Cancelled</b>\n\n"
            f"👥 Total Groups: {total_groups}\n"
            f"✅ Successful: {success}"
        )
    else:
        await sts.edit_text(
            f"✅ <b>Group Broadcast Completed</b>\n\n"
            f"👥 Total Groups: {total_groups}\n"
            f"✅ Successful: {success}"
        )


# ==================== CANCEL BUTTONS ====================

@Client.on_callback_query(filters.regex(r"^cancel_broadcast#"))
async def cancel_broadcast(bot, query):
    try:
        _, admin_id = query.data.split("#", 1)
        admin_id = int(admin_id)
    except ValueError:
        return await query.answer("Invalid request.", show_alert=True)

    if query.from_user.id != admin_id:
        return await query.answer("This is not your broadcast.", show_alert=True)

    BROADCAST_CANCEL.add(admin_id)
    await query.answer("🛑 Broadcast cancelling...")


@Client.on_callback_query(filters.regex(r"^cancel_group_broadcast#"))
async def cancel_group_broadcast(bot, query):
    try:
        _, admin_id = query.data.split("#", 1)
        admin_id = int(admin_id)
    except ValueError:
        return await query.answer("Invalid request.", show_alert=True)

    if query.from_user.id != admin_id:
        return await query.answer("This is not your broadcast.", show_alert=True)

    BROADCAST_CANCEL.add(admin_id)
    await query.answer("🛑 Broadcast cancelling...")
