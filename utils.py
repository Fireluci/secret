import logging
from pyrogram.errors import InputUserDeactivated, UserNotParticipant, FloodWait, UserIsBlocked, PeerIdInvalid
from info import AUTH_CHANNEL, IS_SHORTLINK, SHORT1_URL, SHORT1_API, SHORT2_URL, SHORT2_API, LOG_CHANNEL, SPELL_CHECK_REPLY
import asyncio
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import FloodWait, UserIsBlocked, MessageNotModified, PeerIdInvalid
from pyrogram import enums, filters
from typing import Union
from Script import script
import re
import os
from datetime import datetime 
from typing import List
from database.users_chats_db import db
from bs4 import BeautifulSoup
import requests
import aiohttp
from rapidfuzz import fuzz
import urllib.parse
from shortzy import Shortzy
import regex
import http.client
import json

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BTN_URL_REGEX = re.compile(
    r"(\[([^\[]+?)\]\((buttonurl|buttonalert):(?:/{0,2})(.+?)(:same)?\))"
)

BANNED = {}
SECOND_SHORTENER = {}
SMART_OPEN = '“'
SMART_CLOSE = '”'
START_CHAR = ('\'', '"', SMART_OPEN)
SHORT = {}

class temp(object):
    BANNED_USERS = []
    ME = None
    CURRENT=int(os.environ.get("SKIP", 2))
    CANCEL = False
    MELCOW = {}
    U_NAME = None
    B_NAME = None
    GROUP_ACCESS = {}
    SETTINGS = {}

async def is_subscribed(bot, query):
    try:
        user = await bot.get_chat_member(AUTH_CHANNEL, query.from_user.id)
    except UserNotParticipant:
        pass
    except Exception as e:
        logger.exception(e)
    else:
        if user.status != enums.ChatMemberStatus.BANNED:
            return True

    return False

async def broadcast_messages(user_id, message):
    try:
        await message.copy(chat_id=user_id)
        return True, "Success"
    except FloodWait as e:
        await asyncio.sleep(e.x)
        return await broadcast_messages(user_id, message)
    except InputUserDeactivated:
        await db.delete_user(int(user_id))
        logging.info(f"{user_id}-Removed from Database, since deleted account.")
        return False, "Deleted"
    except UserIsBlocked:
        logging.info(f"{user_id} -Blocked the bot.")
        return False, "Blocked"
    except PeerIdInvalid:
        await db.delete_user(int(user_id))
        logging.info(f"{user_id} - PeerIdInvalid")
        return False, "Error"
    except Exception as e:
        return False, "Error"

async def broadcast_messages_group(chat_id, message):
    try:
        kd = await message.copy(chat_id=chat_id)
        try:
            await kd.pin()
        except:
            pass
        return True, "Success"
    except FloodWait as e:
        await asyncio.sleep(e.x)
        return await broadcast_messages_group(chat_id, message)
    except Exception as e:
        return False, "Error"
    
async def search_gagala(text):

    query = urllib.parse.quote_plus(text)

    url = f"https://html.duckduckgo.com/html/?q={query}"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        )
    }

    timeout = aiohttp.ClientTimeout(total=8)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:

            async with session.get(
                url,
                headers=headers
            ) as response:

                if response.status != 200:
                    return []

                html = await response.text()

        soup = BeautifulSoup(html, "html.parser")

        titles = soup.find_all(
            "a",
            class_="result__a"
        )

        results = []

        for t in titles[:20]:

            title = t.get_text(strip=True)

            score = fuzz.token_set_ratio(
                text.lower(),
                title.lower()
            )

            if score >= 25:
                results.append((score, title))

        results.sort(reverse=True)

        return [x[1] for x in results[:6]]

    except asyncio.TimeoutError:
        return []

    except Exception:
        return []

def _as_bool(value, default):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        value = value.strip().lower()
        if value in {"true", "yes", "1", "on", "enable"}:
            return True
        if value in {"false", "no", "0", "off", "disable"}:
            return False
    return default


async def get_settings(group_id):
    group_id = int(group_id)
    settings = temp.SETTINGS.get(group_id)
    if settings is not None:
        return settings

    overrides = await db.get_group_settings(group_id)
    settings = {
        "spell_check": _as_bool(overrides.get("spell_check"), SPELL_CHECK_REPLY),
        "is_shortlink": _as_bool(overrides.get("is_shortlink"), IS_SHORTLINK),
        "shortlink": overrides.get("shortlink") or SHORT1_URL,
        "shortlink_api": overrides.get("shortlink_api") or SHORT1_API,
        "second_shortlink": overrides.get("second_shortlink") or SHORT2_URL,
        "second_shortlink_api": overrides.get("second_shortlink_api") or SHORT2_API,
    }
    temp.SETTINGS[group_id] = settings
    return settings


async def save_group_settings(group_id, key, value):
    allowed = {
        "spell_check",
        "is_shortlink",
        "shortlink",
        "shortlink_api",
        "second_shortlink",
        "second_shortlink_api",
    }
    if key not in allowed:
        return

    group_id = int(group_id)
    settings = await get_settings(group_id)

    if key == "spell_check":
        default = SPELL_CHECK_REPLY
        value = _as_bool(value, default)
        if value == default:
            await db.remove_group_setting(group_id, key)
        else:
            await db.set_group_setting(group_id, key, value)
        settings[key] = value
        return

    if key == "is_shortlink":
        default = IS_SHORTLINK
        value = _as_bool(value, default)
        if value == default:
            await db.remove_group_setting(group_id, key)
        else:
            await db.set_group_setting(group_id, key, value)
        settings[key] = value
        return

    # Shortener configuration is per-group. If it matches the global default,
    # remove the override so future info.py changes automatically apply.
    defaults = {
        "shortlink": SHORT1_URL,
        "shortlink_api": SHORT1_API,
        "second_shortlink": SHORT2_URL,
        "second_shortlink_api": SHORT2_API,
    }
    value = str(value).strip()
    if value == str(defaults[key]):
        await db.remove_group_setting(group_id, key)
    else:
        await db.set_group_setting(group_id, key, value)
    settings[key] = value or defaults[key]

async def is_group_connected(chat_id):
    chat_id = int(chat_id)
    cached = temp.GROUP_ACCESS.get(chat_id)
    if cached is not None:
        return cached
    connected = await db.is_group_connected(chat_id)
    temp.GROUP_ACCESS[chat_id] = connected
    return connected


async def set_group_connected(chat_id, connected):
    chat_id = int(chat_id)
    if connected:
        await db.connect_group(chat_id, "")
    else:
        await db.disconnect_group(chat_id)
    temp.GROUP_ACCESS[chat_id] = connected


async def connected_group_filter(_, __, update):
    chat = getattr(update, "chat", None)
    if chat is None and getattr(update, "message", None):
        chat = update.message.chat
    if chat is None:
        return True
    if chat.type not in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
        return True
    return await is_group_connected(chat.id)


connected_group = filters.create(connected_group_filter)


def get_size(size):
    """Get size in readable format"""

    units = ["Bytes", "KB", "MB", "GB", "TB", "PB", "EB"]
    size = float(size)
    i = 0
    while size >= 1024.0 and i < len(units):
        i += 1
        size /= 1024.0
    return "%.2f %s" % (size, units[i])

def split_list(l, n):
    for i in range(0, len(l), n):
        yield l[i:i + n]  

def get_file_id(msg: Message):
    if msg.media:
        for message_type in (
            "photo",
            "animation",
            "audio",
            "document",
            "video",
            "video_note",
            "voice",
            "sticker"
        ):
            obj = getattr(msg, message_type)
            if obj:
                setattr(obj, "message_type", message_type)
                return obj

def extract_user(message: Message) -> Union[int, str]:
    """extracts the user from a message"""
    user_id = None
    user_first_name = None
    if message.reply_to_message:
        user_id = message.reply_to_message.from_user.id
        user_first_name = message.reply_to_message.from_user.first_name

    elif len(message.command) > 1:
        if (
            len(message.entities) > 1 and
            message.entities[1].type == enums.MessageEntityType.TEXT_MENTION
        ):
           
            required_entity = message.entities[1]
            user_id = required_entity.user.id
            user_first_name = required_entity.user.first_name
        else:
            user_id = message.command[1]
            user_first_name = user_id
        try:
            user_id = int(user_id)
        except ValueError:
            pass
    else:
        user_id = message.from_user.id
        user_first_name = message.from_user.first_name
    return (user_id, user_first_name)

def last_online(from_user):
    time = ""
    if from_user.is_bot:
        time += "🤖 Bot :("
    elif from_user.status == enums.UserStatus.RECENTLY:
        time += "Recently"
    elif from_user.status == enums.UserStatus.LAST_WEEK:
        time += "Within the last week"
    elif from_user.status == enums.UserStatus.LAST_MONTH:
        time += "Within the last month"
    elif from_user.status == enums.UserStatus.LONG_AGO:
        time += "A long time ago :("
    elif from_user.status == enums.UserStatus.ONLINE:
        time += "Currently Online"
    elif from_user.status == enums.UserStatus.OFFLINE:
        time += from_user.last_online_date.strftime("%a, %d %b %Y, %H:%M:%S")
    return time

def split_quotes(text: str) -> List:
    if not any(text.startswith(char) for char in START_CHAR):
        return text.split(None, 1)
    counter = 1  # ignore first char -> is some kind of quote
    while counter < len(text):
        if text[counter] == "\\":
            counter += 1
        elif text[counter] == text[0] or (text[0] == SMART_OPEN and text[counter] == SMART_CLOSE):
            break
        counter += 1
    else:
        return text.split(None, 1)

    key = remove_escapes(text[1:counter].strip())
    
    rest = text[counter + 1:].strip()
    if not key:
        key = text[0] + text[0]
    return list(filter(None, [key, rest]))

def remove_escapes(text: str) -> str:
    res = ""
    is_escaped = False
    for counter in range(len(text)):
        if is_escaped:
            res += text[counter]
            is_escaped = False
        elif text[counter] == "\\":
            is_escaped = True
        else:
            res += text[counter]
    return res

def humanbytes(size):
    if not size:
        return ""
    power = 2**10
    n = 0
    Dic_powerN = {0: ' ', 1: 'Ki', 2: 'Mi', 3: 'Gi', 4: 'Ti'}
    while size > power:
        size /= power
        n += 1
    return str(round(size, 2)) + " " + Dic_powerN[n] + 'B'

async def get_shortlink(chat_id, link, client=None):
    settings = await get_settings(chat_id)
    primary_site = settings.get("shortlink") or SHORT1_URL
    primary_api = settings.get("shortlink_api") or SHORT1_API
    secondary_site = settings.get("second_shortlink") or SHORT2_URL
    secondary_api = settings.get("second_shortlink_api") or SHORT2_API
    timeout = aiohttp.ClientTimeout(total=6)

    async def _request_shorten(base_site, api_key):
        if not base_site or not api_key:
            raise RuntimeError("Shortener is not configured")
        if base_site == "api.shareus.io":
            url = f"https://{base_site}/api"
            params = {"key": api_key, "link": link}
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as response:
                    response.raise_for_status()
                    return await response.text()

        async with aiohttp.ClientSession(timeout=timeout) as session:
            shortzy = Shortzy(api_key=api_key, base_site=base_site)
            return await shortzy.convert(link)

    try:
        return await _request_shorten(primary_site, primary_api)
    except Exception as first_error:
        logger.warning("Primary shortener failed: %s", first_error)

    try:
        return await _request_shorten(secondary_site, secondary_api)
    except Exception as second_error:
        logger.error("Secondary shortener failed: %s", second_error)
        if client and LOG_CHANNEL:
            try:
                await client.send_message(
                    LOG_CHANNEL,
                    f"⚠️ Shortener failure\nChat: `{chat_id}`\nError: `{second_error}`",
                )
            except Exception:
                pass
        raise RuntimeError("All shorteners are down.") from second_error


async def extract_v2(text):
    text = text.lower()

    # remove emojis & symbols early
    text = regex.sub(r'\p{So}', '', text)
    text = re.sub(r"[@!$_\-.+:*#⁓(),/?]", " ", text)

    # normalize season / episode words
    text = re.sub(
        r'\bseason\s*(\d{1,2})\b',
        lambda m: f's{m.group(1).zfill(2)}',
        text
    )
    text = re.sub(
        r'\bepisode\s*(\d{1,2})\b',
        lambda m: f'e{m.group(1).zfill(2)}',
        text
    )

    # normalize short forms
    text = re.sub(r'\bs(\d)\b', r's0\1', text)
    text = re.sub(r'\be(\d)\b', r'e0\1', text)
    text = re.sub(
        r'\bep\s*(\d{1,2})\b',
        lambda m: f"e{m.group(1).zfill(2)}",
        text
    )

    # 🔥 normalize ALL season + episode combinations

    # season 5 episode 1 / season 5 ep1
    text = re.sub(
        r'season\s*(\d{1,2})\s*(?:episode|ep)\s*(\d{1,2})',
        lambda m: f"s{m.group(1).zfill(2)}e{m.group(2).zfill(2)}",
        text
    )

    # s5 episode 1 / s5 ep1 / s05 ep01
    text = re.sub(
        r's(\d{1,2})\s*(?:episode|ep)\s*(\d{1,2})',
        lambda m: f"s{m.group(1).zfill(2)}e{m.group(2).zfill(2)}",
        text
    )

    # s5 e1 / s05 e01 / s5e1
    text = re.sub(
        r's(\d{1,2})\s*e(\d{1,2})',
        lambda m: f"s{m.group(1).zfill(2)}e{m.group(2).zfill(2)}",
        text
    )

    # cleanup spaces
    text = re.sub(r'\s+', ' ', text).strip()

    # 🔥 if episode exists but season missing → assume s01
    if re.search(r'\be\d{2}\b', text) and not re.search(r'\bs\d{2}\b', text):
        text = re.sub(r'\be(\d{2})\b', r's01e\1', text)

    return text
