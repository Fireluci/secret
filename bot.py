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

# ==============================================================================
# --- STANDALONE STRICT-FILE USERBOT INCOMING REPOSTER MODULE ---
# ==============================================================================

REPOST_API_ID = 20354559
REPOST_API_HASH = "bbdf772b35141fa8b661740dddb840bf"
REPOST_SESSION_STRING = "BQE2lf8AXoh8f-aAjj_WtZ_gEeIyCP8vdcjHR47gU7__HbVbHdA_O1y0Io9Khn0Xby2Nb2030-kQGPCRZh5GUtueQPn87ARv_xE63HehbpYsOao_gULoSEzT_yrtjJYtjIORDkqDMwWLsGHDPlPa1_FtIjUIve-mpc2GS6mTIpkhVUkHttMTWqqLBJd9qTgFggit44Y5eDpZNZcAir4gy-KpcpvgDJBA-YrEmtOn_acs8c-fra37ojzOHluAqiHEGvKJsczh1FPjhc-AjNebhi2zLzGtVAPTs9zSrpg0UAXF6C7f8f_e_bmLrIl4RE8IUJfjCJGR_1jSGq07WS7_ZLQG10UCpgAAAAGF3NwSAA"
DESTINATION_CHANNEL = -1004388839544

# MongoDB Setup for Duplicate Tracking
MONGODB_URL = os.environ.get("DATABASE_URL", "mongodb+srv://test:test@test.i5mjcij.mongodb.net/?appName=test")
mongo_db_client = AsyncIOMotorClient(MONGODB_URL)
repost_db = mongo_db_client["telegram_bot_db"]
duplicates_collection = repost_db["global_seen_files"]

SAFE_DELAY = 0.8  
repost_queue = asyncio.Queue()

# Persistent Userbot Client for Live Incoming Listening
userbot_client = Client(
    "strict_incoming_userbot",
    api_id=REPOST_API_ID,
    api_hash=REPOST_API_HASH,
    session_string=REPOST_SESSION_STRING
)

# 1. Strict Queue Worker (Videos & Documents Only, No Unwanted Extensions)
async def incoming_repost_worker():
    print("🚀 [STRICT REPOST WORKER] Started... Filtering for videos/documents only.", flush=True)
    while True:
        try:
            message = await repost_queue.get()
            
            # --- RULE 1: IGNORE NON-MEDIA, PHOTOS, TEXT, GIFS, STICKERS ---
            if message.empty or not message.media:
                repost_queue.task_done()
                continue
                
            if message.media not in [enums.MessageMediaType.VIDEO, enums.MessageMediaType.DOCUMENT]:
                repost_queue.task_done()
                continue
                
            media_obj = getattr(message, message.media.value, None)
            if not media_obj:
                repost_queue.task_done()
                continue

            # --- RULE 2: IGNORE UNWANTED EXTENSIONS (.srt, .txt, .rar, .zip) ---
            file_name = getattr(media_obj, "file_name", "") or "N/A"
            if file_name.lower().endswith(('.srt', '.txt', '.rar', '.zip')):
                print(f"⏩ [SKIPPED EXTENSION] Ignored restricted file: {file_name}", flush=True)
                repost_queue.task_done()
                continue

            # --- RULE 3: MONGODB DUPLICATE CHECK ---
            file_unique_id = getattr(media_obj, "file_unique_id", None)
            if file_unique_id:
                exists = await duplicates_collection.find_one({"_id": file_unique_id})
                if exists:
                    print(f"🔄 [DUPLICATE BLOCKED] File already in DB. Skipping.", flush=True)
                    repost_queue.task_done()
                    continue
                await duplicates_collection.update_one({"_id": file_unique_id}, {"$set": {"exists": True}}, upsert=True)

            # --- RULE 4: FORMAT CAPTION ({file_name} + existing caption) ---
            file_caption = message.caption or ""
            custom_caption = f"{file_name}\n\n{file_caption}" if file_caption else file_name

            # Safe copy with FloodWait protection
            try:
                await message.copy(chat_id=DESTINATION_CHANNEL, caption=custom_caption)
                print(f"🚀 [MIRRORED FILE] Reposted: {file_name} (ID: {message.id})", flush=True)
            except FloodWait as e:
                print(f"⏳ [FLOODWAIT] Sleeping for {e.value + 2}s...", flush=True)
                await asyncio.sleep(e.value + 2)
                await message.copy(chat_id=DESTINATION_CHANNEL, caption=custom_caption)
            except Exception as e:
                print(f"❌ [REPOST ERROR] Failed to mirror: {e}", flush=True)

            await asyncio.sleep(SAFE_DELAY)
            repost_queue.task_done()
        except Exception as e:
            print(f"⚠️ [WORKER EXCEPTION] {e}", flush=True)
            await asyncio.sleep(1)

# 2. Register Userbot Event Handler & Start Services
def register_reposter_handler(app_client):
    @userbot_client.on_message(filters.channel | filters.group)
    async def global_incoming_reposter_handler(client, message):
        await repost_queue.put(message)

    async def start_userbot_services():
        await userbot_client.start()
        print("🟢 [USERBOT ONLINE] Live incoming reposter session connected successfully!", flush=True)
        
        print("🔄 [SYNCING] Fetching userbot dialogs to activate live channel updates...", flush=True)
        async for _ in userbot_client.get_dialogs():
            pass
        print("✅ [SYNC COMPLETE] Live channel updates are now active!", flush=True)

        asyncio.create_task(incoming_repost_worker())

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
        
        # --- INITIALIZE STANDALONE REPOSTER ---
        register_reposter_handler(self)
        # --------------------------------------

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
