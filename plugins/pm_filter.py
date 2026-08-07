import asyncio, re, ast, math, random, pytz, logging
import time as _time
from datetime import datetime, timedelta, date, time
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto
from pyrogram.errors import FloodWait, UserIsBlocked, MessageNotModified, PeerIdInvalid
from html import escape
from Script import script
from info import *
from utils import get_size, search_gagala, temp
from database.users_chats_db import db
from database.connections_mdb import active_connection, all_connections, delete_connection, if_active, make_active, make_inactive
from database.ia_filterdb import Media, get_file_details, get_search_results, get_bad_files

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

SPELL_CHECK = {}
QUERY_CACHE = {}
lock = asyncio.Lock()

GLOBAL_SEM = asyncio.Semaphore(12)
USER_COOLDOWN = {}

REMOVES = [
    "in", "series", "4k", "kdrama", "ott", "movies", "webseries", "language", "hd", "hollywood", 
    "and", "&", "bollywood", "dub", "anime", "dubbed", "file", "download", "movie", "film", 
    "netflix", "link", "subtitles", "full movie", "korean drama", "web series", "tv series", 
    "television series", "tv show", "with subtitles"
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

async def handle_auto_delete(message_obj):
    try:
        await asyncio.sleep(900)
        await message_obj.delete()
    except Exception:
        pass

async def send_search_results(client, message, search, files, offset, total_results, req_user_id, edit_message=None):
    try:
        offset = int(offset)
    except (TypeError, ValueError):
        offset = 0

    cap = f"<b>🔆 Results For ➔ ‛{search}’👇\n\n</b>"
    for file in files:
        f_size = get_size(file.file_size)
        f_name = escape(file.file_name)
        cap += f"<b>🍿 <a href='https://telegram.me/{temp.U_NAME}?start=files_{file.file_id}'>[{f_size}] {f_name}</a></b>\n\n"

    cache_id = str(random.randint(10000, 99999))
    QUERY_CACHE[cache_id] = search

    current_page = math.floor(offset / 10) + 1
    total_pages = math.ceil(total_results / 10)

    btn = []
    if offset > 0:
        btn.append(InlineKeyboardButton("⏪ Back", callback_data=f"next_{cache_id}_{offset - 10}_{req_user_id}"))
        
    btn.append(InlineKeyboardButton(f"📁 Pages {current_page} / {total_pages}", callback_data="pages"))
    
    if offset + len(files) < total_results:
        btn.append(InlineKeyboardButton("Next ⏩", callback_data=f"next_{cache_id}_{offset + 10}_{req_user_id}"))

    reply_markup = InlineKeyboardMarkup([btn])

    if edit_message:
        try:
            await edit_message.edit_text(text=cap, disable_web_page_preview=True, reply_markup=reply_markup)
            sent_msg = edit_message
        except MessageNotModified:
            sent_msg = edit_message
    else:
        sent_msg = await message.reply_text(text=cap, disable_web_page_preview=True, reply_markup=reply_markup)
        asyncio.create_task(handle_auto_delete(sent_msg))
        if message:
            asyncio.create_task(handle_auto_delete(message))

    return sent_msg

@Client.on_message(filters.group & filters.text & filters.incoming)
async def give_filter(client, message):
    await auto_filter(client, message)

@Client.on_message(filters.private & filters.text & filters.incoming)
async def pm_text(bot, message):
    content = message.text
    if content.startswith("/") or content.startswith("#") or message.from_user.id in ADMINS:
        return
    await message.reply_text(
        text="<b>🌀 Unlimited Movies, Series, Anime\n🔆 New Releases Upload Same Day\n♻️ 24x7 Service 📆 Daily Updates\n🔗 No Ads or Links 📗 Direct Files</b>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🌟 Buy Premium", callback_data="buy_premium_start")]
        ]),
        parse_mode=enums.ParseMode.HTML
    )

@Client.on_callback_query(filters.regex(r"^spolling"))
async def advantage_spoll_choker(bot, query):
    if is_spam(query.from_user.id) or not query.from_user or not query.message:
        return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
    async with GLOBAL_SEM:
        try:
            _, user, movie_ = query.data.split('#')
            user = int(user)
        except:
            return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
        if user != 0 and query.from_user.id != user:
            return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
        if movie_ == "close_spellcheck":
            await query.message.delete()
            return await query.answer("Closed !")
        
        movies = SPELL_CHECK.get(query.message.reply_to_message.id if query.message.reply_to_message else 0)
        if not movies:
            await query.answer(script.OLD_ALRT_TXT.format(query.from_user.first_name), show_alert=True)
            try: await query.message.edit_text(text="❗Link Expired, Request Again ♻", disable_web_page_preview=True)
            except: pass
            return
        try: movie = movies[int(movie_)]
        except: return await query.answer("❗Invalid Option", show_alert=True)
        try: await query.answer("Checking, Please Wait ♻️\n\n[ Don't Spam – Just Wait! ]", show_alert=True)
        except: pass
        
        files, offset, total_results = await get_search_results(query.message.chat.id, movie, offset=0, filter=True)
        if files: 
            # Reusing the unified search results sender instead of duplicated code
            original_msg = query.message.reply_to_message if query.message.reply_to_message else query.message
            try: await query.message.delete()
            except: pass
            await send_search_results(bot, original_msg, movie, files, 0, total_results, query.from_user.id)
        else:
            try:
                msg = await query.message.edit_text(text=script.NO_RESULTS, disable_web_page_preview=True)
                await asyncio.sleep(30)
                await msg.delete()
            except: pass

@Client.on_callback_query(filters.regex(r"^next"))
async def next_page(bot, query):
    try:
        _, cache_id, offset, owner_id = query.data.split("_", 3)
    except ValueError:
        return await query.answer("Invalid query data.", show_alert=True)

    if owner_id != "0" and query.from_user.id != int(owner_id):
        return await query.answer("❌ This is not your search request! Please send your own query.", show_alert=True)

    try:
        offset = int(offset)
    except:
        offset = 0

    search = QUERY_CACHE.get(cache_id)
    if not search:
        return await query.answer("Search session expired. Please search again.", show_alert=True)

    files, _, total_results = await get_search_results(query.message.chat.id, search, offset=offset, filter=True)
    if not files:
        return await query.answer("No more files found !", show_alert=True)
    
    # Reusing the unified search results sender to update pagination buttons correctly
    await send_search_results(bot, None, search, files, offset, total_results, int(owner_id), edit_message=query.message)
    await query.answer()

@Client.on_callback_query()
async def cb_handler(client: Client, query: CallbackQuery):
    if query.data and query.data.startswith(("premium_", "buy_plan_", "prem_", "next_")): return
    user_id = query.from_user.id

    if query.data == "close_data":
        await query.message.delete()
        return await query.answer("Closed !")
    elif query.data == "pages":
        return await query.answer("You are on the page navigation.", show_alert=True)
    elif query.data.startswith("killfilesdq"):
        user_id = query.from_user.id
        chat_type = query.message.chat.type

        if chat_type != enums.ChatType.PRIVATE:
            try:
                st = await client.get_chat_member(query.message.chat.id, user_id)
                is_admin = st.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]
            except Exception:
                is_admin = False
        else:
            is_admin = str(user_id) in map(str, ADMINS)

        if not is_admin and str(user_id) not in map(str, ADMINS):
            return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)

        try: 
            _, keyword = query.data.split("#")
        except: 
            return await query.answer("Invalid query data.", show_alert=True)
        
        files, _ = await get_bad_files(keyword)
        await query.message.edit_text("<b>Deleting files...</b>", parse_mode=enums.ParseMode.HTML)
        
        deleted = 0
        async with lock:
            try:
                for file in files:
                    result = await Media.collection.delete_one({'_id': file.file_id})
                    if result.deleted_count: 
                        deleted += 1
            except Exception as e:
                logger.exception(e)
                return await query.message.edit_text(f'<b>Error: {e}</b>', parse_mode=enums.ParseMode.HTML)
                
        await query.message.edit_text(f"<b>Successfully deleted {deleted} files from database for your query {keyword}.</b>", parse_mode=enums.ParseMode.HTML)
        return await query.answer("Deletion completed!", show_alert=True)

async def auto_filter(client, msg, spoll=False, is_spellcheck=False):
    if not spoll:
        message = msg
        if message.text.startswith("/") or re.findall("((^\/|^,|^!|^\.|^[\U0001F900-\U000E007F]).*)", message.text) or len(message.text) >= 100:
            return
        search = remove_words(message.text.lower())
        search = re.sub(r"\b(complete|combined|all\s*episodes?|full\s*episodes?)\b", "com", search, flags=re.IGNORECASE)
        search = re.sub(r"[-:–]+", " ", search)
        search = re.sub(r"\s+", " ", search).strip()
        search = re.sub(r"(?:session|season)\s?(\d+)", lambda x: f"s{x.group(1).zfill(2)}", search, flags=re.IGNORECASE)
        search = re.sub(r"so(\d+)", lambda x: f"s{x.group(1).zfill(2)}", search, flags=re.IGNORECASE)
        for lang, code in [("english", "eng"), ("hindi", "hin"), ("tamil", "tam"), ("telugu", "tel"), ("kannada", "kan"), ("malayalam", "mal")]:
            search = search.replace(lang, code)
        
        offset = 0
        files, offset, total_results = await get_search_results(message.chat.id, search, offset=offset, filter=True)
        if not files:
            return await advantage_spell_chok(client, msg)
    else:
        message = msg.message.reply_to_message if hasattr(msg.message, 'reply_to_message') else msg.message
        search, files, offset, total_results = spoll
        try: await msg.message.delete()
        except: pass

    req_user_id = message.from_user.id if (message and message.from_user) else (msg.from_user.id if hasattr(msg, 'from_user') else 0)
    
    # Utilizing the unified helper function
    await send_search_results(client, message, search, files, offset, total_results, req_user_id)

async def advantage_spell_chok(client, msg):
    mv_rqst = msg.text
    reqstr1 = msg.from_user.id if msg.from_user else None
    if not reqstr1: 
        return
    try: 
        reqstr = await client.get_users(reqstr1)
    except: 
        return await msg.reply("❌ Unable to fetch user.")

    cleaned_query = re.sub(r"\s+", " ", remove_words(mv_rqst)).strip()
    query_raw = cleaned_query
    query_movie = f"{cleaned_query} movie"

    results_raw, results_movie = await asyncio.gather(
        search_gagala(query_raw),
        search_gagala(query_movie)
    )
    g_s = list(dict.fromkeys(results_raw + results_movie))

    if not g_s:
        k = await msg.reply(script.NO_RESULTS, disable_web_page_preview=True)
        await asyncio.sleep(30)
        await k.delete()
        return

    gs = list(filter(re.compile(r".*(imdb|wikipedia).*", re.IGNORECASE).search, g_s))
    gs_parsed = list(dict.fromkeys(filter(None, [re.sub(r'\b(imdb|wikipedia|reviews|full|all|episode(s)?|film|movie|tv\s*series|television\s*series|web\s*series|tv\s*show|show|series)\b|[\(\)\-]', ' ', i, flags=re.IGNORECASE).strip() for i in gs])))
    
    if not gs_parsed:
        for mv in g_s:
            match = re.compile(r"watch\s+([a-zA-Z0-9_\s\-\(\)]+)", re.IGNORECASE).search(mv)
            if match: 
                gs_parsed.append(match.group(1).strip())
                
    gs_parsed = list(dict.fromkeys(filter(None, gs_parsed)))[:6]
    
    movielist = list(dict.fromkeys(filter(None, [re.sub(r'(\-|\(|\)|_)', '', i, flags=re.IGNORECASE).strip() for i in gs_parsed])))
    if not movielist:
        k = await msg.reply(script.NO_RESULTS, disable_web_page_preview=True)
        await asyncio.sleep(30)
        await k.delete()
        return
        
    SPELL_CHECK[msg.id] = movielist
    btn = [[InlineKeyboardButton(text=movie, callback_data=f"spolling#{reqstr1}#{idx}")] for idx, movie in enumerate(movielist)]
    btn.append([InlineKeyboardButton("×××× ⟨ Close ⟩ ××××", callback_data=f"spolling#{reqstr1}#close_spellcheck")])
    
    k = await msg.reply("<b>🎬 Select Your Pick ↡</b>", reply_markup=InlineKeyboardMarkup(btn))
    await asyncio.sleep(30)
    await k.delete()
