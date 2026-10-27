# Links the first body mention of a listed place or organisation to its official site. Code picks
# the target, never the model: the Japanese name in the source is the key, since the model spells
# the English name more than one way. See the backend spec, "Official site links".

import json
import re
import unicodedata
from pathlib import Path

SITES_PATH = Path(__file__).resolve().parent.parent / "_data" / "official_sites.json"
# The same attributes as the source link, so every external link opens in a new tab.
NEW_TAB = '{:target="_blank" rel="noopener noreferrer"}'
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)(?:\{:[^}]*\})?")


def load_sites(path=SITES_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _english(site):
    # Longest first, so "Zushi Bunka Plaza Hall" is not cut short by a shorter spelling sharing its start.
    names = sorted(site["en"], key=len, reverse=True)
    return re.compile(r"(?<![\w-])(?:" + "|".join(map(re.escape, names)) + r")(?![\w-])", re.IGNORECASE)


def _named_in(source, site):
    source = unicodedata.normalize("NFKC", source)
    return any(unicodedata.normalize("NFKC", name) in source for name in site["ja"])


def link_first_mention(body, source, sites):
    links = [match.span() for match in LINK.finditer(body)]
    found = [(match.start(), match.end(), index)
             for index, site in enumerate(sites)
             if _named_in(source, site) and site["url"] not in body
             for match in _english(site).finditer(body)
             if not any(start < match.end() and match.start() < end for start, end in links)]
    # One pass over every entry, so file order cannot decide: the longer of two overlapping
    # matches wins ("Enoshima Aquarium" over its "Enoshima"), the earlier one on a tie.
    kept = []
    for start, end, index in sorted(found, key=lambda m: (m[0] - m[1], m[0])):
        if not any(start < other_end and other_start < end for other_start, other_end, _ in kept):
            kept.append((start, end, index))
    first = {}
    for start, end, index in sorted(kept):
        first.setdefault(index, (start, end))
    # From the end backwards, so earlier offsets stay valid.
    for index, (start, end) in sorted(first.items(), key=lambda item: item[1], reverse=True):
        body = f"{body[:start]}[{body[start:end]}]({sites[index]['url']}){NEW_TAB}{body[end:]}"
    return body


def unlink(body):
    return LINK.sub(r"\1", body)


def misses(english, source, sites):
    return [site["ja"][0] for site in sites if _named_in(source, site) and not _english(site).search(english)]
