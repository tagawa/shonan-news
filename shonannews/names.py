import difflib
import re
import unicodedata

# One spelling per name, applied in code because a prompt rule cannot guarantee it.
# Add an entry when scripts/audit_names.py or a reader finds a name the model spells
# more than one way. Keyed on the Japanese, so a correction only fires on items whose
# source names it. See the backend spec, "Canonical names".
CANONICAL = {
    # Nakajima Saburōsuke, the Town News Yokosuka series 三郎助を追う. Episodes 57 to 62
    # were published as "Sabrosuke" and 55 to 56 as "Saburōsuke" (live, 2026-09-25).
    "三郎助": "Saburōsuke",
    # Published once as "Hira-tsuka" and fixed by hand by the owner, 2026-09-25.
    "平塚": "Hiratsuka",
    "しおかぜ": "Shiokaze",
    # gpt-6-luna wrote "Kamakura Intel" in 3 of 4 responses in the 2026-09-25 model round.
    # Keyed on the club's full name, since インテル alone is also Intel Corporation.
    "鎌倉インテル": "Inter",
    "ラーテルイベント": "Ratel Event",
    "ソレイユの丘": "Soleil Hill",
    # Hiratsuka's 城島 district, read きじま (the source's own きじまルシェ). Not a postal
    # district, so the place readings cannot hint it.
    "城島": "Kijima",
    "宮原青子": "Seiko Miyahara"
}

# Wrong readings of a CANONICAL name that are too far from it to be near misses, or more than
# one word, rewritten as whole phrases when the source names the key. Only readings the model
# has actually produced.
MISREADINGS = {
    # Published as "Jojima" and "Kishima Marche" on 2026-10-27, fixed by hand by the owner.
    "城島": ("Jojima", "Kishima"),
    # Published once, 2026-09-02, against "Soleil Hill" in 9 live posts (2026-10-27).
    "ソレイユの丘": ("Soleil no Oka",),
}

# Places better known locally by their Japanese name: the first body mention of the English
# name gets the local one in brackets, so a reader can ask the way or search for it. Keyed on
# the Japanese, like CANONICAL. Owner's list, added to by hand. See the backend spec, "Local names".
LOCAL_NAMES = {
    "ソレイユの丘": ("Soleil Hill", "Soleil no Oka"),
    "新江ノ島水族館": ("Enoshima Aquarium", "Enosui"),
}

# Hyphenated parts are included so a split name ("Hira-tsuka") is seen whole; a
# compound on the real name ("Hiratsuka-based") then contains it and is left alone.
# No apostrophe, so a possessive keeps its "'s" on correction.
NAME_TOKEN = re.compile(r"\b[A-Z][A-Za-zāīūēō]{3,}(?:-[A-Za-zāīūēō]+)*\b")


def normalize(text):
    for macron, plain in (("ō", "o"), ("ū", "u"), ("ā", "a"), ("ī", "i"), ("ē", "e")):
        text = text.replace(macron, plain)
    return text.lower()


def _shared_prefix(a, b):
    a, b = normalize(a), normalize(b)
    length = 0
    while length < min(len(a), len(b)) and a[length] == b[length]:
        length += 1
    return length


def is_near_miss(a, b, min_prefix, min_ratio):
    na, nb = normalize(a), normalize(b)
    if na == nb or na in nb or nb in na:
        return False  # a compound holding the whole name is a real name, not a misreading
    return _shared_prefix(a, b) >= min_prefix and difflib.SequenceMatcher(None, na, nb).ratio() >= min_ratio


def enforce_canonical(text, source, table=CANONICAL, misreadings=MISREADINGS):
    for japanese, expected in table.items():
        if japanese not in source:
            continue
        for reading in misreadings.get(japanese, ()):
            text = re.sub(rf"\b{re.escape(reading)}\b", expected, text, flags=re.IGNORECASE)

        def fix(match):
            token = match.group(0).replace("-", "")
            # Stricter ratio than the audit's shortlist, since this rewrites without review. The
            # prefix was 3 until "Sanrosuke" (2026-10-16); at 2 it changed no other live post.
            same_name = normalize(token) == normalize(expected) or is_near_miss(token, expected, 2, 0.8)
            return expected if same_name else match.group(0)

        text = NAME_TOKEN.sub(fix, text)
    return text


def add_local_name(body, source, table=LOCAL_NAMES):
    source = unicodedata.normalize("NFKC", source)
    for japanese, (english, local) in table.items():
        if unicodedata.normalize("NFKC", japanese) not in source or local.lower() in body.lower():
            continue
        # A possessive is skipped: "Soleil Hill (Soleil no Oka)'s field" splits it from its name.
        # No hyphen in the lookbehind: "Shin-Enoshima Aquarium" is the same place with a prefix.
        mention = re.search(rf"(?<!\w){re.escape(english)}(?![\w-]|['’]s\b)", body)
        if mention:
            body = f"{body[:mention.end()]} ({local}){body[mention.end():]}"
    return body
