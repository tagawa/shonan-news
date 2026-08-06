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
    return key in state.get(feed_url, {}).get("processed", [])


def mark_processed(state, feed_url, key, cap=500):
    feed_state = get_feed_state(state, feed_url)
    processed = feed_state["processed"]
    if key not in processed:
        processed.append(key)
    if len(processed) > cap:
        feed_state["processed"] = processed[-cap:]
