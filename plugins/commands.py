import os
import logging
import asyncio
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

async def notify_admins(client: Client, text: str):
    for admin_id in ADMINS:
        try:
            await client.send_message(int(admin_id), text, disable_web_page_preview=True, parse_mode=enums.ParseMode.HTML)
        except Exception:
            pass

async def handle_auto_delete(message_obj):
    try:
        await asyncio.sleep(900)  # 15 minutes auto-delete window
        await message_obj.delete()
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
            await notify_admins(client, f"<b>⚠️ Automated Kick Failed (Attempt 1)\n\n• User ID: <code>{user_id}</code>\n• Reason: <code>{e}</code>\n\n<i>Retrying in 1 minute...</i></b>")
            await asyncio.sleep(60)
            try:
                if hasattr(client, "get_chat"):
                    try: await client.get_chat(cid)
                    except Exception: pass
                await client.ban_chat_member(cid, user_id)
                await asyncio.sleep(0.3)
                await client.unban_chat_member(cid, user_id)
                await notify_admins(client, f"<b>✅ Automated Kick Succeeded on Retry (Attempt 2)\n\n• User ID: <code>{user_id}</code></b>")
            except Exception as retry_err:
                await notify_admins(client, f"<b>❌ Automated Kick Permanently Failed (Attempt 2)\n\n• User ID: <code>{user_id}</code>\n• Final Error: <code>{retry_err}</code></b>")

async def premium_expiry_reminder_loop(client: Client):
    await asyncio.sleep(5)
    while True:
        try:
            now = datetime.utcnow()
            col = get_col()
            if col:
                async for doc in col.find({"active": True}):
                    uid, exp = doc.get("user_id"), doc.get("expires_at") or doc.get("expiry_date")
                    if not isinstance(exp, datetime): continue
                    
                    reminders = doc.get("reminders", {})
                    if not reminders.get("30_sec") and (exp - now) <= timedelta(seconds=30) and (exp - now) > timedelta(seconds=0):
                        try:
                            await client.send_message(uid, "<b>⚠️ Your Premium Membership is expiring in 30 seconds!\n\nRenew now to avoid getting ejected.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Renew Now", callback_data="buy_premium_start")]]), parse_mode=enums.ParseMode.HTML)
                            await col.update_one({"user_id": uid}, {"$set": {"reminders.30_sec": True}})
                        except Exception: pass

                    if now >= exp:
                        await col.delete_one({"user_id": uid})
                        if PREMIUM_GROUP_ID: await safe_kick(client, PREMIUM_GROUP_ID, uid)
                        await notify_admins(client, f"<b>❌ Premium Membership Expired & Ejected\n\n• User ID: <code>{uid}</code>\n• Plan: <code>{doc.get('plan', 'N/A')}</code>\n• Expired On: <code>{fmt_date(exp)}</code></b>")
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
        try: name = (await client.get_users(uid)).first_name or "User"
        except Exception: name = "User"
        
        try:
            col_ses = db.admin_approval_sessions if hasattr(db, 'admin_approval_sessions') else (db.db.admin_approval_sessions if hasattr(db, 'db') else db.get_collection('admin_approval_sessions'))
            if col_ses is not None:
                await col_ses.update_one({"admin_id": message.from_user.id}, {"$set": {"target_user_id": uid}}, upsert=True)
        except Exception: pass

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("2 Min Test", callback_data=f"selplan_{uid}_2m_40"), InlineKeyboardButton("5 Min Test", callback_data=f"selplan_{uid}_5m_80")],
            [InlineKeyboardButton("1 Month - ₹40", callback_data=f"selplan_{uid}_30d_40"), InlineKeyboardButton("2 Months - ₹80", callback_data=f"selplan_{uid}_60d_80")],
            [InlineKeyboardButton("6 Months - ₹240", callback_data=f"selplan_{uid}_180d_240"), InlineKeyboardButton("1 Year - ₹480", callback_data=f"selplan_{uid}_365d_480")],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"min_rej_{uid}")]
        ])
        await message.reply_text(f"<b>💎 Select Plan Package for <a href='tg://user?id={uid}'>{name}</a> (<code>{uid}</code>)</b>", reply_markup=kb, parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        await message.reply_text(f"<b>❌ Error: <code>{e}</code></b>", parse_mode=enums.ParseMode.HTML)

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
        await message.reply_text(f"<b>✅ Successfully revoked premium for user <code>{uid}</code></b>", parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        await message.reply_text(f"<b>❌ Error: <code>{e}</code></b>", parse_mode=enums.ParseMode.HTML)

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
        text += f"<b>{count}.</b> <a href='tg://user?id={uid}'>{name}</a> (<code>{uid}</code>)\n   • <b>Plan:</b> <code>{plan}</code>\n   • <b>Expires:</b> <code>{exp}</code>\n\n"
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
            col_intent = db.user_payment_intents if hasattr(db, 'user_payment_intents') else (db.db.user_payment_intents if hasattr(db, 'db') else db.get_collection('user_payment_intents'))
            if col_intent is not None:
                await col_intent.update_one({"user_id": message.from_user.id}, {"$set": {"action": "i_paid_clicked", "timestamp": datetime.utcnow()}}, upsert=True)
        except Exception: pass
        return await message.reply_text("<b>📸 Send Payment Proof!\n\nPlease upload your transaction screenshot to verify!</b>", parse_mode=enums.ParseMode.HTML)

    data = message.command[1]
    try: pre, file_id = data.split('_', 1)
    except: file_id, pre = data, ""

    if data.split("-", 1)[0] == "BATCH":
        sts = await message.reply("<b>Please wait...</b>")
        file_id = data.split("-", 1)[1]
        msgs = BATCH_FILES.get(file_id)
        if not msgs:
            file = await client.download_media(file_id)
            try: 
                with open(file) as file_data:
                    msgs=json.loads(file_data.read())
            except:
                await sts.edit("FAILED")
                return await client.send_message(LOG_CHANNEL, "UNABLE TO OPEN FILE.")
            os.remove(file)
            BATCH_FILES[file_id] = msgs
        for msg in msgs:
            title = msg.get("title")
            size=get_size(int(msg.get("size", 0)))
            f_caption=msg.get("caption", "")
            if BATCH_FILE_CAPTION:
                try:
                    f_caption=BATCH_FILE_CAPTION.format(file_name= '' if title is None else title, file_size='' if size is None else size, file_caption='' if f_caption is None else f_caption)
                except Exception as e:
                    logger.exception(e)
                    f_caption=f_caption
            if f_caption is None:
                f_caption = f"{title}"
            try:
                sent_b = await client.send_cached_media(
                    chat_id=message.from_user.id,
                    file_id=msg.get("file_id"),
                    caption=f_caption,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton('🔆彡⟨ HEROFLiX ⟩彡🔆', url=f'https://telegram.me/{CHNL_LNK}')]]
                    )
                )
                asyncio.create_task(handle_auto_delete(sent_b))
            except FloodWait as e:
                await asyncio.sleep(e.x)
                logger.warning(f"Floodwait of {e.x} sec.")
                sent_b = await client.send_cached_media(
                    chat_id=message.from_user.id,
                    file_id=msg.get("file_id"),
                    caption=f_caption,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton('🔆彡⟨ HEROFLiX ⟩彡🔆', url=f'https://telegram.me/{CHNL_LNK}')]]
                    )
                )
                asyncio.create_task(handle_auto_delete(sent_b))
            except Exception as e:
                logger.warning(e, exc_info=True)
                continue
            await asyncio.sleep(1) 
        await sts.delete()
        return
    
    elif data.split("-", 1)[0] == "DSTORE":
        sts = await message.reply("<b>Please wait...</b>")
        b_string = data.split("-", 1)[1]
        decoded = (base64.urlsafe_b64decode(b_string + "=" * (-len(b_string) % 4))).decode("ascii")
        try:
            f_msg_id, l_msg_id, f_chat_id = decoded.split("_", 2)
        except:
            pass
        async for msg in client.iter_messages(int(f_chat_id), int(l_msg_id), int(f_chat_id)):
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
                    cp_m = await msg.copy(message.chat.id, caption=f_caption)
                    asyncio.create_task(handle_auto_delete(cp_m))
                except FloodWait as e:
                    await asyncio.sleep(e.x)
                    cp_m = await msg.copy(message.chat.id, caption=f_caption)
                    asyncio.create_task(handle_auto_delete(cp_m))
                except Exception as e:
                    logger.exception(e)
                    continue
            elif msg.empty:
                continue
            else:
                try:
                    cp_m = await msg.copy(message.chat.id)
                    asyncio.create_task(handle_auto_delete(cp_m))
                except FloodWait as e:
                    await asyncio.sleep(e.x)
                    cp_m = await msg.copy(message.chat.id)
                    asyncio.create_task(handle_auto_delete(cp_m))
                except Exception as e:
                    logger.exception(e)
                    continue
            await asyncio.sleep(1) 
        return await sts.delete()
        
    elif data.startswith("all"):
        files = temp.GETALL.get(file_id)
        if not files:
            return await message.reply('<b><i>No such file exist.</b></i>')
        
        for file in files:
            f_id = file.file_id
            files_ = await get_file_details(f_id)
            if not files_: continue
            files1 = files_[0]
            title = ' '.join(filter(lambda x: not x.startswith('www.') and not x.startswith('@'), files1.file_name.split()))
            size = get_size(files1.file_size)
            f_caption = files1.caption
            if CUSTOM_FILE_CAPTION:
                try:
                    f_caption = CUSTOM_FILE_CAPTION.format(file_name='' if title is None else title, file_size='' if size is None else size, file_caption='' if f_caption is None else f_caption)
                except Exception as e:
                    logger.exception(e)
            if f_caption is None:
                f_caption = f"{title}"

            sent_all = await client.send_cached_media(
                chat_id=message.from_user.id,
                file_id=f_id,
                caption=f_caption,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton('🔆彡⟨ HEROFLiX ⟩彡🔆', url=f'https://telegram.me/{CHNL_LNK}')]]
                )
            )
            asyncio.create_task(handle_auto_delete(sent_all))
        return  

    files_ = await get_file_details(file_id)            
    if not files_:
        try:
            pre, file_id = ((base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))).decode("ascii")).split("_", 1)
            msg = await client.send_cached_media(
                chat_id=message.from_user.id,
                file_id=file_id,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔆彡⟨ HEROFLiX ⟩彡🔆', url=f'https://telegram.me/{CHNL_LNK}')]])
            )
            asyncio.create_task(handle_auto_delete(msg))
            filetype = msg.media
            file = getattr(msg, filetype.value)
            title = ' '.join(filter(lambda x: not x.startswith('www.') and not x.startswith('@'), file.file_name.split()))
            size = get_size(file.file_size)
            f_caption = f"<code>{title}</code>"
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

    sent_single = await client.send_cached_media(
        chat_id=message.from_user.id,
        file_id=file_id,
        caption=f_caption,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔆彡⟨ HEROFLiX ⟩彡🔆', url=f'https://telegram.me/{CHNL_LNK}')]])
    )
    asyncio.create_task(handle_auto_delete(sent_single))
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
        f"• 👤 User: <a href='tg://user?id={user_id}'>{message.from_user.first_name}</a> (<code>{user_id}</code>)\n"
        f"• 💰 Plan: <code>{plan} | ₹{price}</code>\n"
        f"• ⌛ Expiry: <code>{fmt_date(expires_at)}</code>\n"
        f"• ⏳ Remaining: <code>{left_str}</code></b>",
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
        "• ✨ 1 Month: <code>₹40</code>\n"
        "• ✨ 2 Months: <code>₹80</code>\n"
        "• ✨ 6 Months: <code>₹240</code>\n"
        "• ✨ 1 Year: <code>₹480</code>\n\n"
        "1. Pay via Button below.\n"
        "2. Click ‘I Have Paid’</b>"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Click Here To Buy", url="https://fireluci.github.io/pay/")], [InlineKeyboardButton("✅ I Have Paid", callback_data="minimal_send_proof")]])
    if isinstance(update, CallbackQuery):
        try: await message.delete()
        except Exception: pass
        await client.send_message(message.chat.id, text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)
    else:
        await message.reply_text(text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex("^minimal_send_proof$"))
async def send_proof_cb(client, callback: CallbackQuery):
    try:
        col_intent = db.user_payment_intents if hasattr(db, 'user_payment_intents') else (db.db.user_payment_intents if hasattr(db, 'db') else db.get_collection('user_payment_intents'))
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
        col_intent = db.user_payment_intents if hasattr(db, 'user_payment_intents') else (db.db.user_payment_intents if hasattr(db, 'db') else db.get_collection('user_payment_intents'))
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
        f"• 👤 User: <a href='tg://user?id={user_id}'>{message.from_user.first_name}</a> (<code>{user_id}</code>)</b>"
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
        col_ses = db.admin_approval_sessions if hasattr(db, 'admin_approval_sessions') else (db.db.admin_approval_sessions if hasattr(db, 'db') else db.get_collection('admin_approval_sessions'))
        if col_ses is not None:
            await col_ses.update_one({"admin_id": callback.from_user.id}, {"$set": {"target_user_id": uid}}, upsert=True)
    except Exception: pass

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("2 Min Test", callback_data=f"selplan_{uid}_2m_40"), InlineKeyboardButton("5 Min Test", callback_data=f"selplan_{uid}_5m_80")],
        [InlineKeyboardButton("1 Month - ₹40", callback_data=f"selplan_{uid}_30d_40"), InlineKeyboardButton("2 Months - ₹80", callback_data=f"selplan_{uid}_60d_80")],
        [InlineKeyboardButton("6 Months - ₹240", callback_data=f"selplan_{uid}_180d_240"), InlineKeyboardButton("1 Year - ₹480", callback_data=f"selplan_{uid}_365d_480")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"min_rej_{uid}")]
    ])
    await callback.answer()
    text = "<b>💎 Select Plan Package</b>"
    try: 
        await callback.message.edit_caption(text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)
    except MessageNotModified: 
        pass
    except Exception: 
        try: 
            await callback.message.edit_text(text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)
        except MessageNotModified: 
            pass

@Client.on_callback_query(filters.regex("^selplan_"))
async def select_plan_cb(client, callback: CallbackQuery):
    if str(callback.from_user.id) not in map(str, ADMINS): return await callback.answer("Unauthorized.", show_alert=True)
    _, uid_str, duration_str, price = callback.data.split("_")
    uid = int(uid_str)
    
    now = datetime.utcnow()
    if duration_str.endswith("m"):
        mins = int(duration_str[:-1])
        delta = timedelta(minutes=mins)
        plan_name = f"{mins} Min Test"
    else:
        days = int(duration_str[:-1])
        delta = timedelta(days=days)
        plan_name = f"{days} Days Plan"

    col = get_col()
    existing = await col.find_one({"user_id": uid, "active": True}) if col else None
    start = existing.get("expires_at") or existing.get("expiry_date") if existing and isinstance(existing.get("expires_at"), datetime) and existing.get("expires_at") > now else now
    exp = start + delta

    try: name = (await client.get_users(uid)).first_name or "User"
    except Exception: name = "User"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data=f"confact_{uid}_{duration_str}_{price}"), InlineKeyboardButton("◀ Back", callback_data=f"min_app_{uid}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"min_rej_{uid}")]
    ])
    text = (
        f"<b>💎 Preview Panel\n\n"
        f"• 👤 User: <a href='tg://user?id={uid}'>{name}</a> (<code>{uid}</code>)\n"
        f"• ✨ Plan: <code>{plan_name} | ₹{price}</code>\n"
        f"• 📆 Expiry: <code>{fmt_date(exp)}</code></b>"
    )
    await callback.answer()
    try: 
        await callback.message.edit_caption(text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)
    except MessageNotModified: 
        pass
    except Exception: 
        try: 
            await callback.message.edit_text(text, reply_markup=kb, parse_mode=enums.ParseMode.HTML)
        except MessageNotModified: 
            pass

@Client.on_callback_query(filters.regex("^confact_"))
async def conf_act_cb(client, callback: CallbackQuery):
    if str(callback.from_user.id) not in map(str, ADMINS): return await callback.answer("Unauthorized.", show_alert=True)
    _, uid_str, duration_str, price = callback.data.split("_")
    uid = int(uid_str)
    
    now = datetime.utcnow()
    if duration_str.endswith("m"):
        mins = int(duration_str[:-1])
        delta = timedelta(minutes=mins)
        plan = f"{mins} Min Test"
    else:
        days = int(duration_str[:-1])
        delta = timedelta(days=days)
        plan = f"{days} Days Plan"

    try: name = (await client.get_users(uid)).first_name or "User"
    except Exception: name = "User"
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
        col_ses = db.admin_approval_sessions if hasattr(db, 'admin_approval_sessions') else (db.db.admin_approval_sessions if hasattr(db, 'db') else db.get_collection('admin_approval_sessions'))
        if col_ses is not None:
            await col_ses.delete_one({"admin_id": callback.from_user.id})
    except Exception: pass

    link = PREMIUM_PERMANENT_LINK or "https://t.me/your_group_link"
    title_msg = "<b>🌟 Premium Membership Renewed ✅</b>" if is_renewal else "<b>🌟 Premium Membership Active ✅</b>"
    try:
        msg = await client.send_message(
            uid, 
            f"{title_msg}\n\n"
            f"• 💰 Plan: <code>{plan} | ₹{price}</code>\n"
            f"• ⌛ Expiry: <code>{fmt_date(exp)}</code>\n\n"
            f"<b>✨ Join Premium Group:</b>", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🧤 click here to join", url=link)]]), 
            parse_mode=enums.ParseMode.HTML
        )
        if not joined and col and msg: await col.update_one({"user_id": uid}, {"$set": {"dm_msg_id": msg.id}})
    except Exception: pass
    
    log_title = "<b>🌟 Premium Renewed ✅</b>" if is_renewal else "<b>🌟 Premium Activated ✅</b>"
    await notify_admins(client, f"{log_title}\n\n• <b>👤 User:</b> <a href='tg://user?id={uid}'>{name}</a> (<code>{uid}</code>)\n• <b>💰 Plan:</b> <code>{plan} | ₹{price}</code>\n• <b>⌛ Expiry:</b> <code>{fmt_date(exp)}</code>")
    success_text = f"<b>✅ Activated Successfully\n• 👤 User:</b> <a href='tg://user?id={uid}'>{name}</a> (<code>{uid}</code>)"
    try: 
        await callback.message.edit_caption(success_text, reply_markup=None, parse_mode=enums.ParseMode.HTML)
    except MessageNotModified: 
        pass
    except Exception: 
        try: 
            await callback.message.edit_text(success_text, reply_markup=None, parse_mode=enums.ParseMode.HTML)
        except MessageNotModified: 
            pass

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
                f"• 👤 User: <a href='tg://user?id={user.id}'>{user.first_name}</a> (<code>{user.id}</code>)\n"
                f"• 💰 Plan: <code>{doc.get('plan')} | ₹{doc.get('price')}</code>\n"
                f"• ⌛ Expiry: <code>{fmt_date(doc.get('expires_at'))}</code></b>"
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
        col_intent = db.user_payment_intents if hasattr(db, 'user_payment_intents') else (db.db.user_payment_intents if hasattr(db, 'db') else db.get_collection('user_payment_intents'))
        col_ses = db.admin_approval_sessions if hasattr(db, 'admin_approval_sessions') else (db.db.admin_approval_sessions if hasattr(db, 'db') else db.get_collection('admin_approval_sessions'))
        if col_intent is not None: await col_intent.delete_one({"user_id": uid})
        if col_ses is not None: await col_ses.delete_one({"admin_id": callback.from_user.id})
    except Exception: pass
    await callback.answer("Rejected.")
    
    try:
        rej_kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ I Have Paid", callback_data="minimal_send_proof")]])
        await client.send_message(uid, "<b>⚠️ Payment Verification Failed.\n\nPlease pay and send a valid screenshot.</b>", reply_markup=rej_kb, parse_mode=enums.ParseMode.HTML)
    except Exception: pass
    
    rej_text = "<b>❌ Status: REJECTED</b>"
    try: 
        await callback.message.edit_caption(rej_text, reply_markup=None, parse_mode=enums.ParseMode.HTML)
    except MessageNotModified: 
        pass
    except Exception: 
        try: 
            await callback.message.edit_text(rej_text, reply_markup=None, parse_mode=enums.ParseMode.HTML)
        except MessageNotModified: 
            pass

@Client.on_message(filters.group & filters.incoming)
async def auto_delete_group_messages(client, message):
    if PREMIUM_GROUP_ID and str(message.chat.id) == str(PREMIUM_GROUP_ID):
        if message.from_user and message.from_user.id in ADMINS:
            return
        asyncio.create_task(handle_auto_delete(message))

@Client.on_message(filters.private & filters.text & filters.incoming & ~filters.command(["start", "premium", "myplan", "approve", "revoke", "premiums", "channel", "logs", "delete", "deleteall", "deletefiles", "restart"]))
async def pm_text(bot, message):
    content = message.text
    user_id = message.from_user.id
    if content.startswith("/") or content.startswith("#"): return  
    if str(user_id) in map(str, ADMINS): return 
    await message.reply_text(
        text="<b>🌀 Unlimited Movies, Series, Anime\n🔆 New Releases Upload Same Day\n♻️ 24x7 Service 📆 Daily Updates</b>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🌟 Paid (No Ads)", url="https://telegram.me/HeroFlixx/49"), InlineKeyboardButton("🍿 Free (With Ads)", url="https://telegram.me/addlist/X5k2lnJLIGAyZjQ1")]])
    )

@Client.on_message(filters.command('channel') & filters.user(ADMINS))
async def channel_info(bot, message):
    channels = [CHANNELS] if isinstance(CHANNELS, (int, str)) else CHANNELS
    text = '<b>📑 Indexed channels/groups\n'
    for channel in channels:
        chat = await bot.get_chat(channel)
        text += ('\n@' + chat.username) if chat.username else ('\n' + (chat.title or chat.first_name))
    text += f'\n\nTotal: <code>{len(channels)}</code></b>'
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
    try: kw = message.text.split(" ", 1)[1]
    except Exception: return await message.reply_text("<b>Give me a keyword!</b>", parse_mode=enums.ParseMode.HTML)
    
    k = await bot.send_message(message.chat.id, "<b>Please Wait...</b>", parse_mode=enums.ParseMode.HTML)
    _, total = await get_bad_files(kw)
    await k.delete()
    
    await message.reply_text(
        f"<b>{total} Files ➠ {kw}</b>", 
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛃 Delete", callback_data=f"killfilesdq#{kw}")], 
            [InlineKeyboardButton("💢 Cancel", callback_data="close_data")]
        ]), 
        parse_mode=enums.ParseMode.HTML
    )

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
