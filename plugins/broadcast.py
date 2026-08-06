from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database.users_chats_db import db
from info import ADMINS
from utils import broadcast_messages, broadcast_messages_group
import asyncio

broadcast_tasks = {}

async def _run_broadcast(bot, message, is_group=False):
    user_id = message.from_user.id
    if user_id in broadcast_tasks:
        return await message.reply_text("A broadcast is already running!")
    b_msg = message.reply_to_message
    cancel_btn = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel Broadcast", callback_data=f"cancel_bc_{user_id}")]])
    records = await db.get_all_chats() if is_group else await db.get_all_users()
    total = await db.total_chat_count() if is_group else await db.total_users_count()
    txt_type = "Groups" if is_group else "Users"
    sts = await message.reply_text(text=f"📢 Broadcasting your messages{' To Groups' if is_group else ''}...", reply_markup=cancel_btn)
    broadcast_tasks[user_id] = True
    done = success = blocked = deleted = failed = 0
    async for record in records:
        if not broadcast_tasks.get(user_id, False):
            break
        if is_group:
            pti, sh = await broadcast_messages_group(int(record['id']), b_msg)
            if pti: success += 1
            elif sh == "Error": failed += 1
        else:
            pti, sh = await broadcast_messages(int(record['id']), b_msg)
            if pti: success += 1
            elif pti is False:
                if sh == "Blocked": blocked += 1
                elif sh == "Deleted": deleted += 1
                elif sh == "Error": failed += 1
        done += 1
        if not done % 20:
            try:
                if is_group:
                    await sts.edit(f"⏳ Broadcast in progress:\n\nTotal {txt_type}: {total}\nCompleted: {done} / {total}\n✅ Success: {success}\n❌ Failed: {failed}", reply_markup=cancel_btn)
                else:
                    await sts.edit(f"⏳ Broadcast in progress:\n\nTotal {txt_type}: {total}\nCompleted: {done} / {total}\n✅ Success: {success}\n🚫 Blocked: {blocked}\n🗑️ Deleted: {deleted}\n❌ Failed: {failed}", reply_markup=cancel_btn)
            except Exception:
                pass
        await asyncio.sleep(0.1)
    broadcast_tasks.pop(user_id, None)
    status_text = "⚠️ Broadcast Cancelled." if done < total else "✨ Broadcast Completed."
    if is_group:
        await sts.edit(f"{status_text}\n\nTotal {txt_type}: {total}\nCompleted: {done} / {total}\n✅ Success: {success}\n❌ Failed: {failed}")
    else:
        await sts.edit(f"{status_text}\n\nTotal {txt_type}: {total}\nCompleted: {done} / {total}\n✅ Success: {success}\n🚫 Blocked: {blocked}\n🗑️ Deleted: {deleted}\n❌ Failed: {failed}")

@Client.on_message(filters.command("broadcast") & filters.user(ADMINS) & filters.reply)
async def verupikkals(bot, message):
    await _run_broadcast(bot, message, is_group=False)

@Client.on_message(filters.command("grp_broadcast") & filters.user(ADMINS) & filters.reply)
async def broadcast_group(bot, message):
    await _run_broadcast(bot, message, is_group=True)

@Client.on_callback_query(filters.regex(r"^cancel_bc_"))
async def cancel_broadcast_callback(bot, callback_query):
    user_id = int(callback_query.data.split("_")[2])
    if callback_query.from_user.id != user_id:
        return
    if user_id in broadcast_tasks:
        broadcast_tasks[user_id] = False
    await callback_query.answer("Broadcast cancellation requested.")
