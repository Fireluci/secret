import re
from os import environ
from Script import script 

id_pattern = re.compile(r'^.\d+$')

SESSION = environ.get('SESSION', 'Media_search')
API_ID = int(environ.get('API_ID', '1736204'))
API_HASH = environ.get('API_HASH', '890d40e0f91a4de32dec2965444b2cbe')
BOT_TOKEN = environ.get('BOT_TOKEN', '')
PREMIUM_LOG = int(environ.get('PREMIUM_LOG', '-1003911194697')) 
PREMIUM_PERMANENT_LINK = environ.get('PREMIUM_PERMANENT_LINK', 'https://t.me/+n0ENmAyL2l0wZmQ1')
PREMIUM_GROUP_ID = int(environ.get("PREMIUM_GROUP_ID", "-1003982795858"))
DATABASE_URI = environ.get('DATABASE_URI', "")
DATABASE_NAME = environ.get('DATABASE_NAME', "heroflix")
COLLECTION_NAME = environ.get('COLLECTION_NAME', 'heroflix')
UPI_ID = environ.get("UPI_ID", "karthik.slice@ybl")
CAPTION_INDEX_CHANNEL = int(environ.get('CAPTION_INDEX_CHANNEL', '-1002299214709'))
CACHE_TIME = int(environ.get('CACHE_TIME', 300))
PREMIUM_LOG_CHANNEL = int(environ.get('PREMIUM_LOG_CHANNEL', '-1003911194697'))
PICS = environ.get("PICS", "https://te.legra.ph/file/d6a23f16e002e86381656.jpg")
ADMINS = [int(admin) if id_pattern.search(admin) else admin for admin in environ.get('ADMINS', '1058015838').split()]
CHANNELS = [int(ch) if id_pattern.search(ch) else ch for ch in environ.get('CHANNELS', '-1001638006524 -1002299214709').split()]
auth_users = [int(user) if id_pattern.search(user) else user for user in environ.get('AUTH_USERS', '1058015838').split()]
AUTH_USERS = (auth_users + ADMINS) if auth_users else []
auth_channel = environ.get('AUTH_CHANNEL', '-1002048881772')
AUTH_CHANNEL = int(auth_channel) if auth_channel and id_pattern.search(auth_channel) else None
support_chat_id = environ.get('SUPPORT_CHAT_ID', '')
REQST_CHANNEL = int(environ.get('REQST_CHANNEL_ID', '')) if environ.get('REQST_CHANNEL_ID') else None
SUPPORT_CHAT_ID = int(support_chat_id) if support_chat_id and id_pattern.search(support_chat_id) else None

PORT = environ.get("PORT", "8080")
GRP_LNK = environ.get('GRP_LNK', 'https://t.me/heroflix')
CHNL_LNK = environ.get('CHNL_LNK', 'heroflix')
LOG_CHANNEL = int(environ.get('LOG_CHANNEL', '-1001652564383'))
SUPPORT_CHAT = environ.get('SUPPORT_CHAT', 'herofeedbot')

CUSTOM_FILE_CAPTION = environ.get("CUSTOM_FILE_CAPTION", f"{script.CAPTION}")
 
