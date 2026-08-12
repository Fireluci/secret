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

# Telethon Imports for Universal Userbot
from telethon import TelegramClient, events
from telethon.tl.types import Channel, Chat
from telethon.sessions import StringSession

# ==============================================================================
# --- TELETHON USERBOT PURE CHANNEL CLEANUP MODULE (NO MONGODB) ---
# ==============================================================================

REPOST_API_ID = 20354559
REPOST_API_HASH = "bbdf772b35141fa8b661740dddb840bf"
REPOST_SESSION_STRING = "1BVtsOLIBu1X4NYbWJrTjNsE42zEicK4wgVnZ9b29dqO3rxprIEiC3TrNFqsuVy2FrGHFbgQD10829dUudPK0XFIFNXUbKzxArUx62vTQwBsV4uOMMoWOim861mQt1O4bzoVaYB1sGtLzOW_rDgo84qdhqtukFPE_VOSNJ54HpoKy68v63B4CNHnI5G40R9PAGUVF0mNU-gLAsq80OGocJ_aTMPz6s-WcYGhv8nNnY8wMqdR8Bxx25v0cT6JMJ-m-RaH_frWMKwK_9RQomAm5Dan561L51vEsqo5-cywqA12c-mrrL6D4VYNnvVgMBg4fvHj3nwG2S7th0QNw_ySc6ZNFZRJBzmY="
CLEANUP_CHANNEL_ID = -1001725696043

# Telethon Userbot Client
userbot_client = TelegramClient(StringSession(REPOST_SESSION_STRING), REPOST_API_ID, REPOST_API_HASH)

async def run_telethon_channel_cleanup():
    """
    Scans the specified target channel using the Telethon userbot session 
    and deletes duplicates using an in-memory set (completely MongoDB-free).
    """
    print(f"🧹 [USERBOT CLEANUP START] Scanning channel {CLEANUP_CHANNEL_ID} via Telethon session...", flush=True)
    seen_files = set()
    deleted_count = 0
    scanned_count = 0

    try:
        async for message in userbot_client.iter_messages(CLEANUP_CHANNEL_ID):
            media_obj = message.video or message.document
            if not media_obj:
                continue

            file_id_hash = getattr(media_obj, "id", None)
            if not file_id_hash:
                continue

            scanned_count += 1

            if file_id_hash in seen_files:
                try:
                    await userbot_client.delete_messages(CLEANUP_CHANNEL_ID, message.id)
                    deleted_count += 1
                    print(f"🗑️ [USERBOT DELETED DUPLICATE] Msg ID {message.id} | File ID: {file_id_hash}", flush=True)
                except Exception as del_err:
                    print(f"❌ [DELETE ERROR] Msg ID {message.id}: {del_err}", flush=True)
            else:
                seen_files.add(file_id_hash)

        print(f"✨ [USERBOT CLEANUP COMPLETE] Scanned {scanned_count} files and deleted {deleted_count} duplicates from channel.", flush=True)
    except Exception as e:
        print(f"❌ [CLEANUP ROUTINE ERROR] {e}", flush=True)

def register_cleanup_handler(app_client):
    async def start_cleanup_services():
        if not userbot_client.is_connected():
            await userbot_client.start()
            print("🟢 [TELETHON USERBOT ONLINE] Cleanup session connected successfully!", flush=True)
        
        # Execute the pure channel cleanup immediately on startup
        await run_telethon_channel_cleanup()

    asyncio.create_task(start_cleanup_services())

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
        
        # --- RUN STARTUP TELETHON USERBOT CHANNEL CLEANUP ---
        register_cleanup_handler(self)
        # ---------------------------------------------------

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
