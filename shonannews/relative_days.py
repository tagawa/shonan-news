# Rewrites relative days in the source as the dates they mean, counted from the item's source
# date, before the model sees them: the model counts from the run date and copies あす as
# "tomorrow", which is wrong for a post dated later. See the backend spec, "Relative days".

import re
from datetime import timedelta

WEEKDAYS = "月火水木金土日"
OFFSETS = {"あさって": 2, "明後日": 2, "あした": 1, "あす": 1, "明日": 1, "きょう": 0, "今日": 0,
           "本日": 0, "昨日": -1, "きのう": -1}
# A day of its own (「24日」, not 「3日間」). \d also matches full-width digits.
DAY = r"\s*\d{1,2}\s*日(?!間)"
WORD_BEFORE_DAY = re.compile(rf"(?:{'|'.join(OFFSETS)})(?={DAY})")
# Only the hiragana words: on 2026-10-24 every live 明日 and 今日 without a day was
# figurative (明日の茅ヶ崎, 今日から始める), and きょう was nearly always きょうだい.
# The lookaheads keep あすなろ, あすか and あしたば.
STANDALONE = re.compile(r"あさって|あした(?!ば)|あす(?!な|か(?!ら))")
MONTH_BEFORE_DAY = re.compile(rf"(先月|今月|来月)(?={DAY})")
MONTH_OFFSETS = {"先月": -1, "今月": 0, "来月": 1}


def _date(day):
    return f"{day.month}月{day.day}日({WEEKDAYS[day.weekday()]})"


def _month(reference, offset):
    return (reference.month - 1 + offset) % 12 + 1


def resolve(text, reference):
    text = WORD_BEFORE_DAY.sub("", text)
    text = STANDALONE.sub(lambda m: _date(reference.date() + timedelta(days=OFFSETS[m.group()])), text)
    return MONTH_BEFORE_DAY.sub(lambda m: f"{_month(reference, MONTH_OFFSETS[m.group()])}月", text)
