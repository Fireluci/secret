import asyncio
import datetime
from html import escape
import logging
import math
import os
import re
import sys
import time
import time as _time

from pyrogram import Client, enums, filters
from pyrogram.errors import FloodWait, MessageNotModified, MessageTooLong, PeerIdInvalid, UserIsBlocked
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatJoinRequest,
    ChatMemberUpdated,
)

from database.ia_filterdb import Media, get_bad_files, get_file_details, get_search_results, unpack_new_file_id
from database.users_chats_db import db
from info import *
from utils import broadcast_messages, connected_group, get_settings, get_size, is_group_connected, is_subscribed, save_group_settings, search_gagala, temp

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
            ttl=600,
        )

async def store_pagination(key, chat_id, search, user_id):
    await db.set_cache(
        f"pagination:{key}",
        {
            "chat_id": chat_id,
            "search": search,
            "user_id": user_id or 0,
        },
        ttl=600,
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

@Client.on_callback_query(filters.regex(r"^next"))
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

        if movie_ == "close_spellcheck":
            await query.message.delete()
            return await query.answer("Closed !")

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

    if query.data == "pages":
        return await query.answer("You are on the page navigation.", show_alert=True)

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

        # Nothing remains after normalization
        if not search.strip():
            k = await message.reply_text(
                NO_RESULTS,
                disable_web_page_preview=True
            )
            asyncio.create_task(handle_auto_delete(k))
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
        # Keep the original user message as the reply target, then remove
        # the spellcheck selection message so users do not confuse results.
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
    btn.append([InlineKeyboardButton("×××× ⟨ Close ⟩ ××××", callback_data="close_data")])
    k = await msg.reply("<b>🎬 Select Your Pick ↡</b>", reply_markup=InlineKeyboardMarkup(btn))
    await asyncio.sleep(30)
    await k.delete()

logger = logging.getLogger(__name__)


# ================= PREMIUM SYSTEM =================

def fmt_date(dt: datetime) -> str:
    return (dt + timedelta(hours=5, minutes=30)).strftime('%d %b, %Y') if isinstance(dt, datetime) else "N/A"


def get_col():
    try:
        return (
            db.premium_users
            if hasattr(db, 'premium_users') and db.premium_users is not None
            else (
                db.db.premium_users
                if hasattr(db, 'db')
                else db.get_collection('premium_users')
            )
        )
    except Exception:
        return None


def get_db_collection(col_name: str):
    try:
        if hasattr(db, col_name) and getattr(db, col_name) is not None:
            return getattr(db, col_name)
        if hasattr(db, 'db') and hasattr(db.db, col_name):
            return getattr(db.db, col_name)
        return db.get_collection(col_name)
    except Exception:
        return None


async def fetch_user_name(client, uid: int) -> str:
    try:
        user = await client.get_users(uid)
        return user.first_name or "User"
    except Exception:
        return "User"


def user_link(name: str, uid: int) -> str:
    return f"<b>👤 User: <a href='tg://user?id={uid}'>{name}</a></b> (<code>{uid}</code>)"


async def get_user_display(client, uid: int, fallback_name: str = "User") -> str:
    name = await fetch_user_name(client, uid)
    if name == "User" and fallback_name != "User":
        name = fallback_name
    return user_link(name, uid)


async def is_premium_user(client, user_id: int) -> bool:
    if int(user_id) == int(OWNER):
        return True
    col = get_col()
    if not col:
        return False
    return bool(await col.find_one({
        "user_id": int(user_id),
        "active": True,
        "expires_at": {"$gt": datetime.utcnow()},
    }))


def get_plan_keyboard(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1 Month - ₹40", callback_data=f"selplan_{uid}_30d_40"),
            InlineKeyboardButton("2 Months - ₹80", callback_data=f"selplan_{uid}_60d_80"),
        ],
        [
            InlineKeyboardButton("6 Months - ₹240", callback_data=f"selplan_{uid}_180d_240"),
            InlineKeyboardButton("1 Year - ₹480", callback_data=f"selplan_{uid}_365d_480"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"min_rej_{uid}")]
    ])


def parse_plan_duration(duration_str: str):
    if duration_str == "30d":
        return timedelta(days=30), "1 Month"
    elif duration_str == "60d":
        return timedelta(days=60), "2 Months"
    elif duration_str == "180d":
        return timedelta(days=180), "6 Months"
    elif duration_str == "365d":
        return timedelta(days=365), "1 Year"
    else:
        raise ValueError("Invalid or expired plan duration selected.")


async def safe_edit_message(message, text, reply_markup=None):
    try:
        await message.edit_caption(
            text,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML,
        )
    except MessageNotModified:
        pass
    except Exception:
        try:
            await message.edit_text(
                text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML,
            )
        except MessageNotModified:
            pass


async def notify_owner(client, text):
    try:
        await client.send_message(
            int(OWNER),
            text,
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.HTML
        )
    except Exception:
        logger.exception("Failed notifying owner")


async def safe_premium_log(client, text):
    global PREMIUM_LOG

    if PREMIUM_LOG:
        try:
            log_id = int(PREMIUM_LOG)

            try:
                await client.get_chat(log_id)
            except Exception:
                await client.resolve_peer(log_id)

            await client.send_message(
                log_id,
                text,
                parse_mode=enums.ParseMode.HTML,
                disable_web_page_preview=True
            )
            return

        except Exception as e:
            logger.warning(
                "PREMIUM_LOG failed (%s), falling back to owner DM.",
                e
            )

    await notify_owner(client, text)


async def safe_kick(client: Client, chat_id, user_id) -> bool:
    if not chat_id:
        return True

    try:
        cid = int(chat_id)
    except ValueError:
        return True

    u_link = await get_user_display(client, user_id)

    try:
        await client.resolve_peer(cid)
    except Exception:
        try:
            await client.get_chat(cid)
        except Exception:
            pass

    try:
        await client.ban_chat_member(cid, user_id)
        await asyncio.sleep(0.3)
        await client.unban_chat_member(cid, user_id)
        return True
    except Exception as e:
        err_str = str(e)
        if "USER_NOT_PARTICIPANT" in err_str or "PEER_ID_INVALID" in err_str:
            return True

        await safe_premium_log(
            client,
            f"<b>⚠️ Expired User Kick Failed (1)</b>\n\n{u_link}\n"
            f"<b>❓ Reason: {e}</b>\n\n",
        )

    await asyncio.sleep(60)

    try:
        try:
            await client.resolve_peer(cid)
        except Exception:
            try:
                await client.get_chat(cid)
            except Exception:
                pass

        await client.ban_chat_member(cid, user_id)
        await asyncio.sleep(0.3)
        await client.unban_chat_member(cid, user_id)
        await safe_premium_log(
            client,
            f"<b>✅ Expired User Kick Successful</b>\n{u_link}",
        )
        return True
    except Exception as retry_err:
        await safe_premium_log(
            client,
            f"<b>⚠️ Expired User Kick Failed (2)</b>\n{u_link}\n"
            f"<b>❓ Reason: {retry_err}\n♻ Retrying in Next Loop</b>",
        )
        return False


async def premium_expiry_reminder_loop(client: Client):
    await asyncio.sleep(10)

    try:
        now = datetime.utcnow()
        col = get_col()
        if col:
            async for doc in col.find({"active": True, "expires_at": {"$lte": now}}):
                uid = doc.get("user_id")
                name = doc.get("username", "User")
                exp = doc.get("expires_at")
                user_display = user_link(name, uid)

                if PREMIUM_GROUP_ID:
                    kicked = await safe_kick(client, PREMIUM_GROUP_ID, uid)
                    if not kicked:
                        continue

                await col.delete_one({"user_id": uid})

                await safe_premium_log(
                    client,
                    f"<b>❌ Missed Expiry Catch-Up & Ejected</b>\n\n"
                    f"{user_display}\n"
                    f"<b>• Plan: {doc.get('plan', 'N/A')}</b>\n"
                    f"<b>• Expired On: {fmt_date(exp)}</b>",
                )
                try:
                    await client.send_message(
                        uid,
                        "<b>⚠️ Premium Membership Expired!</b>",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 Renew Plan", callback_data="buy_premium_start")]
                        ]),
                        parse_mode=enums.ParseMode.HTML,
                    )
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"Startup expiry check error: {e}")

    while True:
        try:
            now = datetime.utcnow()
            col = get_col()
            if col:
                async for doc in col.find({"active": True}):
                    uid, exp = doc.get("user_id"), doc.get("expires_at")
                    name = doc.get("username", "User")
                    user_display = user_link(name, uid)

                    if not isinstance(exp, datetime):
                        continue

                    reminders = doc.get("reminders", {})
                    if (
                        not reminders.get("1_day")
                        and timedelta(seconds=0) < (exp - now) <= timedelta(days=1)
                    ):
                        try:
                            await client.send_message(
                                uid,
                                "<b>⚠️ Your Premium Membership is expiring in 1 day!\n\n"
                                "Renew now to maintain uninterrupted access.</b>",
                                reply_markup=InlineKeyboardMarkup([
                                    [InlineKeyboardButton("🔄 Renew Now", callback_data="buy_premium_start")]
                                ]),
                                parse_mode=enums.ParseMode.HTML,
                            )
                            await col.update_one(
                                {"user_id": uid},
                                {"$set": {"reminders.1_day": True}},
                            )
                        except Exception:
                            pass

                    if now >= exp:
                        if PREMIUM_GROUP_ID:
                            kicked = await safe_kick(client, PREMIUM_GROUP_ID, uid)
                            if not kicked:
                                continue

                        await col.delete_one({"user_id": uid})

                        await safe_premium_log(
                            client,
                            f"<b>❌ Premium Membership Expired & Ejected</b>\n\n"
                            f"{user_display}\n"
                            f"<b>• Plan: {doc.get('plan', 'N/A')}</b>\n"
                            f"<b>• Expired On: {fmt_date(exp)}</b>",
                        )
                        try:
                            await client.send_message(
                                uid,
                                "<b>⚠️ Premium Membership Expired!\n\n"
                                "Renew your plan to restore your premium status.</b>",
                                reply_markup=InlineKeyboardMarkup([
                                    [InlineKeyboardButton("🔄 Renew Plan", callback_data="buy_premium_start")]
                                ]),
                                parse_mode=enums.ParseMode.HTML,
                            )
                        except Exception:
                            pass
        except Exception as e:
            logger.error(f"Expiry loop error: {e}")

        await asyncio.sleep(3600)


@Client.on_message(filters.command("approve") & filters.user(OWNER))
async def approve_command(client, message):
    if len(message.command) < 2:
        return await message.reply_text(
            "<b>⚠️ Usage: /approve [user_id]</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    try:
        uid = int(message.command[1])
        u_link = await get_user_display(client, uid)

        col_ses = get_db_collection("admin_approval_sessions")
        if col_ses is not None:
            await col_ses.update_one(
                {"admin_id": message.from_user.id},
                {"$set": {"target_user_id": uid}},
                upsert=True,
            )

        kb = get_plan_keyboard(uid)
        await message.reply_text(
            f"<b>💎 Select Plan Package for</b>\n{u_link}",
            reply_markup=kb,
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception as e:
        await message.reply_text(
            f"<b>❌ Error: {e}</b>",
            parse_mode=enums.ParseMode.HTML,
        )


@Client.on_message(filters.command("revoke") & filters.user(OWNER))
async def revoke_command(client, message):
    if len(message.command) < 2:
        return await message.reply_text(
            "<b>⚠️ Usage: /revoke [user_id]</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    try:
        uid = int(message.command[1])
        u_link = await get_user_display(client, uid)

        if PREMIUM_GROUP_ID:
            kicked = await safe_kick(client, PREMIUM_GROUP_ID, uid)
            if not kicked:
                return await message.reply_text(
                    f"<b>❌ Revocation Halted</b>\n\n{u_link}\n"
                    "<b>• Automated kick failed. Database record retained for safety.</b>",
                    parse_mode=enums.ParseMode.HTML,
                )

        col = get_col()
        if col:
            await col.delete_one({"user_id": uid})

        try:
            await client.send_message(
                uid,
                "<b>❌ Your Premium Membership has been revoked by administration.</b>",
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            pass

        await message.reply_text(
            f"<b>✅ Successfully revoked premium for</b>\n{u_link}",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception as e:
        await message.reply_text(
            f"<b>❌ Error: {e}</b>",
            parse_mode=enums.ParseMode.HTML,
        )


@Client.on_message(filters.command("premiums") & filters.user(OWNER))
async def premiums_command(client, message):
    col = get_col()
    if not col:
        return await message.reply_text(
            "<b>❌ Database collection unavailable.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    text = "<b>💎 Active Premium Members List:</b>\n\n"
    count = 0

    async for doc in col.find({"active": True}):
        count += 1
        uid = doc.get("user_id")
        name = doc.get("username", "User")
        plan = doc.get("plan")
        exp = fmt_date(doc.get("expires_at"))
        text += (
            f"<b>{count}.</b> {user_link(name, uid)}\n"
            f"<b>   • Plan: {plan}</b>\n"
            f"<b>   • Expires: {exp}</b>\n\n"
        )

    if count == 0:
        text = "<b>❌ No active premium users found.</b>"

    if len(text) > 4096:
        file = "premium_users.txt"
        with open(file, "w", encoding="utf-8") as f:
            f.write(text)
        await message.reply_document(file)
        os.remove(file)
    else:
        await message.reply_text(text, parse_mode=enums.ParseMode.HTML)


@Client.on_message(filters.command("myplan") & filters.private)
async def check_my_plan(client, message):
    user_id = message.from_user.id
    col = get_col()
    doc = await col.find_one({"user_id": user_id, "active": True}) if col else None
    if not doc:
        return await message.reply_text(
            "<b>❌ No active Premium subscription.</b>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🌟 Buy Premium", callback_data="buy_premium_start")]
            ]),
            parse_mode=enums.ParseMode.HTML,
        )

    plan, expires_at, price = (
        doc.get("plan"),
        doc.get("expires_at"),
        doc.get("price", "40"),
    )
    now = datetime.utcnow()
    rem = expires_at - now if expires_at and expires_at > now else None
    left_str = (
        f"{rem.days} Days"
        if rem and rem.days > 0
        else (
            f"{rem.seconds // 3600} Hours {(rem.seconds % 3600) // 60} Minutes"
            if rem
            else "Expired"
        )
    )

    await message.reply_text(
        f"<b>🌟 Premium Membership Active ✅</b>\n\n"
        f"{user_link(message.from_user.first_name, user_id)}\n"
        f"<b>💰 Plan: {plan} | ₹{price}</b>\n"
        f"<b>⌛ Expiry: {fmt_date(expires_at)}</b>\n"
        f"<b>⏳ Remaining: {left_str}</b>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Renew Plan", callback_data="buy_premium_start")]
        ]),
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("premium") & filters.private)
@Client.on_callback_query(filters.regex("^buy_premium_start$"))
async def premium_menu(client, update):
    message = update.message if isinstance(update, CallbackQuery) else update
    if isinstance(update, CallbackQuery):
        await update.answer()

    text = (
        "<b>🌟 Premium Plans:-\n\n"
        "✨ 1 Month: ₹40\n"
        "✨ 2 Months: ₹80\n"
        "✨ 6 Months: ₹240\n"
        "✨ 1 Year: ₹480</b>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Click Here To Pay", callback_data="click_here_to_pay")]
    ])

    if isinstance(update, CallbackQuery):
        try:
            await message.delete()
        except Exception:
            pass
        await client.send_message(
            message.chat.id,
            text,
            reply_markup=kb,
            parse_mode=enums.ParseMode.HTML,
        )
    else:
        await message.reply_text(
            text,
            reply_markup=kb,
            parse_mode=enums.ParseMode.HTML,
        )


@Client.on_callback_query(filters.regex("^click_here_to_pay$"))
async def click_here_to_pay_cb(client, callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass

    qr_caption = (
        f"<b>📸 Scan QR CODE or use UPI ID to Pay:\n\n"
        f"UPI ID:</b> <code>{PREMIUM_UPI_ID}</code>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I Paid", callback_data="minimal_send_proof")]
    ])

    await client.send_photo(
        chat_id=callback.message.chat.id,
        photo=PREMIUM_QR,
        caption=qr_caption,
        reply_markup=kb,
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_callback_query(filters.regex("^minimal_send_proof$"))
async def send_proof_cb(client, callback: CallbackQuery):
    try:
        col_intent = get_db_collection("user_payment_intents")
        if col_intent is not None:
            await col_intent.update_one(
                {"user_id": callback.from_user.id},
                {
                    "$set": {
                        "action": "i_paid_clicked",
                        "timestamp": datetime.datetime.utcnow(),
                    }
                },
                upsert=True,
            )
    except Exception:
        pass

    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass

    await client.send_message(
        callback.message.chat.id,
        "<b>📸 Send Payment Proof!\n\nPlease upload your transaction screenshot to verify!</b>",
        parse_mode=enums.ParseMode.HTML,
    )


async def update_user_payment_intent(client, user_id: int, action: str, file_id: str = None):
    col_intent = get_db_collection("user_payment_intents")
    if col_intent is not None:
        old_doc = await col_intent.find_one({"user_id": user_id})

        if old_doc and old_doc.get("admin_msg_ids"):
            for admin_id, msg_id in old_doc["admin_msg_ids"].items():
                try:
                    await client.delete_messages(
                        chat_id=int(admin_id),
                        message_ids=int(msg_id),
                    )
                except Exception:
                    pass

        data = {
            "user_id": user_id,
            "action": action,
            "file_id": file_id,
            "timestamp": datetime.utcnow(),
            "admin_msg_ids": {},
        }
        await col_intent.update_one(
            {"user_id": user_id},
            {"$set": data},
            upsert=True,
        )


@Client.on_message(filters.private & (filters.photo | filters.document) & ~filters.command(["start", "premium"]))
async def screenshot_handler(client, message):
    user_id = message.from_user.id
    is_valid_intent = False

    try:
        col_intent = get_db_collection("user_payment_intents")
        if col_intent is not None:
            doc = await col_intent.find_one({"user_id": user_id})
            if doc:
                is_valid_intent = True
                if doc.get("admin_msg_ids"):
                    for admin_id, msg_id in doc["admin_msg_ids"].items():
                        try:
                            await client.delete_messages(
                                chat_id=int(admin_id),
                                message_ids=int(msg_id),
                            )
                        except Exception:
                            pass
    except Exception:
        pass

    if not is_valid_intent:
        return

    await message.reply_text(
        "<b>✅ Your screenshot has been submitted for verification, please wait!</b>",
        parse_mode=enums.ParseMode.HTML,
    )

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"min_app_{user_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"min_rej_{user_id}"),
        ]
    ])
    text = (
        f"<b>🔔 New Payment Verification</b>\n\n"
        f"{user_link(message.from_user.first_name, user_id)}"
    )

    fid = message.photo.file_id if message.photo else message.document.file_id
    admin_msg_ids = {}

    try:
        sent_msg = None
        if message.photo:
            sent_msg = await client.send_photo(
                int(OWNER),
                fid,
                caption=text,
                reply_markup=kb,
                parse_mode=enums.ParseMode.HTML,
            )
        else:
            sent_msg = await client.send_document(
                int(OWNER),
                fid,
                caption=text,
                reply_markup=kb,
                parse_mode=enums.ParseMode.HTML,
            )

        if sent_msg:
            admin_msg_ids[str(OWNER)] = sent_msg.id
    except Exception:
        pass

    try:
        col_intent = get_db_collection("user_payment_intents")
        if col_intent is not None:
            await col_intent.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "admin_msg_ids": admin_msg_ids,
                        "action": "screenshot_sent",
                        "timestamp": datetime.utcnow(),
                    }
                },
                upsert=True,
            )
    except Exception:
        pass


@Client.on_callback_query(filters.regex("^min_app_"))
async def admin_app_cb(client, callback: CallbackQuery):
    if callback.from_user.id != OWNER:
        return await callback.answer("Unauthorized.", show_alert=True)

    uid = int(callback.data.split("_")[2])

    try:
        col_ses = get_db_collection("admin_approval_sessions")
        if col_ses is not None:
            await col_ses.update_one(
                {"admin_id": callback.from_user.id},
                {"$set": {"target_user_id": uid}},
                upsert=True,
            )
    except Exception:
        pass

    kb = get_plan_keyboard(uid)
    await callback.answer()
    text = "<b>💎 Select Plan Package</b>"
    await safe_edit_message(callback.message, text, reply_markup=kb)


@Client.on_callback_query(filters.regex("^selplan_"))
async def select_plan_cb(client, callback: CallbackQuery):
    if callback.from_user.id != OWNER:
        return await callback.answer("Unauthorized.", show_alert=True)

    _, uid_str, duration_str, price = callback.data.split("_")
    uid = int(uid_str)

    now = datetime.utcnow()
    delta, plan_name = parse_plan_duration(duration_str)

    col = get_col()
    existing = await col.find_one({"user_id": uid, "active": True}) if col else None
    start = (
        existing.get("expires_at")
        if existing
        and isinstance(existing.get("expires_at"), datetime)
        and existing.get("expires_at") > now
        else now
    )
    exp = start + delta

    u_link = await get_user_display(client, uid)

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm", callback_data=f"confact_{uid}_{duration_str}_{price}"),
            InlineKeyboardButton("◀ Back", callback_data=f"min_app_{uid}"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"min_rej_{uid}")],
    ])
    text = (
        f"<b>💎 Preview Panel</b>\n\n"
        f"{u_link}\n"
        f"<b>✨ Plan: {plan_name} | ₹{price}</b>\n"
        f"<b>📆 Expiry: {fmt_date(exp)}</b>"
    )

    await callback.answer()
    await safe_edit_message(callback.message, text, reply_markup=kb)


@Client.on_callback_query(filters.regex("^confact_"))
async def conf_act_cb(client, callback: CallbackQuery):
    if callback.from_user.id != OWNER:
        return await callback.answer("Unauthorized.", show_alert=True)

    _, uid_str, duration_str, price = callback.data.split("_")
    uid = int(uid_str)

    now = datetime.utcnow()
    delta, plan = parse_plan_duration(duration_str)

    name = await fetch_user_name(client, uid)
    u_link = user_link(name, uid)
    await callback.answer("Activating...")

    col = get_col()
    existing = await col.find_one({"user_id": uid, "active": True}) if col else None
    is_renewal = existing is not None
    start = (
        existing.get("expires_at")
        if existing
        and isinstance(existing.get("expires_at"), datetime)
        and existing.get("expires_at") > now
        else now
    )
    exp = start + delta

    if PREMIUM_GROUP_ID:
        try:
            cid = int(PREMIUM_GROUP_ID)
            await client.unban_chat_member(cid, uid)
            await client.approve_chat_join_request(chat_id=cid, user_id=uid)
        except Exception:
            pass

    data = {
        "user_id": uid,
        "username": name,
        "plan": plan,
        "price": price,
        "purchased_at": now,
        "expires_at": exp,
        "active": True,
        "reminders": {"1_day": False},
    }
    if col:
        await col.update_one({"user_id": uid}, {"$set": data}, upsert=True)

    try:
        col_intent = get_db_collection("user_payment_intents")
        col_ses = get_db_collection("admin_approval_sessions")
        if col_intent is not None:
            await col_intent.delete_many({"user_id": uid})
        if col_ses is not None:
            await col_ses.delete_many({"admin_id": callback.from_user.id})
    except Exception:
        pass

    link = PREMIUM_PERMANENT_LINK or "https://t.me/your_group_link"
    title_msg = (
        "<b>🌟 Premium Membership Renewed ✅</b>"
        if is_renewal
        else "<b>🌟 Premium Membership Active ✅</b>"
    )
    try:
        await client.send_message(
            uid,
            f"{title_msg}\n\n"
            f"<b>💰 Plan: {plan} | ₹{price}</b>\n"
            f"<b>⌛ Expiry: {fmt_date(exp)}</b>\n\n"
            f"<b>✨ Join Premium Group:</b>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🧤 Click Here To Join", url=link)]
            ]),
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass

    log_title = (
        "<b>🌟 Premium Renewed ✅</b>"
        if is_renewal
        else "<b>🌟 Premium Activated ✅</b>"
    )
    await safe_premium_log(
        client,
        f"{log_title}\n\n{u_link}\n"
        f"<b>• 💰 Plan: {plan} | ₹{price}</b>\n"
        f"<b>• ⌛ Expiry: {fmt_date(exp)}</b>",
    )

    success_text = f"<b>✅ Activated Successfully</b>\n{u_link}"
    await safe_edit_message(callback.message, success_text, reply_markup=None)


@Client.on_chat_join_request()
async def auto_accept(client, req: ChatJoinRequest):
    if PREMIUM_GROUP_ID and req.chat.id == int(PREMIUM_GROUP_ID):
        col = get_col()
        if col and await col.find_one({"user_id": req.from_user.id, "active": True}):
            try:
                await client.approve_chat_join_request(req.chat.id, req.from_user.id)
            except Exception:
                pass


@Client.on_chat_member_updated()
async def member_update(client, update: ChatMemberUpdated):
    if not PREMIUM_GROUP_ID:
        return
    try:
        if update.chat.id != int(PREMIUM_GROUP_ID):
            return
    except ValueError:
        return

    old = (
        update.old_chat_member.status
        if update.old_chat_member
        else enums.ChatMemberStatus.LEFT
    )
    new = (
        update.new_chat_member.status
        if update.new_chat_member
        else enums.ChatMemberStatus.LEFT
    )

    if old in [enums.ChatMemberStatus.LEFT, enums.ChatMemberStatus.BANNED] and new in [
        enums.ChatMemberStatus.MEMBER,
        enums.ChatMemberStatus.ADMINISTRATOR,
        enums.ChatMemberStatus.OWNER,
    ]:
        user = update.new_chat_member.user
        if not user or user.is_bot:
            return
        col = get_col()
        if col:
            doc = await col.find_one({"user_id": user.id, "active": True})
            if not doc:
                return
            link = PREMIUM_PERMANENT_LINK or "https://t.me/your_group_link"
            text = (
                f"<b>🌟 Premium Activated ✅</b>\n\n"
                f"{user_link(user.first_name, user.id)}\n"
                f"<b>💰 Plan: {doc.get('plan')} | ₹{doc.get('price')}</b>\n"
                f"<b>⌛ Expiry: {fmt_date(doc.get('expires_at'))}</b>"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✨ Premium Group", url=link)]
            ])
            try:
                await client.send_message(
                    user.id,
                    text,
                    reply_markup=kb,
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                pass


@Client.on_callback_query(filters.regex("^min_rej_"))
async def admin_reject_cb(client, callback: CallbackQuery):
    if callback.from_user.id != OWNER:
        return await callback.answer("Unauthorized.", show_alert=True)

    uid = int(callback.data.split("_")[-1])
    try:
        col_intent = get_db_collection("user_payment_intents")
        col_ses = get_db_collection("admin_approval_sessions")
        if col_intent is not None:
            await col_intent.delete_many({"user_id": uid})
        if col_ses is not None:
            await col_ses.delete_many({"admin_id": callback.from_user.id})
    except Exception:
        pass

    await callback.answer("Rejected.")
    try:
        await client.send_message(
            uid,
            "<b>⚠️ Payment Verification Failed.\n\nPlease Pay and Send a Valid Screenshot.</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass

    await safe_edit_message(
        callback.message,
        "<b>❌ Status: REJECTED</b>",
        reply_markup=None,
    )


async def start_premium_tasks(client):
    asyncio.create_task(premium_expiry_reminder_loop(client))


# ================= AUTOFILTER FILE DELIVERY =================

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


async def delete_later(message, seconds=600):
    await asyncio.sleep(seconds)
    try:
        await message.delete()
    except Exception:
        pass

@Client.on_message(filters.command("start") & filters.incoming)
async def start(client, message):
    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        if not await is_group_connected(message.chat.id):
            return
        buttons = []
        await message.reply(
            START_TXT.format(
                message.from_user.mention if message.from_user else message.chat.title,
                temp.U_NAME,
                temp.B_NAME,
            ),
            reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
            disable_web_page_preview=True,
        )
        return

    if not message.from_user:
        return

    ban_status = await db.get_ban_status(message.from_user.id)
    if ban_status.get("is_banned"):
        return await message.reply_text(
            f'Sorry Dude, You are Banned to use Me.\nBan Reason: {ban_status.get("ban_reason", "No Reason")}'
        )

    if not await db.is_user_exist(message.from_user.id):
        await db.add_user(message.from_user.id, message.from_user.first_name)
        try:
            await client.send_message(LOG_CHANNEL, LOG_TEXT_P.format(message.from_user.id, message.from_user.mention))
        except Exception:
            pass

    if len(message.command) != 2:
        buttons = [
            [InlineKeyboardButton("🌟 Paid (No Ads)", url="https://telegram.me/HeroFlixx/49"), InlineKeyboardButton("🍿 Free (With Ads)", url="https://telegram.me/addlist/X5k2lnJLIGAyZjQ1")],
            [InlineKeyboardButton("👤 Admin", url=f"https://telegram.me/{SUPPORT_CHAT}"), InlineKeyboardButton("⚜ Updates", url=FORCE)],
        ]
        return await message.reply_photo(
            photo=PICS,
            caption=START_TXT.format(message.from_user.mention, temp.U_NAME, temp.B_NAME),
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=enums.ParseMode.HTML,
        )

    if len(message.command) == 2 and message.command[1] == "i_paid":
        col_intent = get_db_collection("user_payment_intents")
        if col_intent is not None:
            await col_intent.update_one(
                {"user_id": message.from_user.id},
                {
                    "$set": {
                        "action": "i_paid_clicked",
                        "timestamp": datetime.datetime.utcnow(),
                    }
                },
                upsert=True,
            )
        return await message.reply_text(
            "<b>📸 Send Payment Proof!\n\nPlease upload your transaction screenshot to verify!</b>",
            parse_mode=enums.ParseMode.HTML,
        )

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
    if data in {"subscribe", "error", "okay", "help"}:
        buttons = [
            [InlineKeyboardButton("🌟 Paid (No Ads)", url="https://telegram.me/HeroFlixx/49"), InlineKeyboardButton("🍿 Free (With Ads)", url="https://telegram.me/addlist/X5k2lnJLIGAyZjQ1")],
            [InlineKeyboardButton("👤 Admin", url=f"https://telegram.me/{SUPPORT_CHAT}"), InlineKeyboardButton("⚜ Updates", url=FORCE)],
        ]
        return await message.reply_photo(
            photo=PICS,
            caption=START_TXT.format(message.from_user.mention, temp.U_NAME, temp.B_NAME),
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=enums.ParseMode.HTML,
        )

    if "_" in data:
        pre, payload = data.split("_", 1)
    else:
        pre, payload = "file", data

    if pre not in {"file", "files"}:
        return

    file_id = payload

    if not await is_premium_user(client, message.from_user.id):
        return await message.reply_text(
            "<b>🔒 This file is exclusive to Premium members.</b>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 Buy Premium", callback_data="buy_premium_start")]
            ]),
            parse_mode=enums.ParseMode.HTML,
        )

    if not await send_file_to_user(client, message.from_user.id, file_id):
        await message.reply("No such file exist.")

