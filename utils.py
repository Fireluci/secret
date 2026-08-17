import logging
from pyrogram.errors import InputUserDeactivated, UserNotParticipant, FloodWait, UserIsBlocked, PeerIdInvalid
from info import AUTH_CHANNEL, IS_SHORTLINK, SPELL_CHECK_REPLY, TUTORIAL, GRP_LNK, CHNL_LNK, CUSTOM_FILE_CAPTION, SHORT1_URL, SHORT1_API, SHORT2_URL, SHORT2_API, LOG_CHANNEL
import asyncio
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import FloodWait, UserIsBlocked, MessageNotModified, PeerIdInvalid
from pyrogram import enums
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
 
class temp(object):
    BANNED_USERS = []
    BANNED_CHATS = []
    ME = None
    CURRENT=int(os.environ.get("SKIP", 2))
    CANCEL = False
    MELCOW = {}
    U_NAME = None
    B_NAME = None
    GETALL = {}
    SHORT = {}
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

    query = text.replace(" ", "+")

    url = f"https://html.duckduckgo.com/html/?q={query}"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        )
    }

    timeout = aiohttp.ClientTimeout(total=8)

    try:
        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.get(
                url,
                headers=headers,
                ssl=False
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

# Only Spell Check and ShortLink are per-group settings.
# All other bot behaviour is hardcoded in the feature that uses it.

def _setting_bool(value, default):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        value = value.strip().lower()
        if value in {"true", "yes", "1", "enable", "enabled", "on", "y"}:
            return True
        if value in {"false", "no", "0", "disable", "disabled", "off", "n"}:
            return False
    return default

async def get_settings(group_id):
    # Cached per group. MongoDB is read only once per group after bot startup.
    if group_id in temp.SETTINGS:
        return temp.SETTINGS[group_id]

    stored = await db.get_settings(group_id)
    settings = {
        "spell_check": _setting_bool(stored.get("spell_check"), SPELL_CHECK_REPLY),
        "is_shortlink": _setting_bool(stored.get("is_shortlink"), IS_SHORTLINK),
        "shortlink": stored.get("shortlink") or SHORT1_URL,
        "shortlink_api": stored.get("shortlink_api") or SHORT1_API,
        "second_shortlink": stored.get("second_shortlink") or SHORT2_URL,
        "second_shortlink_api": stored.get("second_shortlink_api") or SHORT2_API,
    }
    temp.SETTINGS[group_id] = settings
    return settings

async def save_group_settings(group_id, key, value):
    # Only these values may be changed through settings/shortener commands.
    allowed = {
        "spell_check", "is_shortlink",
        "shortlink", "shortlink_api",
        "second_shortlink", "second_shortlink_api",
    }
    if key not in allowed:
        return
    current = await get_settings(group_id)
    if key in {"spell_check", "is_shortlink"}:
        value = _setting_bool(value, False)
    current[key] = value
    temp.SETTINGS[group_id] = current
    await db.update_setting(group_id, key, value)
    
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

def list_to_str(k):
    if not k:
        return "N/A"
    elif len(k) == 1:
        return str(k[0])
    elif MAX_LIST_ELM:
        k = k[:int(MAX_LIST_ELM)]
        return ' '.join(f'{elem}, ' for elem in k)
    else:
        return ' '.join(f'{elem}, ' for elem in k)

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

def gfilterparser(text, keyword):
    if "buttonalert" in text:
        text = (text.replace("\n", "\\n").replace("\t", "\\t"))
    buttons = []
    note_data = ""
    prev = 0
    i = 0
    alerts = []
    for match in BTN_URL_REGEX.finditer(text):
        n_escapes = 0
        to_check = match.start(1) - 1
        while to_check > 0 and text[to_check] == "\\":
            n_escapes += 1
            to_check -= 1

        if n_escapes % 2 == 0:
            note_data += text[prev:match.start(1)]
            prev = match.end(1)
            if match.group(3) == "buttonalert":
                if bool(match.group(5)) and buttons:
                    buttons[-1].append(InlineKeyboardButton(
                        text=match.group(2),
                        callback_data=f"gfilteralert:{i}:{keyword}"
                    ))
                else:
                    buttons.append([InlineKeyboardButton(
                        text=match.group(2),
                        callback_data=f"gfilteralert:{i}:{keyword}"
                    )])
                i += 1
                alerts.append(match.group(4))
            elif bool(match.group(5)) and buttons:
                buttons[-1].append(InlineKeyboardButton(
                    text=match.group(2),
                    url=match.group(4).replace(" ", "")
                ))
            else:
                buttons.append([InlineKeyboardButton(
                    text=match.group(2),
                    url=match.group(4).replace(" ", "")
                )])

        else:
            note_data += text[prev:to_check]
            prev = match.start(1) - 1
    else:
        note_data += text[prev:]

    try:
        return note_data, buttons, alerts
    except:
        return note_data, buttons, None

def parser(text, keyword):
    if "buttonalert" in text:
        text = (text.replace("\n", "\\n").replace("\t", "\\t"))
    buttons = []
    note_data = ""
    prev = 0
    i = 0
    alerts = []
    for match in BTN_URL_REGEX.finditer(text):
        n_escapes = 0
        to_check = match.start(1) - 1
        while to_check > 0 and text[to_check] == "\\":
            n_escapes += 1
            to_check -= 1

        if n_escapes % 2 == 0:
            note_data += text[prev:match.start(1)]
            prev = match.end(1)
            if match.group(3) == "buttonalert":
                if bool(match.group(5)) and buttons:
                    buttons[-1].append(InlineKeyboardButton(
                        text=match.group(2),
                        callback_data=f"alertmessage:{i}:{keyword}"
                    ))
                else:
                    buttons.append([InlineKeyboardButton(
                        text=match.group(2),
                        callback_data=f"alertmessage:{i}:{keyword}"
                    )])
                i += 1
                alerts.append(match.group(4))
            elif bool(match.group(5)) and buttons:
                buttons[-1].append(InlineKeyboardButton(
                    text=match.group(2),
                    url=match.group(4).replace(" ", "")
                ))
            else:
                buttons.append([InlineKeyboardButton(
                    text=match.group(2),
                    url=match.group(4).replace(" ", "")
                )])

        else:
            note_data += text[prev:to_check]
            prev = match.start(1) - 1
    else:
        note_data += text[prev:]

    try:
        return note_data, buttons, alerts
    except:
        return note_data, buttons, None

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
    
    # 1. Load Primary Shortener (Short1)
    if 'shortlink' in settings and settings['shortlink']:
        p_url = settings['shortlink']
        p_api = settings['shortlink_api']
    else:
        p_url = SHORT1_URL
        p_api = SHORT1_API
        
    # 2. Load Secondary Shortener (Short2)
    if 'second_shortlink' in settings and settings['second_shortlink']:
        s_url = settings['second_shortlink']
        s_api = settings['second_shortlink_api']
    else:
        s_url = SHORT2_URL
        s_api = SHORT2_API

    # Strict timeout to prevent hanging
    timeout = aiohttp.ClientTimeout(total=6)

    async def _request_shorten(base_site, api_key, target_link):
        if base_site == "api.shareus.io":
            url = f'https://{base_site}/api'
            params = {"key": api_key, "link": target_link}
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params, raise_for_status=True, ssl=False) as response:
                    return await response.text()
        else:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                shortzy = Shortzy(api_key=api_key, base_site=base_site, session=session)
                return await shortzy.convert(target_link)

    async def notify_admin(error_msg, shortener_name):
        if client and LOG_CHANNEL:
            try:
                await client.send_message(
                    LOG_CHANNEL, 
                    f"⚠️ **Shortener Warning**\n"
                    f"Provider: `{shortener_name}`\n"
                    f"Error: `{error_msg}`\n"
                    f"Chat ID: `{chat_id}`"
                )
            except Exception as e:
                logger.error(f"Failed to send admin notification: {e}")

    # --- ATTEMPT 1: SHORT1 (Tried ONCE) ---
    try:
        return await _request_shorten(p_url, p_api, link)
    except Exception as e1:
        logger.warning(f"SHORT1 failed: {e1}")
        await notify_admin(str(e1), p_url)

        # --- ATTEMPT 2: Immediate Fallback to SHORT2 ---
        try:
            return await _request_shorten(s_url, s_api, link)
        except Exception as e2:
            logger.error(f"SHORT2 fallback also failed: {e2}")
            await notify_admin(str(e2), s_url)

            # All attempts failed, raise exception to trigger user notice
            raise Exception("All shorteners are down.")
    
async def get_tutorial(chat_id):
    return TUTORIAL
    
async def send_all(bot, userid, files, ident, chat_id, user_name, query):
    settings = await get_settings(chat_id)
    ENABLE_SHORTLINK = settings.get('is_shortlink', IS_SHORTLINK)
    try:
        if ENABLE_SHORTLINK:
            for file in files:
                title = file.file_name
                size = get_size(file.file_size)
                await bot.send_message(chat_id=userid, text=f"<b>Hᴇʏ ᴛʜᴇʀᴇ {user_name} 👋🏽 \n\n✅ Sᴇᴄᴜʀᴇ ʟɪɴᴋ ᴛᴏ ʏᴏᴜʀ ғɪʟᴇ ʜᴀs sᴜᴄᴄᴇssғᴜʟʟʏ ʙᴇᴇɴ ɢᴇɴᴇʀᴀᴛᴇᴅ ᴘʟᴇᴀsᴇ ᴄʟɪᴄᴋ ᴅᴏᴡɴʟᴏᴀᴅ ʙᴜᴛᴛᴏɴ\n\n🗃️ Fɪʟᴇ Nᴀᴍᴇ : {title}\n🔖 Fɪʟᴇ Sɪᴢᴇ : {size}</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📤 Dᴏᴡɴʟᴏᴀᴅ 📥", url=await get_shortlink(chat_id, f"https://telegram.me/{temp.U_NAME}?start=files_{file.file_id}"))]]))
        else:
            for file in files:
                    f_caption = file.caption
                    title = file.file_name
                    size = get_size(file.file_size)
                    if CUSTOM_FILE_CAPTION:
                        try:
                            f_caption = CUSTOM_FILE_CAPTION.format(file_name='' if title is None else title,
                                                                    file_size='' if size is None else size,
                                                                    file_caption='' if f_caption is None else f_caption)
                        except Exception as e:
                            print(e)
                            f_caption = f_caption
                    if f_caption is None:
                        f_caption = f"{title}"
                    await bot.send_cached_media(
                        chat_id=userid,
                        file_id=file.file_id,
                        caption=f_caption,
                        protect_content=True if ident == "filep" else False,
                        reply_markup=InlineKeyboardMarkup(
                            [
                                [
                                InlineKeyboardButton('Sᴜᴘᴘᴏʀᴛ Gʀᴏᴜᴘ', url=GRP_LNK),
                                InlineKeyboardButton('Uᴘᴅᴀᴛᴇs Cʜᴀɴɴᴇʟ', url=CHNL_LNK)
                            ],[
                                InlineKeyboardButton("Bᴏᴛ Oᴡɴᴇʀ", url="t.me/heroflix")
                                ]
                            ]
                        )
                    )
    except UserIsBlocked:
        await query.answer('Uɴʙʟᴏᴄᴋ ᴛʜᴇ ʙᴏᴛ ᴍᴀʜɴ !', show_alert=True)
    except PeerIdInvalid:
        await query.answer('Hᴇʏ, Sᴛᴀʀᴛ Bᴏᴛ Fɪʀsᴛ Aɴᴅ Cʟɪᴄᴋ Sᴇɴᴅ Aʟʟ', show_alert=True)
    except Exception as e:
        await query.answer('Hᴇʏ, Sᴛᴀʀᴛ Bᴏᴛ Fɪʀsᴛ Aɴᴅ Cʟɪᴄᴋ Sᴇɴᴅ Aʟʟ', show_alert=True)
    '''if IS_SHORTLINK == True:
        for file in files:
            title = file.file_name
            size = get_size(file.file_size)
            await bot.send_message(chat_id=userid, text=f"<b>Hᴇʏ ᴛʜᴇʀᴇ {user_name} 👋🏽 \n\n✅ Sᴇᴄᴜʀᴇ ʟɪɴᴋ ᴛᴏ ʏᴏᴜʀ ғɪʟᴇ ʜᴀs sᴜᴄᴄᴇssғᴜʟʟʏ ʙᴇᴇɴ ɢᴇɴᴇʀᴀᴛᴇᴅ ᴘʟᴇᴀsᴇ ᴄʟɪᴄᴋ ᴅᴏᴡɴʟᴏᴀᴅ ʙᴜᴛᴛᴏɴ\n\n🗃️ Fɪʟᴇ Nᴀᴍᴇ : {title}\n🔖 Fɪʟᴇ Sɪᴢᴇ : {size}</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📤 Dᴏᴡɴʟᴏᴀᴅ 📥", url=await get_shortlink(chat_id, f"https://telegram.me/{temp.U_NAME}?start=files_{file.file_id}"))]])
    )
    else:
        for file in files:
            f_caption = file.caption
            title = file.file_name
            size = get_size(file.file_size)
            if CUSTOM_FILE_CAPTION:
                try:
                    f_caption = CUSTOM_FILE_CAPTION.format(file_name='' if title is None else title,
                                                            file_size='' if size is None else size,
                                                            file_caption='' if f_caption is None else f_caption)
                except Exception as e:
                    print(e)
                    f_caption = f_caption
            if f_caption is None:
                f_caption = f"{title}"
            await bot.send_cached_media(
                chat_id=userid,
                file_id=file.file_id,
                caption=f_caption,
                protect_content=True if ident == "filep" else False,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                        InlineKeyboardButton('Sᴜᴘᴘᴏʀᴛ Gʀᴏᴜᴘ', url=GRP_LNK),
                        InlineKeyboardButton('Uᴘᴅᴀᴛᴇs Cʜᴀɴɴᴇʟ', url=CHNL_LNK)
                    ],[
                        InlineKeyboardButton("Bᴏᴛ Oᴡɴᴇʀ", url="t.me/heroflix")
                        ]
                    ]
                )
            )'''

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
