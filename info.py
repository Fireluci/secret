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
API_ID = int(environ.get('API_ID', '1736204'))
API_HASH = environ.get('API_HASH', '890d40e0f91a4de32dec2965444b2cbe')
BOT_TOKEN = environ.get('BOT_TOKEN', '8586754770:AAF8lcZRg-4fLdK6Pu7tdRlLYC5wt7JdQb4')

DATABASE_URI = environ.get('DATABASE_URI', "mongodb+srv://ariana:ariana@ariana.vxqvh5x.mongodb.net/?appName=ariana")
DATABASE_NAME = environ.get('DATABASE_NAME', "heroflix")
COLLECTION_NAME = environ.get('COLLECTION_NAME', 'index')

CAPTION_INDEX_CHANNEL = int(environ.get('CAPTION_INDEX_CHANNEL', '-1002299214709'))
CHANNELS = [int(ch) if id_pattern.search(ch) else ch for ch in environ.get('CHANNELS', '-1001638006524').split()] + [CAPTION_INDEX_CHANNEL]
PREMIUM_LOG = int(environ.get('PREMIUM_LOG', '-1003911194697'))
PICS = environ.get("PICS", "https://te.legra.ph/file/d6a23f16e002e86381656.jpg")
FORCE = "https://telegram.me/+W6BkAHSGGME3OGY1"
OWNER = int(environ.get('OWNER', '1058015838'))
ADMINS = [OWNER]


auth_channel = environ.get('AUTH_CHANNEL', '-1002048881772')
AUTH_CHANNEL = int(auth_channel) if auth_channel and id_pattern.search(auth_channel) else None

PORT = environ.get("PORT", "8080")
CHNL_LNK = environ.get('CHNL_LNK', 'HEROFLiX')
LOG_CHANNEL = int(environ.get('LOG_CHANNEL', '-1001652564383'))
PREMIUM_GROUP_ID = environ.get('PREMIUM_GROUP_ID', '-1004463577278')
PREMIUM_PERMANENT_LINK = environ.get('PREMIUM_PERMANENT_LINK', 'https://t.me/+b9x5RFpJdCJlM2Vl')
PREMIUM_UPI_ID = environ.get('PREMIUM_UPI_ID', 'karthik.slice@ibl')
PREMIUM_QR = environ.get('PREMIUM_QR', 'https://ibb.co/KHqPKqg')
SUPPORT_CHAT = environ.get('SUPPORT_CHAT', 'herofeedbot')
 

# ==================== BOT TEXT ====================
START_TXT = """<b>🌀 Unlimited Movies, Series, Anime
🔆 New Releases Upload Every Day
♻️ 24 x 7 Service 📆 Daily Updates
🔗 No Ads or Links 🗃 Direct Files</b>"""

STATUS_TXT = """<b>★ Tᴏᴛᴀʟ Fɪʟᴇs: <code>{}</code>
★ Tᴏᴛᴀʟ Usᴇʀs: <code>{}</code>
★ Tᴏᴛᴀʟ Cʜᴀᴛs: <code>{}</code>
★ Usᴇᴅ Sᴛᴏʀᴀɢᴇ: <code>{}</code>
★ Fʀᴇᴇ Sᴛᴏʀᴀɢᴇ: <code>{}</code></b>"""

LOG_TEXT_P = """#NewUser
ID - <code>{}</code>
Nᴀᴍᴇ - {}"""



NO_RESULTS = """<b><i>💢 No Results For Your Search❗️

⚠️ The Reason❓[<a href="https://telegram.me/HeroFlixx/3">Click Here</a>]
🌀 Please Follow Request Tips!
🔆 Request Tips ➔ [<a href="https://telegram.me/HeroFlixx/2">Click Here</a>]</i></b>"""

CAPTION = '<a href="https://telegram.me/HeroFlix"><b>{file_name}</b></a>'

RESTART_TXT = """
<b>Bᴏᴛ Rᴇsᴛᴀʀᴛᴇᴅ !

📅 Dᴀᴛᴇ : <code>{}</code>
⏰ Tɪᴍᴇ : <code>{}</code>
🌐 Tɪᴍᴇᴢᴏɴᴇ : <code>Asia/Kolkata</code>
🛠️ Bᴜɪʟᴅ Sᴛᴀᴛᴜs: <code>v2.7.1 [ Sᴛᴀʙʟᴇ ]</code></b>"""

LOGO = '🔆彡[ HEROFLiX ]彡🔆'

 
 
SPELL_CHECK_REPLY = is_enabled(environ.get("SPELL_CHECK_REPLY", "True"), True)
 
 
