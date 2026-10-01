# Official readings of coverage-area districts, from Japan Post's postcode data, given to the
# model as hints. See the backend spec, "Place readings". The data file is built by
# `python3 -m scripts.gazetteer build`, which also holds the offline audit.

import functools
import json
import re
import unicodedata
from pathlib import Path

GAZETTEER_PATH = Path(__file__).resolve().parent.parent / "data" / "gazetteer.json"

# The twelve municipalities on the About page, as Japan Post writes them. Feed `towns` lists
# in _data/feeds.json use the English names.
MUNICIPALITIES = {
    "Fujisawa": "藤沢市", "Kamakura": "鎌倉市", "Chigasaki": "茅ヶ崎市", "Hiratsuka": "平塚市",
    "Zushi": "逗子市", "Hayama": "三浦郡葉山町", "Samukawa": "高座郡寒川町", "Oiso": "中郡大磯町",
    "Ninomiya": "中郡二宮町", "Nakai": "足柄上郡中井町", "Yokosuka": "横須賀市", "Miura": "三浦市",
}
MIN_KEY = 2  # a one-character stem (上 from 上町) matches 以上, 屋上 and so on
# Japan Post writes 七里ガ浜 and 雪ノ下 where sources write 七里ヶ浜 and 雪の下.
SPELLING = str.maketrans({"ケ": "ヶ", "ガ": "ヶ", "が": "ヶ", "の": "ノ", "之": "ノ"})

KANA = dict(zip(
    "アイウエオカキクケコガギグゲゴサシスセソザジズゼゾタチツテトダヂヅデドナニヌネノ"
    "ハヒフヘホバビブベボパピプペポマミムメモヤユヨラリルレロワヰヱヲンヴ",
    "a i u e o ka ki ku ke ko ga gi gu ge go sa shi su se so za ji zu ze zo ta chi tsu te to "
    "da ji zu de do na ni nu ne no ha hi fu he ho ba bi bu be bo pa pi pu pe po ma mi mu me mo "
    "ya yu yo ra ri ru re ro wa i e o n vu".split(),
))
SMALL_Y = {"ャ": "ya", "ュ": "yu", "ョ": "yo"}
SMALL_VOWEL = {"ァ": "a", "ィ": "i", "ゥ": "u", "ェ": "e", "ォ": "o"}


def romanise(kana):
    syllables = []
    for ch in kana:
        if ch in SMALL_Y and syllables:
            base = syllables.pop()
            # シャ is sha, not shya; ヒャ is hya.
            syllables.append(base[:-1] + SMALL_Y[ch][1] if base in ("shi", "chi", "ji")
                             else base[:-1] + SMALL_Y[ch])
        elif ch in SMALL_VOWEL and syllables:
            syllables.append(syllables.pop()[:-1] + SMALL_VOWEL[ch])
        elif ch == "ー" and syllables:
            syllables.append(syllables[-1][-1])
        else:
            syllables.append(KANA.get(ch, ch))
    out = ""
    for index, syllable in enumerate(syllables):
        if syllable == "ッ":
            following = syllables[index + 1] if index + 1 < len(syllables) else ""
            out += "t" if following.startswith("ch") else following[:1]
        else:
            out += syllable
    return out


def _short_name(municipality):
    # 三浦郡葉山町 is written 葉山 or 葉山町 in a source; 横須賀市 as 横須賀.
    return re.sub(r"[市町]$", "", municipality.split("郡")[-1])


# Consumed whole and never reported, so 須賀 (a Hiratsuka district) cannot match inside 横須賀.
# They win over a district of the same name (藤沢, 鎌倉): a source means the town, which is
# read correctly almost always, and town-name misreads (中井) are audit_names.py's job.
MUNICIPALITY_NAMES = {name for m in MUNICIPALITIES.values()
                      for name in (m, m.split("郡")[-1], _short_name(m)) if len(name) >= MIN_KEY}
# Compounds that contain a district but never mean it: 湘南藤沢 (Keio's SFC campus, a hospital)
# is not 南藤沢.
CONSUMED = MUNICIPALITY_NAMES | {"湘南藤沢"}


def find_keys(source, places):
    source = unicodedata.normalize("NFKC", source).translate(SPELLING)
    longest = max(map(len, [*places, *CONSUMED]), default=0)
    found, skipped, index = [], [], 0
    while index < len(source):
        for size in range(min(longest, len(source) - index), MIN_KEY - 1, -1):
            key = source[index:index + size]
            if key in CONSUMED:
                index += size
                break
            if key in places:
                reading = _resolve(places[key], source)
                if reading is None:
                    skipped.append(key)
                elif (key, reading) not in found:
                    found.append((key, reading))
                index += size
                break
        else:
            index += 1
    return found, skipped


def _resolve(by_municipality, source):
    distinct = {r for readings in by_municipality.values() for r in readings}
    if len(distinct) == 1:
        return distinct.pop()
    named = [m for m in by_municipality if _short_name(m) in source and len(by_municipality[m]) == 1]
    return by_municipality[named[0]][0] if len(named) == 1 else None


# A district name followed by one of these is a shrine, temple, surname or river (鶴岡八幡宮,
# 長谷川), so its reading would be a wrong hint. Withholding one costs only today's behaviour.
NOT_A_PLACE_AFTER = ("宮", "神社", "寺", "川")


def display_reading(kana):
    # Plain Hepburn as most live posts write it: Shorin, not Shourin or Shōrin.
    reading = re.sub(r"o[ou]+", "o", romanise(kana))
    return re.sub(r"u+", "u", reading).capitalize()


def hints(source, places):
    text = unicodedata.normalize("NFKC", source).translate(SPELLING)
    found, _ = find_keys(source, places)
    return [(key, display_reading(kana)) for key, kana in found
            if not all(text[m.end():].startswith(NOT_A_PLACE_AFTER) for m in re.finditer(re.escape(key), text))]


def scoped_hints(source, places, edition):
    # A district of a town the item is not about is almost always a surname or another place
    # (大蔵 in Kamakura is not Samukawa's 大蔵). In scope: the edition's own towns, plus any
    # town the source names in full, since 三浦按針 would otherwise count as 三浦. A feed
    # without a fixed area (empty edition) keeps every hint.
    found = hints(source, places)
    if not edition:
        return found
    text = unicodedata.normalize("NFKC", source).translate(SPELLING)
    allowed = set(edition) | {m for m in MUNICIPALITIES.values() if m.split("郡")[-1] in text}
    return [(key, reading) for key, reading in found if set(places[key]) & allowed]


@functools.cache
def load_places():
    return json.loads(GAZETTEER_PATH.read_text(encoding="utf-8"))["places"]
