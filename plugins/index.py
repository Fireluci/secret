import asyncio, logging, re
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait
from pyrogram.errors.exceptions.bad_request_400 import ChannelInvalid, ChatAdminRequired, UsernameInvalid, UsernameNotModified
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from info import ADMINS, INDEX_REQ_CHANNEL as LOG_CHANNEL
from database.ia_filterdb import Media
from utils import temp

logger=logging.getLogger(__name__)
lock=asyncio.Lock()

async def save_files_bulk(media_list):
    if not media_list: return 0,0,0
    docs,ids=[],set()
    for m in media_list:
        if m.file_id in ids: continue
        ids.add(m.file_id)
        docs.append({"file_id":m.file_id,"file_name":m.file_name,"file_size":m.file_size,"file_type":m.file_type,"caption":m.caption})
    existing=await Media.find({"file_id":{"$in":list(ids)}},{"file_id":1}).to_list(None)
    exist_ids={x["file_id"] for x in existing}
    new_docs=[d for d in docs if d["file_id"] not in exist_ids]
    if not new_docs: return 0,len(exist_ids),0
    try:
        await Media.insert_many(new_docs,ordered=False)
        return len(new_docs),len(exist_ids),0
    except:
        return 0,0,len(new_docs)

@Client.on_callback_query(filters.regex("^index"))
async def index_files(bot,q):
    if q.data=="index_cancel":
        temp.CANCEL=True
        return await q.answer("Cancelling")
    _,act,chat,last,uid=q.data.split("#")
    if act=="reject":
        await q.message.delete()
        return await bot.send_message(int(uid),"Index request rejected",reply_to_message_id=int(last))
    if lock.locked(): return await q.answer("Index running",show_alert=True)
    await q.answer("Processing",show_alert=True)
    await q.message.edit("Starting Indexing",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel",callback_data="index_cancel")]]))
    try: chat=int(chat)
    except: pass
    await index_files_to_db(int(last),chat,q.message,bot)

@Client.on_message(filters.private & (filters.forwarded | filters.regex(r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)")))
async def send_for_index(bot,m):
    if m.text:
        r=re.search(r"(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$",m.text)
        if not r: return await m.reply("Invalid link")
        chat_id=r.group(2); last=int(r.group(3))
        if chat_id.isnumeric(): chat_id=int("-100"+chat_id)
    elif m.forward_from_chat and m.forward_from_chat.type==enums.ChatType.CHANNEL:
        chat_id=m.forward_from_chat.username or m.forward_from_chat.id
        last=m.forward_from_message_id
    else: return
    try: await bot.get_chat(chat_id)
    except ChannelInvalid: return await m.reply("Make me admin in channel")
    except (UsernameInvalid,UsernameNotModified): return await m.reply("Invalid link")
    try: k=await bot.get_messages(chat_id,last)
    except: return await m.reply("Bot not admin")
    if k.empty: return await m.reply("Cannot access message")
    btn=[[InlineKeyboardButton("✅ Accept",callback_data=f"index#accept#{chat_id}#{last}#{m.from_user.id}"),
          InlineKeyboardButton("❌ Reject",callback_data=f"index#reject#{chat_id}#{m.id}#{m.from_user.id}")]]
    await bot.send_message(LOG_CHANNEL,f"#IndexRequest\nUser: {m.from_user.mention}\nChannel: {chat_id}",reply_markup=InlineKeyboardMarkup(btn))
    await m.reply("Request sent")

@Client.on_message(filters.command("setskip") & filters.user(ADMINS))
async def setskip(_,m):
    try: temp.CURRENT=int(m.command[1])
    except: return await m.reply("Usage: /setskip <num>")
    await m.reply(f"Skip set to {temp.CURRENT}")

async def index_files_to_db(last_id,chat,msg,bot):
    total=dup=err=delm=nom=uns=0
    buf=[]; temp.CANCEL=False
    async with lock:
        try:
            async for m in bot.iter_messages(chat,None,last_id):
                if temp.CANCEL: break
                if m.id<=temp.CURRENT: continue
                if m.empty: delm+=1; continue
                if not m.media: nom+=1; continue
                if m.media not in (enums.MessageMediaType.VIDEO,enums.MessageMediaType.AUDIO,enums.MessageMediaType.DOCUMENT):
                    uns+=1; continue
                media=getattr(m,m.media.value,None)
                if not media: uns+=1; continue
                media.file_type=m.media.value; media.caption=m.caption
                buf.append(media)
                if len(buf)>=50:
                    s,d,e=await save_files_bulk(buf)
                    total+=s; dup+=d; err+=e; buf.clear()
                if (total+dup+err)%200==0:
                    try:
                        await msg.edit_text(f"Saved:{total}\nDup:{dup}\nDel:{delm}\nNon:{nom+uns}\nErr:{err}",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel",callback_data="index_cancel")]]))
                    except FloodWait: pass
            if buf:
                s,d,e=await save_files_bulk(buf)
                total+=s; dup+=d; err+=e
        except Exception as e:
            logger.exception(e)
            try: await msg.edit(f"Error: {e}")
            except FloodWait: pass
        else:
            try:
                await msg.edit(f"✅ Done\nSaved:{total}\nDup:{dup}\nDel:{delm}\nNon:{nom+uns}\nErr:{err}")
            except FloodWait: pass
