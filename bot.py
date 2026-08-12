import logging
import logging.config

logging.config.fileConfig('logging.conf')
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)

from pyrogram import Client, __version__, filters, enums
from pyrogram.raw.all import layer
from pyrogram.errors import FloodWait
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

# Telethon Imports for Universal Userbot
from telethon import TelegramClient, events
from telethon.tl.types import Channel, Chat
from telethon.sessions import StringSession

# ==============================================================================
# --- CHANNEL MONGODB INDEXER MODULE (SAVES FILE UNIQUE IDs) ---
# ==============================================================================

TARGET_CHANNEL_ID = -1001725696043

# MongoDB Setup for Cross-Channel Duplicate Tracking
MONGODB_URL = os.environ.get("DATABASE_URL", "mongodb+srv://test:test@test.i5mjcij.mongodb.net/?appName=test")
mongo_db_client = AsyncIOMotorClient(MONGODB_URL)
repost_db = mongo_db_client["telegram_bot_db"]
duplicates_collection = repost_db["global_seen_files"]

async def index_channel_files_to_db(bot_client):
    """
    Scans all posts in the target channel using Pyrogram and stores their native 
    file_unique_id into MongoDB's global_seen_files collection without deleting anything.
    """
    print(f"📥 [DB INDEXER START] Scanning channel {TARGET_CHANNEL_ID} to populate reposter database...", flush=True)
    indexed_count = 0

    try:
        async for message in bot_client.get_chat_history(TARGET_CHANNEL_ID):
            media_obj = message.video or message.document
            if not media_obj:
                continue

            file_unique_id = getattr(media_obj, "file_unique_id", None)
            if not file_unique_id:
                continue

            # Upsert into MongoDB global_seen_files collection
            await duplicates_collection.update_one(
                {"_id": file_unique_id},
                {"$set": {"exists": True}},
                upsert=True
            )
            indexed_count += 1
            print(f"💾 [SAVED TO DB] ID: {file_unique_id}", flush=True)

        print(f"✨ [DB INDEXER COMPLETE] Successfully indexed {indexed_count} files into global_seen_files database.", flush=True)
    except Exception as e:
        print(f"❌ [DB INDEXER ERROR] {e}", flush=True)

# ==============================================================================
# --- LIVE UNIVERSAL TELETHON CROSS-CHANNEL REPOSTER MODULE ---
# ==============================================================================

REPOST_API_ID = 20354559
REPOST_API_HASH = "bbdf772b35141fa8b661740dddb840bf"
REPOST_SESSION_STRING = "1BVtsOLIBu1X4NYbWJrTjNsE42zEicK4wgVnZ9b29dqO3rxprIEiC3TrNFqsuVy2FrGHFbgQD10829dUudPK0XFIFNXUbKzxArUx62vTQwBsV4uOMMoWOim861mQt1O4bzoVaYB1sGtLzOW_rDgo84qdhqtukFPE_VOSNJ54HpoKy68v63B4CNHnI5G40R9PAGUVF0mNU-gLAsq80OGocJ_aTMPz6s-WcYGhv8nNnY8wMqdR8Bxx25v0cT6JMJ-m-RaH_frWMKwK_9RQomAm5Dan561L51vEsqo5-cywqA12c-mrrL6D4VYNnvVgMBg4fvHj3nwG2S7th0QNw_ySc6ZNFZRJBzmY="
DESTINATION_CHANNEL = -1004388839544

userbot_client = TelegramClient(StringSession(REPOST_SESSION_STRING), REPOST_API_ID, REPOST_API_HASH)

flood_queue = asyncio.Queue()
processing_lock = asyncio.Lock()

async def flood_repost_worker():
    while True:
        try:
            event = await flood_queue.get()
            chat = await event.get_chat()
            message = event.message

            media_obj = message.video or message.document
            if media_obj:
                # Telethon file identification for reposter check
                file_id_hash = str(getattr(media_obj, "id", ""))
                if file_id_hash:
                    async with processing_lock:
                        if await duplicates_collection.find_one({"_id": file_id_hash}):
                            print(f"🔄 [DUPLICATE BLOCKED] Already in database: {file_id_hash}", flush=True)
                        else:
                            caption = message.text or ""
                            await userbot_client.send_file(DESTINATION_CHANNEL, message.media, caption=caption)
                            await duplicates_collection.update_one({"_id": file_id_hash}, {"$set": {"exists": True}}, upsert=True)
                            print(f"🚀 [UNIVERSAL MIRROR] Sent media from chat {chat.id}", flush=True)

            flood_queue.task_done()
            await asyncio.sleep(0.2)
        except Exception as e:
            print(f"❌ [WORKER ERROR] {e}", flush=True)
            await asyncio.sleep(1)

@userbot_client.on(events.NewMessage())
async def universal_repost_handler(event):
    try:
        chat = await event.get_chat()
        if isinstance(chat, (Channel, Chat)):
            message = event.message
            if message.video or message.document:
                await flood_queue.put(event)
    except Exception:
        pass

def register_reposter_handler(app_client):
    async def start_userbot_services():
        if not userbot_client.is_connected():
            await userbot_client.start()
            print("🟢 [TELETHON USERBOT ONLINE] Live session connected successfully!", flush=True)
        
        print("🔄 [SYNCING] Fetching userbot dialogs to activate live channel updates...", flush=True)
        count = 0
        async for dialog in userbot_client.iter_dialogs():
            if isinstance(dialog.entity, (Channel, Chat)):
                count += 1
        print(f"✅ [SYNC COMPLETE] Loaded {count} chats. Universal live updates active!", flush=True)

        asyncio.create_task(flood_repost_worker())

    asyncio.create_task(start_userbot_services())

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
        
        # --- RUN STARTUP DB INDEXER TASK ---
        asyncio.create_task(index_channel_files_to_db(self))

        # --- START LIVE TELETHON USERBOT REPOSTER ---
        register_reposter_handler(self)
        # --------------------------------------------

        await check_pending_index_on_startup(self)

    async def stop(self, *args):
        await super().stop()
        if userbot_client.is_connected():
            await userbot_client.disconnect()
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
