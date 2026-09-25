import difflib
import re

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


def enforce_canonical(text, source, table=CANONICAL):
    for japanese, expected in table.items():
        if japanese not in source:
            continue

        def fix(match):
            token = match.group(0).replace("-", "")
            # Stricter than the audit's shortlist threshold, since this rewrites without review.
            same_name = normalize(token) == normalize(expected) or is_near_miss(token, expected, 3, 0.8)
            return expected if same_name else match.group(0)

        text = NAME_TOKEN.sub(fix, text)
    return text
