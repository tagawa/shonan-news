import json


class StateCorruptError(Exception):
    pass


def load_state(path):
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as exc:
            raise StateCorruptError(f"Could not parse state file {path}: {exc}") from exc


def save_state(path, state):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")


def get_feed_state(state, feed_url):
    return state.setdefault(feed_url, {"etag": None, "modified": None, "processed": []})


def is_processed(state, feed_url, key):
    processed = state.get(feed_url, {}).get("processed", [])
    # Link keys stored before identity.normalize_link folded http to https still say http.
    legacy = key.replace("link:https://", "link:http://", 1)
    return key in processed or legacy in processed


def mark_processed(state, feed_url, key, cap=500):
    feed_state = get_feed_state(state, feed_url)
    processed = feed_state["processed"]
    if key not in processed:
        processed.append(key)
    if len(processed) > cap:
        feed_state["processed"] = processed[-cap:]


def _is_listed(state, list_key, value):
    if not value:
        return False
    return value in state.get(list_key, [])


def _mark_listed(state, list_key, value, cap):
    if not value:
        return
    values = state.setdefault(list_key, [])
    if value not in values:
        values.append(value)
    if len(values) > cap:
        state[list_key] = values[-cap:]


def is_source_title_posted(state, normalized_title):
    return _is_listed(state, "posted_source_titles", normalized_title)


def mark_source_title_posted(state, normalized_title, cap=750):
    _mark_listed(state, "posted_source_titles", normalized_title, cap)


def is_source_description_posted(state, key):
    return _is_listed(state, "posted_source_descriptions", key)


def mark_source_description_posted(state, key, cap=750):
    _mark_listed(state, "posted_source_descriptions", key, cap)


def record_merge_shadow(state, entry, cap=200):
    # Temporary: the story merge shadow's record, read at the morning check. Removed at release 2.
    entries = state.setdefault("merge_shadow", [])
    entries.append(entry)
    if len(entries) > cap:
        state["merge_shadow"] = entries[-cap:]
