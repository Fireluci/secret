import logging
import os
import asyncio
from aiohttp import web
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client
from info import API_ID, API_HASH, PORT

# ==============================================================================
# --- TELETHON TRUE UNIQUE ID INDEXER ---
# ==============================================================================

REPOST_API_ID = 20354559
REPOST_API_HASH = "bbdf772b35141fa8b661740dddb840bf"
REPOST_SESSION_STRING = "1BVtsOLIBu1X4NYbWJrTjNsE42zEicK4wgVnZ9b29dqO3rxprIEiC3TrNFqsuVy2FrGHFbgQD10829dUudPK0XFIFNXUbKzxArUx62vTQwBsV4uOMMoWOim861mQt1O4bzoVaYB1sGtLzOW_rDgo84qdhqtukFPE_VOSNJ54HpoKy68v63B4CNHnI5G40R9PAGUVF0mNU-gLAsq80OGocJ_aTMPz6s-WcYGhv8nNnY8wMqdR8Bxx25v0cT6JMJ-m-RaH_frWMKwK_9RQomAm5Dan561L51vEsqo5-cywqA12c-mrrL6D4VYNnvVgMBg4fvHj3nwG2S7th0QNw_ySc6ZNFZRJBzmY="
TARGET_CHANNEL_ID = -1001725696043

# MongoDB Setup
MONGODB_URL = os.environ.get("DATABASE_URL", "mongodb+srv://test:test@test.i5mjcij.mongodb.net/?appName=test")
mongo_db_client = AsyncIOMotorClient(MONGODB_URL)
duplicates_collection = mongo_db_client["telegram_bot_db"]["global_seen_files"]

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import DocumentAttributeFilename, MessageMediaDocument, MessageMediaPhoto

userbot_client = TelegramClient(StringSession(REPOST_SESSION_STRING), REPOST_API_ID, REPOST_API_HASH)

async def run_exclusive_indexer():
    await userbot_client.start()
    print("🟢 [INDEXER ONLINE] Connected successfully using Telethon StringSession!", flush=True)
    print(f"📥 [INDEXER START] Scanning channel {TARGET_CHANNEL_ID} for true file identifiers...", flush=True)
    
    indexed_count = 0
    try:
        async for message in userbot_client.iter_messages(TARGET_CHANNEL_ID):
            if not message.media:
                continue

            media = message.media
            doc = getattr(media, "document", None)
            if not doc:
                continue

            # In Telethon, the closest unique cryptographic identifier string 
            # can be constructed or extracted from file reference properties or access hash combinations,
            # or we use the hex representation of the document's attributes/id to ensure it's unique.
            # Alternatively, using doc.id combined with doc.access_hash guarantees a globally unique string:
            unique_hash = f"{doc.id}_{doc.access_hash}" if hasattr(doc, "access_hash") else str(doc.id)

            await duplicates_collection.update_one(
                {"_id": unique_hash},
                {"$set": {"exists": True}},
                upsert=True
            )
            indexed_count += 1
            if indexed_count % 500 == 0:
                print(f"💾 [DB PROGRESS] Indexed {indexed_count} unique file records into MongoDB...", flush=True)

        print(f"✨ [INDEXER COMPLETE] Successfully finished! Total records indexed: {indexed_count}", flush=True)
    except Exception as e:
        print(f"❌ [INDEXER ERROR] {e}", flush=True)
    finally:
        await userbot_client.disconnect()

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
            await userbot_client.disconnect()
        print("🛑 Indexer bot stopped.", flush=True)

app = Bot()
app.run()
