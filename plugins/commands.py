import os
import re
import sys
import asyncio
import logging
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database.ia_filterdb import Media, get_file_details, unpack_new_file_id, get_bad_files
from database.users_chats_db import db
from info import *
from utils import get_settings, get_size, is_subscribed, save_group_settings, temp, get_shortlink, is_group_connected

logger = logging.getLogger(__name__)

def tutorial_url():
    if not TUTORIAL:
        return None
    return TUTORIAL if str(TUTORIAL).startswith("http") else f"https://telegram.me/{TUTORIAL}"

async def send_file_to_user(client, user_id, file_id):
    files = await get_file_details(file_id)
    if not files:
        return False
    file = files[0]
    title = " ".join(x for x in (file.file_name or "").split() if not x.startswith(("www.", "@")))
    caption = title
    if CUSTOM_FILE_CAPTION:
        try:
            caption = CUSTOM_FILE_CAPTION.format(
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
        return None

    msg = await client.send_message(
        chat_id=user_id,
        text=f'<b>🔆 [ {get_size(file.file_size)} ] <a href="https://telegram.me/HEROFLiX">{title}</a>\n\n📥 Download Link↓\n{short_url}</b>',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("♻️ Download Link ♻️", url=short_url)],
            [InlineKeyboardButton("❓ How To Download ❓", url=tutorial_url())],
        ]),
    )
    asyncio.create_task(delete_later(msg))
    return True

async def delete_later(message, seconds=900):
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
        tut = tutorial_url()
        if tut:
            buttons = [[InlineKeyboardButton('❓How To Use Me❓', url=tut)]]
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

    if pre not in {"file", "files", "short"}:
        return

    if pre == "short":
        file_id = payload
        short_cache = getattr(temp, "SHORT", {})
        chat_id = short_cache.get((message.from_user.id, file_id)) or short_cache.get(message.from_user.id)
        if chat_id is None:
            return await message.reply("Invalid or expired link.")
        result = await send_shortlink_page(client, message.from_user.id, file_id, chat_id)
        if result is None:
            return await message.reply("❌ Link generation failed. Please try again later.")
        if result is False:
            return await message.reply("No such file exist.")
        return

    if pre == "files":
        file_id = payload
        short_cache = getattr(temp, "SHORT", {})
        chat_id = short_cache.get((message.from_user.id, file_id)) or short_cache.get(message.from_user.id)
        if chat_id is None:
            return await message.reply_text("<b>Link Expired, Search Again in Group!</b>")

        settings = await get_settings(chat_id)
        if settings.get("is_shortlink", IS_SHORTLINK):
            result = await send_shortlink_page(client, message.from_user.id, file_id, chat_id)
            if result is None:
                return await message.reply("❌ Link generation failed. Please try again later.")
            if result is False:
                return await message.reply("No such file exist.")
            return

    if not await send_file_to_user(client, message.from_user.id, file_id):
        await message.reply("No such file exist.")

@Client.on_message(filters.command('channel') & filters.user(ADMINS))
async def channel_info(bot, message):
    channels = CHANNELS if isinstance(CHANNELS, list) else [CHANNELS]
    text = '📑 **Indexed channels/groups**\n'
    for channel in channels:
        try:
            chat = await bot.get_chat(channel)
            text += '\n@' + chat.username if chat.username else '\n' + (chat.title or chat.first_name)
        except Exception:
            continue
    text += f'\n\n**Total:** {len(channels)}'
    await message.reply(text)

@Client.on_message(filters.command('logs') & filters.user(ADMINS))
async def log_file(bot, message):
    try:
        await message.reply_document('TelegramBot.log')
    except Exception as e:
        await message.reply(str(e))

@Client.on_message(filters.command('delete') & filters.user(ADMINS))
async def delete(bot, message):
    reply = message.reply_to_message
    if not reply or not reply.media:
        return await message.reply('Reply to file with /delete which you want to delete', quote=True)

    msg = await message.reply("Processing...⏳", quote=True)
    for file_type in ("document", "video", "audio"):
        media = getattr(reply, file_type, None)
        if media is not None:
            break
    else:
        return await msg.edit('This is not supported file format')

    file_id, _ = unpack_new_file_id(media.file_id)
    result = await Media.collection.delete_one({'_id': file_id})
    if result.deleted_count:
        return await msg.edit('🛃 Deleted File!')

    file_name = re.sub(r"(_|\-|\.|\+)", " ", str(media.file_name))
    result = await Media.collection.delete_many({'file_name': file_name, 'file_size': media.file_size, 'mime_type': media.mime_type})
    if result.deleted_count:
        return await msg.edit('🛃 Deleted File!')

    result = await Media.collection.delete_many({'file_name': media.file_name, 'file_size': media.file_size, 'mime_type': media.mime_type})
    await msg.edit('🛃 Deleted File!' if result.deleted_count else 'File not found in database')

@Client.on_message(filters.command('deleteall') & filters.user(ADMINS))
async def delete_all_index(bot, message):
    await message.reply_text(
        'This will delete all indexed files.\nDo you want to continue??',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(text="🛃 Delete Files!", callback_data="autofilter_delete")],
            [InlineKeyboardButton(text="💢 Cancel 💢", callback_data="close_data")],
        ]),
        quote=True,
    )

@Client.on_callback_query(filters.regex(r'^autofilter_delete$'))
async def delete_all_index_confirm(bot, callback):
    if callback.from_user.id not in ADMINS:
        return await callback.answer("Unauthorized!", show_alert=True)
    await Media.collection.drop()
    await callback.answer('Done')
    await callback.message.edit('Successfully deleted all the indexed files.')

def get_settings_keyboard(settings: dict):
    spell = bool(settings.get("spell_check", SPELL_CHECK_REPLY))
    short = bool(settings.get("is_shortlink", IS_SHORTLINK))
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Spell Check", callback_data=f"setgs#spell_check#{spell}"), InlineKeyboardButton("✔ Oɴ" if spell else "✘ Oғғ", callback_data=f"setgs#spell_check#{spell}")],
        [InlineKeyboardButton("ShortLink", callback_data=f"setgs#is_shortlink#{short}"), InlineKeyboardButton("✔ Oɴ" if short else "✘ Oғғ", callback_data=f"setgs#is_shortlink#{short}")],
    ])

@Client.on_callback_query(filters.regex(r'^setgs#'))
async def settings_callback(client, callback):
    if callback.from_user.id not in ADMINS:
        return await callback.answer("Only bot admins can change settings.", show_alert=True)
    try:
        _, setting, _ = callback.data.split("#")
    except Exception:
        return await callback.answer("Invalid setting.", show_alert=True)
    if setting not in {"spell_check", "is_shortlink"}:
        return await callback.answer("Invalid setting.", show_alert=True)

    chat_id = callback.message.chat.id
    if chat_id and callback.message.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
        if not await is_group_connected(chat_id):
            return await callback.answer("This group is disconnected.", show_alert=True)
    settings = await get_settings(chat_id)
    current = bool(settings.get(setting))
    await save_group_settings(chat_id, setting, not current)
    settings = await get_settings(chat_id)
    try:
        await callback.message.edit_reply_markup(reply_markup=get_settings_keyboard(settings))
    except Exception:
        pass
    await callback.answer("Updated")

@Client.on_message(filters.command('settings') & filters.user(ADMINS))
async def settings(client, message):
    if message.chat.type not in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        return await message.reply_text("Use /settings inside a connected group.")
    if not await is_group_connected(message.chat.id):
        return
    settings = await get_settings(message.chat.id)
    await message.reply_text(
        f"<b>⚙️ Settings For {message.chat.title}</b>",
        reply_markup=get_settings_keyboard(settings),
        parse_mode=enums.ParseMode.HTML,
        reply_to_message_id=message.id,
    )

@Client.on_message(filters.command("deletefiles") & filters.user(ADMINS))
async def deletemultiplefiles(bot, message):
    if message.chat.type != enums.ChatType.PRIVATE:
        return await message.reply_text("<b>Only Works in PM !</b>")
    try:
        keyword = message.text.split(" ", 1)[1]
    except Exception:
        return await message.reply_text(f"<b>Hey {message.from_user.mention}, Give me a keyword along with the command to delete files.</b>")
    k = await bot.send_message(chat_id=message.chat.id, text="<b>♻️ Please Wait!</b>")
    files, total = await get_bad_files(keyword)
    await k.delete()
    await message.reply_text(
        text=f"<b>{total} Files ➠ {keyword}</b>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛃 Delete Files!", callback_data=f"killfilesdq#{keyword}")],
            [InlineKeyboardButton("💢 Cancel 💢", callback_data="close_data")],
        ]),
        parse_mode=enums.ParseMode.HTML,
    )

@Client.on_message(filters.command("shortlink1") & filters.user(ADMINS))
async def update_shortlink1(bot, message):
    if message.chat.type == enums.ChatType.PRIVATE:
        return await message.reply_text("<b>Only works in groups !</b>")
    if not await is_group_connected(message.chat.id):
        return await message.reply_text("Connect this group first with /connect.")
    try:
        _, shortlink_url, api = message.text.split(" ", 2)
    except Exception:
        return await message.reply_text("<b>Wrong Format. Example - /shortlink1 softurl.in YOUR_API</b>")

    reply = await message.reply_text("<b>Please Wait...</b>")
    shortlink_url = re.sub(r"[:/]", "", re.sub(r"https?://?", "", shortlink_url))
    await save_group_settings(message.chat.id, 'shortlink', shortlink_url)
    await save_group_settings(message.chat.id, 'shortlink_api', api)
    await save_group_settings(message.chat.id, 'is_shortlink', True)
    await reply.edit_text(f"<b>Successfully updated Primary Shortener (Short1)!\n\nWebsite: <code>{shortlink_url}</code>\nAPI: <code>{api}</code></b>")
    await asyncio.sleep(10)
    await reply.delete()

@Client.on_message(filters.command("shortlink2") & filters.user(ADMINS))
async def update_shortlink2(bot, message):
    if message.chat.type == enums.ChatType.PRIVATE:
        return await message.reply_text("<b>Only works in groups !</b>")
    if not await is_group_connected(message.chat.id):
        return await message.reply_text("Connect this group first with /connect.")
    try:
        _, shortlink_url, api = message.text.split(" ", 2)
    except Exception:
        return await message.reply_text("<b>Wrong Format. Example - /shortlink2 nowshort.com YOUR_API</b>")

    reply = await message.reply_text("<b>Please Wait...</b>")
    shortlink_url = re.sub(r"[:/]", "", re.sub(r"https?://?", "", shortlink_url))
    await save_group_settings(message.chat.id, 'second_shortlink', shortlink_url)
    await save_group_settings(message.chat.id, 'second_shortlink_api', api)
    await save_group_settings(message.chat.id, 'is_shortlink', True)
    await reply.edit_text(f"<b>Successfully updated Secondary Shortener (Short2)!\n\nWebsite: <code>{shortlink_url}</code>\nAPI: <code>{api}</code></b>")
    await asyncio.sleep(10)
    await reply.delete()

@Client.on_message(filters.command("shorteners") & filters.user(ADMINS))
async def view_shorteners(bot, message):
    if message.chat.type == enums.ChatType.PRIVATE:
        return await message.reply_text("<b>Only works in groups !</b>")
    if not await is_group_connected(message.chat.id):
        return await message.reply_text("Connect this group first with /connect.")
    settings = await get_settings(message.chat.id)
    s1_url = settings.get('shortlink') or SHORT1_URL
    s1_api = settings.get('shortlink_api') or SHORT1_API
    s2_url = settings.get('second_shortlink') or SHORT2_URL
    s2_api = settings.get('second_shortlink_api') or SHORT2_API
    is_active = settings.get('is_shortlink', IS_SHORTLINK)
    await message.reply_text(
        f"⚙️ **Current Group Shortener Configuration**\n\n"
        f"• **Status:** `{'Enabled' if is_active else 'Disabled'}`\n"
        f"• **Primary (Short1):** `{s1_url}` (API: `{s1_api}`)\n"
        f"• **Secondary (Short2):** `{s2_url}` (API: `{s2_api}`)",
        parse_mode=enums.ParseMode.MARKDOWN,
    )

@Client.on_message(filters.command("restart") & filters.user(ADMINS))
async def stop_button(bot, message):
    msg = await bot.send_message(text="**🔄 𝙱𝙾𝚃 𝙸𝚂 𝚁𝙴𝚂𝚃𝙰𝚁𝚃𝙸𝙽𝙶**", chat_id=message.chat.id)
    await asyncio.sleep(60)
    await msg.edit("**✅️ 𝙱𝙾𝚃 𝙸𝚂 𝚁𝙴𝚂𝚃𝙰𝚁𝚃𝙴𝙳**")
    os.execl(sys.executable, sys.executable, *sys.argv)
