
# pm_filter.py
# Complete, refactored, ready-to-run version.
# Open for all users (no premium gating).
import asyncio
import re
import ast
import math
import random
import logging
from datetime import datetime, timedelta

import pytz
import pyrogram
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto
from pyrogram.errors import FloodWait, UserIsBlocked, MessageNotModified, PeerIdInvalid

# Project imports - ensure these exist
from Script import script
from plugins.auto_filter import auto_filter
from plugins.manual_filter import manual_filters
from utils import get_size, is_subscribed, temp, get_settings, save_group_settings, get_tutorial, send_all
from database.connections_mdb import active_connection, all_connections, delete_connection, if_active, make_active, make_inactive
from database.users_chats_db import db
from database.ia_filterdb import Media, get_file_details, get_search_results, get_bad_files
from database.filters_mdb import del_all, find_filter, get_filters
from info import ADMINS, MAX_B_TN, PICS, CUSTOM_FILE_CAPTION, AUTH_CHANNEL, PREMIUM_USER, CHNL_LNK, MSG_ALRT, LANGUAGES, SEASONS, temp as info_temp

# If any of the above imports fail in your environment, please adjust paths.

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Global state (as in original file)
BUTTON = {}
BUTTONS = {}
FRESH = {}
BUTTONS0 = {}
BUTTONS1 = {}
BUTTONS2 = {}
SPELL_CHECK = {}

lock = asyncio.Lock()

# ----------------- Helpers -----------------

async def check_user_permission_for_query(query: CallbackQuery) -> bool:
    """
    If callback message was a reply, only original requester (or id 0) may interact.
    """
    try:
        if query.message and query.message.reply_to_message:
            owner = query.message.reply_to_message.from_user.id
            if int(query.from_user.id) not in [owner, 0]:
                await query.answer("🔆 It's Not For You❗", show_alert=True)
                return False
    except Exception:
        # If there's no reply_to_message or any attribute error, allow
        pass
    return True

async def safe_answer_url(query: CallbackQuery, url: str):
    """
    Try to answer callback with URL; if PeerIdInvalid, show a start link alert instead.
    """
    try:
        await query.answer(url=url)
    except PeerIdInvalid:
        try:
            await query.answer(f"Please start the bot: https://t.me/{temp.U_NAME}?start", show_alert=True)
        except Exception as e:
            logger.exception("safe_answer_url fallback error: %s", e)
    except Exception as e:
        logger.exception("safe_answer_url unexpected error: %s", e)

async def safe_send_cached_media(client: Client, chat_id: int, file_id: str, caption: str = None, protect: bool = False, reply_markup=None):
    """
    Send cached media with robust error handling.
    Returns True on success, False otherwise.
    """
    try:
        await client.send_cached_media(
            chat_id=chat_id,
            file_id=file_id,
            caption=caption,
            protect_content=protect,
            reply_markup=reply_markup
        )
        return True
    except UserIsBlocked:
        logger.info("User %s has blocked the bot.", chat_id)
        return False
    except PeerIdInvalid:
        logger.warning("PeerIdInvalid when sending to %s", chat_id)
        return False
    except FloodWait as e:
        logger.warning("FloodWait %s seconds; sleeping.", e.value)
        await asyncio.sleep(e.value)
        try:
            await client.send_cached_media(
                chat_id=chat_id,
                file_id=file_id,
                caption=caption,
                protect_content=protect,
                reply_markup=reply_markup
            )
            return True
        except Exception as ex:
            logger.exception("Retry after FloodWait failed: %s", ex)
            return False
    except Exception as e:
        logger.exception("safe_send_cached_media error: %s", e)
        return False

def format_custom_caption(template, title, size, file_caption):
    if not template:
        return file_caption or title or ""
    try:
        return template.format(file_name='' if title is None else title,
                               file_size='' if size is None else size,
                               file_caption='' if file_caption is None else file_caption)
    except Exception as e:
        logger.exception("format_custom_caption error: %s", e)
        return file_caption or title or ""

# fallback del_allg if not present in imports
async def del_allg(message, collection_name='gfilters'):
    try:
        await del_all(message, collection_name)
    except Exception as e:
        logger.exception("del_allg wrapper error: %s", e)

# ----------------- Message handlers -----------------

@Client.on_message(filters.group & filters.text & filters.incoming)
async def give_filter(client: Client, message):
    try:
        success = await manual_filters(client, message)
        if not success:
            await auto_filter(client, message)
    except Exception as e:
        logger.exception("give_filter error: %s", e)

@Client.on_message(filters.private & filters.text & filters.incoming)
async def pm_text(bot: Client, message):
    try:
        content = message.text or ""
        user_id = message.from_user.id if message.from_user else None
        if content.startswith("/") or content.startswith("#"):
            return
        if user_id in ADMINS:
            return
        await message.reply_text(
            text=(
                "<b>🌟 Click Here For Any Movie, Series, Anime & More!!!👇 \n\n"
                "🌟 For movies, series, anime & more, click below!!!👇</b>"
            ),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎬 Click Here 🧤", url=f"https://telegram.me/herofeedbot")]]),
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.exception("pm_text error: %s", e)

# ----------------- Callback handlers -----------------

@Client.on_callback_query(filters.regex(r"^next"))
async def next_page(bot: Client, query: CallbackQuery):
    try:
        if not await check_user_permission_for_query(query):
            return

        parts = query.data.split("_", 3)
        if len(parts) < 4:
            await query.answer("Invalid request", show_alert=True)
            return
        _, req, key, offset_s = parts
        try:
            offset = int(offset_s) if offset_s not in ("None", "null", "") else 0
        except Exception:
            offset = 0

        search = BUTTONS.get(key) or FRESH.get(key)
        if not search:
            await query.answer(script.OLD_ALRT_TXT.format(query.from_user.first_name), show_alert=True)
            return

        files, n_offset, total = await get_search_results(query.message.chat.id, search, offset=offset, filter=True)
        try:
            n_offset = int(n_offset)
        except Exception:
            n_offset = 0

        if not files:
            return
        temp.GETALL[key] = files
        temp.SHORT[query.from_user.id] = query.message.chat.id
        settings = await get_settings(query.message.chat.id)

        pre = 'filep' if settings.get('file_secure') else 'file'
        btn = []
        if settings.get("button"):
            btn = [
                [
                    InlineKeyboardButton(
                        text=f"[{get_size(file.file_size)}] {' '.join(filter(lambda x: not x.startswith('@') and not x.startswith('www.'), file.file_name.split()))}",
                        callback_data=f'{pre}#{file.file_id}'
                    ),
                ]
                for file in files
            ]
            btn.insert(0, [
                InlineKeyboardButton("Languages", callback_data=f"languages#{key}"),
                InlineKeyboardButton("Seasons", callback_data=f"seasons#{key}")
            ])
        else:
            btn = [
                [
                    InlineKeyboardButton(
                        text=f"{' '.join(filter(lambda x: not x.startswith('@') and not x.startswith('www.'), file.file_name.split()))}",
                        callback_data=f'{pre}#{file.file_id}'
                    ),
                    InlineKeyboardButton(
                        text=f"{get_size(file.file_size)}",
                        callback_data=f'{pre}#{file.file_id}',
                    ),
                ]
                for file in files
            ]

        try:
            if settings.get('max_btn'):
                step = 10
            else:
                step = int(MAX_B_TN)
        except Exception:
            step = 10
        if step <= 0:
            step = 10

        # pagination logic simplified
        if n_offset == 0:
            if offset == 0:
                btn.append([InlineKeyboardButton("✦ ────「 The End 」──── ✦", callback_data="pages")])
            else:
                prev = offset - step if offset - step >= 0 else 0
                btn.append([InlineKeyboardButton("⏪ BACK", callback_data=f"next_{req}_{key}_{prev}"), InlineKeyboardButton(f"{math.ceil(int(offset)/step)+1} / {math.ceil(total/step)}", callback_data="pages")])
        else:
            prev = offset - step if offset - step >= 0 else 0
            btn.append([InlineKeyboardButton("⏪ BACK", callback_data=f"next_{req}_{key}_{prev}"), InlineKeyboardButton(f"{math.ceil(int(offset)/step)+1} / {math.ceil(total/step)}", callback_data="pages"), InlineKeyboardButton(" NEXT ⏩", callback_data=f"next_{req}_{key}_{n_offset}")])

        cap = f"<b>🔆 Results For ➔ ‛{search}’👇\n\n<i>🗨 Select A Link & Press Start ↷</i>\n\n</b>"
        if not settings.get("button"):
            for file in files:
                cap += f"<b>📙 <a href='https://telegram.me/{temp.U_NAME}?start=files_{file.file_id}'>[{get_size(file.file_size)}] {' '.join(filter(lambda x: not x.startswith('@') and not x.startswith('www.'), file.file_name.split()))}\n\n</a></b>"

        try:
            await query.message.edit_text(text=cap, reply_markup=InlineKeyboardMarkup(btn), disable_web_page_preview=True)
        except MessageNotModified:
            pass
        await query.answer()
    except Exception as e:
        logger.exception("next_page error: %s", e)
        try:
            await query.answer("An error occurred.", show_alert=True)
        except Exception:
            pass

@Client.on_callback_query(filters.regex(r"^spolling"))
async def advantage_spoll_choker(bot: Client, query: CallbackQuery):
    try:
        parts = query.data.split('#')
        if len(parts) < 3:
            return
        _, user, movie_ = parts
        if int(user) != 0 and query.from_user.id != int(user):
            return await query.answer("🔆 It's Not For You❗", show_alert=True)
        if movie_ == "close_spellcheck":
            return await query.message.delete()
        movies = SPELL_CHECK.get(query.message.reply_to_message.id)
        if not movies:
            return await query.answer("❗Link Expired, Request Again ♻", show_alert=True)
        movie = movies[int(movie_)]
        await query.answer("Checking, Please Wait ♻️ \n\n[ Don't Spam - Just Wait! ]", show_alert=True)
        k = await manual_filters(bot, query.message, text=movie)
        if k == False:
            files, offset, total_results = await get_search_results(query.message.chat.id, movie, offset=0, filter=True)
            if files:
                k = (movie, files, offset, total_results)
                await auto_filter(bot, query, k)
            else:
                kmsg = await query.message.edit(script.I_CUDNT, disable_web_page_preview=True)
                await asyncio.sleep(60)
                await kmsg.delete()
    except Exception as e:
        logger.exception("spolling error: %s", e)

@Client.on_callback_query(filters.regex(r"^languages#"))
async def languages_cb_handler(client: Client, query: CallbackQuery):
    try:
        if not await check_user_permission_for_query(query):
            return
        _, key = query.data.split("#", 1)
        search = FRESH.get(key, "")
        search = search.replace(' ', '_')
        btn = []
        for i in range(0, len(LANGUAGES)-1, 2):
            left = LANGUAGES[i]
            right = LANGUAGES[i+1] if i+1 < len(LANGUAGES) else None
            row = [InlineKeyboardButton(text=left.title(), callback_data=f"fl#{left.lower()}#{key}")]
            if right:
                row.append(InlineKeyboardButton(text=right.title(), callback_data=f"fl#{right.lower()}#{key}"))
            btn.append(row)
        btn.insert(0, [InlineKeyboardButton(text="👇 Select Your Language 👇", callback_data="ident")])
        btn.append([InlineKeyboardButton(text="↭ Back to Files ↭", callback_data=f"fl#homepage#{key}")])
        await query.edit_message_reply_markup(InlineKeyboardMarkup(btn))
    except Exception as e:
        logger.exception("languages_cb_handler error: %s", e)

@Client.on_callback_query(filters.regex(r"^fl#"))
async def filter_languages_cb_handler(client: Client, query: CallbackQuery):
    try:
        if not await check_user_permission_for_query(query):
            return
        _, lang, key = query.data.split("#", 2)
        search = FRESH.get(key, "")
        search = search.replace("_", " ")
        # Toggle language token
        if re.search(rf"\b{re.escape(lang)}\b", search, flags=re.IGNORECASE):
            search = re.sub(rf"\b{re.escape(lang)}\b", "", search, flags=re.IGNORECASE)
        else:
            search = f"{search} {lang}"
        BUTTONS[key] = search
        files, offset, total_results = await get_search_results(query.message.chat.id, search, offset=0, filter=True)
        if not files:
            await query.answer("🚫 No File Were Found 🚫", show_alert=True)
            return
        temp.GETALL[key] = files
        settings = await get_settings(query.message.chat.id)
        pre = 'filep' if settings.get('file_secure') else 'file'
        if settings.get("button"):
            btn = [[InlineKeyboardButton(text=f"[{get_size(file.file_size)}] {' '.join(filter(lambda x: not x.startswith('@') and not x.startswith('www.'), file.file_name.split()))}", callback_data=f'{pre}#{file.file_id}')] for file in files]
        else:
            btn = [[InlineKeyboardButton(text=f"{' '.join(filter(lambda x: not x.startswith('@') and not x.startswith('www.'), file.file_name.split()))}", callback_data=f'{pre}#{file.file_id}'),
                    InlineKeyboardButton(text=f"{get_size(file.file_size)}", callback_data=f'{pre}#{file.file_id}')] for file in files]
        btn.insert(0, [InlineKeyboardButton("Languages", callback_data=f"languages#{key}"), InlineKeyboardButton("Seasons", callback_data=f"seasons#{key}")])
        # pagination
        try:
            if offset:
                if settings.get('max_btn'):
                    btn.append([InlineKeyboardButton("🔅 Page", callback_data="pages"), InlineKeyboardButton(text=f"1/{math.ceil(int(total_results)/10)}", callback_data="pages"), InlineKeyboardButton(text=" NEXT ⏩", callback_data=f"next_{query.from_user.id}_{key}_{offset}")])
                else:
                    btn.append([InlineKeyboardButton("🔅 Page", callback_data="pages"), InlineKeyboardButton(text=f"1/{math.ceil(int(total_results)/int(MAX_B_TN))}", callback_data="pages"), InlineKeyboardButton(text=" NEXT ⏩", callback_data=f"next_{query.from_user.id}_{key}_{offset}")])
            else:
                btn.append([InlineKeyboardButton(text="✦ ────「 The End 」──── ✦", callback_data="pages")])
        except Exception:
            btn.append([InlineKeyboardButton(text="✦ ────「 The End 」──── ✦", callback_data="pages")])
        try:
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))
        except MessageNotModified:
            pass
        await query.answer()
    except Exception as e:
        logger.exception("filter_languages_cb_handler error: %s", e)

@Client.on_callback_query(filters.regex(r"^seasons#"))
async def seasons_cb_handler(client: Client, query: CallbackQuery):
    try:
        if not await check_user_permission_for_query(query):
            return
        _, key = query.data.split("#", 1)
        search = FRESH.get(key, "")
        search = search.replace(' ', '_')
        btn = []
        for i in range(0, len(SEASONS)-1, 2):
            left = SEASONS[i]
            right = SEASONS[i+1] if i+1 < len(SEASONS) else None
            row = [InlineKeyboardButton(text=left.title(), callback_data=f"fs#{left.lower()}#{key}")]
            if right:
                row.append(InlineKeyboardButton(text=right.title(), callback_data=f"fs#{right.lower()}#{key}"))
            btn.append(row)
        btn.insert(0, [InlineKeyboardButton(text="👇 Select Season 👇", callback_data="ident")])
        btn.append([InlineKeyboardButton(text="↭ Back to Files ↭", callback_data=f"next_{query.from_user.id}_{key}_0")])
        await query.edit_message_reply_markup(InlineKeyboardMarkup(btn))
    except Exception as e:
        logger.exception("seasons_cb_handler error: %s", e)

@Client.on_callback_query(filters.regex(r"^fs#"))
async def filter_seasons_cb_handler(client: Client, query: CallbackQuery):
    try:
        if not await check_user_permission_for_query(query):
            return
        _, seas, key = query.data.split("#", 2)
        search = FRESH.get(key, "")
        # remove any season tokens
        season_search = [f"s{str(i).zfill(2)}" for i in range(1, 11)] + [f"season {i}" for i in range(1, 11)]
        for s in season_search:
            if s in search.lower():
                search = re.sub(re.escape(s), "", search, flags=re.IGNORECASE)
                break
        search = f"{search} {seas}"
        BUTTONS0[key] = search

        # try three patterns
        search_variants = [search, f"{search} s01", f"{search} season 01"]
        files_combined = []
        for sv in search_variants:
            files, _, _ = await get_search_results(query.message.chat.id, sv, max_results=10)
            if files:
                files_filtered = [file for file in files if re.search(re.escape(seas), file.file_name, re.IGNORECASE)]
                files_combined.extend(files_filtered)

        if not files_combined:
            await query.answer("🚫 No File Were Found 🚫", show_alert=True)
            return

        temp.GETALL[key] = files_combined
        settings = await get_settings(query.message.chat.id)
        pre = 'filep' if settings.get('file_secure') else 'file'
        if settings.get("button"):
            btn = [[InlineKeyboardButton(text=f"[{get_size(file.file_size)}] {' '.join(filter(lambda x: not x.startswith('@') and not x.startswith('www.'), file.file_name.split()))}", callback_data=f'{pre}#{file.file_id}')] for file in files_combined]
        else:
            btn = [[InlineKeyboardButton(text=f"{' '.join(filter(lambda x: not x.startswith('@') and not x.startswith('www.'), file.file_name.split()))}", callback_data=f'{pre}#{file.file_id}'), InlineKeyboardButton(text=f"{get_size(file.file_size)}", callback_data=f'{pre}#{file.file_id}')] for file in files_combined]
        btn.append([InlineKeyboardButton(text="↭ Back to Files ↭", callback_data=f"next_{query.from_user.id}_{key}_0")])
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))
    except Exception as e:
        logger.exception("filter_seasons_cb_handler error: %s", e)

@Client.on_callback_query()
async def cb_handler(client: Client, query: CallbackQuery):
    try:
        data = query.data or ""
        # Basic actions
        if data == "close_data":
            await query.message.delete()
            return
        if data == "pages":
            await query.answer()
            return

        if data == "gfiltersdeleteallconfirm":
            await del_allg(query.message, 'gfilters')
            await query.answer("Done !")
            return
        if data == "gfiltersdeleteallcancel":
            await query.message.reply_to_message.delete()
            await query.message.delete()
            await query.answer("Process Cancelled !")
            return

        if data == "delallconfirm":
            userid = query.from_user.id
            chat_type = query.message.chat.type
            if chat_type == enums.ChatType.PRIVATE:
                grpid = await active_connection(str(userid))
                if grpid is not None:
                    grp_id = grpid
                    try:
                        chat = await client.get_chat(grpid)
                        title = chat.title
                    except Exception:
                        await query.message.edit_text("Make sure I'm present in your group!!", quote=True)
                        return await query.answer(MSG_ALRT)
                else:
                    await query.message.edit_text("I'm not connected to any groups! Check /connections or connect to a group", quote=True)
                    return await query.answer(MSG_ALRT)
            elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
                grp_id = query.message.chat.id
                title = query.message.chat.title
            else:
                return await query.answer(MSG_ALRT)

            st = await client.get_chat_member(grp_id, userid)
            if (st.status == enums.ChatMemberStatus.OWNER) or (str(userid) in ADMINS):
                await del_all(query.message, grp_id, title)
            else:
                await query.answer("You need to be group owner or an auth user to do that!", show_alert=True)
            return

        if data == "delallcancel":
            userid = query.from_user.id
            chat_type = query.message.chat.type
            if chat_type == enums.ChatType.PRIVATE:
                await query.message.reply_to_message.delete()
                await query.message.delete()
            elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
                grp_id = query.message.chat.id
                st = await client.get_chat_member(grp_id, userid)
                if (st.status == enums.ChatMemberStatus.OWNER) or (str(userid) in ADMINS):
                    await query.message.delete()
                    try:
                        await query.message.reply_to_message.delete()
                    except Exception:
                        pass
                else:
                    await query.answer("🔆 It's Not For You❗", show_alert=True)
            return

        # group connect/disconnect handlers
        if "groupcb" in data:
            await query.answer()
            parts = data.split(":")
            group_id = parts[1]
            act = parts[2] if len(parts) > 2 else ""
            hr = await client.get_chat(int(group_id))
            title = hr.title
            user_id = query.from_user.id
            stat = "CONNECT" if act == "" else "DISCONNECT"
            cb = "connectcb" if act == "" else "disconnect"
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{stat}", callback_data=f"{cb}:{group_id}"),
                 InlineKeyboardButton("DELETE", callback_data=f"deletecb:{group_id}")],
                [InlineKeyboardButton("BACK", callback_data="backcb")]
            ])
            await query.message.edit_text(f"Group Name : **{title}**\nGroup ID : `{group_id}`", reply_markup=keyboard, parse_mode=enums.ParseMode.MARKDOWN)
            return await query.answer(MSG_ALRT)

        if "connectcb" in data:
            await query.answer()
            group_id = data.split(":")[1]
            hr = await client.get_chat(int(group_id))
            title = hr.title
            user_id = query.from_user.id
            mkact = await make_active(str(user_id), str(group_id))
            if mkact:
                await query.message.edit_text(f"Connected to **{title}**", parse_mode=enums.ParseMode.MARKDOWN)
            else:
                await query.message.edit_text("Some error occurred!!", parse_mode=enums.ParseMode.MARKDOWN)
            return await query.answer(MSG_ALRT)

        if "disconnect" in data and data.startswith("disconnect"):
            await query.answer()
            group_id = data.split(":")[1]
            hr = await client.get_chat(int(group_id))
            title = hr.title
            user_id = query.from_user.id
            mkinact = await make_inactive(str(user_id))
            if mkinact:
                await query.message.edit_text(f"Disconnected from **{title}**", parse_mode=enums.ParseMode.MARKDOWN)
            else:
                await query.message.edit_text("Some error occurred!!", parse_mode=enums.ParseMode.MARKDOWN)
            return await query.answer(MSG_ALRT)

        if "deletecb" in data:
            await query.answer()
            user_id = query.from_user.id
            group_id = data.split(":")[1]
            delcon = await delete_connection(str(user_id), str(group_id))
            if delcon:
                await query.message.edit_text("Successfully deleted connection!")
            else:
                await query.message.edit_text("Some error occurred!!", parse_mode=enums.ParseMode.MARKDOWN)
            return await query.answer(MSG_ALRT)

        if data == "backcb":
            await query.answer()
            userid = query.from_user.id
            groupids = await all_connections(str(userid))
            if groupids is None:
                await query.message.edit_text("There are no active connections!! Connect to some groups first.")
                return await query.answer(MSG_ALRT)
            buttons = []
            for groupid in groupids:
                try:
                    ttl = await client.get_chat(int(groupid))
                    title = ttl.title
                    active = await if_active(str(userid), str(groupid))
                    act = " - ACTIVE" if active else ""
                    buttons.append([InlineKeyboardButton(text=f"{title}{act}", callback_data=f"groupcb:{groupid}:{act}")])
                except Exception:
                    pass
            if buttons:
                await query.message.edit_text("Your connected group details ;\n\n", reply_markup=InlineKeyboardMarkup(buttons))
            return

        # gfilter alert handling
        if "gfilteralert" in data:
            grp_id = query.message.chat.id
            i = data.split(":")[1]
            keyword = data.split(":")[2]
            reply_text, btn, alerts, fileid = await find_gfilter('gfilters', keyword)
            if alerts is not None:
                alerts = ast.literal_eval(alerts)
                alert = alerts[int(i)]
                alert = alert.replace("\\n", "\n").replace("\\t", "\t")
                await query.answer(alert, show_alert=True)
            return

        if "alertmessage" in data:
            grp_id = query.message.chat.id
            i = data.split(":")[1]
            keyword = data.split(":")[2]
            reply_text, btn, alerts, fileid = await find_filter(grp_id, keyword)
            if alerts is not None:
                alerts = ast.literal_eval(alerts)
                alert = alerts[int(i)]
                alert = alert.replace("\\n", "\n").replace("\\t", "\t")
                await query.answer(alert, show_alert=True)
            return

        # file click handling (file, filep)
        if data.startswith("file") or data.startswith("filep"):
            clicked = query.from_user.id
            try:
                typed = query.message.reply_to_message.from_user.id
            except Exception:
                typed = query.from_user.id
            ident, file_id = data.split("#")
            files_ = await get_file_details(file_id)
            if not files_:
                return await query.answer('No such file exists.')
            files = files_[0]
            title = files.file_name
            size = get_size(files.file_size)
            f_caption = files.caption
            settings = await get_settings(query.message.chat.id)
            if CUSTOM_FILE_CAPTION:
                try:
                    f_caption = format_custom_caption(CUSTOM_FILE_CAPTION, title, size, f_caption)
                except Exception as e:
                    logger.exception("custom caption format error: %s", e)
            if f_caption is None:
                f_caption = f"{files.file_name}"

            try:
                if AUTH_CHANNEL and not await is_subscribed(client, query):
                    if clicked == typed:
                        await safe_answer_url(query, f"https://telegram.me/{temp.U_NAME}?start={ident}_{file_id}")
                        return
                    else:
                        await query.answer("🔆 It's Not For You❗", show_alert=True)
                        return
                elif settings.get('botpm') and settings.get('is_shortlink') and clicked not in PREMIUM_USER:
                    if clicked == typed:
                        temp.SHORT[clicked] = query.message.chat.id
                        await safe_answer_url(query, f"https://telegram.me/{temp.U_NAME}?start=short_{file_id}")
                        return
                    else:
                        await query.answer("🔆 It's Not For You❗", show_alert=True)
                        return
                elif settings.get('is_shortlink') and not settings.get('botpm') and clicked not in PREMIUM_USER:
                    if clicked == typed:
                        temp.SHORT[clicked] = query.message.chat.id
                        await safe_answer_url(query, f"https://telegram.me/{temp.U_NAME}?start=short_{file_id}")
                        return
                    else:
                        await query.answer("🔆 It's Not For You❗", show_alert=True)
                        return
                elif settings.get('botpm') or clicked in PREMIUM_USER:
                    if clicked == typed:
                        await safe_answer_url(query, f"https://telegram.me/{temp.U_NAME}?start={ident}_{file_id}")
                        return
                    else:
                        await query.answer("🔆 It's Not For You❗", show_alert=True)
                        return
                else:
                    if clicked == typed:
                        sent = await safe_send_cached_media(
                            client=client,
                            chat_id=query.from_user.id,
                            file_id=file_id,
                            caption=f_caption,
                            protect=True if ident == "filep" else False,
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔆彡[ HEROFLiX ]彡🔆', url=f'https://telegram.me/{CHNL_LNK}')]])
                        )
                        if not sent:
                            # fallback: answer with start url
                            await safe_answer_url(query, f"https://telegram.me/{temp.U_NAME}?start={ident}_{file_id}")
                    else:
                        await query.answer("🔆 It's Not For You❗", show_alert=True)
                        return
                    await query.answer('Check PM, I have sent files in PM', show_alert=True)
            except UserIsBlocked:
                await query.answer('Unblock the bot!', show_alert=True)
            except PeerIdInvalid:
                await safe_answer_url(query, f"https://telegram.me/{temp.U_NAME}?start={ident}_{file_id}")
            except Exception as e:
                logger.exception("file click handler error: %s", e)
                await safe_answer_url(query, f"https://telegram.me/{temp.U_NAME}?start={ident}_{file_id}")
            return

        # sendfiles/send all flows
        if data.startswith("sendfiles"):
            clicked = query.from_user.id
            ident, key = data.split("#")
            settings = await get_settings(query.message.chat.id)
            try:
                # open for all users: always send start url that triggers sendfiles flow
                await safe_answer_url(query, f"https://telegram.me/{temp.U_NAME}?start=sendfiles_{key}")
                return
            except Exception as e:
                logger.exception("sendfiles handler error: %s", e)
                await query.answer("Failed to process sendfiles", show_alert=True)
                return

        if data.startswith("send_fsall"):
            try:
                temp_var, ident, key, offset = data.split("#")
                search = BUTTON.get(key)
                if not search:
                    await query.answer(script.OLD_ALRT_TXT.format(query.from_user.first_name), show_alert=True)
                    return
                files, n_offset, total = await get_search_results(query.message.chat.id, search, offset=int(offset), filter=True)
                await send_all(client, query.from_user.id, files, ident, query.message.chat.id, query.from_user.first_name, query)
                # also try BUTTONS1 and BUTTONS2
                for key_search in (BUTTONS1.get(key), BUTTONS2.get(key)):
                    if key_search:
                        files, n_offset, total = await get_search_results(query.message.chat.id, key_search, offset=int(offset), filter=True)
                        await send_all(client, query.from_user.id, files, ident, query.message.chat.id, query.from_user.first_name, query)
                await query.answer(f"Hey {query.from_user.first_name}, All files on this page have been sent to your PM!", show_alert=True)
            except Exception as e:
                logger.exception("send_fsall error: %s", e)
                await query.answer("Failed to send all files", show_alert=True)
            return

        if data.startswith("send_fall"):
            try:
                temp_var, ident, key, offset = data.split("#")
                search = BUTTONS.get(key) or FRESH.get(key)
                if not search:
                    await query.answer(script.OLD_ALRT_TXT.format(query.from_user.first_name), show_alert=True)
                    return
                files, n_offset, total = await get_search_results(query.message.chat.id, search, offset=int(offset), filter=True)
                await send_all(client, query.from_user.id, files, ident, query.message.chat.id, query.from_user.first_name, query)
                await query.answer(f"Hey {query.from_user.first_name}, All files on this page have been sent to your PM!", show_alert=True)
            except Exception as e:
                logger.exception("send_fall error: %s", e)
                await query.answer("Failed to send files", show_alert=True)
            return

        # killfilesdq: delete bad files
        if data.startswith("killfilesdq"):
            try:
                ident, keyword = data.split("#")
                files, total = await get_bad_files(keyword)
                await query.message.edit_text("<b>File deletion process will start in 5 seconds !</b>")
                await asyncio.sleep(5)
                deleted = 0
                async with lock:
                    try:
                        for file in files:
                            file_ids = file.file_id
                            file_name = file.file_name
                            result = await Media.collection.delete_one({'_id': file_ids})
                            if result.deleted_count:
                                logger.info("Deleted %s from DB", file_name)
                            deleted += 1
                            if deleted % 20 == 0:
                                await query.message.edit_text(f"<b>Process started... Successfully deleted {str(deleted)} files from DB for your query {keyword} !\n\nPlease wait...</b>")
                    except Exception as e:
                        logger.exception("Deletion loop error: %s", e)
                        await query.message.edit_text(f'Error: {e}')
                    else:
                        await query.message.edit_text(f"<b>Process Completed for file deletion !\n\nSuccessfully deleted {str(deleted)} files from database for your query {keyword}.</b>")
            except Exception as e:
                logger.exception("killfilesdq error: %s", e)
            return

        # settings open group
        if data.startswith("opnsetgrp"):
            try:
                ident, grp_id = data.split("#")
                userid = query.from_user.id if query.from_user else None
                st = await client.get_chat_member(grp_id, userid)
                if (st.status != enums.ChatMemberStatus.ADMINISTRATOR and st.status != enums.ChatMemberStatus.OWNER and str(userid) not in ADMINS):
                    await query.answer("You don't have the rights to do this!", show_alert=True)
                    return
                title = query.message.chat.title
                settings = await get_settings(grp_id)
                if settings is not None:
                    buttons = [
                        [InlineKeyboardButton('Result Page', callback_data=f'setgs#button#{settings.get("button")}#{str(grp_id)}'),
                         InlineKeyboardButton('Button' if settings.get("button") else 'Text', callback_data=f'setgs#button#{settings.get("button")}#{str(grp_id)}')],
                        [InlineKeyboardButton('File Send Mode', callback_data=f'setgs#botpm#{settings.get("botpm")}#{str(grp_id)}'),
                         InlineKeyboardButton('Manual Start' if settings.get("botpm") else 'Auto Send', callback_data=f'setgs#botpm#{settings.get("botpm")}#{str(grp_id)}')],
                        [InlineKeyboardButton('Protect Content', callback_data=f'setgs#file_secure#{settings.get("file_secure")}#{str(grp_id)}'),
                         InlineKeyboardButton('✔ On' if settings.get("file_secure") else '✘ Off', callback_data=f'setgs#file_secure#{settings.get("file_secure")}#{str(grp_id)}')],
                        [InlineKeyboardButton('IMDB', callback_data=f'setgs#imdb#{settings.get("imdb")}#{str(grp_id)}'),
                         InlineKeyboardButton('✔ On' if settings.get("imdb") else '✘ Off', callback_data=f'setgs#imdb#{settings.get("imdb")}#{str(grp_id)}')],
                        [InlineKeyboardButton('Spell Check', callback_data=f'setgs#spell_check#{settings.get("spell_check")}#{str(grp_id)}'),
                         InlineKeyboardButton('✔ On' if settings.get("spell_check") else '✘ Off', callback_data=f'setgs#spell_check#{settings.get("spell_check")}#{str(grp_id)}')],
                        [InlineKeyboardButton('Welcome Msg', callback_data=f'setgs#welcome#{settings.get("welcome")}#{str(grp_id)}'),
                         InlineKeyboardButton('✔ On' if settings.get("welcome") else '✘ Off', callback_data=f'setgs#welcome#{settings.get("welcome")}#{str(grp_id)}')],
                        [InlineKeyboardButton('Auto-Delete', callback_data=f'setgs#auto_delete#{settings.get("auto_delete")}#{str(grp_id)}'),
                         InlineKeyboardButton('5 Mins' if settings.get("auto_delete") else '✘ Off', callback_data=f'setgs#auto_delete#{settings.get("auto_delete")}#{str(grp_id)}')],
                        [InlineKeyboardButton('Auto-Filter', callback_data=f'setgs#auto_ffilter#{settings.get("auto_ffilter")}#{str(grp_id)}'),
                         InlineKeyboardButton('✔ On' if settings.get("auto_ffilter") else '✘ Off', callback_data=f'setgs#auto_ffilter#{settings.get("auto_ffilter")}#{str(grp_id)}')],
                        [InlineKeyboardButton('Max Buttons', callback_data=f'setgs#max_btn#{settings.get("max_btn")}#{str(grp_id)}'),
                         InlineKeyboardButton('10' if settings.get("max_btn") else f'{MAX_B_TN}', callback_data=f'setgs#max_btn#{settings.get("max_btn")}#{str(grp_id)}')],
                        [InlineKeyboardButton('Shortlink', callback_data=f'setgs#is_shortlink#{settings.get("is_shortlink")}#{str(grp_id)}'),
                         InlineKeyboardButton('✔ On' if settings.get("is_shortlink") else '✘ Off', callback_data=f'setgs#is_shortlink#{settings.get("is_shortlink")}#{str(grp_id)}')],
                    ]
                    reply_markup = InlineKeyboardMarkup(buttons)
                    await query.message.edit_text(text=f"<b>Change Your Settings For {title}</b>", disable_web_page_preview=True, parse_mode=enums.ParseMode.HTML)
                    await query.message.edit_reply_markup(reply_markup)
            except Exception as e:
                logger.exception("opnsetgrp error: %s", e)
            return

        # open settings in PM
        if data.startswith("opnsetpm"):
            try:
                ident, grp_id = data.split("#")
                userid = query.from_user.id if query.from_user else None
                st = await client.get_chat_member(grp_id, userid)
                if (st.status != enums.ChatMemberStatus.ADMINISTRATOR and st.status != enums.ChatMemberStatus.OWNER and str(userid) not in ADMINS):
                    await query.answer("You don't have the rights to do this!", show_alert=True)
                    return
                title = query.message.chat.title
                settings = await get_settings(grp_id)
                btn2 = [[InlineKeyboardButton("Check PM", url=f"telegram.me/{temp.U_NAME}")]]
                reply_markup = InlineKeyboardMarkup(btn2)
                await query.message.edit_text(f"<b>Your settings menu for {title} has been sent to your PM</b>")
                await query.message.edit_reply_markup(reply_markup)
                if settings is not None:
                    buttons = [
                        [InlineKeyboardButton('Result Page', callback_data=f'setgs#button#{settings.get("button")}#{str(grp_id)}'),
                         InlineKeyboardButton('Button' if settings.get("button") else 'Text', callback_data=f'setgs#button#{settings.get("button")}#{str(grp_id)}')],
                        [InlineKeyboardButton('File Send Mode', callback_data=f'setgs#botpm#{settings.get("botpm")}#{str(grp_id)}'),
                         InlineKeyboardButton('Manual Start' if settings.get("botpm") else 'Auto Send', callback_data=f'setgs#botpm#{settings.get("botpm")}#{str(grp_id)}')],
                        [InlineKeyboardButton('Protect Content', callback_data=f'setgs#file_secure#{settings.get("file_secure")}#{str(grp_id)}'),
                         InlineKeyboardButton('✔ On' if settings.get("file_secure") else '✘ Off', callback_data=f'setgs#file_secure#{settings.get("file_secure")}#{str(grp_id)}')],
                        [InlineKeyboardButton('IMDB', callback_data=f'setgs#imdb#{settings.get("imdb")}#{str(grp_id)}'),
                         InlineKeyboardButton('✔ On' if settings.get("imdb") else '✘ Off', callback_data=f'setgs#imdb#{settings.get("imdb")}#{str(grp_id)}')],
                        [InlineKeyboardButton('Spell Check', callback_data=f'setgs#spell_check#{settings.get("spell_check")}#{str(grp_id)}'),
                         InlineKeyboardButton('✔ On' if settings.get("spell_check") else '✘ Off', callback_data=f'setgs#spell_check#{settings.get("spell_check")}#{str(grp_id)}')],
                        [InlineKeyboardButton('Welcome Msg', callback_data=f'setgs#welcome#{settings.get("welcome")}#{str(grp_id)}'),
                         InlineKeyboardButton('✔ On' if settings.get("welcome") else '✘ Off', callback_data=f'setgs#welcome#{settings.get("welcome")}#{str(grp_id)}')],
                        [InlineKeyboardButton('Auto-Delete', callback_data=f'setgs#auto_delete#{settings.get("auto_delete")}#{str(grp_id)}'),
                         InlineKeyboardButton('5 Mins' if settings.get("auto_delete") else '✘ Off', callback_data=f'setgs#auto_delete#{settings.get("auto_delete")}#{str(grp_id)}')],
                        [InlineKeyboardButton('Auto-Filter', callback_data=f'setgs#auto_ffilter#{settings.get("auto_ffilter")}#{str(grp_id)}'),
                         InlineKeyboardButton('✔ On' if settings.get("auto_ffilter") else '✘ Off', callback_data=f'setgs#auto_ffilter#{settings.get("auto_ffilter")}#{str(grp_id)}')],
                        [InlineKeyboardButton('Max Buttons', callback_data=f'setgs#max_btn#{settings.get("max_btn")}#{str(grp_id)}'),
                         InlineKeyboardButton('10' if settings.get("max_btn") else f'{MAX_B_TN}', callback_data=f'setgs#max_btn#{settings.get("max_btn")}#{str(grp_id)}')],
                        [InlineKeyboardButton('Shortlink', callback_data=f'setgs#is_shortlink#{settings.get("is_shortlink")}#{str(grp_id)}'),
                         InlineKeyboardButton('✔ On' if settings.get("is_shortlink") else '✘ Off', callback_data=f'setgs#is_shortlink#{settings.get("is_shortlink")}#{str(grp_id)}')],
                    ]
                    reply_markup = InlineKeyboardMarkup(buttons)
                    await client.send_message(chat_id=userid, text=f"<b>Change Your Settings For {title}</b>", reply_markup=reply_markup, disable_web_page_preview=True, parse_mode=enums.ParseMode.HTML, reply_to_message_id=query.message.id)
            except Exception as e:
                logger.exception("opnsetpm error: %s", e)
            return

        # start payload
        if data == "start":
            buttons = [[InlineKeyboardButton('Join Our Main Group', url=f'https://telegram.me/{CHNL_LNK}')],
                       [InlineKeyboardButton('Update', url=f'https://telegram.me/{CHNL_LNK}'), InlineKeyboardButton('Movie Group', url=f'https://telegram.me/{CHNL_LNK}')],
                       [InlineKeyboardButton('Help', callback_data='help'), InlineKeyboardButton('About', callback_data='about')],
                       [InlineKeyboardButton('Premium Plan', callback_data="shortlink_info")]]
            reply_markup = InlineKeyboardMarkup(buttons)
            try:
                await client.edit_message_media(query.message.chat.id, query.message.id, InputMediaPhoto(random.choice(PICS)))
            except Exception:
                pass
            await query.message.edit_text(text=script.START_TXT.format(query.from_user.mention, temp.U_NAME, temp.B_NAME), reply_markup=reply_markup, parse_mode=enums.ParseMode.HTML)
            await query.answer(MSG_ALRT)
            return

        # help, about, other navigation simplified
        if data == "help":
            buttons = [[InlineKeyboardButton('Filters', callback_data='filters'), InlineKeyboardButton('File Store', callback_data='store_file')],
                       [InlineKeyboardButton('Connection', callback_data='coct'), InlineKeyboardButton('Extra Mods', callback_data='extra')],
                       [InlineKeyboardButton('Home', callback_data='start'), InlineKeyboardButton('Status', callback_data='stats')]]
            reply_markup = InlineKeyboardMarkup(buttons)
            try:
                await client.edit_message_media(query.message.chat.id, query.message.id, InputMediaPhoto(random.choice(PICS)))
            except Exception:
                pass
            await query.message.edit_text(text=script.HELP_TXT.format(query.from_user.mention), reply_markup=reply_markup, parse_mode=enums.ParseMode.HTML)
            return

        if data == "about":
            buttons = [[InlineKeyboardButton('Support Group', url=f'https://telegram.me/{CHNL_LNK}'), InlineKeyboardButton('Source Code', callback_data='source')],
                       [InlineKeyboardButton('Home', callback_data='start'), InlineKeyboardButton('Close', callback_data='close_data')]]
            try:
                await client.edit_message_media(query.message.chat.id, query.message.id, InputMediaPhoto(random.choice(PICS)))
            except Exception:
                pass
            await query.message.edit_text(text=script.ABOUT_TXT.format(temp.B_NAME), reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            return

        if data == "source":
            buttons = [[InlineKeyboardButton('Back', callback_data='about')]]
            try:
                await client.edit_message_media(query.message.chat.id, query.message.id, InputMediaPhoto(random.choice(PICS)))
            except Exception:
                pass
            await query.message.edit_text(text=script.SOURCE_TXT, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            return

        if data == "filters":
            buttons = [[InlineKeyboardButton('Manual Filter', callback_data='manuelfilter'), InlineKeyboardButton('Auto Filter', callback_data='autofilter')],
                       [InlineKeyboardButton('Back', callback_data='help'), InlineKeyboardButton('Global Filters', callback_data='global_filters')]]
            try:
                await client.edit_message_media(query.message.chat.id, query.message.id, InputMediaPhoto(random.choice(PICS)))
            except Exception:
                pass
            await query.message.edit_text(text=script.ALL_FILTERS.format(query.from_user.mention), reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            return

        if data == "global_filters":
            buttons = [[InlineKeyboardButton('Back', callback_data='filters')]]
            try:
                await client.edit_message_media(query.message.chat.id, query.message.id, InputMediaPhoto(random.choice(PICS)))
            except Exception:
                pass
            await query.message.edit_text(text=script.GFILTER_TXT, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            return

        if data == "manuelfilter":
            buttons = [[InlineKeyboardButton('Back', callback_data='filters'), InlineKeyboardButton('Buttons', callback_data='button')]]
            try:
                await client.edit_message_media(query.message.chat.id, query.message.id, InputMediaPhoto(random.choice(PICS)))
            except Exception:
                pass
            await query.message.edit_text(text=script.MANUELFILTER_TXT, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            return

        if data == "button":
            buttons = [[InlineKeyboardButton('Back', callback_data='manuelfilter')]]
            try:
                await client.edit_message_media(query.message.chat.id, query.message.id, InputMediaPhoto(random.choice(PICS)))
            except Exception:
                pass
            await query.message.edit_text(text=script.BUTTON_TXT, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            return

        if data == "autofilter":
            buttons = [[InlineKeyboardButton('Back', callback_data='filters')]]
            try:
                await client.edit_message_media(query.message.chat.id, query.message.id, InputMediaPhoto(random.choice(PICS)))
            except Exception:
                pass
            await query.message.edit_text(text=script.AUTOFILTER_TXT, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            return

        if data == "coct":
            buttons = [[InlineKeyboardButton('Back', callback_data='help')]]
            try:
                await client.edit_message_media(query.message.chat.id, query.message.id, InputMediaPhoto(random.choice(PICS)))
            except Exception:
                pass
            await query.message.edit_text(text=script.CONNECTION_TXT, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            return

        if data == "extra":
            buttons = [[InlineKeyboardButton('Back', callback_data='help'), InlineKeyboardButton('Admin', callback_data='admin')]]
            try:
                await client.edit_message_media(query.message.chat.id, query.message.id, InputMediaPhoto(random.choice(PICS)))
            except Exception:
                pass
            await query.message.edit_text(text=script.EXTRAMOD_TXT, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            return

        if data == "store_file":
            buttons = [[InlineKeyboardButton('Back', callback_data='help')]]
            try:
                await client.edit_message_media(query.message.chat.id, query.message.id, InputMediaPhoto(random.choice(PICS)))
            except Exception:
                pass
            await query.message.edit_text(text=script.FILE_STORE_TXT, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            return

        if data == "admin":
            buttons = [[InlineKeyboardButton('Back', callback_data='extra')]]
            try:
                await client.edit_message_media(query.message.chat.id, query.message.id, InputMediaPhoto(random.choice(PICS)))
            except Exception:
                pass
            await query.message.edit_text(text=script.ADMIN_TXT, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            return

        if data == "stats":
            buttons = [[InlineKeyboardButton('Back', callback_data='help'), InlineKeyboardButton('Refresh', callback_data='rfrsh')]]
            try:
                await client.edit_message_media(query.message.chat.id, query.message.id, InputMediaPhoto(random.choice(PICS)))
            except Exception:
                pass
            total = await Media.count_documents()
            users = await db.total_users_count()
            chats = await db.total_chat_count()
            monsize = await db.get_db_size()
            free = 536870912 - monsize
            monsize = get_size(monsize)
            free = get_size(free)
            await query.message.edit_text(text=script.STATUS_TXT.format(total, users, chats, monsize, free), reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            return

        if data == "rfrsh":
            await query.answer("Fetching MongoDb DataBase")
            buttons = [[InlineKeyboardButton('Back', callback_data='help'), InlineKeyboardButton('Refresh', callback_data='rfrsh')]]
            try:
                await client.edit_message_media(query.message.chat.id, query.message.id, InputMediaPhoto(random.choice(PICS)))
            except Exception:
                pass
            total = await Media.count_documents()
            users = await db.total_users_count()
            chats = await db.total_chat_count()
            monsize = await db.get_db_size()
            free = 536870912 - monsize
            monsize = get_size(monsize)
            free = get_size(free)
            await query.message.edit_text(text=script.STATUS_TXT.format(total, users, chats, monsize, free), reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            return

        # fallback
        await query.answer()
    except Exception as e:
        logger.exception("cb_handler unexpected error: %s", e)
        try:
            await query.answer("An error occurred.", show_alert=True)
        except Exception:
            pass
