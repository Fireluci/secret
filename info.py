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

DATABASE_URI = environ.get('DATABASE_URI', "mongodb+srv://ariana:ariana@ariana.vxqvh5x.mongodb.net/?appName=ariana")
DATABASE_NAME = environ.get('DATABASE_NAME', "heroflix")
COLLECTION_NAME = environ.get('COLLECTION_NAME', 'heroflix')

CAPTION_INDEX_CHANNEL = int(environ.get('CAPTION_INDEX_CHANNEL', '-1002299214709'))

PICS = environ.get("PICS", "https://te.legra.ph/file/d6a23f16e002e86381656.jpg")
FORCE = "https://telegram.me/+W6BkAHSGGME3OGY1"
ADMINS = [int(admin) if id_pattern.search(admin) else admin for admin in environ.get('ADMINS', '1058015838').split()]
CHANNELS = [int(ch) if id_pattern.search(ch) else ch for ch in environ.get('CHANNELS', '-1001638006524 -1002299214709').split()]
PREMIUM_USER = [int(user) if id_pattern.search(user) else user for user in environ.get('PREMIUM_USER', '').split()]
auth_channel = environ.get('AUTH_CHANNEL', '-1002048881772')
AUTH_CHANNEL = int(auth_channel) if auth_channel and id_pattern.search(auth_channel) else None

SHORT1_URL = environ.get('SHORT1_URL', 'cpmshort.com')
SHORT1_API = environ.get('SHORT1_API', '4edd2741cf55b86fd7306942fd25bb163c8f8cd6')
SHORT2_URL = environ.get('SHORT2_URL', 'easysky.in')
SHORT2_API = environ.get('SHORT2_API', 'f3753546bce8faa1a5e9ef961431c0b57e4d26a9')
IS_SHORTLINK = is_enabled(environ.get("IS_SHORTLINK", "True"), True)
PORT = environ.get("PORT", "8080")
CHNL_LNK = environ.get('CHNL_LNK', 'heroflix')
TUTORIAL = environ.get('TUTORIAL', 'HeroFlixx/54')
LOG_CHANNEL = int(environ.get('LOG_CHANNEL', '-1001652564383'))
SUPPORT_CHAT = environ.get('SUPPORT_CHAT', 'herofeedbot')
 
CUSTOM_FILE_CAPTION = environ.get("CUSTOM_FILE_CAPTION", f"{script.CAPTION}")
 
SPELL_CHECK_REPLY = is_enabled(environ.get("SPELL_CHECK_REPLY", "True"), True)
 
 
