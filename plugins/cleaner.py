import asyncio
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait

# --- USERBOT CONFIGURATION ---
API_ID = 20354559
API_HASH = "bbdf772b35141fa8b661740dddb840bf"
SESSION_STRING = "BQE2lf8AKLqlyjLoygEnyioQKt-iyJKQi6IxqUvpSIk5FCVW259dcZoUbYnath0zqwqRvf66o1IvsOyJL7-PI8gPiGlAHijRl25aa1Verk1bdd7s1y5Am4V7QtqY1k5jL1mu4-_beBdfWt5BmvLz4uKmQ4I8ERtQuPwGzLF7xqOVY2OMdAMaYGn5hpVKIWWU1iNa4ZYcUlHfqh6Ws1SNdYM6a13SxcFRMzIRtX0f41GXYG_ISuTxbR-G8jZH0i5XnE-IYx0F2Lev9fe_MbklaP5OlyzARvbIHmPdnc-DDeFuFw_c3-pNiKTROTtYCXbHjWGG4Hr3oayjHOq3h_964mHZmwHCSQAAAAGF3NwSAA"
INVITE_LINK = "https://t.me/+tREA7LOsFaFhY2Fl"
ADMIN_ID = 1058015838

# Initialize the separate Userbot client using your session string
userbot = Client(
    "cleaner_userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)

@Client.on_message(filters.command("cleandups") & filters.user(ADMIN_ID))
async def trigger_cleanups(client, message):
    await message.reply("🚀 **Userbot filter-cleaner started in the background!** (Deleting non-video/non-document files & duplicates...)")
    asyncio.create_task(run_userbot_cleaner(message))

async def run_userbot_cleaner(message):
    try:
        if not userbot.is_connected:
            await userbot.start()

        try:
            chat = await userbot.join_chat(INVITE_LINK)
            target_chat_id = chat.id
        except Exception:
            chat = await userbot.get_chat(INVITE_LINK)
            target_chat_id = chat.id

        seen_file_ids = set()
        deleted_count = 0
        scanned_count = 0
        junk_deleted_count = 0
        duplicate_deleted_count = 0

        async for msg in userbot.get_chat_history(target_chat_id):
            scanned_count += 1
            
            # Rule 1: If it's empty or text-only (no media), delete it instantly as junk
            if msg.empty or not msg.media:
                try:
                    await userbot.delete_messages(chat_id=target_chat_id, message_ids=msg.id)
                    deleted_count += 1
                    junk_deleted_count += 1
                    await asyncio.sleep(1.2)
                except FloodWait as e:
                    await asyncio.sleep(e.value)
                    await userbot.delete_messages(chat_id=target_chat_id, message_ids=msg.id)
                    deleted_count += 1
                    junk_deleted_count += 1
                except Exception:
                    pass
                continue
            
            # Rule 2: Only keep Video and Document. If it's Photo, Sticker, Audio, Animation/GIF, etc., delete it.
            if msg.media not in [enums.MessageMediaType.VIDEO, enums.MessageMediaType.DOCUMENT]:
                try:
                    await userbot.delete_messages(chat_id=target_chat_id, message_ids=msg.id)
                    deleted_count += 1
                    junk_deleted_count += 1
                    await asyncio.sleep(1.2)
                except FloodWait as e:
                    await asyncio.sleep(e.value)
                    await userbot.delete_messages(chat_id=target_chat_id, message_ids=msg.id)
                    deleted_count += 1
                    junk_deleted_count += 1
                except Exception:
                    pass
                continue
                
            media = getattr(msg, msg.media.value, None)
            if not media:
                continue
                
            # Rule 3: Check document extensions (.srt, .txt, .rar, .zip) and delete them
            file_name = getattr(media, "file_name", "") or ""
            if file_name.lower().endswith(('.srt', '.txt', '.rar', '.zip')):
                try:
                    await userbot.delete_messages(chat_id=target_chat_id, message_ids=msg.id)
                    deleted_count += 1
                    junk_deleted_count += 1
                    await asyncio.sleep(1.2)
                except FloodWait as e:
                    await asyncio.sleep(e.value)
                    await userbot.delete_messages(chat_id=target_chat_id, message_ids=msg.id)
                    deleted_count += 1
                    junk_deleted_count += 1
                except Exception:
                    pass
                continue
                
            file_unique_id = getattr(media, "file_unique_id", None)
            if not file_unique_id:
                continue

            # Rule 4: Handle duplicates for valid videos/documents
            if file_unique_id in seen_file_ids:
                try:
                    await userbot.delete_messages(chat_id=target_chat_id, message_ids=msg.id)
                    deleted_count += 1
                    duplicate_deleted_count += 1
                    await asyncio.sleep(1.2)
                except FloodWait as e:
                    await asyncio.sleep(e.value)
                    await userbot.delete_messages(chat_id=target_chat_id, message_ids=msg.id)
                    deleted_count += 1
                    duplicate_deleted_count += 1
                except Exception:
                    pass
            else:
                seen_file_ids.add(file_unique_id)

            if scanned_count % 500 == 0:
                await message.reply(f"📊 Progress: Scanned {scanned_count} | Deleted Junk: {junk_deleted_count} | Deleted Duplicates: {duplicate_deleted_count}")

        await message.reply(f"✅ **Cleanup Finished!**\n● Total Scanned: {scanned_count}\n● Junk/Non-Target Deleted: {junk_deleted_count}\n● Duplicates Deleted: {duplicate_deleted_count}\n● Total Deleted: {deleted_count}")

    except Exception as e:
        await message.reply(f"❌ Error: <code>{e}</code>")
