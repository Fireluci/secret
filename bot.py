import logging
import os
import asyncio
from aiohttp import web
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client
from info import API_ID, API_HASH, BOT_TOKEN, PORT
from plugins import web_server

# ==============================================================================
# --- PRODUCTION-READY KOYEB BOT & INDEXER SCRIPT ---
# ==============================================================================

REPOST_API_ID = 20354559
REPOST_API_HASH = "bbdf772b35141fa8b661740dddb840bf"
REPOST_SESSION_STRING = "BQE2lf8Ak7aUiRRPt2LadWMCXevjN2-aTRLGCaQ-MJckmw-f4p0SkGJVd_BV41MkYv4JU7pgYJatLFOKQouj_cgCipabcHzhT7X5mr_fGGNqmhSMKkg-cN9bGEk7cIQfENls7TwEr0lJjQUl6q_Mx5zPJYVw_EzpM344UnuY5JlX95LzPMKB_cABTIp48L15YdhVnsqUS_8tfxdj6-7doepM982-6xcehN7I3lEHhARiWBcZWlLm-I8yZGDRdIDiI5gd2RIxxxnF_fcI-BTaFyy6olqq5nY5ce2QW2baUkM9FKVDgtGMSrrH0CGf-boDjxe2CPqDk5_VuxctoWwt8ccqobw6YQAAAAGF3NwSAA"

NEXUS_2_CHANNEL_ID = -1001725696043  # Protected Primary Source
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
    name="koyeb_production_indexer",
    api_id=REPOST_API_ID,
    api_hash=REPOST_API_HASH,
    session_string=REPOST_SESSION_STRING,
    in_memory=True
)

async def process_nexus_2():
    print(f"📥 [STEP 1] Scanning protected Nexus 2 channel ({NEXUS_2_CHANNEL_ID}) for official file_unique_ids...", flush=True)
    indexed_count = 0
    
    async for message in userbot_client.get_chat_history(NEXUS_2_CHANNEL_ID):
        media_obj = message.video or message.document
        if not media_obj:
            continue

        file_unique_id = getattr(media_obj, "file_unique_id", None)
        if not file_unique_id:
            continue

        await duplicates_collection.update_one(
            {"_id": file_unique_id},
            {"$set": {"exists": True}},
            upsert=True
        )
        indexed_count += 1
        if indexed_count % 500 == 0:
            print(f"💾 [NEXUS 2 PROGRESS] Indexed {indexed_count} file_unique_ids into MongoDB...", flush=True)

    print(f"✨ [STEP 1 COMPLETE] Nexus 2 fully indexed. Total protected records: {indexed_count}", flush=True)

async def process_backup_channels():
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

        print(f"🧹 [STEP 2] Processing and cleaning backup channel {channel_id}...", flush=True)
        deleted_junk = 0
        deleted_duplicates = 0
        new_indexed = 0

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

        print(f"✅ [CHANNEL COMPLETE] Cleaned {deleted_junk} junk items, removed {deleted_duplicates} duplicates, added {new_indexed} new files.", flush=True)

async def run_workflow():
    print("🟢 Connecting userbot...", flush=True)
    await userbot_client.start()
    print("🟢 [ONLINE] Userbot connected successfully!", flush=True)
    try:
        await process_nexus_2()
        await process_backup_channels()
        print("✨ [ALL TASKS FINISHED] Nexus 2 fully protected, all backup channels cleaned and deduplicated!")
    except Exception as e:
        print(f"❌ [WORKFLOW ERROR] {e}", flush=True)
    finally:
        if userbot_client.is_connected():
            await userbot_client.stop()
        print("🛑 Session disconnected cleanly.")

class Bot(Client):
    def __init__(self):
        super().__init__(
            name="main_runner_bot",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            workers=2,
        )

    async def start(self):
        await super().start()

        app = web.AppRunner(await web_server())
        await app.setup()
        site = web.TCPSite(app, "0.0.0.0", PORT)
        await site.start()
        print(f"🌐 [WEB SERVER] Health check server running on port {PORT}", flush=True)
        
        asyncio.create_task(run_workflow())

    async def stop(self, *args):
        if userbot_client.is_connected():
            await userbot_client.stop()

        await super().stop()
        print("🛑 Bot stopped.", flush=True)

app = Bot()
app.run()
