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
API_ID = int(environ.get('API_ID', '24314601'))
API_HASH = environ.get('API_HASH', 'ede341e2d490a0fad5469866dedf8a95')
BOT_TOKEN = environ.get('BOT_TOKEN', '')

DATABASE_URI = environ.get('DATABASE_URI', "")
DATABASE_NAME = environ.get('DATABASE_NAME', "database")
COLLECTION_NAME = environ.get('COLLECTION_NAME', 'database')

CAPTION_INDEX_CHANNEL = int(environ.get('CAPTION_INDEX_CHANNEL', '-1002299214709'))
CHANNELS = [int(ch) if id_pattern.search(ch) else ch for ch in environ.get('CHANNELS', '-1001638006524').split()] + [CAPTION_INDEX_CHANNEL]

PICS = environ.get("PICS", "https://te.legra.ph/file/7bece5ddc3e001805c02f.jpg")
FORCE = "https://t.me/kannadacineplex2"
ADMINS = [int(admin) if id_pattern.search(admin) else admin for admin in environ.get('ADMINS', '1058015838 6178075056 640617767').split()]


auth_channel = environ.get('AUTH_CHANNEL', '-1002215944038')
AUTH_CHANNEL = int(auth_channel) if auth_channel and id_pattern.search(auth_channel) else None

SHORT1_URL = environ.get('SHORT1_URL', 'softurl.in')
SHORT1_API = environ.get('SHORT1_API', '65676573da083f670527098369bf4417fae2b457')
SHORT2_URL = environ.get('SHORT2_URL', 'softurl.in')
SHORT2_API = environ.get('SHORT2_API', '65676573da083f670527098369bf4417fae2b457')
IS_SHORTLINK = is_enabled(environ.get("IS_SHORTLINK", "True"), True)
PORT = environ.get("PORT", "8080")
CHNL_LNK = environ.get('CHNL_LNK', 'CinepleX1')
TUTORIAL = environ.get('TUTORIAL', 'publicth001/2')
LOG_CHANNEL = int(environ.get('LOG_CHANNEL', '-1002196916445'))
SUPPORT_CHAT = environ.get('SUPPORT_CHAT', 'link_report')
 

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



NO_RESULTS = """<b>💢 No Results For Your Search❗️</b>"""

CAPTION = '<a href="https://telegram.me/CinepleX1"><b>{file_name}</b></a>'

RESTART_TXT = """
<b>Bᴏᴛ Rᴇsᴛᴀʀᴛᴇᴅ !

📅 Dᴀᴛᴇ : <code>{}</code>
⏰ Tɪᴍᴇ : <code>{}</code>
🌐 Tɪᴍᴇᴢᴏɴᴇ : <code>Asia/Kolkata</code>
🛠️ Bᴜɪʟᴅ Sᴛᴀᴛᴜs: <code>v2.7.1 [ Sᴛᴀʙʟᴇ ]</code></b>"""

LOGO = '🔆彡[ CiNEPLEX1 ]彡🔆'

 
 
SPELL_CHECK_REPLY = is_enabled(environ.get("SPELL_CHECK_REPLY", "True"), True)
 
 
