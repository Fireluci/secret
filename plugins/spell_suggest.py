from pyrogram import Client, filters
from spellchecker import SpellChecker

spell = SpellChecker(language='en')

@Client.on_message(filters.text)
async def spell_suggest(client, message):
    user_text = message.text
    words = user_text.split()

    # Find possible corrections for misspelled words
    suggestions = []
    for word in words:
        if word.lower() in spell:
            suggestions.append(word)  # already correct
        else:
            suggestion = spell.correction(word)
            suggestions.append(suggestion if suggestion else word)

    suggested_text = " ".join(suggestions)

    # Reply with suggested correct spelling
    await message.reply_text(f"📝 Did you mean: {suggested_text}")
