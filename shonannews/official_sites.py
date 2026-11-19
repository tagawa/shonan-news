# Links the first body mention of a listed place or organisation to its official site. Code picks
# the target, never the model: the Japanese name in the source is the key, since the model spells
# the English name more than one way. See the backend spec, "Official site links".

import json
import re
import unicodedata
from pathlib import Path

import yaml

from shonannews.places import SPELLING

SITES_PATH = Path(__file__).resolve().parent.parent / "_data" / "official_sites.json"
# The same attributes as the source link, so every external link opens in a new tab.
NEW_TAB = '{:target="_blank" rel="noopener noreferrer"}'
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)(?:\{:[^}]*\})?")
# Text ending just before a place named only to say where something else is ("a 2-minute walk from
# the north exit of Fujisawa Station"). See the backend spec, "Place photos", "Directions".
DIRECTIONS = re.compile(
    r"\b(?:near(?:by)?|next to|close to|beside|opposite|across from|(?:north|south|east|west) of|walk from|minutes? from|on foot from)"
    r"\s+(?:the\s+)?(?:[\w-]+\s+exit\s+of\s+(?:the\s+)?)?$", re.IGNORECASE)


def load_sites(path=SITES_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def spelling_pattern(site):
    # Longest first, so "Zushi Bunka Plaza Hall" is not cut short by a shorter spelling sharing its start.
    names = sorted(site["en"], key=len, reverse=True)
    return re.compile(r"(?<![\w-])(?:" + "|".join(map(re.escape, names)) + r")(?![\w-])", re.IGNORECASE)


def _named_in(source, site):
    source = unicodedata.normalize("NFKC", source)
    return any(unicodedata.normalize("NFKC", name) in source for name in site["ja"])


def with_short_names(source: str, edition: set[str], sites: list) -> str:
    # Town News drops the city in its own edition (市美術館 for 平塚市美術館), so in an edition with one
    # city a listed name's short form counts as the full name, appended here. Two cities would make
    # 市役所 ambiguous. Only links and photos see this; misses() keeps the plain source. See the
    # backend spec, "Official site links", "Short names".
    cities = [city.translate(SPELLING) for city in edition if city.endswith("市")]
    if len(cities) != 1:
        return source
    folded = unicodedata.normalize("NFKC", source).translate(SPELLING)
    full = [name for site in sites for name in site["ja"]
            if (key := unicodedata.normalize("NFKC", name).translate(SPELLING)).startswith(cities[0])
            and key[len(cities[0]) - 1:] in folded]
    return "\n".join([source, *full]) if full else source


def first_mentions(body, source, sites):
    # Each listed entry's earliest mention in the body, {index: (start, end)}, shared by the links
    # and the place photo so the two cannot disagree.
    links = [match.span() for match in LINK.finditer(body)]
    found = [(match.start(), match.end(), index)
             for index, site in enumerate(sites)
             # An entry without a url (a photo only) still counts, so it wins its overlaps.
             if _named_in(source, site) and not ("url" in site and site["url"] in body)
             for match in spelling_pattern(site).finditer(body)
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
    return first


def new_tab_link(text, url):
    return f"[{text}]({url}){NEW_TAB}"


def link_first_mention(body, source, sites):
    first = first_mentions(body, source, sites)
    # From the end backwards, so earlier offsets stay valid.
    for index, (start, end) in sorted(first.items(), key=lambda item: item[1], reverse=True):
        if "url" not in sites[index]:
            continue
        body = f"{body[:start]}{new_tab_link(body[start:end], sites[index]['url'])}{body[end:]}"
    return body


def add_site_line(body, head, source, sites):
    # A place spelled only in the title or lede (head) has no body mention to link, and those two
    # are never linked, so it gets a line of its own. See the backend spec, "Official site links".
    first = sorted(first_mentions(head, source, sites).items(), key=lambda item: item[1])
    links = [new_tab_link(head[start:end], sites[index]['url'])
             for index, (start, end) in first if "url" in sites[index] and not spelling_pattern(sites[index]).search(body)]
    if not links:
        return body
    return f"{body}\n\nOfficial site{'s' if len(links) > 1 else ''}: {', '.join(links)}"


def given_as_directions(text, site):
    # Any one such mention is enough: better no photo than a wrong one (owner decision, 2026-11-19).
    text = unlink(text)
    return any(DIRECTIONS.search(text[max(0, match.start() - 60):match.start()])
               for match in spelling_pattern(site).finditer(text))


def place_photo(body, source, sites):
    # The photo of the first place mentioned that has one. See the backend spec, "Place photos".
    for index, _ in sorted(first_mentions(body, source, sites).items(), key=lambda item: item[1]):
        if "photo" in sites[index] and not given_as_directions(body, sites[index]):
            return sites[index]["photo"]["file"]
    return None


def backfill_photos(posts_dir, sites):
    # A photo added after a post was written, given to that post. Keyed on the link, since old posts
    # no longer have their source. See the backend spec, "Place photos", "Later photos".
    photographed = [(f"]({site['url']})", site["photo"]["file"], site) for site in sites if "photo" in site and "url" in site]
    changed = []
    for path in sorted(Path(posts_dir).rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        _, front_matter, body = text.split("---\n", 2)
        if any(yaml.safe_load(front_matter).get(key) for key in ("image_url", "thumb_url", "place_photo")):
            continue
        found = sorted((body.find(link), file) for link, file, site in photographed
                       if link in body and not given_as_directions(body, site))
        if found:
            path.write_text(f"---\n{front_matter}place_photo: {found[0][1]}\n---\n{body}", encoding="utf-8")
            changed.append(path)
    return changed


def unlink(body):
    return LINK.sub(r"\1", body)


def misses(english, source, sites):
    return [site["ja"][0] for site in sites if _named_in(source, site) and not spelling_pattern(site).search(english)]
