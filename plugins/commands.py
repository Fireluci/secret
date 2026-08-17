import asyncio
import logging
import os
import re
import sys

from pyrogram import Client, enums, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import FloodWait

from database.ia_filterdb import Media, get_bad_files, get_file_details, unpack_new_file_id
from database.users_chats_db import db
from info import (
    ADMINS, AUTH_CHANNEL, CHANNELS, CHNL_LNK, CUSTOM_FILE_CAPTION, FORCE, LOG_CHANNEL,
    PICS, PREMIUM_USER, SUPPORT_CHAT, TUTORIAL
)
from utils import (
    connected_group, get_settings, save_group_settings, get_shortlink, get_size, is_subscribed,
    temp
)
from Script import script

logger = logging.getLogger(__name__)


def tutorial_url():
    return TUTORIAL if TUTORIAL.startswith("http") else f"https://telegram.me/{TUTORIAL}"


async def send_indexed_file(client, user_id, file_id):
    files = await get_file_details(file_id)
    if not files:
        return False

    file = files[0]
    title = " ".join(
        x for x in (file.file_name or "").split()
        if not x.startswith(("www.", "@"))
    )
    size = get_size(file.file_size)

    caption = title
    if CUSTOM_FILE_CAPTION:
        try:
            caption = CUSTOM_FILE_CAPTION.format(
                file_name=title,
                file_size=size,
                file_caption="",
            )
        except Exception:
            logger.exception("Invalid CUSTOM_FILE_CAPTION")

    await client.send_cached_media(
        chat_id=user_id,
        file_id=file.file_id,
        caption=caption,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔆彡⟨ HEROFLiX ⟩彡🔆", url=f"https://telegram.me/{CHNL_LNK}")]]
        ),
    )
    return True


@Client.on_message(filters.command("start") & filters.incoming & connected_group)
async def start(client, message):
    if message.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
        await message.reply(
            script.START_TXT.format(
                message.from_user.mention if message.from_user else message.chat.title,
                temp.U_NAME,
                temp.B_NAME,
            ),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("❓How To Use Me❓", url=tutorial_url())]]
            ),
            disable_web_page_preview=True,
        )
        return

    if not message.from_user:
        return

    if not await db.is_user_exist(message.from_user.id):
        await db.add_user(message.from_user.id, message.from_user.first_name)
        try:
            await client.send_message(
                LOG_CHANNEL,
                script.LOG_TEXT_P.format(message.from_user.id, message.from_user.mention),
            )
        except Exception:
            pass

    if len(message.command) != 2:
        await message.reply_photo(
            photo=PICS,
            caption=script.START_TXT.format(
                message.from_user.mention, temp.U_NAME, temp.B_NAME
            ),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🌟 Paid (No Ads)", url="https://telegram.me/HeroFlixx/49"),
                    InlineKeyboardButton("🍿 Free (With Ads)", url="https://telegram.me/addlist/X5k2lnJLIGAyZjQ1"),
                ],
                [
                    InlineKeyboardButton("👤 Admin", url=f"https://telegram.me/{SUPPORT_CHAT}"),
                    InlineKeyboardButton("⚜ Updates", url=FORCE),
                ],
            ]),
            parse_mode=enums.ParseMode.HTML,
        )
        return

    if AUTH_CHANNEL and not await is_subscribed(client, message):
        payload = message.text.split(" ", 1)[1]
        retry = f"https://telegram.me/{temp.U_NAME}?start={payload}"
        await client.send_message(
            message.from_user.id,
            "**🔆 First Join Our Main Channel & Then Click Try Again ♻**",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏮 Main Channel ⟨Click Here⟩ 🏮", url=FORCE)],
                [InlineKeyboardButton("🔄 Try Again", url=retry)],
            ]),
        )
        return

    data = message.command[1]
    parts = data.split("_", 2)
    pre = parts[0]
    payload_chat_id = None

    if pre in {"files", "short"} and len(parts) == 3:
        try:
            payload_chat_id = int(parts[1])
            file_id = parts[2]
        except ValueError:
            file_id = data.split("_", 1)[1]
    else:
        file_id = data.split("_", 1)[1] if "_" in data else data

    if pre == "short":
        chat_id = payload_chat_id
        if chat_id is None:
            return await message.reply("Invalid or expired link.")

        try:
            short_url = await get_shortlink(
                chat_id,
                f"https://telegram.me/{temp.U_NAME}?start=file_{file_id}",
                client=client,
            )
        except Exception:
            return await message.reply("❌ Link generation failed. Please try again later.")

        files = await get_file_details(file_id)
        if not files:
            return await message.reply("No such file exist.")

        file = files[0]
        title = " ".join(
            x for x in (file.file_name or "").split()
            if not x.startswith(("www.", "@"))
        )
        msg = await message.reply_text(
            f"<b>[ {get_size(file.file_size)} ] {title}</b>\n\n📗 Download Link ➔ {short_url}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("♻️ Download Link ♻️", url=short_url)],
                [InlineKeyboardButton("❓ How To Download ❓", url=tutorial_url())],
            ]),
        )
        await asyncio.sleep(900)
        try:
            await msg.delete()
        except Exception:
            pass
        return

    if pre == "files":
        chat_id = payload_chat_id
        settings = await get_settings(chat_id) if chat_id is not None else {
            "is_shortlink": IS_SHORTLINK
        }

        if settings["is_shortlink"] and message.from_user.id not in PREMIUM_USER:
            try:
                short_url = await get_shortlink(
                    chat_id,
                    f"https://telegram.me/{temp.U_NAME}?start=file_{file_id}",
                    client=client,
                )
                msg = await message.reply_text(
                    f"<b>📗 Download Link ➔ {short_url}</b>",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("♻️ Download Link ♻️", url=short_url)],
                        [InlineKeyboardButton("❓ How To Download ❓", url=tutorial_url())],
                    ]),
                )
                await asyncio.sleep(900)
                try:
                    await msg.delete()
                except Exception:
                    pass
                return
            except Exception:
                return await message.reply("❌ Link generation failed. Please try again later.")

        return await send_indexed_file(client, message.from_user.id, file_id)

    if pre == "file" or not pre:
        if not await send_indexed_file(client, message.from_user.id, file_id):
            return await message.reply("No such file exist.")


@Client.on_message(filters.command("channel") & filters.user(ADMINS) & connected_group)
async def channel_info(bot, message):
    channels = CHANNELS if isinstance(CHANNELS, list) else [CHANNELS]
    text = "📑 **Indexed channels/groups**\n"
    for channel in channels:
        chat = await bot.get_chat(channel)
        text += f"\n@{chat.username}" if chat.username else f"\n{chat.title or chat.first_name}"
    text += f"\n\n**Total:** {len(channels)}"
    await message.reply(text)


@Client.on_message(filters.command("logs") & filters.user(ADMINS) & connected_group)
async def log_file(bot, message):
    try:
        await message.reply_document("TelegramBot.log")
    except Exception as e:
        await message.reply(str(e))


@Client.on_message(filters.command("delete") & filters.user(ADMINS) & connected_group)
async def delete(bot, message):
    reply = message.reply_to_message
    if not reply or not reply.media:
        return await message.reply("Reply to a file with /delete.")

    media = next(
        (getattr(reply, t, None) for t in ("document", "video", "audio")
         if getattr(reply, t, None) is not None),
        None,
    )
    if not media:
        return await message.reply("This is not a supported file format.")

    msg = await message.reply("Processing...", quote=True)
    file_id, _ = unpack_new_file_id(media.file_id)

    result = await Media.collection.delete_one({"_id": file_id})
    if not result.deleted_count:
        result = await Media.collection.delete_many({
            "file_name": re.sub(r"(_|\-|\.|\+)", " ", str(media.file_name)),
            "file_size": media.file_size,
            "mime_type": media.mime_type,
        })

    await msg.edit("🛃 Deleted File!" if result.deleted_count else "File not found in database")


@Client.on_message(filters.command("deleteall") & filters.user(ADMINS) & connected_group)
async def delete_all_index(bot, message):
    await message.reply_text(
        "This will delete all indexed files.\n\nDo you want to continue?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛃 Delete Files!", callback_data="autofilter_delete")],
            [InlineKeyboardButton("💢 Cancel 💢", callback_data="close_data")],
        ]),
    )


@Client.on_callback_query(filters.regex(r"^autofilter_delete") & filters.user(ADMINS) & connected_group)
async def delete_all_index_confirm(bot, callback):
    await Media.collection.drop()
    await callback.answer("Deleted all indexed files.", show_alert=True)
    await callback.message.edit("Successfully deleted all indexed files.")


@Client.on_message(filters.command("deletefiles") & filters.user(ADMINS) & connected_group)
async def deletemultiplefiles(bot, message):
    if message.chat.type != enums.ChatType.PRIVATE:
        return await message.reply_text("Only works in PM.")
    parts = message.text.split(" ", 1)
    if len(parts) != 2:
        return await message.reply_text("Give me a keyword along with the command.")
    wait = await message.reply_text("♻️ Please Wait!")
    keyword = parts[1]
    files, total = await get_bad_files(keyword)
    await wait.delete()
    await message.reply_text(
        f"<b>{total} Files ➠ {keyword}</b>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛃 Delete Files!", callback_data=f"killfilesdq#{keyword}")],
            [InlineKeyboardButton("💢 Cancel 💢", callback_data="close_data")],
        ]),
        parse_mode=enums.ParseMode.HTML,
    )




def get_settings_keyboard(settings):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Sᴘᴇʟʟ Cʜᴇᴄᴋ", callback_data="setgs#spell_check"),
            InlineKeyboardButton(
                "✔ Oɴ" if settings["spell_check"] else "✘ Oғғ",
                callback_data="setgs#spell_check",
            ),
        ],
        [
            InlineKeyboardButton("SʜᴏʀᴛLɪɴᴋ", callback_data="setgs#is_shortlink"),
            InlineKeyboardButton(
                "✔ Oɴ" if settings["is_shortlink"] else "✘ Oғғ",
                callback_data="setgs#is_shortlink",
            ),
        ],
    ])


@Client.on_callback_query(filters.regex(r"^setgs#") & filters.user(ADMINS) & connected_group)
async def settings_callback(client, callback):
    setting = callback.data.split("#", 1)[1]
    if setting not in {"spell_check", "is_shortlink"}:
        return await callback.answer("Invalid setting.", show_alert=True)

    chat_id = callback.message.chat.id
    settings = await get_settings(chat_id)
    await save_group_settings(chat_id, setting, not settings[setting])
    settings = await get_settings(chat_id)

    await callback.message.edit_reply_markup(get_settings_keyboard(settings))
    await callback.answer("Updated.")


@Client.on_message(filters.command("settings") & filters.user(ADMINS) & connected_group)
async def settings(client, message):
    if message.chat.type not in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
        return await message.reply_text("Use /settings inside a connected group.")

    settings = await get_settings(message.chat.id)
    await message.reply_text(
        f"<b>⚙️ Settings For {message.chat.title}</b>",
        reply_markup=get_settings_keyboard(settings),
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("restart") & filters.user(ADMINS) & connected_group)
async def stop_button(bot, message):
    msg = await bot.send_message(
        chat_id=message.chat.id,
        text="**🔄 𝙱𝙾𝚃 𝙸𝚂 𝚁𝙴𝚂𝚃𝙰𝚁𝚃𝙸𝙽𝙶**",
    )
    await asyncio.sleep(3)
    await msg.edit("**✅️ 𝙱𝙾𝚃 𝙸𝚂 𝚁𝙴𝚂𝚃𝙰𝚁𝚃𝙴𝙳**")
    os.execl(sys.executable, sys.executable, *sys.argv)
