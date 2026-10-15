import hashlib
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit


def normalize_link(link):
    parts = urlsplit(link)
    # A publisher moving to https must not make every item look new (Keizai, 2026-10-06).
    scheme = "https" if parts.scheme.lower() == "http" else parts.scheme.lower()
    return urlunsplit((scheme, parts.netloc.lower(), parts.path, "", ""))


# Town News labels a story carried in another town's edition with 〈藤沢市〉, so without
# this the same article reaches the site twice. 【】 labels stay: most are event dates,
# and dropping them would merge next week's edition of a recurring event with this one.
ANGLE_LABEL = re.compile(r"^\s*〈[^〉]*〉")


def normalize_title(title):
    return " ".join(ANGLE_LABEL.sub("", title).split())


# Town News descriptions are a fixed teaser of the body, so a retitled copy of one article
# in another edition still has the same one. Hashed to keep state.json small.
def description_key(description):
    text = " ".join(unicodedata.normalize("NFKC", description).split())
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] if text else ""


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
