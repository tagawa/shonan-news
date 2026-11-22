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
    "宮原青子": "Seiko Miyahara",
    # Kamakura's 深沢, published as "Fukazawa" on 2026-11-06; reading from the owner.
    "深沢": "Fukasawa",
    # Filmmaker, reading from the owner, 2026-11-06. More than one word, so it acts
    # only through MISREADINGS.
    "藤本東子": "Haruko Fujimoto",
    # Hiratsuka's prefectural flower garden, read かなガーデン (kana-garden.com). All three live
    # posts naming it misread it, 2026-08-19 to 2026-11-13. More than one word, so it acts only
    # through MISREADINGS.
    "花菜ガーデン": "Kana Garden",
    # Chigasaki ballet company, read のわ (nowa-ballet.com). Published as "Noba", 2026-11-16.
    "乃羽": "Nowa",
    # Nickname of Kandai Park, Tsujido: "Seacross", "C-X" and "Sea Cross" in its three live posts,
    # 2026-10-22 to 2026-11-17. Owner chose the Tsujido development's own spelling (湘南C-X).
    "シークロス公園": "C-X Park",
    # 辻堂今昔物語, published as "Ima Mukashi" on 2026-11-17, fixed by hand.
    "今昔": "Konjaku",
    # KOTOWA鎌倉鶴ヶ丘会館, a Kamakura venue named after Tsurugaoka Hachimangu. Published as
    # "Tsuruoka Kaikan" on 2026-11-20, fixed by hand. 鶴ヶ丘 is a postal district only in
    # Yokosuka, so Kamakura items get no reading hint. Two words, so it acts only through MISREADINGS.
    "鶴ヶ丘会館": "Tsurugaoka Kaikan",
    # Miura temple, read えんぷくじ (owner, 2026-11-20). Published as "Enfukuji" on 2026-11-20, fixed by
    # hand. Both spellings, since the check is a plain substring and NFKC does not fold 圓 to 円.
    "圓福寺": "Enpukuji",
    "円福寺": "Enpukuji",
    # Yokosuka's venue at Honcho 3-27; official English name from its site (yokosuka-sanpla.jp/english),
    # owner, 2026-11-20. The model translates 産業交流 literally as "Exchange". More than one word, so it
    # acts only through MISREADINGS.
    "横須賀市産業交流プラザ": "Yokosuka Industrial Community Plaza",
    # Hiratsuka's 崇善小学校: its own histories read スウゼン in the Kanagawa Prefectural Library and
    # CiNii Books, against two other prefectural libraries' ソウゼン (NDL Search, scripts.ndl).
    # Published as "Shuzan" on 2026-11-20, fixed by hand. Too far from "Suzen" to be a near miss.
    "崇善": "Suzen",
    # Hiratsuka's 吉沢 area: NDL authority 00632025 reads 吉沢小学校 キサワ, and the community centre's
    # newsletter is きさわだより, although Japan Post gives the districts as カミキチサワ. Keyed on the
    # facilities, since 吉沢 alone is also a surname read Yoshizawa. All four live mentions were
    # "Yoshizawa", 2026-08-19 to 2026-11-20; the post office's reading is inferred from the area.
    "吉沢小": "Kisawa",
    "吉沢公民館": "Kisawa",
    "吉沢郵便局": "Kisawa",
    # Surname; every NDL authority record for 沖津 reads オキツ. Published as "Okinatsu" on 2026-11-20.
    "沖津": "Okitsu",
    # The square by Fujisawa Station's north exit; official English name from the city's press page
    # (city.fujisawa.kanagawa.jp/jinkendanjyo/press/2026festival.html), owner, 2026-11-21. More than one
    # word, so it acts only through MISREADINGS.
    "サンパール広場": "Sun Pearl Square",
    # Yokosuka's citizens' seminar series. Keyed on the full name, since いきいき alone is an everyday
    # word. Published as "Iikiki" on 2026-11-22; the 2026-10-17 post translated it "Lively".
    "いきいき市民塾": "Ikiiki",
}

# Wrong readings of a CANONICAL name that are too far from it to be near misses, or more than
# one word, rewritten as whole phrases when the source names the key. Only readings the model
# has actually produced.
MISREADINGS = {
    # Published as "Jojima" and "Kishima Marche" on 2026-10-27, fixed by hand by the owner.
    "城島": ("Jojima", "Kishima"),
    # Published once, 2026-09-02, against "Soleil Hill" in 9 live posts (2026-10-27).
    "ソレイユの丘": ("Soleil no Oka",),
    # Published 2026-11-06; the 2026-10-23 post on the same film had "Haruko".
    "藤本東子": ("Toko Fujimoto",),
    # Published 2026-08-19 and 2026-09-11 / 2026-11-13 respectively.
    "花菜ガーデン": ("Hana-na Garden", "Hana Garden"),
    # Published 2026-11-16; too far from "Nowa" to be a near miss (ratio 0.75).
    "乃羽": ("Noba",),
    "シークロス公園": ("Seacross Park", "Sea Cross Park"),
    "今昔": ("Ima Mukashi",),
    "鶴ヶ丘会館": ("Tsuruoka Kaikan",),
    # Published 2026-11-20 and 2026-09-04 ("Honmachi Industry Exchange Plaza") respectively; the
    # middle one is the owner's. Longest first, since each rewrite runs on the last one's output.
    "横須賀市産業交流プラザ": ("Yokosuka City Industrial Exchange Plaza", "Yokosuka Industrial Exchange Plaza",
                       "Industry Exchange Plaza"),
    "崇善": ("Shuzan",),
    "吉沢小": ("Yoshizawa",),
    "吉沢公民館": ("Yoshizawa",),
    "吉沢郵便局": ("Yoshizawa",),
    "沖津": ("Okinatsu",),
    # "Sun Pearl Plaza" in nine live posts, 2026-09-11 to 2026-11-21; "Sunpearl Plaza" on 2026-09-16.
    "サンパール広場": ("Sun Pearl Plaza", "Sunpearl Plaza"),
    # Shares only its first letter with "Ikiiki", so the near-miss rule cannot reach it.
    "いきいき市民塾": ("Iikiki",),
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
