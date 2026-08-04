import os
import logging
import random
import asyncio
from Script import script
from pyrogram import Client, filters, enums
from pyrogram.errors import ChatAdminRequired, FloodWait
from pyrogram.types import *
from database.ia_filterdb import Media, get_file_details, unpack_new_file_id, get_bad_files
from database.users_chats_db import db
from info import CHANNELS, ADMINS, AUTH_CHANNEL, LOG_CHANNEL, PICS, BATCH_FILE_CAPTION, CUSTOM_FILE_CAPTION, PROTECT_CONTENT, CHNL_LNK, FORCE, GRP_LNK, REQST_CHANNEL, SUPPORT_CHAT_ID, SUPPORT_CHAT, MAX_B_TN, SHORTLINK_API, SHORTLINK_URL, TUTORIAL, IS_TUTORIAL, PREMIUM_USER
from utils import get_settings, get_size, is_subscribed, save_group_settings, temp, get_shortlink, get_tutorial
from database.connections_mdb import active_connection
import re, asyncio, os, sys
import json
import base64
logger = logging.getLogger(__name__)

BATCH_FILES = {}

@Client.on_message(filters.command("start") & filters.incoming)
async def start(client, message):
    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        buttons = [
            [
                InlineKeyboardButton('❓How To Use Me❓', url=f'https://telegram.me/{TUTORIAL}')
            ]
               ]
        reply_markup = InlineKeyboardMarkup(buttons)
        await message.reply(script.START_TXT.format(message.from_user.mention if message.from_user else message.chat.title, temp.U_NAME, temp.B_NAME), reply_markup=reply_markup, disable_web_page_preview=True)
        await asyncio.sleep(2) # 😢 https://github.com/EvamariaTG/EvaMaria/blob/master/plugins/p_ttishow.py#L17 😬 wait a bit, before checking.
        if not await db.get_chat(message.chat.id):
            total=await client.get_chat_members_count(message.chat.id)
            await client.send_message(LOG_CHANNEL, script.LOG_TEXT_G.format(message.chat.title, message.chat.id, total, "Unknown"))       
            await db.add_chat(message.chat.id, message.chat.title)
        return 
    if not await db.is_user_exist(message.from_user.id):
        await db.add_user(message.from_user.id, message.from_user.first_name)
        await client.send_message(LOG_CHANNEL, script.LOG_TEXT_P.format(message.from_user.id, message.from_user.mention))
    if len(message.command) != 2:
        buttons = [
            [InlineKeyboardButton("🌟 Paid (No Ads)", url="https://telegram.me/HeroFlixx/49"),
             InlineKeyboardButton("🍿 Free (With Ads)", url="https://telegram.me/addlist/X5k2lnJLIGAyZjQ1")],
            [InlineKeyboardButton("👤 Admin", url=f"https://telegram.me/{SUPPORT_CHAT}"),
             InlineKeyboardButton("⚜ Updates", url=FORCE)]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        await message.reply_photo(
            photo=PICS,
            caption=script.START_TXT.format(message.from_user.mention, temp.U_NAME, temp.B_NAME),
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
        return
    if AUTH_CHANNEL and not await is_subscribed(client, message):
        payload = message.text.split(" ", 1)[1] if " " in message.text else "subscribe"
        retry = f"https://telegram.me/{temp.U_NAME}?start={payload}"

        btn = [
            [InlineKeyboardButton("🏮 Main Channel ⟨Click Here⟩ 🏮", url=FORCE)],
            [InlineKeyboardButton("🔄 Try Again", url=retry)]
        ]

        await client.send_message(
            message.from_user.id,
            "**🔆 First Join Our Main Channel & Then Click Try Again ♻\n\n"
            "🔆 पहले हमारे मैन चैनल से जुड़ें और फिर Try Again दबाएँ ♻**",
            reply_markup=InlineKeyboardMarkup(btn),
            parse_mode=enums.ParseMode.MARKDOWN
        )
        return

    if len(message.command) == 2 and message.command[1] in ["subscribe", "error", "okay", "help"]:
        buttons = [
            [InlineKeyboardButton("🌟 Paid (No Ads)", url="https://telegram.me/HeroFlixx/49"),
             InlineKeyboardButton("🍿 Free (With Ads)", url="https://telegram.me/addlist/X5k2lnJLIGAyZjQ1")],
            [InlineKeyboardButton("👤 Admin", url=f"https://telegram.me/{SUPPORT_CHAT}"),
             InlineKeyboardButton("⚜ Updates", url=FORCE)]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)      
        await message.reply_photo(
            photo=PICS,
            caption=script.START_TXT.format(message.from_user.mention, temp.U_NAME, temp.B_NAME),
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
        return
    data = message.command[1]
    try:
        pre, file_id = data.split('_', 1)
    except:
        file_id = data
        pre = ""
    if data.split("-", 1)[0] == "BATCH":
        sts = await message.reply("<b>Please wait...</b>")
        file_id = data.split("-", 1)[1]
        msgs = BATCH_FILES.get(file_id)
        if not msgs:
            file = await client.download_media(file_id)
            try: 
                with open(file) as file_data:
                    msgs=json.loads(file_data.read())
            except:
                await sts.edit("FAILED")
                return await client.send_message(LOG_CHANNEL, "UNABLE TO OPEN FILE.")
            os.remove(file)
            BATCH_FILES[file_id] = msgs
        for msg in msgs:
            title = msg.get("title")
            size=get_size(int(msg.get("size", 0)))
            f_caption=msg.get("caption", "")
            if BATCH_FILE_CAPTION:
                try:
                    f_caption=BATCH_FILE_CAPTION.format(file_name= '' if title is None else title, file_size='' if size is None else size, file_caption='' if f_caption is None else f_caption)
                except Exception as e:
                    logger.exception(e)
                    f_caption=f_caption
            if f_caption is None:
                f_caption = f"{title}"
            try:
                await client.send_cached_media(
                    chat_id=message.from_user.id,
                    file_id=msg.get("file_id"),
                    caption=f_caption,
                    protect_content=msg.get('protect', False),
                    reply_markup=InlineKeyboardMarkup(
                        [
                         [
                          InlineKeyboardButton('🔆彡⟨ HEROFLiX ⟩彡🔆', url=f'https://telegram.me/{CHNL_LNK}'),
                         ]
                        ]
                    )
                )
            except FloodWait as e:
                await asyncio.sleep(e.x)
                logger.warning(f"Floodwait of {e.x} sec.")
                await client.send_cached_media(
                    chat_id=message.from_user.id,
                    file_id=msg.get("file_id"),
                    caption=f_caption,
                    protect_content=msg.get('protect', False),
                    reply_markup=InlineKeyboardMarkup(
                        [
                         [
                          InlineKeyboardButton('🔆彡⟨ HEROFLiX ⟩彡🔆', url=f'https://telegram.me/{CHNL_LNK}'),
                         ]
                        ]
                    )
                )
            except Exception as e:
                logger.warning(e, exc_info=True)
                continue
            await asyncio.sleep(1) 
        await sts.delete()
        return
    
    elif data.split("-", 1)[0] == "DSTORE":
        sts = await message.reply("<b>Please wait...</b>")
        b_string = data.split("-", 1)[1]
        decoded = (base64.urlsafe_b64decode(b_string + "=" * (-len(b_string) % 4))).decode("ascii")
        try:
            f_msg_id, l_msg_id, f_chat_id, protect = decoded.split("_", 3)
        except:
            f_msg_id, l_msg_id, f_chat_id = decoded.split("_", 2)
            protect = "/pbatch" if PROTECT_CONTENT else "batch"
        diff = int(l_msg_id) - int(f_msg_id)
        async for msg in client.iter_messages(int(f_chat_id), int(l_msg_id), int(f_msg_id)):
            if msg.media:
                media = getattr(msg, msg.media.value)
                if BATCH_FILE_CAPTION:
                    try:
                        f_caption=BATCH_FILE_CAPTION.format(file_name=getattr(media, 'file_name', ''), file_size=getattr(media, 'file_size', ''), file_caption=getattr(msg, 'caption', ''))
                    except Exception as e:
                        logger.exception(e)
                        f_caption = getattr(msg, 'caption', '')
                else:
                    media = getattr(msg, msg.media.value)
                    file_name = getattr(media, 'file_name', '')
                    f_caption = getattr(msg, 'caption', file_name)
                try:
                    await msg.copy(message.chat.id, caption=f_caption, protect_content=True if protect == "/pbatch" else False)
                except FloodWait as e:
                    await asyncio.sleep(e.x)
                    await msg.copy(message.chat.id, caption=f_caption, protect_content=True if protect == "/pbatch" else False)
                except Exception as e:
                    logger.exception(e)
                    continue
            elif msg.empty:
                continue
            else:
                try:
                    await msg.copy(message.chat.id, protect_content=True if protect == "/pbatch" else False)
                except FloodWait as e:
                    await asyncio.sleep(e.x)
                    await msg.copy(message.chat.id, protect_content=True if protect == "/pbatch" else False)
                except Exception as e:
                    logger.exception(e)
                    continue
            await asyncio.sleep(1) 
        return await sts.delete()

    if data.startswith("sendfiles"):
        chat_id = int("-" + file_id.split("-")[1])
        userid = message.from_user.id if message.from_user else None
        st = await client.get_chat_member(chat_id, userid)
        if (
                st.status != enums.ChatMemberStatus.ADMINISTRATOR
                and st.status != enums.ChatMemberStatus.OWNER
        ):
            g = await get_shortlink(chat_id, f"https://telegram.me/{temp.U_NAME}?start=allfiles_{file_id}", True)
        else:
            g = await get_shortlink(chat_id, f"https://telegram.me/{temp.U_NAME}?start=allfiles_{file_id}", False)
        k = await client.send_message(chat_id=message.from_user.id,text=f"<b>Get All Files in a Single Click!!!\n\n♻️ ʟɪɴᴋ ➠ {g}</b>", reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton('♻️ Download Link ♻️', url=g)
                    ], [
                        InlineKeyboardButton('❓ How To Download ❓', url=f'https://telegram.me/{TUTORIAL}')
                    ]
                ]
            )
        )
        await asyncio.sleep(900)
        await k.edit("<b>Link Deleted!</b>")
        return
        
    elif data.startswith("short"):
        user = message.from_user.id
        chat_id = temp.SHORT.get(user)
        files_ = await get_file_details(file_id)
        files = files_[0]
        cleaned_file_name = f"{' '.join(filter(lambda x: not x.startswith('www.') and not x.startswith('@'), files.file_name.split()))}"
        g = await get_shortlink(chat_id, f"https://telegram.me/{temp.U_NAME}?start=file_{file_id}")
        k = await client.send_message(chat_id=user,text=f'<b>[ {get_size(files.file_size)} ] <a href="https://telegram.me/HEROFLiX">{cleaned_file_name}</a> \n\n📗 Download Link ➔ {g} {g}</b>', reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton('♻️ Download Link ♻️', url=g)
                    ], [
                        InlineKeyboardButton('❓ How To Download ❓', url=f'https://telegram.me/{TUTORIAL}')
                    ], [
                        InlineKeyboardButton('🌟 Direct Download 🌟', url="https://telegram.me/HeroFlixx/49")
                    ]
                ]
            )
        )
        await asyncio.sleep(900)
        await k.edit("<b>Link Deleted!</b>")
        return
        
    elif data.startswith("all"):
        files = temp.GETALL.get(file_id)
        if not files:
            return await message.reply('<b><i>No such file exist.</b></i>')
        filesarr = []
        for file in files:
            file_id = file.file_id
            files_ = await get_file_details(file_id)
            files1 = files_[0]
            title = ' '.join(filter(lambda x: not x.startswith('www.') and not x.startswith('@'), files1.file_name.split()))
            size=get_size(files1.file_size)
            f_caption=files1.caption
            if CUSTOM_FILE_CAPTION:
                try:
                    f_caption=CUSTOM_FILE_CAPTION.format(file_name= '' if title is None else title, file_size='' if size is None else size, file_caption='' if f_caption is None else f_caption)
                except Exception as e:
                    logger.exception(e)
                    f_caption=f_caption
            if f_caption is None:
                f_caption = f"{' '.join(filter(lambda x: not x.startswith('www.') and not x.startswith('@'), files1.file_name.split()))}"

            msg = await client.send_cached_media(
                chat_id=message.from_user.id,
                file_id=file_id,
                caption=f_caption,
                protect_content=True if pre == 'filep' else False,
                reply_markup=InlineKeyboardMarkup(
                    [
                     [
                      InlineKeyboardButton('🔆彡⟨ HEROFLiX ⟩彡🔆', url=f'https://telegram.me/{CHNL_LNK}'),
                     ]
                    ]
                )
            )
            filesarr.append(msg)
        await k.edit_text("<b>File Deleted!</b>")
        return    
        
    elif data.startswith("files"):
        user = message.from_user.id
        if temp.SHORT.get(user)==None:
            await message.reply_text(text="<b>Link Expired, Search Again in Group!</b>")
            return
        else:
            chat_id = temp.SHORT.get(user)
        settings = await get_settings(chat_id)
        if settings['is_shortlink'] and user not in PREMIUM_USER:
            files_ = await get_file_details(file_id)
            files = files_[0]
            g = await get_shortlink(chat_id, f"https://telegram.me/{temp.U_NAME}?start=file_{file_id}")
            cleaned_file_name = f"{' '.join(filter(lambda x: not x.startswith('www.') and not x.startswith('@'), files.file_name.split()))}"
            k = await client.send_message(chat_id=message.from_user.id,text=f'<b>[ {get_size(files.file_size)} ] <a href="https://telegram.me/HEROFLiX">{cleaned_file_name}</a> \n\n📗 Download Link ➠ {g} {g}</b>', reply_markup=InlineKeyboardMarkup(
                [
                        [
                            InlineKeyboardButton('♻️ Download Link ♻️', url=g)
                        ], [
                            InlineKeyboardButton('❓ How To Download ❓', url=f"https://telegram.me/{TUTORIAL}")
                        ], [
                            InlineKeyboardButton('🌟 Direct Download 🌟', url="https://telegram.me/HeroFlixx/49")
                        ]
                    ]
                )
            )
            await asyncio.sleep(900)
            try:
                await k.edit_text("Link Deleted!")
            except Exception:
                pass
            return
    user = message.from_user.id
    files_ = await get_file_details(file_id)           
    if not files_:
        pre, file_id = ((base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))).decode("ascii")).split("_", 1)
        try:

            msg = await client.send_cached_media(
                chat_id=message.from_user.id,
                file_id=file_id,
                protect_content=True if pre == 'filep' else False,
                reply_markup=InlineKeyboardMarkup(
                    [
                     [
                      InlineKeyboardButton('🔆彡⟨ HEROFLiX ⟩彡🔆', url=f'https://telegram.me/{CHNL_LNK}'),
                     ]
                    ]
                )
            )
            filetype = msg.media
            file = getattr(msg, filetype.value)
            title = '' + ' '.join(filter(lambda x: not x.startswith('www.') and not x.startswith('@'), file.file_name.split()))
            size=get_size(file.file_size)
            f_caption = f"<code>{title}</code>"
            if CUSTOM_FILE_CAPTION:
                try:
                    f_caption=CUSTOM_FILE_CAPTION.format(file_name= '' if title is None else title, file_size='' if size is None else size, file_caption='')
                except:
                    return
            await msg.edit_caption(f_caption)
            btn = [[
                InlineKeyboardButton("Get File Again", callback_data=f'delfile#{file_id}')
            ]]
            await k.edit_text("<b>Your File/Video is deleted!!!\n\nClick below button to get your deleted file 👇</b>",reply_markup=InlineKeyboardMarkup(btn))
            return
        except:
            pass
        return await message.reply('No such file exist.')
    files = files_[0]
    title = '' + ' '.join(filter(lambda x: not x.startswith('www.') and not x.startswith('@'), files.file_name.split()))
    size=get_size(files.file_size)
    f_caption=files.caption
    if CUSTOM_FILE_CAPTION:
        try:
            f_caption=CUSTOM_FILE_CAPTION.format(file_name= '' if title is None else title, file_size='' if size is None else size, file_caption='' if f_caption is None else f_caption)
        except Exception as e:
            logger.exception(e)
            f_caption=f_caption
    if f_caption is None:
        f_caption = f"{' '.join(filter(lambda x: not x.startswith('www.') and not x.startswith('@'), files.file_name.split()))}"

    msg = await client.send_cached_media(
        chat_id=message.from_user.id,
        file_id=file_id,
        caption=f_caption,
        protect_content=True if pre == 'filep' else False,
        reply_markup=InlineKeyboardMarkup(
            [
             [
              InlineKeyboardButton('🔆彡⟨ HEROFLiX ⟩彡🔆', url=f'https://telegram.me/{CHNL_LNK}'),
             ]
            ]
        )
    )
    return   

@Client.on_message(filters.command('channel') & filters.user(ADMINS))
async def channel_info(bot, message):
           
    """Send basic information of channel"""
    if isinstance(CHANNELS, (int, str)):
        channels = [CHANNELS]
    elif isinstance(CHANNELS, list):
        channels = CHANNELS
    else:
        raise ValueError("Unexpected type of CHANNELS")

    text = '📑 **Indexed channels/groups**\n'
    for channel in channels:
        chat = await bot.get_chat(channel)
        if chat.username:
            text += '\n@' + chat.username
        else:
            text += '\n' + chat.title or chat.first_name

    text += f'\n\n**Total:** {len(CHANNELS)}'

    if len(text) < 4096:
        await message.reply(text)
    else:
        file = 'Indexed channels.txt'
        with open(file, 'w') as f:
            f.write(text)
        await message.reply_document(file)
        os.remove(file)

@Client.on_message(filters.command('logs') & filters.user(ADMINS))
async def log_file(bot, message):
    """Send log file"""
    try:
        await message.reply_document('TelegramBot.log')
    except Exception as e:
        await message.reply(str(e))

@Client.on_message(filters.command('delete') & filters.user(ADMINS))
async def delete(bot, message):
    """Delete file from database"""
    reply = message.reply_to_message
    if reply and reply.media:
        msg = await message.reply("Processing...⏳", quote=True)
    else:
        await message.reply('Reply to file with /delete which you want to delete', quote=True)
        return

    for file_type in ("document", "video", "audio"):
        media = getattr(reply, file_type, None)
        if media is not None:
            break
    else:
        await msg.edit('This is not supported file format')
        return
    
    file_id, file_ref = unpack_new_file_id(media.file_id)

    result = await Media.collection.delete_one({
        '_id': file_id,
    })
    if result.deleted_count:
        await msg.edit('🛃 Deleted File!')
    else:
        file_name = re.sub(r"(_|\-|\.|\+)", " ", str(media.file_name))
        result = await Media.collection.delete_many({
            'file_name': file_name,
            'file_size': media.file_size,
            'mime_type': media.mime_type
            })
        if result.deleted_count:
            await msg.edit('🛃 Deleted File!')
        else:
            # files indexed before https://github.com/EvamariaTG/EvaMaria/commit/f3d2a1bcb155faf44178e5d7a685a1b533e714bf#diff-86b613edf1748372103e94cacff3b578b36b698ef9c16817bb98fe9ef22fb669R39 
            # have original file name.
            result = await Media.collection.delete_many({
                'file_name': media.file_name,
                'file_size': media.file_size,
                'mime_type': media.mime_type
            })
            if result.deleted_count:
                await msg.edit('🛃 Deleted File!')
            else:
                await msg.edit('File not found in database')

@Client.on_message(filters.command('deleteall') & filters.user(ADMINS))
async def delete_all_index(bot, message):
    await message.reply_text(
        'This will delete all indexed files.\nDo you want to continue??',
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text="🛃 Delete Files!", callback_data="autofilter_delete"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="💢 Cancel 💢", callback_data="close_data"
                    )
                ],
            ]
        ),
        quote=True,
    )

@Client.on_callback_query(filters.regex(r'^autofilter_delete'))
async def delete_all_index_confirm(bot, message):
    await Media.collection.drop()
    await message.answer('Piracy Is Crime')
    await message.message.edit('Succesfully Deleted All The Indexed Files.')

def get_settings_keyboard(settings: dict, grp_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('Rᴇsᴜʟᴛ Pᴀɢᴇ', callback_data=f'setgs#button#{settings.get("button", False)}#{grp_id}'), InlineKeyboardButton('Bᴜᴛᴛᴏɴ' if settings.get("button", False) else 'Tᴇxᴛ', callback_data=f'setgs#button#{settings.get("button", False)}#{grp_id}')],
        [InlineKeyboardButton('Fɪʟᴇ Sᴇɴᴅ Mᴏᴅᴇ', callback_data=f'setgs#botpm#{settings.get("botpm", False)}#{grp_id}'), InlineKeyboardButton('Mᴀɴᴜᴀʟ Sᴛᴀʀᴛ' if settings.get("botpm", False) else 'Aᴜᴛᴏ Sᴇɴᴅ', callback_data=f'setgs#botpm#{settings.get("botpm", False)}#{grp_id}')],
        [InlineKeyboardButton('Pʀᴏᴛᴇᴄᴛ Cᴏɴᴛᴇɴᴛ', callback_data=f'setgs#file_secure#{settings.get("file_secure", False)}#{grp_id}'), InlineKeyboardButton('✔ Oɴ' if settings.get("file_secure", False) else '✘ Oғғ', callback_data=f'setgs#file_secure#{settings.get("file_secure", False)}#{grp_id}')],
        [InlineKeyboardButton('Sᴘᴇʟʟ Cʜᴇᴄᴋ', callback_data=f'setgs#spell_check#{settings.get("spell_check", True)}#{grp_id}'), InlineKeyboardButton('✔ Oɴ' if settings.get("spell_check", True) else '✘ Oғғ', callback_data=f'setgs#spell_check#{settings.get("spell_check", True)}#{grp_id}')],
        [InlineKeyboardButton('Wᴇʟᴄᴏᴍᴇ Msɢ', callback_data=f'setgs#welcome#{settings.get("welcome", True)}#{grp_id}'), InlineKeyboardButton('✔ Oɴ' if settings.get("welcome", True) else '✘ Oғғ', callback_data=f'setgs#welcome#{settings.get("welcome", True)}#{grp_id}')],
        [InlineKeyboardButton('Aᴜᴛᴏ-Dᴇʟᴇᴛᴇ', callback_data=f'setgs#auto_delete#{settings.get("auto_delete", False)}#{grp_id}'), InlineKeyboardButton('10 Mɪns' if settings.get("auto_delete", False) else '✘ Oғғ', callback_data=f'setgs#auto_delete#{settings.get("auto_delete", False)}#{grp_id}')],
        [InlineKeyboardButton('Aᴜᴛᴏ-Fɪʟᴛᴇʀ', callback_data=f'setgs#auto_ffilter#{settings.get("auto_ffilter", True)}#{grp_id}'), InlineKeyboardButton('✔ Oɴ' if settings.get("auto_ffilter", True) else '✘ Oғғ', callback_data=f'setgs#auto_ffilter#{settings.get("auto_ffilter", True)}#{grp_id}')],
        [InlineKeyboardButton('Mᴀx Bᴜᴛᴛᴏns', callback_data=f'setgs#max_btn#{settings.get("max_btn", False)}#{grp_id}'), InlineKeyboardButton('10' if settings.get("max_btn", False) else f'{MAX_B_TN}', callback_data=f'setgs#max_btn#{settings.get("max_btn", False)}#{grp_id}')],
        [InlineKeyboardButton('ShortLink', callback_data=f'setgs#is_shortlink#{settings.get("is_shortlink", False)}#{grp_id}'), InlineKeyboardButton('✔ Oɴ' if settings.get("is_shortlink", False) else '✘ Oғғ', callback_data=f'setgs#is_shortlink#{settings.get("is_shortlink", False)}#{grp_id}')],
    ])

@Client.on_callback_query(filters.regex(r'^setgs'))
async def settings_callback(client, callback):
    dat = callback.data.split('#')
    setting, current, chat_id = dat[1], dat[2] == 'True', int(dat[3])
    st = await client.get_chat_member(chat_id, callback.from_user.id)
    if st.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] and str(callback.from_user.id) not in ADMINS:
        return await callback.answer("Unauthorized!", show_alert=True)
    
    await save_group_settings(chat_id, setting, not current)
    settings = await get_settings(chat_id)
    try: await callback.message.edit_reply_markup(reply_markup=get_settings_keyboard(settings, chat_id))
    except Exception: pass

@Client.on_message(filters.command('settings'))
async def settings(client, message):
    userid = message.from_user.id if message.from_user else None
    if not userid: return await message.reply(f"<b>⚠️ <code>Use /connect {message.chat.id} in PM</code></b>")
    if message.chat.type == enums.ChatType.PRIVATE:
        grp_id = await active_connection(str(userid))
        if not grp_id: return await message.reply_text("<b>⚠️ <code>Not connected to any group! Use /connect first.</code></b>", quote=True)
        try: title = (await client.get_chat(grp_id)).title
        except Exception: return await message.reply_text("<b>⚠️ <code>Make sure I'm in your group!</code></b>", quote=True)
    else:
        grp_id, title = message.chat.id, message.chat.title

    st = await client.get_chat_member(grp_id, userid)
    if st.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] and str(userid) not in ADMINS: return
    
    settings = await get_settings(grp_id)
    await message.reply_text(f"<b>⚙️ <code>Settings For {title}</code></b>", reply_markup=get_settings_keyboard(settings, grp_id), parse_mode=enums.ParseMode.HTML, reply_to_message_id=message.id)

@Client.on_message(filters.command("deletefiles") & filters.user(ADMINS))
async def deletemultiplefiles(bot, message):
    chat_type = message.chat.type
    if chat_type != enums.ChatType.PRIVATE:
        return await message.reply_text(f"<b>Only Works in PM !</b>")
    else:
        pass
    try:
        keyword = message.text.split(" ", 1)[1]
    except:
        return await message.reply_text(f"<b>Hey {message.from_user.mention}, Give me a keyword along with the command to delete files.</b>")
    k = await bot.send_message(chat_id=message.chat.id, text=f"<b>♻️ Please Wait!</b>")
    files, total = await get_bad_files(keyword)
    await k.delete()
    btn = [[
       InlineKeyboardButton("🛃 Delete Files!", callback_data=f"killfilesdq#{keyword}")
       ],[
       InlineKeyboardButton("💢 Cancel 💢", callback_data="close_data")
    ]]
    await message.reply_text(
        text=f"<b>{total} Files ➠ {keyword}</b>",
        reply_markup=InlineKeyboardMarkup(btn),
        parse_mode=enums.ParseMode.HTML
    )

@Client.on_message(filters.command("shortlink1"))
async def update_shortlink1(bot, message):
    userid = message.from_user.id if message.from_user else None
    if not userid:
        return await message.reply("Turn off anonymous admin and try again.")
    if message.chat.type == enums.ChatType.PRIVATE:
        return await message.reply_text("<b>Only works in groups !</b>")
    
    # Restrict ONLY to global bot admins from info.py
    if str(userid) not in ADMINS and userid not in ADMINS:
        return await message.reply_text("<b>You don't have access to use this command! Only bot admins can change shorteners.</b>")
        
    grpid = message.chat.id
    try:
        command, shortlink_url, api = message.text.split(" ", 2)
    except:
        return await message.reply_text("<b>Wrong Format. Example - /shortlink1 softurl.in YOUR_API</b>")
        
    reply = await message.reply_text("<b>Please Wait...</b>")
    shortlink_url = re.sub(r"https?://?", "", shortlink_url)
    shortlink_url = re.sub(r"[:/]", "", shortlink_url)
    
    await save_group_settings(grpid, 'shortlink', shortlink_url)
    await save_group_settings(grpid, 'shortlink_api', api)
    await save_group_settings(grpid, 'is_shortlink', True)
    
    await reply.edit_text(f"<b>Successfully updated Primary Shortener (Short1)!\n\nWebsite: <code>{shortlink_url}</code>\nAPI: <code>{api}</code></b>")
    await asyncio.sleep(10)
    await reply.delete()


@Client.on_message(filters.command("shortlink2"))
async def update_shortlink2(bot, message):
    userid = message.from_user.id if message.from_user else None
    if not userid:
        return await message.reply("Turn off anonymous admin and try again.")
    if message.chat.type == enums.ChatType.PRIVATE:
        return await message.reply_text("<b>Only works in groups !</b>")
        
    # Restrict ONLY to global bot admins from info.py
    if str(userid) not in ADMINS and userid not in ADMINS:
        return await message.reply_text("<b>You don't have access to use this command! Only bot admins can change shorteners.</b>")
        
    grpid = message.chat.id
    try:
        command, shortlink_url, api = message.text.split(" ", 2)
    except:
        return await message.reply_text("<b>Wrong Format. Example - /shortlink2 nowshort.com YOUR_API</b>")
        
    reply = await message.reply_text("<b>Please Wait...</b>")
    shortlink_url = re.sub(r"https?://?", "", shortlink_url)
    shortlink_url = re.sub(r"[:/]", "", shortlink_url)
    
    await save_group_settings(grpid, 'second_shortlink', shortlink_url)
    await save_group_settings(grpid, 'second_shortlink_api', api)
    
    await reply.edit_text(f"<b>Successfully updated Secondary Shortener (Short2)!\n\nWebsite: <code>{shortlink_url}</code>\nAPI: <code>{api}</code></b>")
    await asyncio.sleep(10)
    await reply.delete()

@Client.on_message(filters.command("shorteners"))
async def view_shorteners(bot, message):
    userid = message.from_user.id if message.from_user else None
    if not userid:
        return await message.reply("Turn off anonymous admin and try again.")
    if message.chat.type == enums.ChatType.PRIVATE:
        return await message.reply_text("<b>Only works in groups !</b>")
        
    # Restrict ONLY to global bot admins from info.py
    if str(userid) not in ADMINS and userid not in ADMINS:
        return await message.reply_text("<b>You don't have access to use this command! Only bot admins can check shorteners.</b>")
        
    grpid = message.chat.id
    settings = await get_settings(grpid)
    
    s1_url = settings.get('shortlink') or SHORT1_URL
    s1_api = settings.get('shortlink_api') or SHORT1_API
    s2_url = settings.get('second_shortlink') or SHORT2_URL
    s2_api = settings.get('second_shortlink_api') or SHORT2_API
    is_active = settings.get('is_shortlink', False)

    status_text = (
        f"⚙️ **Current Group Shortener Configuration**\n\n"
        f"• **Status:** `{'Enabled' if is_active else 'Disabled'}`\n"
        f"• **Primary (Short1):** `{s1_url}` (API: `{s1_api}`)\n"
        f"• **Secondary (Short2):** `{s2_url}` (API: `{s2_api}`)"
    )
    await message.reply_text(status_text, parse_mode=enums.ParseMode.MARKDOWN)

@Client.on_message(filters.command("restart") & filters.user(ADMINS))
async def stop_button(bot, message):
    msg = await bot.send_message(text="**🔄 𝙱𝙾𝚃 𝙸𝚂 𝚁𝙴𝚂𝚃𝙰𝚁𝚃𝙸𝙽𝙶**", chat_id=message.chat.id)       
    await asyncio.sleep(3)
    await msg.edit("**✅️ 𝙱𝙾𝚃 𝙸𝚂 𝚁𝙴𝚂𝚃𝙰𝚁𝚃𝙴𝙳**")
    os.execl(sys.executable, sys.executable, *sys.argv)
