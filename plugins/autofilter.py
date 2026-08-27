import asyncio
import logging
import math
import re
import time as _time
from html import escape
from pyrogram import Client, enums, filters
from pyrogram.errors import MessageNotModified
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from database.ia_filterdb import Media, get_bad_files, get_file_details, get_search_results
from database.users_chats_db import db
from info import *
from utils import get_settings, get_shortlink, get_size, is_group_connected, is_subscribed, search_gagala, temp

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)
lock = asyncio.Lock()
SPELL_CHECK = {}
GLOBAL_SEM = asyncio.Semaphore(12)
USER_COOLDOWN = {}

EXPIRED = '♻ Link Expired, Please Request in Group Again!'
ALRT_TXT = '🔒 This option belongs to another user. '
REMOVES = [
    "in", "series", "4k", "kdrama", "ott", 
    "movies", "webseries", "language", "hd", "hollywood", 
    "and", "&", "bollywood", "dub", "anime",
    "dubbed", "file", "download", "movie", "film",
    "netflix", "link", "subtitles", "dubbing",
    "full movie", "korean drama", "web series", "k drama",
    "tv series", "television series", "tv show", "with subtitles"
]

def remove_words(text):
    text = " ".join(text.split())
    for x in sorted(REMOVES, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(x)}\b", " ", text, flags=re.I)
    return " ".join(text.split())

def is_spam(uid, cooldown=2):
    now = _time.monotonic()
    last = USER_COOLDOWN.get(uid, 0)
    if now - last < cooldown:
        return True
    USER_COOLDOWN[uid] = now
    return False

async def get_result_buttons(chat_id, req_user_id, cache_id, offset, next_offset, total_results):
    max_results = 10
    current_page = (offset // max_results) + 1
    total_pages = max(1, math.ceil(total_results / max_results))

    btn = []

    if offset > 0:
        btn.append(
            InlineKeyboardButton(
                "⏪ Back",
                callback_data=f"next_{cache_id}_{offset - max_results}_{req_user_id}"
            )
        )

    btn.append(
        InlineKeyboardButton(
            f"📒 Pages {current_page} / {total_pages}",
            callback_data="pages"
        )
    )

    if offset + max_results < total_results:
        btn.append(
            InlineKeyboardButton(
                "Next ⏩",
                callback_data=f"next_{cache_id}_{offset + max_results}_{req_user_id}"
            )
        )

    settings = await get_settings(chat_id)

    if settings.get("is_shortlink", IS_SHORTLINK):
        return [
            btn,
            [
                InlineKeyboardButton(
                    "❓ How To Download ❓",
                    url=f"https://telegram.me/{TUTORIAL}"
                )
            ]
        ]

    return [btn]

def build_results_caption(search, files):
    cap = (
        f"<b>🔆 Results For ➔ ‛{escape(search)}’👇\n\n"
        f"🎬 Select Your Pick ↡\n\n"
    )

    for file in files:
        title = file.file_name or ""
        cap += (
            f"🍿 <a href=\"https://telegram.me/{temp.U_NAME}"
            f"?start=files_{file.file_id}\">"
            f"[{get_size(file.file_size)}] {escape(title)}</a>\n\n"
        )

    cap += "</b>"
    return cap

async def store_file_links(chat_id, files):
    for file in files:
        await db.set_cache(
            f"file:{file.file_id}",
            {"chat_id": chat_id},
            ttl=660,
        )

async def store_pagination(key, chat_id, search, user_id):
    await db.set_cache(
        f"pagination:{key}",
        {
            "chat_id": chat_id,
            "search": search,
        },
        ttl=660,
    )

async def handle_auto_delete(message_obj):
    try:
        await asyncio.sleep(600)
        await message_obj.delete()
    except Exception:
        pass

@Client.on_message(
    filters.group
    & filters.text
    & filters.incoming
    & ~filters.regex(r"^/")
)
async def give_filter(client, message):

    try:
        connected = await db.is_group_connected(message.chat.id)
    except Exception:
        logger.exception("Failed to check connected status for group %s", message.chat.id)
        return

    if not connected:
        return

    await auto_filter(client, message)

@Client.on_callback_query(filters.regex(r"^next_"))
async def next_page(bot, query):
    if not query.message or query.message.chat.type not in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
        return await query.answer(ALRT_TXT, show_alert=True)
    if not await db.is_group_connected(query.message.chat.id):
        return await query.answer("This group is not connected.", show_alert=True)
    if is_spam(query.from_user.id):
        return

    async with GLOBAL_SEM:
        try:
            _, key, offset, req = query.data.split("_")
            offset = int(offset)
            req = int(req)
        except Exception:
            return await query.answer(ALRT_TXT, show_alert=True)

        if req not in (query.from_user.id, 0):
            return await query.answer(ALRT_TXT, show_alert=True)

        cache = await db.get_cache(f"pagination:{key}")
        if not cache:
            return await query.answer(EXPIRED, show_alert=True)

        search = cache.get("search")
        if not search:
            return await query.answer(EXPIRED, show_alert=True)

        files, next_offset, total = await get_search_results(
            query.message.chat.id, search, offset=offset
        )
        if not files:
            return await query.answer(EXPIRED, show_alert=True)

        buttons = await get_result_buttons(
            query.message.chat.id, req, key, offset, next_offset, total
        )
        await store_file_links(query.message.chat.id, files)
        cap = build_results_caption(search, files)

        try:
            await query.message.edit_text(
                cap,
                reply_markup=InlineKeyboardMarkup(buttons),
                disable_web_page_preview=True,
            )
            await query.answer()
        except MessageNotModified:
            await query.answer()
        except Exception:
            await query.answer(ALRT_TXT, show_alert=True)

@Client.on_callback_query(filters.regex(r"^spolling"))
async def advantage_spoll_choker(bot, query):
    if not query.from_user or not query.message:
        return await query.answer(ALRT_TXT, show_alert=True)
    if query.message.chat.type not in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
        return await query.answer(ALRT_TXT, show_alert=True)
    if not await db.is_group_connected(query.message.chat.id):
        return await query.answer("This group is not connected.", show_alert=True)
    if is_spam(query.from_user.id):
        return

    async with GLOBAL_SEM:
        try:
            _, user, movie_ = query.data.split('#')
            user = int(user)
        except:
            return await query.answer(ALRT_TXT, show_alert=True)

        if user != 0 and query.from_user.id != user:
            return await query.answer(ALRT_TXT, show_alert=True)

        if movie_ == "close":
            await query.message.delete()
            return await query.answer()

        movies = SPELL_CHECK.get(query.message.reply_to_message.id if query.message.reply_to_message else 0)
        if not movies:
            await query.answer(EXPIRED, show_alert=True)
            try:
                await query.message.edit_text(text="❗Link Expired, Request Again ♻", disable_web_page_preview=True)
            except:
                pass
            return

        try:
            movie = movies[int(movie_)]
        except:
            return await query.answer("❗Invalid Option", show_alert=True)

        files, offset, total_results = await get_search_results(
            query.message.chat.id, movie, offset=0
        )
        if files:
            await auto_filter(bot, query, (movie, files, offset, total_results))
        else:
            try:
                msg = await query.message.edit_text(text=NO_RESULTS, disable_web_page_preview=True)
                await asyncio.sleep(60)
                await msg.delete()
            except Exception:
                pass

@Client.on_callback_query(filters.regex(r"^(close_data|pages|killfilesdq#)"))
async def cb_handler(client, query):
    if query.data == "close_data":
        try:
            await query.message.delete()
        except Exception:
            pass
        return await query.answer("Closed!")

    if query.data.startswith("killfilesdq"):
        user_id = query.from_user.id
        if query.message.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
            member = await client.get_chat_member(query.message.chat.id, user_id)
            if member.status not in (
                enums.ChatMemberStatus.ADMINISTRATOR,
                enums.ChatMemberStatus.OWNER,
            ) and str(user_id) not in ADMINS:
                return await query.answer(ALRT_TXT, show_alert=True)

        try:
            _, keyword = query.data.split("#", 1)
        except ValueError:
            return await query.answer(ALRT_TXT, show_alert=True)

        files, _ = await get_bad_files(keyword)
        await query.message.edit_text("<b>File deletion process will start in 5 seconds!</b>")
        await asyncio.sleep(5)

        deleted = 0
        async with lock:
            for file in files:
                result = await Media.collection.delete_one({"_id": file.file_id})
                if result.deleted_count:
                    deleted += 1

        await query.message.edit_text(
            f"<b>Process completed! Successfully deleted {deleted} files for: {escape(keyword)}</b>"
        )
        return await query.answer("Deletion completed.", show_alert=True)

async def auto_filter(client, msg, spoll=False):
    if not spoll:
        message = msg
        if (
            message.text.startswith("/")
            or re.findall(r"((^/|^,|^!|^\.|^[\U0001F900-\U000E007F]).*)", message.text)
            or len(message.text) >= 100
        ):
            return

        search = remove_words(message.text.lower())
        search = re.sub(
            r"\b(complete|combined|all\s*episodes?|full\s*episodes?)\b",
            "com",
            search,
            flags=re.IGNORECASE,
        )
        search = re.sub(r"[-:–]+", " ", search)
        search = re.sub(r"\s+", " ", search).strip()
        search = re.sub(
            r"(?:(?:session|season)\s?)(\d+)",
            lambda x: f"s{x.group(1).zfill(2)}",
            search,
            flags=re.IGNORECASE,
        )
        search = re.sub(
            r"so(\d+)",
            lambda x: f"s{x.group(1).zfill(2)}",
            search,
            flags=re.IGNORECASE,
        )

        for lang, code in [
            ("english", "eng"), ("hindi", "hin"), ("tamil", "tam"),
            ("telugu", "tel"), ("kannada", "kan"), ("malayalam", "mal"),
        ]:
            search = search.replace(lang, code)

        if not search.strip():
            k = await message.reply_text(
                NO_RESULTS,
                disable_web_page_preview=True
            )
            await asyncio.sleep(60)
            await k.delete()
            return

        files, offset, total_results = await get_search_results(
            message.chat.id, search, offset=0
        )
        if not files:
            settings = await get_settings(message.chat.id)
            if settings.get("spell_check", False):
                return await advantage_spell_chok(client, msg)
            return
    else:
        message = msg.message.reply_to_message
        if not message:
            return await msg.answer(EXPIRED, show_alert=True)
        search, files, offset, total_results = spoll
        try:
            await msg.message.delete()
        except Exception:
            pass

    key = f"{message.chat.id}-{message.id}"
    req = message.from_user.id if message.from_user else 0
    await store_pagination(key, message.chat.id, search, req)
    buttons = await get_result_buttons(
        message.chat.id, req, key, 0, offset, total_results
    )
    await store_file_links(message.chat.id, files)
    cap = build_results_caption(search, files)

    result = await message.reply_text(
        cap,
        reply_markup=InlineKeyboardMarkup(buttons),
        disable_web_page_preview=True,
    )
    asyncio.create_task(handle_auto_delete(result))
    asyncio.create_task(handle_auto_delete(message))

async def advantage_spell_chok(client, msg):
    mv_rqst = msg.text
    reqstr1 = msg.from_user.id if msg.from_user else None
    if not reqstr1: return
    try: reqstr = await client.get_users(reqstr1)
    except: return await msg.reply("❌ Unable to fetch user.")

    query = re.sub(r"\s+", " ", remove_words(mv_rqst)).strip() + "movie"
    g_s = await search_gagala(query) + await search_gagala(msg.text)

    if not g_s:
        k = await msg.reply(NO_RESULTS, disable_web_page_preview=True)
        await asyncio.sleep(60)
        return await k.delete()

    gs = list(filter(re.compile(r".*(imdb|wikipedia).*", re.IGNORECASE).search, g_s))
    gs_parsed = list(dict.fromkeys(filter(None, [re.sub(r'\b(imdb|wikipedia|reviews|full|all|episode(s)?|film|movie|tv\s*series|television\s*series|web\s*series|tv\s*show|show|series)\b|[\(\)\-]', ' ', i, flags=re.IGNORECASE).strip() for i in gs])))

    if not gs_parsed:
        for mv in g_s:
            match = re.compile(r"watch\s+([a-zA-Z0-9_\s\-\(\)]+)", re.IGNORECASE).search(mv)
            if match: gs_parsed.append(match.group(1).strip())
    gs_parsed = list(dict.fromkeys(filter(None, gs_parsed)))[:3]

    movielist = list(dict.fromkeys(filter(None, [re.sub(r'(\-|\(|\)|_)', '', i, flags=re.IGNORECASE).strip() for i in gs_parsed])))
    if not movielist:
        k = await msg.reply(NO_RESULTS, disable_web_page_preview=True)
        await asyncio.sleep(60)
        return await k.delete()

    SPELL_CHECK[msg.id] = movielist
    btn = [[InlineKeyboardButton(text=movie, callback_data=f"spolling#{reqstr1}#{idx}")] for idx, movie in enumerate(movielist)]
    btn.append([InlineKeyboardButton("×××× ⟨ Close ⟩ ××××", callback_data=f"spolling#{reqstr1}#close")])
    k = await msg.reply("<b>🎬 Select Your Pick ↡</b>", reply_markup=InlineKeyboardMarkup(btn))
    await asyncio.sleep(60)
    await k.delete()
    SPELL_CHECK.pop(msg.id, None)

async def send_file_to_user(client, user_id, file_id):
    files = await get_file_details(file_id)
    if not files:
        return False
    file = files[0]
    title = " ".join(x for x in (file.file_name or "").split() if not x.startswith(("www.", "@")))
    caption = title
    if CAPTION:
        try:
            caption = CAPTION.format(
                file_name=title,
                file_size=get_size(file.file_size),
                file_caption="",
            )
        except Exception:
            caption = title

    await client.send_cached_media(
        chat_id=user_id,
        file_id=file_id,
        caption=caption,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('🔆彡⟨ HEROFLiX ⟩彡🔆', url=f'https://telegram.me/{CHNL_LNK}')]
        ]),
    )
    return True

async def send_shortlink_page(client, user_id, file_id, chat_id):
    files = await get_file_details(file_id)
    if not files:
        return False
    file = files[0]
    title = " ".join(x for x in (file.file_name or "").split() if not x.startswith(("www.", "@")))

    try:
        short_url = await get_shortlink(
            chat_id,
            f"https://telegram.me/{temp.U_NAME}?start=file_{file_id}",
            client=client,
        )
    except Exception:
        logger.exception("Shortlink generation failed for %s", file_id)
        return None

    msg = await client.send_message(
        chat_id=user_id,
        text=f'<b>🔆 [ {get_size(file.file_size)} ] <a href="https://telegram.me/{CHNL_LNK}">{title}</a>\n\n📥 Download Link↓\n{short_url}</b>',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("♻️ Download Link ♻️", url=short_url)],
            [InlineKeyboardButton("❓ How To Download ❓", url=tutorial_url())],
        ]),
    )
    asyncio.create_task(delete_later(msg))
    return True

async def delete_later(message, seconds=600):
    await asyncio.sleep(seconds)
    try:
        await message.delete()
    except Exception:
        pass

@Client.on_message(filters.command("start") & filters.incoming)
async def start(client, message):

    # Group / supergroup
    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        if not await is_group_connected(message.chat.id):
            return

        buttons = [[
            InlineKeyboardButton(
                "❓How To Use Me❓",
                url=f"https://telegram.me/{TUTORIAL}"
            )
        ]]

        return await message.reply(
            START_TXT.format(
                message.from_user.mention if message.from_user else message.chat.title,
                temp.U_NAME,
                temp.B_NAME,
            ),
            reply_markup=InlineKeyboardMarkup(buttons),
            disable_web_page_preview=True,
        )

    # Private
    if not message.from_user:
        return

    ban_status = await db.get_ban_status(message.from_user.id)
    if ban_status.get("is_banned"):
        return await message.reply_text(
            f'Sorry Dude, You are Banned to use Me.\n'
            f'Ban Reason: {ban_status.get("ban_reason", "No Reason")}'
        )

    if not await db.is_user_exist(message.from_user.id):
        await db.add_user(
            message.from_user.id,
            message.from_user.first_name
        )
        try:
            await client.send_message(
                LOG_CHANNEL,
                LOG_TEXT_P.format(
                    message.from_user.id,
                    message.from_user.mention
                )
            )
        except Exception:
            pass

    # Common start buttons
    start_buttons = [
        [
            InlineKeyboardButton(
                "🌟 Paid (No Ads)",
                url="https://telegram.me/HeroFlixx/49"
            ),
            InlineKeyboardButton(
                "🍿 Free (With Ads)",
                url="https://telegram.me/addlist/X5k2lnJLIGAyZjQ1"
            )
        ],
        [
            InlineKeyboardButton(
                "👤 Admin",
                url=f"https://telegram.me/{SUPPORT_CHAT}"
            ),
            InlineKeyboardButton(
                "⚜ Updates",
                url=FORCE
            )
        ]
    ]

    # Plain /start
    if len(message.command) != 2:
        return await message.reply_photo(
            photo=PICS,
            caption=START_TXT.format(
                message.from_user.mention,
                temp.U_NAME,
                temp.B_NAME
            ),
            reply_markup=InlineKeyboardMarkup(start_buttons),
            parse_mode=enums.ParseMode.HTML,
        )

    # Force subscription
    if AUTH_CHANNEL and not await is_subscribed(client, message):
        payload = message.text.split(" ", 1)[1] if " " in message.text else "subscribe"
        retry = f"https://telegram.me/{temp.U_NAME}?start={payload}"

        return await client.send_message(
            message.from_user.id,
            "**🔆 First Join Our Main Channel & Click Try Again ♻**",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏮 Main Channel ⟨Click Here⟩ 🏮", url=FORCE)],
                [InlineKeyboardButton("🔄 Try Again", url=retry)],
            ]),
            parse_mode=enums.ParseMode.MARKDOWN,
        )

    data = message.command[1]

    # Non-file start payloads
    if data in {"subscribe", "error", "okay", "help"}:
        return await message.reply_photo(
            photo=PICS,
            caption=START_TXT.format(
                message.from_user.mention,
                temp.U_NAME,
                temp.B_NAME
            ),
            reply_markup=InlineKeyboardMarkup(start_buttons),
            parse_mode=enums.ParseMode.HTML,
        )

    # File / shortlink payload
    if "_" in data:
        pre, payload = data.split("_", 1)
    else:
        pre, payload = "file", data

    if pre not in {"file", "files", "short"}:
        return

    if pre in {"short", "files"}:
        file_id = payload

        cache = await db.get_cache(f"file:{file_id}")
        if not cache:
            return await message.reply_text(
                "<b>Link Expired, Search Again in Group!</b>"
            )

        chat_id = cache.get("chat_id")
        if chat_id is None:
            return await message.reply_text(
                "<b>Link Expired, Search Again in Group!</b>"
            )

        settings = await get_settings(chat_id)

        if settings.get("is_shortlink", IS_SHORTLINK):
            result = await send_shortlink_page(
                client,
                message.from_user.id,
                file_id,
                chat_id
            )

            if result is None:
                return await message.reply(
                    "❌ Link generation failed. Please try again later."
                )

            if result is False:
                return await message.reply(
                    "No such file exist."
                )

            return

        if not await send_file_to_user(
            client,
            message.from_user.id,
            file_id
        ):
            await message.reply("No such file exist.")

        return
