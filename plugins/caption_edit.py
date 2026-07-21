import re
import logging
from pyrogram import Client, filters
from info import CAPTION_INDEX_CHANNEL
from database.ia_filterdb import Media, normalize, normalize_basic_episode, unpack_new_file_id

logger = logging.getLogger(__name__)

REMOVE_WORDS={"WEBRIP","WEB","HDRIP","BLURAY","BDRIP","DVDRIP","WEBDL","AMZN","NF","DSNP","HMAX","ATVP","ZEE5","JIO","SONYLIV","DDP","DD","AAC","AC3","EAC3","TRUEHD","ATMOS","TRUE","UNTOUCHED","KBPS","MKV","MP4","AVI","PRIVATEMOVIEZ","FREEDRIVEMOVIE","COM","EON","DUAL","MULTI","AUDIO"}

LANG_MAP={
"ENG":"English","ENGLISH":"English","HIN":"Hindi","HINDI":"Hindi","TAM":"Tamil","TAMIL":"Tamil","TEL":"Telugu","TELUGU":"Telugu","MAL":"Malayalam","MALAYALAM":"Malayalam","KAN":"Kannada","KANNADA":"Kannada","MAR":"Marathi","MARATHI":"Marathi","BEN":"Bengali","BENGALI":"Bengali","PUN":"Punjabi","PUNJABI":"Punjabi","GUJ":"Gujarati","GUJARATI":"Gujarati","ORI":"Odia","ODIA":"Odia","ODIYA":"Odia","ASM":"Assamese","ASSAMESE":"Assamese","CHI":"Chinese","CHINESE":"Chinese","JAP":"Japanese","JPN":"Japanese","JAPANESE":"Japanese","KOR":"Korean","KOREAN":"Korean","THAI":"Thai","INDO":"Indonesian","INDONESIAN":"Indonesian","VIE":"Vietnamese","VIETNAMESE":"Vietnamese","ARA":"Arabic","ARABIC":"Arabic","TUR":"Turkish","TURKISH":"Turkish","RUS":"Russian","RUSSIAN":"Russian","SPA":"Spanish","SPANISH":"Spanish","POR":"Portuguese","PORTUGUESE":"Portuguese","FRE":"French","FRA":"French","FRENCH":"French","GER":"German","DEU":"German","GERMAN":"German","ITA":"Italian","ITALIAN":"Italian","DUT":"Dutch","NLD":"Dutch","DUTCH":"Dutch","POL":"Polish","POLISH":"Polish","SWE":"Swedish","SWEDISH":"Swedish","NOR":"Norwegian","NORWEGIAN":"Norwegian","DAN":"Danish","DANISH":"Danish","FIN":"Finnish","FINNISH":"Finnish"}

def clean_caption(text):
    if not text:return ""
    text=text.split("\n")[0]
    text=re.sub(r'@\S+',' ',text)
    text=re.sub(r'\b(MSUBS?|ESUBS?)\b','ESubs',text,flags=re.I)
    text=re.sub(r'\bAVC\b','x264',text,flags=re.I)
    text=re.sub(r'\bH[\.\-_ ]?264\b','x264',text,flags=re.I)
    text=re.sub(r'\bH[\.\-_ ]?265\b','x265',text,flags=re.I)
    text=re.sub(r'\bWEB[\.\-_ ]?DL\b',' ',text,flags=re.I)
    text=re.sub(r'\bDDP?\+?\s*[\d\.]+\b',' ',text,flags=re.I)
    text=re.sub(r'\b(AAC|AC3|EAC3)\s*[\d\.]+\b',' ',text,flags=re.I)
    text=re.sub(r'\b\d+\s*KBPS\b',' ',text,flags=re.I)
    text=re.sub(r'\b\d+(\.\d+)?\s?(GB|MB|TB)\b',' ',text,flags=re.I)
    text=re.sub(r'\b\d{1,2}:\d{2}(:\d{2})?\b',' ',text)
    text=re.sub(r'\.(mkv|mp4|avi|m4v)$','',text,flags=re.I)
    text=re.sub(r'[\[\]\(\)\{\}]',' ',text)
    text=re.sub(r'[^A-Za-z0-9 ]+',' ',text)
    for k,v in LANG_MAP.items():text=re.sub(rf"\b{k}\b",v,text,flags=re.I)
    out=[];seen=set()
    for w in text.split():
        u=w.upper()
        if u=="10BIT":w="10bit"
        elif u=="X264":w="x264"
        elif u=="X265":w="x265"
        elif u in("HEVC","AV1","PSA"):w=u
        elif u in REMOVE_WORDS:continue
        if w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
    text=" ".join(out)
    for c in("x264","x265"):
        if re.search(rf"\b{c}\b",text,re.I):
            text=re.sub(rf"\b{c}\b","",text,flags=re.I)
            text=re.sub(r"\bESubs\b",f"{c} ESubs",text,flags=re.I)
            break
    return re.sub(r"\s+"," ",text).strip()

@Client.on_edited_message(filters.chat(CAPTION_INDEX_CHANNEL))
async def caption_edit_handler(client,message):
    media=message.document or message.video or message.audio
    if not media:return
    source_text=clean_caption(message.caption or media.file_name)[:1000]
    tmp=normalize_basic_episode(source_text)
    normalized_name=" ".join(normalize(tmp))
    display_name=" ".join(w.capitalize() for w in normalize(tmp))
    try:
        file_id,_=unpack_new_file_id(media.file_id)
        await Media.collection.update_one(
            {"_id":file_id},
            {"$set":{
                "file_name":normalized_name,
                "display_name":display_name,
                "caption":source_text if source_text else None
            }}
        )
        logger.info(f"Caption updated for {file_id}")
    except Exception:
        logger.exception("Failed updating caption edit")
