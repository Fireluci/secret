import re
from os import environ
from Script import script 

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
BOT_TOKEN = environ.get('BOT_TOKEN', '')
PREMIUM_PERMANENT_LINK = environ.get('PREMIUM_PERMANENT_LINK', 'https://t.me/+n0ENmAyL2l0wZmQ1')
DATABASE_URI = environ.get('DATABASE_URI', "")
DATABASE_NAME = environ.get('DATABASE_NAME', "heroflix")
COLLECTION_NAME = environ.get('COLLECTION_NAME', 'heroflix')
PREMIUM_GROUP_ID = int(environ.get("PREMIUM_GROUP_ID", "-1004332579881"))
UPI_ID = environ.get("UPI_ID", "karthik.slice@ybl")
CAPTION_INDEX_CHANNEL = int(environ.get('CAPTION_INDEX_CHANNEL', '-1002299214709'))
CACHE_TIME = int(environ.get('CACHE_TIME', 300))
USE_CAPTION_FILTER = bool(environ.get('USE_CAPTION_FILTER', False))
PREMIUM_LOG_CHANNEL = int(environ.get('PREMIUM_LOG_CHANNEL', '-1003911194697'))
PICS = environ.get("PICS", "https://te.legra.ph/file/d6a23f16e002e86381656.jpg")
FORCE = "https://telegram.me/+W6BkAHSGGME3OGY1"
ADMINS = [int(admin) if id_pattern.search(admin) else admin for admin in environ.get('ADMINS', '1058015838').split()]
CHANNELS = [int(ch) if id_pattern.search(ch) else ch for ch in environ.get('CHANNELS', '-1001638006524 -1002299214709').split()]
auth_users = [int(user) if id_pattern.search(user) else user for user in environ.get('AUTH_USERS', '1058015838').split()]
AUTH_USERS = (auth_users + ADMINS) if auth_users else []
PREMIUM_USER = [int(user) if id_pattern.search(user) else user for user in environ.get('PREMIUM_USER', '').split()]
auth_channel = environ.get('AUTH_CHANNEL', '-1002048881772')
auth_grp = environ.get('AUTH_GROUP', '')
AUTH_CHANNEL = int(auth_channel) if auth_channel and id_pattern.search(auth_channel) else None
AUTH_GROUPS = [int(ch) for ch in auth_grp.split()] if auth_grp else None
support_chat_id = environ.get('SUPPORT_CHAT_ID', '')
reqst_channel = environ.get('REQST_CHANNEL_ID', '')
REQST_CHANNEL = int(reqst_channel) if reqst_channel and id_pattern.search(reqst_channel) else None
SUPPORT_CHAT_ID = int(support_chat_id) if support_chat_id and id_pattern.search(support_chat_id) else None
NO_RESULTS_MSG = bool(environ.get("NO_RESULTS_MSG", False))

SHORTLINK_URL = environ.get('SHORTLINK_URL', 'softurl.in')
SHORTLINK_API = environ.get('SHORTLINK_API', '373c1560e683c6254a5eb3c56209ef8e46ac8923')
SECOND_SHORTLINK_URL = environ.get('SECOND_SHORTLINK_URL', 'softurl.in')
SECOND_SHORTLINK_API = environ.get('SECOND_SHORTLINK_API', '373c1560e683c6254a5eb3c56209ef8e46ac8923')
IS_SHORTLINK = bool(environ.get('IS_SHORTLINK', True))
MAX_B_TN = environ.get("MAX_B_TN", "10")
MAX_BTN = is_enabled((environ.get('MAX_BTN', "True")), True)
PORT = environ.get("PORT", "8080")
GRP_LNK = environ.get('GRP_LNK', 'https://t.me/heroflix')
CHNL_LNK = environ.get('CHNL_LNK', 'heroflix')
TUTORIAL = environ.get('TUTORIAL', 'HeroFlixx/54')
IS_TUTORIAL = bool(environ.get('IS_TUTORIAL', True))
MSG_ALRT = environ.get('MSG_ALRT', 'Wʜᴀᴛ Aʀᴇ Yᴏᴜ Lᴏᴏᴋɪɴɢ Aᴛ ?')
LOG_CHANNEL = int(environ.get('LOG_CHANNEL', '-1001652564383'))
SUPPORT_CHAT = environ.get('SUPPORT_CHAT', 'herofeedbot')
P_TTI_SHOW_OFF = is_enabled((environ.get('P_TTI_SHOW_OFF', "False")), False)
 
AUTO_FFILTER = is_enabled((environ.get('AUTO_FFILTER', "True")), True)
AUTO_DELETE = is_enabled((environ.get('AUTO_DELETE', "True")), True)
SINGLE_BUTTON = is_enabled((environ.get('SINGLE_BUTTON', "False")), False)
CUSTOM_FILE_CAPTION = environ.get("CUSTOM_FILE_CAPTION", f"{script.CAPTION}")
BATCH_FILE_CAPTION = environ.get("BATCH_FILE_CAPTION", CUSTOM_FILE_CAPTION)
 
SPELL_CHECK_REPLY = is_enabled(environ.get("SPELL_CHECK_REPLY", "True"), True)
MELCOW_NEW_USERS = is_enabled((environ.get('MELCOW_NEW_USERS', "False")), False)
PROTECT_CONTENT = is_enabled((environ.get('PROTECT_CONTENT', "False")), False)
 
 
