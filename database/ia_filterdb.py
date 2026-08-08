async def get_search_results(chat_id, query, file_type=None, max_results=10, offset=0, filter=False, **kwargs):
    max_results = 10
    try:
        offset = int(offset)
    except (TypeError, ValueError):
        offset = 0

    query = await extract_v2(query) if 'extract_v2' in globals() else query
    query = query.strip()
    
    if not query:
        return [], 0, 0

    words = normalize(query)
    if not words:
        return [], 0, 0

    base_filter = {}
    if file_type:
        base_filter["file_type"] = file_type

    # 1. Strict Query: All words must match completely as distinct words
    strict_conditions = [{"file_name": {"$regex": rf"\b{re.escape(w)}\b", "$options": "i"}} for w in words]
    strict_filter = {**base_filter, "$and": strict_conditions}

    # 2. Inside-Word Fuzzy Query: Keeps ALL words (including "of", "in", "the") 
    # but allows substring matching so truncated words like "throne" match inside "thrones"
    fuzzy_conditions = [{"file_name": {"$regex": re.escape(w), "$options": "i"}} for w in words]
    fuzzy_filter = {**base_filter, "$and": fuzzy_conditions}

    # Execute both queries simultaneously
    strict_cursor = Media.find(strict_filter).sort("$natural", -1)
    strict_files = await strict_cursor.to_list(length=100)

    fuzzy_cursor = Media.find(fuzzy_filter).sort("$natural", -1)
    fuzzy_files = await fuzzy_cursor.to_list(length=100)

    # Combine results: Strict matches first, followed by inside-word fuzzy matches (no duplicates)
    seen_ids = set()
    combined_files = []
    
    for file in strict_files:
        if file.file_id not in seen_ids:
            seen_ids.add(file.file_id)
            combined_files.append(file)
            
    for file in fuzzy_files:
        if file.file_id not in seen_ids:
            seen_ids.add(file.file_id)
            combined_files.append(file)

    total_results = len(combined_files)
    if total_results == 0:
        return [], 0, 0

    paginated_files = combined_files[offset:offset + max_results]

    next_offset = offset + len(paginated_files)
    if next_offset >= total_results:
        next_offset = ""

    return paginated_files, next_offset, total_results
