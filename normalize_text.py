# liz/helpers/normalize_text.py
import unicodedata
import re

def normalize_fancy_text(text: str) -> str:
    """
    Convert any fancy Unicode fonts to plain lowercase text.
    Works for bold, italic, cursive, fullwidth, small caps, etc.
    """
    if not text:
        return ""
    # Decompose Unicode characters into normal forms
    text = unicodedata.normalize("NFKD", text)
    # Remove symbols and keep letters/numbers/spaces only
    text = re.sub(r'[^0-9A-Za-z\s]+', '', text)
    return text.lower().strip()
