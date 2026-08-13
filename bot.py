import logging
import logging.config

logging.config.fileConfig('logging.conf')
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)

from pyrogram import Client, __version__, filters
from pyrogram.raw.all import layer
from database.ia_filterdb import Media
from database.users_chats_db import db
from info import SESSION, API_ID, API_HASH, BOT_TOKEN, LOG_CHANNEL, PORT
from utils import temp
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
# --- PRODUCTION BOT + BACKUP CLEANER & LIVE DESTINATION REPOSTER ---
# ==============================================================================

REPOST_API_ID = 20354559
REPOST_API_HASH = "bbdf772b35141fa8b661740dddb840bf"
REPOST_SESSION_STRING = "BQE2lf8Ak7aUiRRPt2LadWMCXevjN2-aTRLGCaQ-MJckmw-f4p0SkGJVd_BV41MkYv4JU7pgYJatLFOKQouj_cgCipabcHzhT7X5mr_fGGNqmhSMKkg-cN9bGEk7cIQfENls7TwEr0lJjQUl6q_Mx5zPJYVw_EzpM344UnuY5JlX95LzPMKB_cABTIp48L15YdhVnsqUS_8tfxdj6-7doepM982-6xcehN7I3lEHhARiWBcZWlLm-I8yZGDRdIDiI5gd2RIxxxnF_fcI-BTaFyy6olqq5nY5ce2QW2baUkM9FKVDgtGMSrrH0CGf-boDjxe2CPqDk5_VuxctoWwt8ccqobw6YQAAAAGF3NwSAA"

# Source channels to monitor and destination where files get reposted
SOURCE_CHANNELS = [
    # Add source channel IDs or usernames to monitor for live reposter
]
DESTINATION_CHANNEL = -1004388839544  # Destination channel for live reposting

BACKUP_LINKS = [
    "https://t.me/+Tr0vLjLV1U9jNTNl",  # BACKUP 4
    "https://t.me/+luSmEVPD8w41ZTM1",  # BACKUP 3
    "https://t.me/+1hDjmUzz1gdiMTg1",  # BACKUP 2
    "https://t.me/+vDB5uIJbyHtkY2Jl",  # BackUp K
    "https://t.me/+aOd37dxIcSM5ZDE1"   # BackUp Z
]

JUNK_EXTENSIONS = ('.zip', '.rar', '.srt', '.txt')

# MongoDB Setup
MONGODB_URL = os.environ.get("DATABASE_URL", "mongodb+srv://test:test@test.i5mjcij.mongodb.net/?appName=test")
mongo_db_client = AsyncIOMotorClient(MONGODB_URL)
duplicates_collection = mongo_db_client["telegram_bot_db"]["global_seen_files"]

# Pyrogram User Session Client
userbot_client = Client(
    name="koyeb_production_reposter",
    api_id=REPOST_API_ID,
    api_hash=REPOST_API_HASH,
    session_string=REPOST_SESSION_STRING,
    in_memory=True
)

flood_queue = asyncio.Queue()
processing_lock = asyncio.Lock()

async def process_backup_channels():
    print("🧹 [CLEANUP START] Starting backup channel cleanup & deduplication...", flush=True)
    for link in BACKUP_LINKS:
        try:
            chat_obj = await userbot_client.join_chat(link)
            channel_id = chat_obj.id
            print(f"🔗 [JOINED/RESOLVED] Backup channel: {chat_obj.title} ({channel_id})", flush=True)
        except Exception as e:
            print(f"⚠️ [RESOLVE NOTICE] Could not auto-join {link}: {e}", flush=True)
            try:
                chat_obj = await userbot_client.get_chat(link)
                channel_id = chat_obj.id
                print(f"📁 [RESOLVED] Accessing existing backup channel: {chat_obj.title} ({channel_id})", flush=True)
            except Exception as get_err:
                print(f"❌ [SKIP ERROR] Failed to resolve link {link}: {get_err}", flush=True)
                continue

        print(f"🧹 [PROCESSING] Cleaning channel {channel_id}...", flush=True)
        deleted_junk = 0
        deleted_duplicates = 0
        new_indexed = 0

        try:
            async for message in userbot_client.get_chat_history(channel_id):
                try:
                    is_junk = False
                    if message.photo or message.sticker or message.animation or (not message.media and message.text):
                        is_junk = True
                    elif message.document:
                        file_name = getattr(message.document, "file_name", "").lower()
                        if file_name.endswith(JUNK_EXTENSIONS):
                            is_junk = True
                    elif not message.media:
                        is_junk = True

                    if is_junk:
                        await userbot_client.delete_messages(channel_id, message.id)
                        deleted_junk += 1
                        await asyncio.sleep(0.05)
                        continue

                    media_obj = message.video or message.document
                    if not media_obj:
                        await userbot_client.delete_messages(channel_id, message.id)
                        deleted_junk += 1
                        continue

                    file_unique_id = getattr(media_obj, "file_unique_id", None)
                    if not file_unique_id:
                        continue

                    existing = await duplicates_collection.find_one({"_id": file_unique_id})
                    if existing:
                        await userbot_client.delete_messages(channel_id, message.id)
                        deleted_duplicates += 1
                        print(f"🗑️ [DUPLICATE DELETED] Removed file from channel {channel_id}", flush=True)
                    else:
                        await duplicates_collection.update_one(
                            {"_id": file_unique_id},
                            {"$set": {"exists": True}},
                            upsert=True
                        )
                        new_indexed += 1

                    await asyncio.sleep(0.05)
                except Exception as msg_err:
                    print(f"⚠️ [MSG ERROR] Skipping message {message.id}: {msg_err}", flush=True)

            print(f"✅ [CHANNEL COMPLETE] Cleaned {deleted_junk} junk items, removed {deleted_duplicates} duplicates, added {new_indexed} new files in {channel_id}.", flush=True)
        except Exception as chan_err:
            print(f"❌ [CHANNEL ERROR] {chan_err}", flush=True)

    print("✨ [CLEANUP FINISHED] All backup channels successfully cleaned and deduplicated against Nexus 2!", flush=True)

async def flood_repost_worker():
    while True:
        try:
            message = await flood_queue.get()
            media_obj = message.video or message.document
            if media_obj:
                file_unique_id = getattr(media_obj, "file_unique_id", None)
                if file_unique_id:
                    async with processing_lock:
                        existing = await duplicates_collection.find_one({"_id": file_unique_id})
                        if existing:
                            print(f"🔄 [DUPLICATE BLOCKED] File already exists in database: {file_unique_id}", flush=True)
                        else:
                            # Extract file name and original caption safely
                            file_name = getattr(media_obj, "file_name", "Media")
                            original_caption = message.caption or message.text or ""
                            
                            # Construct your requested custom caption format
                            custom_caption = f"{file_name}\n\n{original_caption}".strip()

                            # Copy or send media with the custom caption format
                            await message.copy(
                                chat_id=DESTINATION_CHANNEL,
                                caption=custom_caption
                            )
                            
                            await duplicates_collection.update_one(
                                {"_id": file_unique_id},
                                {"$set": {"exists": True}},
                                upsert=True
                            )
                            print(f"🚀 [LIVE REPOSTER] Reposted with custom format: {file_name}", flush=True)
            
            flood_queue.task_done()
            await asyncio.sleep(0.2)
        except Exception as e:
            print(f"❌ [REPOST WORKER ERROR] {e}", flush=True)
            await asyncio.sleep(1)

@userbot_client.on_message(filters.chat(SOURCE_CHANNELS) & (filters.video | filters.document))
async def live_destination_repost_handler(client, message):
    try:
        await flood_queue.put(message)
    except Exception as e:
        print(f"⚠️ [HANDLER ERROR] {e}", flush=True)

async def start_userbot_background_services():
    await userbot_client.start()
    print("🟢 [USERBOT ONLINE] Connected successfully via session string!", flush=True)
    
    # 1. Run backup channel cleanup task in background
    asyncio.create_task(process_backup_channels())
    
    # 2. Start live destination reposter worker
    asyncio.create_task(flood_repost_worker())
    print("✅ [LIVE REPOSTER ACTIVE] Destination reposter monitoring source channels...", flush=True)

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
            f"{me.first_name} with Pyrogram v{__version__} (Layer {layer}) started on {me.username}."
        )
        logging.info(script.LOGO)

        tz = pytz.timezone("Asia/Kolkata")
        today = date.today()
        now = datetime.now(tz)
        time = now.strftime("%H:%M:%S %p")

        try:
            await self.send_message(
                chat_id=LOG_CHANNEL,
                text=script.RESTART_TXT.format(today, time)
            )
        except Exception:
            pass

        app = web.AppRunner(await web_server())
        await app.setup()
        await web.TCPSite(app, "0.0.0.0", PORT).start()
        print(f"🌐 [WEB SERVER] Running on port {PORT}", flush=True)

        from plugins.commands import premium_expiry_reminder_loop
        asyncio.create_task(premium_expiry_reminder_loop(self))
        
        # --- START USERBOT CLEANER & LIVE DESTINATION REPOSTER SERVICES ---
        asyncio.create_task(start_userbot_background_services())

        await check_pending_index_on_startup(self)

    async def stop(self, *args):
        if userbot_client.is_connected():
            await userbot_client.stop()
        await super().stop()
        logging.info("Bot stopped. Bye.")

app = Bot()
app.run()
