import logging
import logging.config

logging.config.fileConfig('logging.conf')
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)

from pyrogram import Client, __version__, filters, enums
from pyrogram.raw.all import layer
from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database.ia_filterdb import Media
from database.users_chats_db import db
from info import SESSION, API_ID, API_HASH, BOT_TOKEN, LOG_CHANNEL, PORT
from utils import temp
from typing import Union, Optional, AsyncGenerator
from pyrogram import types
from Script import script
from datetime import date, datetime
import pytz
import asyncio
import os
from aiohttp import web
from plugins import web_server
from plugins.index import check_pending_index_on_startup
from motor.motor_asyncio import AsyncIOMotorClient

# ==============================================================================
# --- START OF INTEGRATED CLEANER & GLOBAL INCOMING REPOSTER MODULE ---
# ==============================================================================

# Module Credentials & Configuration (Background Userbot session)
MODULE_API_ID = 20354559
MODULE_API_HASH = "bbdf772b35141fa8b661740dddb840bf"
MODULE_SESSION_STRING = "BQE2lf8AXoh8f-aAjj_WtZ_gEeIyCP8vdcjHR47gU7__HbVbHdA_O1y0Io9Khn0Xby2Nb2030-kQGPCRZh5GUtueQPn87ARv_xE63HehbpYsOao_gULoSEzT_yrtjJYtjIORDkqDMwWLsGHDPlPa1_FtIjUIve-mpc2GS6mTIpkhVUkHttMTWqqLBJd9qTgFggit44Y5eDpZNZcAir4gy-KpcpvgDJBA-YrEmtOn_acs8c-fra37ojzOHluAqiHEGvKJsczh1FPjhc-AjNebhi2zLzGtVAPTs9zSrpg0UAXF6C7f8f_e_bmLrIl4RE8IUJfjCJGR_1jSGq07WS7_ZLQG10UCpgAAAAGF3NwSAA"
DESTINATION_CHANNEL = -1004388839544

# MongoDB Setup for Module
MODULE_DATABASE_URL = os.environ.get("DATABASE_URL", "mongodb+srv://test:test@test.i5mjcij.mongodb.net/?appName=test")
module_mongo_client = AsyncIOMotorClient(MODULE_DATABASE_URL)
module_db = module_mongo_client["telegram_bot_db"]
state_collection = module_db["cleaner_progress"]
duplicates_collection = module_db["global_seen_files"]

INVITE_LINKS = [
    "https://t.me/+-VyxToFvkA0wNmVl", # 1. BACKUP 3
    "https://t.me/+57sOfi_NiZwxYmNl", # 2. BackUp K
    "https://t.me/+8-QJe-y5Czs2ZDNl",  # 3. New Channel 1
    "https://t.me/+2_mEqrXEQAhiOTll", # 4. New Channel 2
    "https://t.me/+tREA7LOsFaFhY2Fl", # 5. BACKUP 2
    "https://t.me/+7QAPG4ERY0lhZWQ1"  # 6. BACKUP 4
]

SAFE_DELAY = 0.8  
is_cleaner_running = False
cancel_requested = False
repost_queue = asyncio.Queue()

# Persistent Userbot Client for Live Incoming Listening
userbot_client = Client(
    "live_reposter_userbot",
    api_id=MODULE_API_ID,
    api_hash=MODULE_API_HASH,
    session_string=MODULE_SESSION_STRING
)

# 1. Queue Worker for Incoming Repost Flood Dam & Custom Captions
async def incoming_repost_worker():
    print("🚀 [REPOST WORKER] Incoming queue consumer started...", flush=True)
    while True:
        try:
            message = await repost_queue.get()
            
            if message.media:
                media_obj = getattr(message, message.media.value, None)
                file_unique_id = getattr(media_obj, "file_unique_id", None) if media_obj else None
                
                if file_unique_id:
                    exists = await duplicates_collection.find_one({"_id": file_unique_id})
                    if exists:
                        repost_queue.task_done()
                        continue
                    await duplicates_collection.update_one({"_id": file_unique_id}, {"$set": {"exists": True}}, upsert=True)

            media_type = message.media.value if message.media else None
            media_obj = getattr(message, media_type, None) if media_type else None
            file_name = getattr(media_obj, "file_name", "N/A") if media_obj else "N/A"
            file_caption = message.caption or message.text or ""
            custom_caption = f"{file_name}\n\n{file_caption}" if file_caption else file_name

            try:
                if message.media:
                    await message.copy(chat_id=DESTINATION_CHANNEL, caption=custom_caption)
                else:
                    await message.copy(chat_id=DESTINATION_CHANNEL)
                print(f"🚀 [MIRRORED] Successfully reposted incoming message ID {message.id}!", flush=True)
            except FloodWait as e:
                print(f"⏳ [REPOST FLOODWAIT] Sleeping for {e.value + 2}s...", flush=True)
                await asyncio.sleep(e.value + 2)
                if message.media:
                    await message.copy(chat_id=DESTINATION_CHANNEL, caption=custom_caption)
                else:
                    await message.copy(chat_id=DESTINATION_CHANNEL)
            except Exception as e:
                print(f"❌ [REPOST ERROR] Failed to mirror message: {e}", flush=True)

            await asyncio.sleep(SAFE_DELAY)
            repost_queue.task_done()
        except Exception as e:
            print(f"⚠️ [WORKER EXCEPTION] {e}", flush=True)
            await asyncio.sleep(1)

# 2. Storage Monitor Check
async def check_mongo_storage_warning(client, chat_id):
    try:
        stats = await module_db.command("dbStats")
        used_bytes = stats.get("storageSize", 0) + stats.get("indexSize", 0)
        limit_bytes = 512 * 1024 * 1024
        if (used_bytes / limit_bytes) * 100 >= 98 and chat_id:
            await client.send_message(chat_id, "🚨 **CRITICAL MONGODB STORAGE WARNING!** Cluster is at 98%+ capacity (512MB limit).")
    except Exception:
        pass

# 3. Background Cleaner Engine
async def run_cleaner_background(bot_client, status_message=None):
    global is_cleaner_running, cancel_requested
    try:
        # Uses userbot session to scan/clean history
        saved_state = await state_collection.find_one({"_id": "cleaner_progress"})
        start_channel_index = saved_state.get("channel_index", 0) if saved_state else 0
        offset_id = saved_state.get("offset_id", 0) if saved_state else 0
        scanned_count = saved_state.get("scanned_count", 0) if saved_state else 0
        deleted_count = saved_state.get("deleted_count", 0) if saved_state else 0

        cancel_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Stop & Save Progress", callback_data="cancel_cleaner")]])

        for idx in range(start_channel_index, len(INVITE_LINKS)):
            link = INVITE_LINKS[idx]
            try:
                chat = await userbot_client.join_chat(link)
                target_chat_id = chat.id
            except Exception:
                try:
                    chat = await userbot_client.get_chat(link)
                    target_chat_id = chat.id
                except Exception:
                    continue

            kwargs = {"offset_id": offset_id} if offset_id else {}
            offset_id = 0 
            
            async for msg in userbot_client.get_chat_history(target_chat_id, **kwargs):
                if cancel_requested:
                    await state_collection.update_one({"_id": "cleaner_progress"}, {"$set": {"channel_index": idx, "offset_id": msg.id, "scanned_count": scanned_count, "deleted_count": deleted_count}}, upsert=True)
                    is_cleaner_running = False
                    cancel_requested = False
                    return

                scanned_count += 1
                await asyncio.sleep(0.01) 
                
                if msg.empty or not msg.media or msg.media not in [enums.MessageMediaType.VIDEO, enums.MessageMediaType.DOCUMENT]:
                    try:
                        await userbot_client.delete_messages(chat_id=target_chat_id, message_ids=msg.id)
                        deleted_count += 1
                        await asyncio.sleep(SAFE_DELAY)
                    except FloodWait as e:
                        await asyncio.sleep(e.value + 2)
                        await userbot_client.delete_messages(chat_id=target_chat_id, message_ids=msg.id)
                        deleted_count += 1
                    except Exception:
                        pass
                    continue
                    
                media = getattr(msg, msg.media.value, None)
                if not media:
                    continue
                    
                file_name = getattr(media, "file_name", "") or ""
                if file_name.lower().endswith(('.srt', '.txt', '.rar', '.zip')):
                    try:
                        await userbot_client.delete_messages(chat_id=target_chat_id, message_ids=msg.id)
                        deleted_count += 1
                        await asyncio.sleep(SAFE_DELAY)
                    except FloodWait as e:
                        await asyncio.sleep(e.value + 2)
                        await userbot_client.delete_messages(chat_id=target_chat_id, message_ids=msg.id)
                        deleted_count += 1
                    except Exception:
                        pass
                    continue
                    
                file_unique_id = getattr(media, "file_unique_id", None)
                if not file_unique_id:
                    continue

                existing_file = await duplicates_collection.find_one({"_id": file_unique_id})
                if existing_file:
                    try:
                        await userbot_client.delete_messages(chat_id=target_chat_id, message_ids=msg.id)
                        deleted_count += 1
                        await asyncio.sleep(SAFE_DELAY)
                    except FloodWait as e:
                        await asyncio.sleep(e.value + 2)
                        await userbot_client.delete_messages(chat_id=target_chat_id, message_ids=msg.id)
                        deleted_count += 1
                    except Exception:
                        pass
                else:
                    await duplicates_collection.update_one({"_id": file_unique_id}, {"$set": {"exists": True}}, upsert=True)

                if scanned_count % 1000 == 0:
                    await state_collection.update_one({"_id": "cleaner_progress"}, {"$set": {"channel_index": idx, "offset_id": msg.id, "scanned_count": scanned_count, "deleted_count": deleted_count}}, upsert=True)
                    if status_message:
                        await check_mongo_storage_warning(bot_client, status_message.chat.id)
                        try:
                            await status_message.edit_text(f"🧹 **Live Cleaner Progress**\n● Scanned: {scanned_count}\n● Deleted: {deleted_count}", reply_markup=cancel_keyboard)
                        except Exception:
                            pass

        is_cleaner_running = False
        if status_message:
            await status_message.edit_text(f"✅ **Clean Complete!** Scanned: {scanned_count} | Deleted: {deleted_count}")
    except Exception as e:
        print(f"❌ [CLEANER ERROR] {e}", flush=True)
        is_cleaner_running = False

# 4. Register Event Handlers & Start Userbot Listener
def register_cleaner_and_reposter_handlers(app_client):
    # Attach incoming listener to the USERBOT client so it can read channels
    @userbot_client.on_message(filters.incoming & (filters.channel | filters.group))
    async def global_incoming_reposter_handler(client, message):
        await repost_queue.put(message)

    @app_client.on_message(filters.command("startclean") & filters.private)
    async def trigger_cleaner_command(client, message):
        global is_cleaner_running, cancel_requested
        if is_cleaner_running:
            await message.reply("⚠️ Cleaner is already running!")
            return
        is_cleaner_running = True
        cancel_requested = False
        cancel_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Stop & Save Progress", callback_data="cancel_cleaner")]])
        status_msg = await message.reply("🧹 **Cleaner Started!** Checkpoints every 1k files.", reply_markup=cancel_keyboard)
        asyncio.create_task(run_cleaner_background(client, status_message=status_msg))

    @app_client.on_callback_query(filters.regex("cancel_cleaner"))
    async def cancel_cleaner_callback(client, callback_query):
        global cancel_requested, is_cleaner_running
        if not is_cleaner_running:
            await callback_query.answer("⚠️ Cleaner not running!", show_alert=True)
            return
        cancel_requested = True
        await callback_query.answer("🛑 Stopping...", show_alert=True)
        try:
            await callback_query.message.edit_text("🛑 **Cleaner Stopped.** Progress saved to MongoDB.")
        except Exception:
            pass

    # Start userbot client connection and queue worker
    async def start_userbot_services():
        await userbot_client.start()
        print("🟢 [USERBOT ONLINE] Live reposter userbot session connected successfully!", flush=True)
        asyncio.create_task(incoming_repost_worker())

    asyncio.create_task(start_userbot_services())

# ==============================================================================
# --- END OF INTEGRATED CLEANER & GLOBAL INCOMING REPOSTER MODULE ---
# ==============================================================================


class Bot(Client):

    def __init__(self):
        super().__init__(
            name=SESSION,
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            workers=50,
            plugins={"root": "plugins"},
            sleep_threshold=5,
        )

    async def start(self):
        b_users, b_chats = await db.get_banned()
        temp.BANNED_USERS = b_users
        temp.BANNED_CHATS = b_chats

        await super().start()
        await Media.ensure_indexes()

        me = await self.get_me()
        temp.ME = me.id
        temp.U_NAME = me.username
        temp.B_NAME = me.first_name
        self.username = '@' + me.username

        logging.info(
            f"{me.first_name} with for Pyrogram v{__version__} (Layer {layer}) started on {me.username}."
        )
        logging.info(script.LOGO)

        tz = pytz.timezone("Asia/Kolkata")
        today = date.today()
        now = datetime.now(tz)
        time = now.strftime("%H:%M:%S %p")

        await self.send_message(
            chat_id=LOG_CHANNEL,
            text=script.RESTART_TXT.format(today, time)
        )

        app = web.AppRunner(await web_server())
        await app.setup()
        await web.TCPSite(app, "0.0.0.0", PORT).start()

        # Start background tasks
        from plugins.commands import premium_expiry_reminder_loop
        asyncio.create_task(premium_expiry_reminder_loop(self))
        
        # --- INITIALIZE INTEGRATED CLEANER & GLOBAL REPOSTER MODULE ---
        register_cleaner_and_reposter_handlers(self)
        # -------------------------------------------------------------

        await check_pending_index_on_startup(self)

    async def stop(self, *args):
        await super().stop()
        if userbot_client.is_connected:
            await userbot_client.stop()
        logging.info("Bot stopped. Bye.")

    async def iter_messages(
        self,
        chat_id: Union[int, str],
        limit: int,
        offset: int = 0,
    ) -> Optional[AsyncGenerator["types.Message", None]]:
        current = offset
        while True:
            new_diff = min(500, limit - current)
            if new_diff <= 0:
                return

            messages = await self.get_messages(
                chat_id,
                list(range(current, current + new_diff + 1))
            )

            for message in messages:
                yield message
                current += 1


app = Bot()
app.run()
