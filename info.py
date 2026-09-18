import re
from os import environ

id_pattern = re.compile(r'^.\d+$')
def is_enabled(value, default):
    if value.lower() in ["true", "yes", "1", "enable", "y"]:
        return True
    elif value.lower() in ["false", "no", "0", "disable", "n"]:
        return False
    else:
        return default

SESSION = environ.get('SESSION', 'Media_search')
API_ID = int(environ.get('API_ID', '28780052'))
API_HASH = environ.get('API_HASH', '2bc69d5385f8e8b62c682883b97621fd')
BOT_TOKEN = environ.get('BOT_TOKEN', '85867547u7tdRlLYC5wt7JdQb4')

DATABASE_URI = environ.get('DATABASE_URI', "mongodbriana")
DATABASE_NAME = environ.get('DATABASE_NAME', "mini")
COLLECTION_NAME = environ.get('COLLECTION_NAME', 'index')

CAPTION_INDEX_CHANNEL = int(environ.get('CAPTION_INDEX_CHANNEL', '-1002299214709'))
CHANNELS = [int(ch) if id_pattern.search(ch) else ch for ch in environ.get('CHANNELS', '-1001638006524').split()] + [CAPTION_INDEX_CHANNEL]

PICS = environ.get("PICS", "https://te.legra.ph/file/26e6f0b8df376da856c80.jpg")
FORCE = "https://t.me/MiniStudiosX"
ADMINS = [int(admin) if id_pattern.search(admin) else admin for admin in environ.get('ADMINS', '1058015838 1945334264').split()]


auth_channel = environ.get('AUTH_CHANNEL', '-1001624917302')
AUTH_CHANNEL = int(auth_channel) if auth_channel and id_pattern.search(auth_channel) else None

SHORT1_URL = environ.get('SHORT1_URL', 'easysky.in')
SHORT1_API = environ.get('SHORT1_API', '66c315c6bc6df05d9cb4eec4bae3a2ebda102144')
SHORT2_URL = environ.get('SHORT2_URL', 'vplink.in')
SHORT2_API = environ.get('SHORT2_API', '8cbd12391c0c8dac548a1d0b7a039e77055e86ed')
IS_SHORTLINK = is_enabled(environ.get("IS_SHORTLINK", "True"), True)
PORT = environ.get("PORT", "8080")
CHNL_LNK = environ.get('CHNL_LNK', 'MiniStudiosX')
TUTORIAL = environ.get('TUTORIAL', 'OpenMSLinkX')
LOG_CHANNEL = int(environ.get('LOG_CHANNEL', '-1002486392693'))
SUPPORT_CHAT = environ.get('SUPPORT_CHAT', 'MiniStudiosAdmin_bot')
 

# ==================== BOT TEXT ====================
START_TXT = """<b>🌀 Unlimited Movies, Series, Anime
🔆 New Releases Upload Every Day
♻️ 24 x 7 Service 📆 Daily Updates</b>"""

STATUS_TXT = """<b>★ Tᴏᴛᴀʟ Fɪʟᴇs: <code>{}</code>
★ Tᴏᴛᴀʟ Usᴇʀs: <code>{}</code>
★ Tᴏᴛᴀʟ Cʜᴀᴛs: <code>{}</code>
★ Usᴇᴅ Sᴛᴏʀᴀɢᴇ: <code>{}</code>
★ Fʀᴇᴇ Sᴛᴏʀᴀɢᴇ: <code>{}</code></b>"""

LOG_TEXT_P = """#NewUser
ID - <code>{}</code>
Nᴀᴍᴇ - {}"""



NO_RESULTS = """<b><i>💢 No Results For Your Search❗️

⚠️ The Reason❓[<a href="https://telegram.me/MiniStudiosX/386">Click Here</a>]
🌀 Please Follow Request Tips!
🔆 Request Tips ➔ [<a href="https://telegram.me/MiniStudiosX/385">Click Here</a>]</i></b>"""

CAPTION = '<a href="https://telegram.me/HeroFlix"><b>{file_name}</b></a>'

RESTART_TXT = """
<b>Bᴏᴛ Rᴇsᴛᴀʀᴛᴇᴅ !

📅 Dᴀᴛᴇ : <code>{}</code>
⏰ Tɪᴍᴇ : <code>{}</code>
🌐 Tɪᴍᴇᴢᴏɴᴇ : <code>Asia/Kolkata</code>
🛠️ Bᴜɪʟᴅ Sᴛᴀᴛᴜs: <code>v2.7.1 [ Sᴛᴀʙʟᴇ ]</code></b>"""

LOGO = '🔆彡[ MiniStudiosX ]彡🔆'

 
 
SPELL_CHECK_REPLY = is_enabled(environ.get("SPELL_CHECK_REPLY", "True"), True)
 
 
