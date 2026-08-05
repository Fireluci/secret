import asyncio, re, ast, math, random, pytz, logging
import time as _time
from datetime import datetime, timedelta, date, time
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto
from pyrogram.errors import FloodWait, UserIsBlocked, MessageNotModified, PeerIdInvalid
from pyrogram.errors.exceptions.bad_request_400 import MediaEmpty, PhotoInvalidDimensions, WebpageMediaEmpty
from html import escape
from Script import script
from info import *
from utils import get_size, is_subscribed, search_gagala, temp, get_settings, save_group_settings, get_shortlink, get_tutorial, send_all
from database.users_chats_db import db
from database.connections_mdb import active_connection, all_connections, delete_connection, if_active, make_active, make_inactive
from database.ia_filterdb import Media, get_file_details, get_search_results, get_bad_files
from database.filters_mdb import del_all, find_filter, get_filters

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

lock = asyncio.Lock()

BUTTON = {}
BUTTONS = {}
FRESH = {}
SPELL_CHECK = {}

GLOBAL_SEM = asyncio.Semaphore(12)
USER_COOLDOWN = {}

REMOVES = [
    "in", "series", "4k", "kdrama", "ott", 
    "movies", "webseries", "language", "hd", "hollywood", 
    "and", "&", "bollywood", "dub", "anime",
    "dubbed", "file", "download", "movie", "film",
    "netflix", "link", "subtitles",
    "full movie", "korean drama", "web series",
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

async def handle_auto_delete(message_obj, settings):
    try:
        # 🔑 Ensure it checks if auto_delete is explicitly True for this group
        if settings.get('auto_delete') is True:
            await asyncio.sleep(900)  # 15 minutes / 900 seconds
            await message_obj.delete()
    except Exception:
        pass

@Client.on_message(filters.group & filters.text & filters.incoming)
async def give_filter(client, message):
    if not await manual_filters(client, message):
        await auto_filter(client, message)

@Client.on_message(filters.private & filters.text & filters.incoming)
async def pm_text(bot, message):
    content = message.text
    if content.startswith("/") or content.startswith("#") or content.startswith("file") or content.startswith("short") or message.from_user.id in ADMINS:
        return
    await message.reply_text(
        text="<b>🌀 Unlimited Movies, Series, Anime\n🔆 New Releases Upload Same Day\n♻️ 24x7 Service 📆 Daily Updates</b>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🌟 Paid (No Ads)", url="https://telegram.me/HeroFlixx/49"), InlineKeyboardButton("🍿 Free (With Ads)", url="https://telegram.me/addlist/X5k2lnJLIGAyZjQ1")]])
    )

@Client.on_callback_query(filters.regex(r"^next"))
async def next_page(bot, query):
    if is_spam(query.from_user.id):
        return

    async with GLOBAL_SEM:
        try:
            ident, req, key, offset = query.data.split("_")
            req = int(req)
            offset = int(offset)
        except:
            return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)

        if req not in [query.from_user.id, 0]:
            return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)

        search = BUTTONS.get(key) or FRESH.get(key)
        if len(BUTTONS) > 5000: BUTTONS.clear()
        if len(FRESH) > 5000: FRESH.clear()
        if len(SPELL_CHECK) > 2000: SPELL_CHECK.clear()
        if len(temp.GETALL) > 500: temp.GETALL.clear()

        if not search:
            return await query.answer(script.OLD_ALRT_TXT.format(query.from_user.first_name), show_alert=True)

        files, n_offset, total = await get_search_results(query.message.chat.id, search, offset=offset, filter=True)
        try:
            n_offset = int(n_offset)
        except:
            n_offset = 0

        if not files:
            return await query.answer(script.OLD_ALRT_TXT.format(query.from_user.first_name), show_alert=True)

        temp.GETALL[key] = files
        temp.SHORT[query.from_user.id] = query.message.chat.id
        settings = await get_settings(query.message.chat.id)
        pre = 'filep' if settings.get('file_secure') else 'file'

        btn = [[InlineKeyboardButton(text=f"[{get_size(file.file_size)}] {file.file_name}", callback_data=f'{pre}#{file.file_id}')] for file in files] if settings.get('button') else []

        try:
            max_limit = 10 if settings.get('max_btn') else int(MAX_B_TN)
            if 0 < offset <= max_limit:
                off_set = 0
            elif offset == 0:
                off_set = None
            else:
                off_set = offset - max_limit

            curr_page = math.ceil(int(offset) / max_limit) + 1
            total_pages = math.ceil(total / max_limit)

            if n_offset == 0:
                btn.append([InlineKeyboardButton("⏪ BACK", callback_data=f"next_{req}_{key}_{off_set}"), InlineKeyboardButton(f"{curr_page} / {total_pages}", callback_data="pages")])
            elif off_set is None:
                btn.append([InlineKeyboardButton("🔅 Page", callback_data="pages"), InlineKeyboardButton(f"{curr_page} / {total_pages}", callback_data="pages"), InlineKeyboardButton(" NEXT ⏩", callback_data=f"next_{req}_{key}_{n_offset}")])
            else:
                btn.append([InlineKeyboardButton("⏪ BACK", callback_data=f"next_{req}_{key}_{off_set}"), InlineKeyboardButton(f"{curr_page} / {total_pages}", callback_data="pages"), InlineKeyboardButton(" NEXT ⏩", callback_data=f"next_{req}_{key}_{n_offset}")])
        except KeyError:
            pass

        if TUTORIAL:
            tut_url = TUTORIAL if TUTORIAL.startswith("http") else f"https://telegram.me/{TUTORIAL}"
            btn.append([InlineKeyboardButton("🌟 How To Download ❓", url=tut_url)])

        cap = f"<b>🔆 Results For ➔ ‛{search}’👇\n\n<i>🗨 Choose Link - Press Start ↷</i>\n\n</b>"
        if not settings.get('button'):
            for file in files:
                cap += f"<b>🍿 <a href='https://telegram.me/{temp.U_NAME}?start=files_{file.file_id}'>[{get_size(file.file_size)}] {' '.join(filter(lambda x: not x.startswith('@') and not x.startswith('www.'), file.file_name.split()))}\n\n</a></b>"

        try:
            await query.message.edit_text(text=cap, reply_markup=InlineKeyboardMarkup(btn), disable_web_page_preview=True)
            await query.answer()
        except MessageNotModified:
            await query.answer()
        except Exception:
            await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)

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
            try:
                await query.message.edit_text(text="❗Link Expired, Request Again ♻", disable_web_page_preview=True)
            except:
                pass
            return

        try:
            movie = movies[int(movie_)]
        except:
            return await query.answer("❗Invalid Option", show_alert=True)

        try:
            await query.answer("Checking, Please Wait ♻️\n\n[ Don't Spam – Just Wait! ]", show_alert=True)
        except:
            pass

        if await manual_filters(bot, query.message, text=movie) is False:
            files, offset, total_results = await get_search_results(query.message.chat.id, movie, offset=0, filter=True)
            if files:
                await auto_filter(bot, query, (movie, files, offset, total_results))
            else:
                try:
                    msg = await query.message.edit_text(text=script.NO_RESULTS, disable_web_page_preview=True)
                    await asyncio.sleep(60)
                    await msg.delete()
                except:
                    pass

@Client.on_callback_query()
async def cb_handler(client: Client, query: CallbackQuery):
    if query.data and query.data.startswith(("premium_", "buy_plan_", "prem_")):
        return

    user_id = query.from_user.id
    chat_type = query.message.chat.type

    if query.data == "close_data":
        await query.message.delete()
        return await query.answer("Closed !")
    elif query.data == "gfiltersdeleteallconfirm":
        await del_allg(query.message, 'gfilters')
        return await query.answer("Done !", show_alert=True)
    elif query.data == "gfiltersdeleteallcancel":
        try:
            await query.message.reply_to_message.delete()
        except:
            pass
        await query.message.delete()
        return await query.answer("Process Cancelled !", show_alert=True)
    elif query.data == "delallconfirm":
        if chat_type == enums.ChatType.PRIVATE:
            grpid = await active_connection(str(user_id))
            if grpid is not None:
                try:
                    chat = await client.get_chat(grpid)
                    title, grp_id = chat.title, grpid
                except:
                    await query.message.edit_text("Mᴀᴋᴇ sᴜʀᴇ I'ᴍ ᴘʀᴇsᴇɴᴛ ɪɴ ʏᴏᴜʀ ɢʀᴏᴜᴘ!!", quote=True)
                    return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
            else:
                await query.message.edit_text("I'ᴍ ɴᴏᴛ ᴄᴏɴɴᴇᴄᴛᴇᴅ ᴛᴏ ᴀɴʏ ɢʀᴏᴜᴘs!\nCʜᴇᴄᴋ /connections ᴏʀ ᴄᴏɴɴᴇᴄᴛ ᴛᴏ ᴀɴʏ ɢʀᴏᴜᴘs", quote=True)
                return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
        elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
            grp_id, title = query.message.chat.id, query.message.chat.title
        else:
            return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)

        st = await client.get_chat_member(grp_id, user_id)
        if (st.status == enums.ChatMemberStatus.OWNER) or (str(user_id) in ADMINS):
            await del_all(query.message, grp_id, title)
            return await query.answer("Successfully deleted all filters!", show_alert=True)
        else:
            return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
    elif query.data == "delallcancel":
        if chat_type == enums.ChatType.PRIVATE:
            try:
                await query.message.reply_to_message.delete()
            except:
                pass
            await query.message.delete()
            return await query.answer("Cancelled !", show_alert=True)
        elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
            st = await client.get_chat_member(query.message.chat.id, user_id)
            if (st.status == enums.ChatMemberStatus.OWNER) or (str(user_id) in ADMINS):
                await query.message.delete()
                try: await query.message.reply_to_message.delete()
                except: pass
                return await query.answer("Cancelled !", show_alert=True)
            else:
                return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
    elif "groupcb" in query.data:
        try:
            _, group_id, act = query.data.split(":")
        except:
            return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
        hr = await client.get_chat(int(group_id))
        stat, cb = ("DISCONNECT", "disconnect") if act else ("CONNECT", "connectcb")
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(stat, callback_data=f"{cb}:{group_id}"), InlineKeyboardButton("DELETE", callback_data=f"deletecb:{group_id}")], [InlineKeyboardButton("BACK", callback_data="backcb")]])
        await query.message.edit_text(f"Gʀᴏᴜᴘ Nᴀᴍᴇ : **{hr.title}**\nGʀᴏᴜᴘ ID : `{group_id}`", reply_markup=keyboard, parse_mode=enums.ParseMode.MARKDOWN)
        return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
    elif "connectcb" in query.data or "disconnect" in query.data:
        try: _, group_id = query.data.split(":")
        except: return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
        hr = await client.get_chat(int(group_id))
        if "connectcb" in query.data:
            mkact = await make_active(str(user_id), str(group_id))
            msg = f"Cᴏɴɴᴇᴄᴛᴇᴅ ᴛᴏ **{hr.title}**" if mkact else 'Sᴏᴍᴇ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ!!'
        else:
            mkinact = await make_inactive(str(user_id))
            msg = f"Dɪsᴄᴏɴɴᴇᴄᴛᴇᴅ ғʀᴏᴍ **{hr.title}**" if mkinact else 'Sᴏᴍᴇ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ!!'
        await query.message.edit_text(msg, parse_mode=enums.ParseMode.MARKDOWN)
        return await query.answer(msg, show_alert=True)
    elif "deletecb" in query.data:
        try: _, group_id = query.data.split(":")
        except: return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
        delcon = await delete_connection(str(user_id), str(group_id))
        msg = "Sᴜᴄᴄᴇssғᴜʟʟʏ ᴅᴇʟᴇᴛᴇᴅ ᴄᴏɴɴᴇᴄᴛɪᴏɴ !" if delcon else 'Sᴏᴍᴇ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ!!'
        await query.message.edit_text(msg, parse_mode=enums.ParseMode.MARKDOWN)
        return await query.answer(msg, show_alert=True)
    elif query.data == "backcb":
        groupids = await all_connections(str(user_id))
        if not groupids:
            await query.message.edit_text("Tʜᴇʀᴇ ᴀʀᴇ ɴᴏ ᴀᴄᴛɪᴠᴇ ᴄᴏɴɴᴇᴄᴛɪᴏns!! Cᴏɴɴᴇᴄᴛ ᴛᴏ sᴏᴍᴇ ɢʀᴏᴜᴘs ғɪʀsᴛ.")
            return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
        buttons = []
        for groupid in groupids:
            try:
                ttl = await client.get_chat(int(groupid))
                active = await if_active(str(user_id), str(groupid))
                buttons.append([InlineKeyboardButton(text=f"{ttl.title}{' - ACTIVE' if active else ''}", callback_data=f"groupcb:{groupid}:{' - ACTIVE' if active else ''}")])
            except:
                pass
        if buttons:
            await query.message.edit_text("Yᴏᴜʀ ᴄᴏɴɴᴇᴄᴛᴇᴅ ɢʀᴏᴜᴘ ᴅᴇᴛᴀɪʟs ;\n\n", reply_markup=InlineKeyboardMarkup(buttons))
            return await query.answer()
    elif "gfilteralert" in query.data or "alertmessage" in query.data:
        try: _, i, keyword = query.data.split(":")
        except: return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
        reply_text, btn, alerts, fileid = await find_gfilter('gfilters', keyword) if "gfilteralert" in query.data else await find_filter(query.message.chat.id, keyword)
        if alerts is not None:
            alert = ast.literal_eval(alerts)[int(i)].replace("\\n", "\n").replace("\\t", "\t")
            return await query.answer(alert, show_alert=True)
        return await query.answer("Alert displayed!", show_alert=True)
    elif query.data.startswith("file"):
        clicked = query.from_user.id
        try: typed = query.message.reply_to_message.from_user.id
        except: typed = clicked
        try: ident, file_id = query.data.split("#")
        except: return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
        
        if clicked != typed:
            return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)

        files_ = await get_file_details(file_id)
        if not files_:
            return await query.answer('Nᴏ sᴜᴄʜ ғɪʟᴇ ᴇxɪsᴛ.', show_alert=True)
        files = files_[0]
        f_caption = CUSTOM_FILE_CAPTION.format(file_name=files.file_name or '', file_size=get_size(files.file_size) or '', file_caption=files.caption or '') if CUSTOM_FILE_CAPTION else (files.caption or files.file_name)
        
        chat_id = query.message.chat.id
        settings = await get_settings(chat_id)

        try:
            if AUTH_CHANNEL and not await is_subscribed(client, query):
                return await query.answer(url=f"https://telegram.me/{temp.U_NAME}?start={ident}_{file_id}")
            elif settings.get('is_shortlink') and clicked not in PREMIUM_USER:
                temp.SHORT[clicked] = chat_id
                return await query.answer(url=f"https://telegram.me/{temp.U_NAME}?start=short_{file_id}")
            # ✅ Fixed: botpm setting correctly evaluated here (sends via background task if False)
            elif not settings.get('botpm', True) and clicked not in PREMIUM_USER:
                is_protected = settings.get('file_secure', False)
                await client.send_cached_media(
                    chat_id=query.from_user.id, 
                    file_id=file_id, 
                    caption=f_caption, 
                    protect_content=is_protected, 
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔆彡[ HEROFLiX ]彡🔆', url=f'https://telegram.me/{CHNL_LNK}')]])
                )
                return await query.answer('Cʜᴇᴄᴋ PM, I ʜᴀᴠᴇ sᴇɴᴛ ғɪʟᴇs ɪɴ PM', show_alert=True)
            else:
                return await query.answer(url=f"https://telegram.me/{temp.U_NAME}?start={ident}_{file_id}")
        except UserIsBlocked:
            return await query.answer('Uɴʙʟᴏᴄᴋ ᴛʜᴇ ʙᴏᴛ ᴍᴀʜɴ !', show_alert=True)
        except PeerIdInvalid:
            return await query.answer(url=f"https://telegram.me/{temp.U_NAME}?start={ident}_{file_id}")
        except Exception:
            return await query.answer(url=f"https://telegram.me/{temp.U_NAME}?start={ident}_{file_id}")
    elif query.data.startswith("sendfiles"):
        clicked = query.from_user.id
        try: _, key = query.data.split("#")
        except: return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
        settings = await get_settings(query.message.chat.id)
        try:
            if settings.get('botpm', True) and settings.get('is_shortlink') and clicked not in PREMIUM_USER:
                return await query.answer(url=f"https://telegram.me/{temp.U_NAME}?start=sendfiles1_{key}")
            elif settings.get('is_shortlink') and not settings.get('botpm', True) and clicked not in PREMIUM_USER:
                return await query.answer(url=f"https://telegram.me/{temp.U_NAME}?start=sendfiles2_{key}")
            else:
                return await query.answer(url=f"https://telegram.me/{temp.U_NAME}?start=allfiles_{key}")
        except UserIsBlocked:
            return await query.answer('Uɴʙʟᴏᴄᴋ ᴛʜᴇ ʙᴏᴛ ᴍᴀʜɴ !', show_alert=True)
        except PeerIdInvalid:
            return await query.answer(url=f"https://telegram.me/{temp.U_NAME}?start=sendfiles3_{key}")
        except Exception as e:
            logger.exception(e)
            return await query.answer(url=f"https://telegram.me/{temp.U_NAME}?start=sendfiles4_{key}")
    elif query.data.startswith("del"):
        try: _, file_id = query.data.split("#")
        except: return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
        return await query.answer(url=f"https://telegram.me/{temp.U_NAME}?start=file_{file_id}")
    elif query.data.startswith("checksub"):
        if AUTH_CHANNEL and not await is_subscribed(client, query):
            return await query.answer("😒 You Didn’t Join Channel", show_alert=True)
        try: ident, file_id = query.data.split("#")
        except: return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
        files_ = await get_file_details(file_id)
        if not files_:
            return await query.answer('Nᴏ sᴜᴄʜ ғɪʟᴇ ᴇxɪsᴛ.', show_alert=True)
        files = files_[0]
        f_caption = CUSTOM_FILE_CAPTION.format(file_name=files.file_name or '', file_size=get_size(files.file_size) or '', file_caption=files.caption or '') if CUSTOM_FILE_CAPTION else (files.caption or files.file_name)
        await client.send_cached_media(chat_id=query.from_user.id, file_id=file_id, caption=f_caption, protect_content=(ident == 'checksubp'), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔆彡[ HEROFLiX ]彡🔆', url=f'https://telegram.me/{CHNL_LNK}')]]))
        return await query.answer("File sent to PM successfully!", show_alert=True)
    elif query.data == "pages":
        return await query.answer("You are on the page navigation.", show_alert=True)
    elif query.data.startswith("send_fsall") or query.data.startswith("send_fall"):
        try: _, ident, key, offset = query.data.split("#")
        except: return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
        search = BUTTON.get(key) or FRESH.get(key)
        if not search:
            return await query.answer(script.OLD_ALRT_TXT.format(query.from_user.first_name), show_alert=True)
        files, _, _ = await get_search_results(query.message.chat.id, search, offset=int(offset), filter=True)
        await send_all(client, query.from_user.id, files, ident, query.message.chat.id, query.from_user.first_name, query)
        return await query.answer(f"Hey {query.from_user.first_name}, All files on this page has been sent successfully to your PM !", show_alert=True)
    elif query.data.startswith("killfilesdq"):
        st = await client.get_chat_member(query.message.chat.id, user_id)
        if st.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] and str(user_id) not in ADMINS:
            return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
        try: _, keyword = query.data.split("#")
        except: return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
        files, total = await get_bad_files(keyword)
        await query.message.edit_text("<b>File deletion process will start in 5 seconds !</b>")
        await asyncio.sleep(5)
        deleted = 0
        async with lock:
            try:
                for file in files:
                    result = await Media.collection.delete_one({'_id': file.file_id})
                    if result.deleted_count: deleted += 1
                    if deleted % 20 == 0:
                        await query.message.edit_text(f"<b>Process started for deleting files from DB. Successfully deleted {deleted} files from DB for your query {keyword} !\n\nPlease wait...</b>")
            except Exception as e:
                logger.exception(e)
                await query.message.edit_text(f'Error: {e}')
            else:
                await query.message.edit_text(f"<b>Process Completed for file deletion !\n\nSuccessfully deleted {deleted} files from database for your query {keyword}.</b>")
        return await query.answer("Deletion process completed!", show_alert=True)
        
async def auto_filter(client, msg, spoll=False):
    if not spoll:
        message = msg
        if message.text.startswith("/") or re.findall("((^\/|^,|^!|^\.|^[\U0001F900-\U000E007F]).*)", message.text) or len(message.text) >= 100:
            return
            
        # 🔑 CRITICAL CHECK: Fetch settings and abort if Auto-Filter is turned OFF
        settings = await get_settings(message.chat.id)
        if not settings.get('auto_ffilter', True):
            return  # Completely stops the bot from replying when disabled!
        search = remove_words(message.text.lower())
        search = re.sub(r"\b(complete|combined|all\s*episodes?|full\s*episodes?)\b", "com", search, flags=re.IGNORECASE)
        search = re.sub(r"[-:–]+", " ", search)
        search = re.sub(r"\s+", " ", search).strip()
        search = re.sub(r"(?:session|season)\s?(\d+)", lambda x: f"s{x.group(1).zfill(2)}", search, flags=re.IGNORECASE)
        search = re.sub(r"so(\d+)", lambda x: f"s{x.group(1).zfill(2)}", search, flags=re.IGNORECASE)
        for lang, code in [("english", "eng"), ("hindi", "hin"), ("tamil", "tam"), ("telugu", "tel"), ("kannada", "kan"), ("malayalam", "mal")]:
            search = search.replace(lang, code)
        files, offset, total_results = await get_search_results(message.chat.id, search, offset=0, filter=True)
        settings = await get_settings(message.chat.id)
        
        if not files:
            # 🔑 Only trigger spell check if it is enabled in MongoDB settings
            if settings.get("spell_check", True):
                return await advantage_spell_chok(client, msg)
            return
    else:
        message = msg.message.reply_to_message
        search, files, offset, total_results = spoll
        settings = await get_settings(message.chat.id)
        await msg.message.delete()

    pre = 'filep' if settings.get('file_secure') else 'file'
    key = f"{message.chat.id}-{message.id}"
    FRESH[key] = search
    temp.GETALL[key] = files
    if not hasattr(temp, "SHORT"): temp.SHORT = {}
    temp.SHORT[message.from_user.id] = message.chat.id

    btn = [[InlineKeyboardButton(text=f"[{get_size(file.file_size)}] {file.file_name}", callback_data=f'{pre}#{file.file_id}')] for file in files] if settings.get('button') else []

    if offset != "":
        req = message.from_user.id if message.from_user else 0
        try:
            max_limit = 10 if settings.get('max_btn') else int(MAX_B_TN)
            total_pages = math.ceil(int(total_results) / max_limit)
            btn.append([InlineKeyboardButton("🔅 Page", callback_data="pages"), InlineKeyboardButton(text=f"1/{total_pages}", callback_data="pages"), InlineKeyboardButton(text=" NEXT ⏩", callback_data=f"next_{req}_{key}_{offset}")])
        except KeyError:
            await save_group_settings(message.chat.id, 'max_btn', True)
            btn.append([InlineKeyboardButton("🔅 Page", callback_data="pages"), InlineKeyboardButton(text=f"1/{math.ceil(int(total_results)/10)}", callback_data="pages"), InlineKeyboardButton(text=" NEXT ⏩", callback_data=f"next_{req}_{key}_{offset}")])
    else:
        btn.append([InlineKeyboardButton(text="✦ ────「 The End 」──── ✦", callback_data="pages")])

    if TUTORIAL:
        tut_url = TUTORIAL if TUTORIAL.startswith("http") else f"https://telegram.me/{TUTORIAL}"
        btn.append([InlineKeyboardButton("🌟 How To Download ❓", url=tut_url)])

    cap = f"<b>🔆 Results For ➔ ‛{search}’👇\n\n🎬 Select Your Pick ↡\n\n</b>"
    if not settings.get('button'):
        for file in files:
            cap += f"<b>🍿 <a href='https://telegram.me/{temp.U_NAME}?start=files_{file.file_id}'>[{get_size(file.file_size)}] {escape(file.file_name)}</a></b>\n\n"

    fuk = await message.reply_text(text=cap, reply_markup=InlineKeyboardMarkup(btn), disable_web_page_preview=True)
    asyncio.create_task(handle_auto_delete(fuk, settings))
    asyncio.create_task(handle_auto_delete(message, settings))

async def advantage_spell_chok(client, msg):
    mv_rqst = msg.text
    reqstr1 = msg.from_user.id if msg.from_user else None
    if not reqstr1: return
    try: reqstr = await client.get_users(reqstr1)
    except: return await msg.reply("❌ Unable to fetch user.")

    query = re.sub(r"\s+", " ", remove_words(mv_rqst)).strip() + "movie"
    g_s = await search_gagala(query) + await search_gagala(msg.text)

    if not g_s:
        if NO_RESULTS_MSG:
            await client.send_message(chat_id=LOG_CHANNEL, text=script.NORSLTS.format(reqstr.id, reqstr.mention, mv_rqst))
        k = await msg.reply(script.NO_RESULTS, disable_web_page_preview=True)
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
        if NO_RESULTS_MSG:
            await client.send_message(chat_id=LOG_CHANNEL, text=script.NORSLTS.format(reqstr.id, reqstr.mention, mv_rqst))
        k = await msg.reply(script.NO_RESULTS, disable_web_page_preview=True)
        await asyncio.sleep(60)
        return await k.delete()

    SPELL_CHECK[msg.id] = movielist
    btn = [[InlineKeyboardButton(text=movie, callback_data=f"spolling#{reqstr1}#{idx}")] for idx, movie in enumerate(movielist)]
    btn.append([InlineKeyboardButton("×××× ⟨ Close ⟩ ××××", callback_data="close_data")])
    k = await msg.reply("<b>🎬 Select Your Pick ↡</b>", reply_markup=InlineKeyboardMarkup(btn))
    asyncio.create_task(handle_auto_delete(k, await get_settings(msg.chat.id)))

async def manual_filters(client, message, text=False):
    settings = await get_settings(message.chat.id)
    group_id = message.chat.id
    name = text or message.text
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id
    keywords = await get_filters('filters')
    
    for keyword in reversed(sorted(keywords, key=len)):
        if re.search(r"( |^|[^\w])" + re.escape(keyword) + r"( |$|[^\w])", name, flags=re.IGNORECASE):
            reply_text, btn, alert, fileid = await find_filter('filters', keyword)
            if reply_text: reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")
            if btn is not None:
                try:
                    button = ast.literal_eval(btn) if btn != "[]" else []
                    if fileid == "None":
                        joelkb = await client.send_message(group_id, reply_text, disable_web_page_preview=True, reply_markup=InlineKeyboardMarkup(button) if button else None, protect_content=bool(settings.get("file_secure")), reply_to_message_id=reply_id)
                    else:
                        joelkb = await client.send_cached_media(group_id, fileid, caption=reply_text or "", reply_markup=InlineKeyboardMarkup(button) if button else None, protect_content=bool(settings.get("file_secure")), reply_to_message_id=reply_id)
                    asyncio.create_task(handle_auto_delete(joelkb, settings))
                except Exception as e:
                    logger.exception(e)
                break
    else:
        return False
