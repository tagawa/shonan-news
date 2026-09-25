import hashlib
import re
from urllib.parse import urlsplit, urlunsplit


def normalize_link(link):
    parts = urlsplit(link)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, "", ""))


# Town News labels a story carried in another town's edition with 〈藤沢市〉, so without
# this the same article reaches the site twice. 【】 labels stay: most are event dates,
# and dropping them would merge next week's edition of a recurring event with this one.
ANGLE_LABEL = re.compile(r"^\s*〈[^〉]*〉")


def normalize_title(title):
    return " ".join(ANGLE_LABEL.sub("", title).split())


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
