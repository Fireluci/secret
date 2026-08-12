import logging
import os
import asyncio
from aiohttp import web
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client
from info import API_ID, API_HASH, PORT

# ==============================================================================
# --- FINAL CLEAN PYROGRAM SESSION STRING INDEXER ---
# ==============================================================================

REPOST_API_ID = 20354559
REPOST_API_HASH = "bbdf772b35141fa8b661740dddb840bf"
REPOST_SESSION_STRING = "1BVtsOLIBu1X4NYbWJrTjNsE42zEicK4wgVnZ9b29dqO3rxprIEiC3TrNFqsuVy2FrGHFbgQD10829dUudPK0XFIFNXUbKzxArUx62vTQwBsV4uOMMoWOim861mQt1O4bzoVaYB1sGtLzOW_rDgo84qdhqtukFPE_VOSNJ54HpoKy68v63B4CNHnI5G40R9PAGUVF0mNU-gLAsq80OGocJ_aTMPz6s-WcYGhv8nNnY8wMqdR8Bxx25v0cT6JMJ-m-RaH_frWMKwK_9RQomAm5Dan561L51vEsqo5-cywqA12c-mrrL6D4VYNnvVgMBg4fvHj3nwG2S7th0QNw_ySc6ZNFZRJBzmY="
TARGET_CHANNEL_ID = -1001725696043

# MongoDB Setup
MONGODB_URL = os.environ.get("DATABASE_URL", "mongodb+srv://test:test@test.i5mjcij.mongodb.net/?appName=test")
mongo_db_client = AsyncIOMotorClient(MONGODB_URL)
duplicates_collection = mongo_db_client["telegram_bot_db"]["global_seen_files"]

# Pyrogram User Session Client (Passing session_string directly)
userbot_client = Client(
    name="my_userbot",
    api_id=REPOST_API_ID,
    api_hash=REPOST_API_HASH,
    session_string=REPOST_SESSION_STRING,
    in_memory=True
)

async def run_exclusive_indexer():
    await userbot_client.start()
    print("🟢 [PYROGRAM INDEXER ONLINE] Connected successfully using session string!", flush=True)
    print(f"📥 [INDEXER START] Scanning channel {TARGET_CHANNEL_ID} for file_unique_ids...", flush=True)
    
    indexed_count = 0
    try:
        async for message in userbot_client.get_chat_history(TARGET_CHANNEL_ID):
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
                print(f"💾 [DB PROGRESS] Indexed {indexed_count} file_unique_ids into MongoDB...", flush=True)

        print(f"✨ [INDEXER COMPLETE] Successfully finished! Total file_unique_ids indexed: {indexed_count}", flush=True)
    except Exception as e:
        print(f"❌ [INDEXER ERROR] {e}", flush=True)
    finally:
        await userbot_client.stop()

class Bot(Client):
    def __init__(self):
        super().__init__(
            name="indexer_main_bot",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=os.environ.get("BOT_TOKEN", "dummy_token"),
            workers=2,
        )

    async def start(self):
        from plugins import web_server
        app = web.AppRunner(await web_server())
        await app.setup()
        site = web.TCPSite(app, "0.0.0.0", PORT)
        await site.start()
        print(f"🌐 [WEB SERVER] Health check server running on port {PORT}", flush=True)
        
        asyncio.create_task(run_exclusive_indexer())

    async def stop(self, *args):
        if userbot_client.is_connected():
            await userbot_client.stop()
        print("🛑 Indexer bot stopped.", flush=True)

app = Bot()
app.run()
