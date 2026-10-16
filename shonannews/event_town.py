# The town an event happens in, for What's on rows. Chosen on 100 live events and passed on the
# next 103 (0 wrong of 88 shown). See the backend spec, "Event town".

import re
import unicodedata
from collections import Counter

from shonannews import places

TOWNS = list(places.MUNICIPALITIES)
NAMED = re.compile(r"\b(" + "|".join(TOWNS) + r")\b")
_TOWN = "(?:" + "|".join(TOWNS) + ")"
# A town named as where a person or organisation is from, not where the event is. The Miura
# Peninsula is not Miura.
NOT_THE_VENUE = re.compile(
    rf"\b{_TOWN}-born\b|\bborn in {_TOWN}\b|\b{_TOWN} [Rr]esidents?\b|\b[Rr]esidents? of {_TOWN}\b"
    rf"|\blives? in {_TOWN}\b|\bliving in {_TOWN}\b|\bbased in {_TOWN}(?: and {_TOWN})?\b"
    rf"|\bnative of {_TOWN}\b|\b{_TOWN} Peninsula\b")
JAPANESE_NAMES = {places.short_name(ja): en for en, ja in places.MUNICIPALITIES.items()}


def find(title, lede, summary, source_title, towns):
    english = " ".join([title, lede or "", summary])
    mentions = NAMED.findall(NOT_THE_VENUE.sub(" ", english))
    found = list(dict.fromkeys(mentions))
    if len(found) == 1:
        return found[0]
    if found:
        in_edition = [town for town in found if town in towns]
        if len(in_edition) == 1:
            return in_edition[0]
        counts = Counter(mentions).most_common(2)
        return counts[0][0] if counts[0][1] > counts[1][1] else None
    # Every town the English names is where someone is from: a story about a person, often
    # one taking part in something far away.
    if NAMED.search(english):
        return None
    candidates = _japanese_towns(source_title, towns)
    return candidates[0] if len(candidates) == 1 else None


def _japanese_towns(source_title, towns):
    text = unicodedata.normalize("NFKC", source_title or "").translate(places.SPELLING)
    named = [en for short, en in JAPANESE_NAMES.items() if short in text]
    # A district counts only inside the edition's towns: elsewhere it is usually a surname or
    # another place. A feed with no edition allows every town.
    allowed = {places.MUNICIPALITIES[town] for town in towns} or set(places.MUNICIPALITIES.values())
    english = {ja: en for en, ja in places.MUNICIPALITIES.items()}
    gazetteer = places.load_places()
    found, _ = places.find_keys(text, gazetteer)
    districts = []
    for key, _reading in found:
        matches = set(gazetteer[key]) & allowed
        if len(matches) == 1:
            districts.append(english[matches.pop()])
    return list(dict.fromkeys(named + districts))
