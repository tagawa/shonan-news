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
# Peninsula is not Miura, nor is Miura Anjin (William Adams), whose land was in Yokosuka.
NOT_THE_VENUE = re.compile(
    rf"\b{_TOWN}-born\b|\bborn in {_TOWN}\b|\b{_TOWN} [Rr]esidents?\b|\b[Rr]esidents? of {_TOWN}\b"
    rf"|\blives? in {_TOWN}\b|\bliving in {_TOWN}\b|\bbased in {_TOWN}(?: and {_TOWN})?\b"
    rf"|\bnative of {_TOWN}\b|\b{_TOWN} Peninsula\b|\bMiura Anjin\b")
JAPANESE_NAMES = {places.short_name(ja): en for en, ja in places.MUNICIPALITIES.items()}
# The description's own version of NOT_THE_VENUE: a clause saying where someone lives,
# comes from or is based.
NOT_THE_VENUE_JA = re.compile(r"在住|出身|拠点")
CLAUSE = re.compile(r"[、。()]")
# Somewhere outside the twelve towns: another prefecture or Tokyo, or a Kanagawa municipality
# outside the area. An event there is often a local team or artist travelling.
OUTSIDE = re.compile(
    r"北海道|青森|岩手|宮城|秋田|山形|福島|茨城|栃木|群馬|埼玉|千葉|東京|新潟|富山|石川|福井|山梨|長野"
    r"|岐阜|静岡|愛知|三重|滋賀|京都|大阪|兵庫|奈良|和歌山|鳥取|島根|岡山|広島|山口|徳島|香川|愛媛|高知"
    r"|福岡|佐賀|長崎|熊本|大分|宮崎|鹿児島|沖縄"
    r"|横浜|川崎|相模原|小田原|厚木|大和市|伊勢原|海老名|座間|南足柄|綾瀬|秦野|大井町|松田町|山北|開成町"
    r"|箱根|真鶴|湯河原|愛川|清川")


def find(title, lede, summary, source_title, towns, description=""):
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
    if candidates:
        return candidates[0] if len(candidates) == 1 else None
    return _description_town(description, towns)


def _description_town(description, towns):
    # Read last, and more warily than the title: a description also says where people live
    # and where they travel to. Measured on 38 posts; see the backend spec, "Event town".
    text = unicodedata.normalize("NFKC", description or "")
    text = "、".join(clause for clause in CLAUSE.split(text) if not NOT_THE_VENUE_JA.search(clause))
    if OUTSIDE.search(text):
        return None
    candidates = _japanese_towns(text, towns)
    return candidates[0] if len(candidates) == 1 else None


def _japanese_towns(source, towns):
    text = unicodedata.normalize("NFKC", source or "").translate(places.SPELLING)
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
