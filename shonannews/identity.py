import hashlib
from urllib.parse import urlsplit, urlunsplit


def normalize_link(link):
    parts = urlsplit(link)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, "", ""))


def identity_key(entry):
    guid = entry.get("id")
    if guid:
        return f"guid:{guid}"

    link = entry.get("link")
    if link:
        return f"link:{normalize_link(link)}"

    title = entry.get("title", "")
    digest = hashlib.sha256(title.encode("utf-8")).hexdigest()
    return f"title:{digest}"
