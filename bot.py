import logging
import logging.config
import asyncio

# Get logging configurations
logging.config.fileConfig('logging.conf')
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)
 
from plugins.index import check_pending_index_on_startup
from plugins.autofilter import start_premium_tasks
from pyrogram import Client, __version__
from pyrogram.raw.all import layer
from database.ia_filterdb import Media
from database.users_chats_db import db
from utils import temp
from typing import Union, Optional, AsyncGenerator
from pyrogram import types
from datetime import date, datetime 
import pytz
from aiohttp import web
from plugins import web_server
from info import (
    SESSION,
    API_ID,
    API_HASH,
    BOT_TOKEN,
    LOG_CHANNEL,
    PORT,
    RESTART_TXT,
    LOGO,
    ADMINS,
)

OWNER = ADMINS[0]
class Bot(Client):

    def __init__(self):
        super().__init__(
            name=SESSION,
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            workers=20,
            plugins={"root": "plugins"},
            sleep_threshold=5,
        )

    async def start(self):
        await db.ensure_cache_indexes()
        temp.BANNED_USERS = await db.get_banned_users()
        await super().start()
        await Media.ensure_indexes()
        me = await self.get_me()
        temp.ME = me.id
        temp.U_NAME = me.username
        temp.B_NAME = me.first_name
        self.username = '@' + me.username
        logging.info(f"{me.first_name} with for Pyrogram v{__version__} (Layer {layer}) started on {me.username}.")
        logging.info(LOGO)
        tz = pytz.timezone('Asia/Kolkata')
        today = date.today()
        now = datetime.now(tz)
        time = now.strftime("%H:%M:%S %p")

        manual_restart = await db.consume_restart_flag()

        if manual_restart:
            try:
                restart_msg = await self.send_message(
                    chat_id=OWNER,
                    text=RESTART_TXT.format(today, time),
                )

                async def delete_restart_notification():
                    await asyncio.sleep(10)
                    try:
                        await restart_msg.delete()
                    except Exception:
                        pass

                asyncio.create_task(delete_restart_notification())
            except Exception:
                logging.exception("Failed to send restart notification to owner")
        else:
            try:
                await self.send_message(
                    chat_id=LOG_CHANNEL,
                    text=RESTART_TXT.format(today, time),
                )
            except Exception:
                logging.exception("Failed to send startup notification to log channel")

        app = web.AppRunner(await web_server())
        await app.setup()
        bind_address = "0.0.0.0"
        await web.TCPSite(app, bind_address, PORT).start()
        
        # Trigger check for pending index tasks right after bot starts up successfully
        await check_pending_index_on_startup(self)
        await start_premium_tasks(self)

    async def stop(self, *args):
        await super().stop()
        logging.info("Bot stopped. Bye.")

    async def iter_messages(
        self,
        chat_id: Union[int, str],
        limit: int,
        offset: int = 0,
    ) -> Optional[AsyncGenerator["types.Message", None]]:
        current = offset
        while True:
            new_diff = min(200, limit - current)
            if new_diff <= 0:
                return
            messages = await self.get_messages(chat_id, list(range(current, current+new_diff+1)))
            for message in messages:
                yield message
                current += 1


app = Bot()
app.run()
