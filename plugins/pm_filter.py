import asyncio
import logging
import math
import re
import time as _time
from html import escape

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import MessageNotModified

from Script import script
from info import *
from utils import get_size, is_subscribed, search_gagala, temp, get_settings, get_shortlink, connected_group
from database.ia_filterdb import Media, get_file_details, get_search_results, get_bad_files
from database.users_chats_db import db

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)


def tutorial_url():
    if not TUTORIAL:
        return None
    return TUTORIAL if str(TUTORIAL).startswith("http") else f"https://telegram.me/{TUTORIAL}"

GLOBAL_SEM = asyncio.Semaphore(12)
USER_COOLDOWN = {}
FRESH = {}
SPELL_CHECK = {}

REMOVES = [
    "in", "series", "4k", "kdrama", "ott", "movies", "webseries", "language", "hd",
    "hollywood", "and", "&", "bollywood", "dub", "anime", "dubbed", "file", "download",
    "movie", "film", "netflix", "link", "subtitles", "full movie", "korean drama",
    "web series", "tv series", "television series", "tv show", "with subtitles"
]


def remove_words(text):
    text = " ".join(text.split())
    for word in sorted(REMOVES, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(word)}\b", " ", text, flags=re.I)
    return " ".join(text.split())




async def connected_group_check(chat_id):
    try:
        return await db.is_group_connected(int(chat_id))
    except Exception:
        return False

def is_spam(uid, cooldown=2):
    now = _time.monotonic()
    last = USER_COOLDOWN.get(uid, 0)
    if now - last < cooldown:
        return True
    USER_COOLDOWN[uid] = now
    if len(USER_COOLDOWN) > 10000:
        cutoff = now - 60
        stale = [user_id for user_id, timestamp in USER_COOLDOWN.items() if timestamp < cutoff]
        for user_id in stale:
            USER_COOLDOWN.pop(user_id, None)
        if len(USER_COOLDOWN) > 10000:
            oldest = sorted(USER_COOLDOWN.items(), key=lambda item: item[1])[:1000]
            for user_id, _ in oldest:
                USER_COOLDOWN.pop(user_id, None)
    return False


async def _delete_later(message, seconds=900):
    await asyncio.sleep(seconds)
    try:
        await message.delete()
    except Exception:
        pass


async def _send_shortlink_message(client, user_id, file_id, chat_id):
    files = await get_file_details(file_id)
    if not files:
        return None
    file = files[0]
    title = " ".join(x for x in (file.file_name or "").split() if not x.startswith(("www.", "@")))
    try:
        short_url = await get_shortlink(
            chat_id,
            f"https://telegram.me/{temp.U_NAME}?start=file_{file_id}",
            client=client,
        )
    except Exception:
        return False

    msg = await client.send_message(
        chat_id=user_id,
        text=f"<b>[ {get_size(file.file_size)} ] {escape(title)}\n\n📗 Download Link ➔ {short_url}</b>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("♻️ Download Link ♻️", url=short_url)],
            [InlineKeyboardButton("❓ How To Download ❓", url=tutorial_url())],
        ]),
    )
    asyncio.create_task(_delete_later(msg))
    return True


@Client.on_message(filters.group & filters.text & filters.incoming & connected_group)
async def give_filter(client, message):
    if message.text.startswith("/"):
        return
    await auto_filter(client, message)


@Client.on_callback_query(filters.regex(r"^next"))
async def next_page(bot, query):
    if query.message and query.message.chat and query.message.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP) and not await connected_group_check(query.message.chat.id):
        return await query.answer("This group is disconnected.", show_alert=True)
    if is_spam(query.from_user.id):
        return

    async with GLOBAL_SEM:
        try:
            _, req, key, offset = query.data.split("_")
            req = int(req)
            offset = int(offset)
        except Exception:
            return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)

        if req not in (query.from_user.id, 0):
            return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)

        search = FRESH.get(key)
        if not search:
            return await query.answer(script.OLD_ALRT_TXT.format(query.from_user.first_name), show_alert=True)

        files, n_offset, total = await get_search_results(query.message.chat.id, search, offset=offset)
        if not files:
            return await query.answer(script.OLD_ALRT_TXT.format(query.from_user.first_name), show_alert=True)

        try:
            n_offset = int(n_offset)
        except Exception:
            n_offset = 0

        temp.GETALL[key] = files
        temp.SHORT[(query.from_user.id, query.message.chat.id)] = query.message.chat.id

        max_limit = 10
        btn = []
        try:
            curr_page = math.ceil(int(offset) / max_limit) + 1
            total_pages = math.ceil(total / max_limit)
            previous = None if offset == 0 else max(0, offset - max_limit)
            if n_offset == 0:
                btn.append([
                    InlineKeyboardButton("⏪ BACK", callback_data=f"next_{req}_{key}_{previous}"),
                    InlineKeyboardButton(f"{curr_page} / {total_pages}", callback_data="pages"),
                ])
            elif previous is None:
                btn.append([
                    InlineKeyboardButton("🔅 Page", callback_data="pages"),
                    InlineKeyboardButton(f"{curr_page} / {total_pages}", callback_data="pages"),
                    InlineKeyboardButton(" NEXT ⏩", callback_data=f"next_{req}_{key}_{n_offset}"),
                ])
            else:
                btn.append([
                    InlineKeyboardButton("⏪ BACK", callback_data=f"next_{req}_{key}_{previous}"),
                    InlineKeyboardButton(f"{curr_page} / {total_pages}", callback_data="pages"),
                    InlineKeyboardButton(" NEXT ⏩", callback_data=f"next_{req}_{key}_{n_offset}"),
                ])
        except Exception:
            pass

        tut = tutorial_url()
        if tut:
            btn.append([InlineKeyboardButton("❓ How To Download ❓", url=tut)])

        cap = f"<b>🔆 Results For ➔ ‛{escape(search)}’👇\n\n🎬 Select Your Pick ↡\n\n</b>"
        for file in files:
            title = " ".join(x for x in (file.file_name or "").split() if not x.startswith(("@", "www.")))
            cap += f"<b>🍿 <a href='https://telegram.me/{temp.U_NAME}?start=files_{file.file_id}'>[{get_size(file.file_size)}] {escape(title)}</a></b>\n\n"

        try:
            await query.message.edit_text(cap, reply_markup=InlineKeyboardMarkup(btn), disable_web_page_preview=True)
            await query.answer()
        except MessageNotModified:
            await query.answer()
        except Exception:
            await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)


@Client.on_callback_query(filters.regex(r"^spolling"))
async def advantage_spoll_choker(bot, query):
    if query.message and query.message.chat and query.message.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP) and not await connected_group_check(query.message.chat.id):
        return await query.answer("This group is disconnected.", show_alert=True)
    if is_spam(query.from_user.id) or not query.from_user or not query.message:
        return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)

    async with GLOBAL_SEM:
        try:
            _, user, movie_ = query.data.split('#')
            user = int(user)
        except Exception:
            return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)

        if user != 0 and query.from_user.id != user:
            return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)

        if movie_ == "close_spellcheck":
            await query.message.delete()
            return await query.answer("Closed !")

        movies = SPELL_CHECK.get(query.message.reply_to_message.id if query.message.reply_to_message else 0)
        if not movies:
            await query.answer(script.OLD_ALRT_TXT.format(query.from_user.first_name), show_alert=True)
            try:
                await query.message.edit_text("❗Link Expired, Request Again ♻", disable_web_page_preview=True)
            except Exception:
                pass
            return

        try:
            movie = movies[int(movie_)]
        except Exception:
            return await query.answer("❗Invalid Option", show_alert=True)

        await query.answer("Checking, Please Wait ♻️\n\n[ Don't Spam – Just Wait! ]", show_alert=True)
        files, offset, total_results = await get_search_results(query.message.chat.id, movie, offset=0)
        if files:
            await auto_filter(bot, query, (movie, files, offset, total_results))
        else:
            try:
                msg = await query.message.edit_text(script.NO_RESULTS, disable_web_page_preview=True)
                await asyncio.sleep(60)
                await msg.delete()
            except Exception:
                pass


@Client.on_callback_query()
async def cb_handler(client: Client, query: CallbackQuery):
    if not query.data:
        return
    if query.data.startswith(("premium_", "buy_plan_", "prem_")):
        return

    if query.data == "close_data":
        try:
            await query.message.delete()
        except Exception:
            pass
        return await query.answer("Closed !")

    if query.data == "pages":
        return await query.answer("You are on the page navigation.", show_alert=True)

    if query.data.startswith("file#"):
        if query.message and query.message.chat and query.message.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP) and not await connected_group_check(query.message.chat.id):
            return await query.answer("This group is disconnected.", show_alert=True)
        file_id = query.data.split("#", 1)[1]
        if not await _send_indexed_file(client, query.from_user.id, file_id):
            return await query.answer("No such file exist.", show_alert=True)
        return await query.answer("File sent to PM successfully!", show_alert=True)

    if query.data.startswith("killfilesdq"):
        if str(query.from_user.id) not in ADMINS:
            return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
        try:
            _, keyword = query.data.split("#", 1)
        except Exception:
            return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
        files, total = await get_bad_files(keyword)
        await query.message.edit_text("<b>File deletion process will start in 5 seconds !</b>")
        await asyncio.sleep(5)
        deleted = 0
        for file in files:
            try:
                result = await Media.collection.delete_one({'_id': file.file_id})
                deleted += result.deleted_count
            except Exception:
                logger.exception("Failed deleting %s", file.file_id)
        await query.message.edit_text(
            f"<b>Process Completed!\n\nSuccessfully deleted {deleted} files for {escape(keyword)}.</b>"
        )
        return await query.answer("Deletion process completed!", show_alert=True)


async def _send_indexed_file(client, user_id, file_id):
    files = await get_file_details(file_id)
    if not files:
        return False
    file = files[0]
    caption = file.file_name or ""
    if CUSTOM_FILE_CAPTION:
        try:
            caption = CUSTOM_FILE_CAPTION.format(
                file_name=file.file_name or "",
                file_size=get_size(file.file_size),
                file_caption="",
            )
        except Exception:
            caption = file.file_name or ""

    await client.send_cached_media(
        chat_id=user_id,
        file_id=file_id,
        caption=caption,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('🔆彡⟨ HEROFLiX ⟩彡🔆', url=f'https://telegram.me/{CHNL_LNK}')]
        ]),
    )
    return True


async def auto_filter(client, msg, spoll=False):
    if not spoll:
        message = msg
        if message.text.startswith("/") or re.findall(r"((^/|^,|^!|^\.|^[\U0001F900-\U000E007F]).*)", message.text) or len(message.text) >= 100:
            return
        search = remove_words(message.text.lower())
        search = re.sub(r"\b(complete|combined|all\s*episodes?|full\s*episodes?)\b", "com", search, flags=re.IGNORECASE)
        search = re.sub(r"[-:–]+", " ", search)
        search = re.sub(r"\s+", " ", search).strip()
        search = re.sub(r"(?:session|season)\s?(\d+)", lambda x: f"s{x.group(1).zfill(2)}", search, flags=re.IGNORECASE)
        search = re.sub(r"so(\d+)", lambda x: f"s{x.group(1).zfill(2)}", search, flags=re.IGNORECASE)
        for lang, code in [("english", "eng"), ("hindi", "hin"), ("tamil", "tam"), ("telugu", "tel"), ("kannada", "kan"), ("malayalam", "mal")]:
            search = search.replace(lang, code)
        files, offset, total_results = await get_search_results(message.chat.id, search, offset=0)
        settings = await get_settings(message.chat.id)
        if not files:
            if settings.get("spell_check", SPELL_CHECK_REPLY):
                return await advantage_spell_chok(client, msg)
            return
    else:
        message = msg.message.reply_to_message
        search, files, offset, total_results = spoll
        settings = await get_settings(message.chat.id)
        try:
            await msg.message.delete()
        except Exception:
            pass

    key = f"{message.chat.id}-{message.id}"
    FRESH[key] = search
    temp.GETALL[key] = files
    if not hasattr(temp, "SHORT"):
        temp.SHORT = {}
    temp.SHORT[(message.from_user.id, message.chat.id)] = message.chat.id

    btn = []
    if offset != "":
        req = message.from_user.id if message.from_user else 0
        try:
            total_pages = math.ceil(int(total_results) / 10)
            btn.append([
                InlineKeyboardButton("🔅 Page", callback_data="pages"),
                InlineKeyboardButton(text=f"1/{total_pages}", callback_data="pages"),
                InlineKeyboardButton(text=" NEXT ⏩", callback_data=f"next_{req}_{key}_{offset}"),
            ])
        except Exception:
            pass
    else:
        btn.append([InlineKeyboardButton("✦ ────「 The End 」──── ✦", callback_data="pages")])

    tut = tutorial_url()
    if tut:
        btn.append([InlineKeyboardButton("❓ How To Download ❓", url=tut)])

    cap = f"<b>🔆 Results For ➔ ‛{escape(search)}’👇\n\n🎬 Select Your Pick ↡\n\n</b>"
    for file in files:
        title = " ".join(x for x in (file.file_name or "").split() if not x.startswith(("@", "www.")))
        cap += f"<b>🍿 <a href='https://telegram.me/{temp.U_NAME}?start=files_{file.file_id}'>[{get_size(file.file_size)}] {escape(title)}</a></b>\n\n"

    sent = await message.reply_text(cap, reply_markup=InlineKeyboardMarkup(btn), disable_web_page_preview=True)
    asyncio.create_task(_delete_later(sent))
    asyncio.create_task(_delete_later(message))


async def advantage_spell_chok(client, msg):
    mv_rqst = msg.text
    reqstr1 = msg.from_user.id if msg.from_user else None
    if not reqstr1:
        return
    try:
        reqstr = await client.get_users(reqstr1)
    except Exception:
        return await msg.reply("❌ Unable to fetch user.")

    query = re.sub(r"\s+", " ", remove_words(mv_rqst)).strip() + "movie"
    # Keep the existing DuckDuckGo spell-check implementation unchanged.
    g_s = await search_gagala(query) + await search_gagala(msg.text)

    if not g_s:
        if NO_RESULTS_MSG:
            await client.send_message(chat_id=LOG_CHANNEL, text=script.NORSLTS.format(reqstr.id, reqstr.mention, mv_rqst))
        k = await msg.reply(script.NO_RESULTS, disable_web_page_preview=True)
        await asyncio.sleep(60)
        return await k.delete()

    gs = list(filter(re.compile(r".*(imdb|wikipedia).*", re.IGNORECASE).search, g_s))
    gs_parsed = list(dict.fromkeys(filter(None, [
        re.sub(r'\b(imdb|wikipedia|reviews|full|all|episode(s)?|film|movie|tv\s*series|television\s*series|web\s*series|tv\s*show|show|series)\b|[\(\)\-]', ' ', i, flags=re.IGNORECASE).strip()
        for i in gs
    ])))

    if not gs_parsed:
        for mv in g_s:
            match = re.compile(r"watch\s+([a-zA-Z0-9_\s\-\(\)]+)", re.IGNORECASE).search(mv)
            if match:
                gs_parsed.append(match.group(1).strip())

    gs_parsed = list(dict.fromkeys(filter(None, gs_parsed)))[:3]
    movielist = list(dict.fromkeys(filter(None, [re.sub(r'(\-|\(|\)|_)', '', i, flags=re.IGNORECASE).strip() for i in gs_parsed])))

    if not movielist:
        if NO_RESULTS_MSG:
            await client.send_message(chat_id=LOG_CHANNEL, text=script.NORSLTS.format(reqstr.id, reqstr.mention, mv_rqst))
        k = await msg.reply(script.NO_RESULTS, disable_web_page_preview=True)
        await asyncio.sleep(60)
        return await k.delete()

    SPELL_CHECK[msg.id] = movielist
    btn = [[InlineKeyboardButton(text=movie, callback_data=f"spolling#{reqstr1}#{idx}")] for idx, movie in enumerate(movielist)]
    btn.append([InlineKeyboardButton("×××× ⟨ Close ⟩ ××××", callback_data="close_data")])
    k = await msg.reply("<b>🎬 Select Your Pick ↡</b>", reply_markup=InlineKeyboardMarkup(btn))
    await asyncio.sleep(30)
    try:
        await k.delete()
    except Exception:
        pass
