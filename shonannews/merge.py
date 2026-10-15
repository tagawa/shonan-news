# Story merge: deciding whether a new item is an existing post's story, and merging it.
# See the backend spec, "Story merge shadow".
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

from . import llm, validate, weekdays

MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december")
MONTH_WORD = (r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?"
              r"|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?")
DATE_DM = re.compile(rf"\b(\d{{1,2}})\s+{MONTH_WORD}(?![a-z])", re.I)
DATE_MD = re.compile(rf"\b{MONTH_WORD}\s+(\d{{1,2}})\b(?!:)", re.I)
TIME_12H = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)(?![a-z])", re.I)
TIME_24H = re.compile(r"\b(\d{1,2}):(\d{2})\b")
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
# Not after a letter: the "Pad" in "iPad" is not a name.
CAPITALISED = re.compile(r"(?<![A-Za-z])[A-Z][A-Za-z'’-]*[A-Za-z]")
SENTENCE_START = re.compile(r"(?:^|[.!?]['\"’”)]*\s+)['\"‘“(]*([A-Z][A-Za-z'’-]*)")
WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
NOT_NAMES = {m.capitalize() for m in MONTHS} | {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
                                               "Sunday", "Sept", "Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Aug",
                                               "Sep", "Oct", "Nov", "Dec"}


def blocked_by_event_date(first_source_day, first_event_day, second_source_day, second_event_day):
    # A preview and its report are different stories; this catches most of them with no LLM.
    if first_event_day and second_event_day and first_event_day != second_event_day:
        return True
    earlier, later = sorted((first_source_day, second_source_day))
    return any(day and earlier < day <= later for day in (first_event_day, second_event_day))



def _nearest_day(month, day, reference):
    candidates = []
    for year in (reference.year - 1, reference.year, reference.year + 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue  # 29 February in a non-leap year
    return min(candidates, key=lambda c: abs((c - reference).days)) if candidates else None


def blocked_by_stated_dates(first_text, first_source_day, second_text, second_source_day):
    # The event-date guard for posts with no event_date: a preview written in the past tense
    # still names its date, and that date falls between the two publication dates.
    earlier, later = sorted((first_source_day, second_source_day))
    for text in (first_text, second_text):
        for kind, *parts in facts(text, names=False):
            if kind == "date":
                day = _nearest_day(parts[0], parts[1], earlier)
                if day and earlier < day <= later:
                    return True
    return False

# Town News profiles (人物風土記) end their title with the person's age. Measured on the labelled
# pairs: it separates 27 of 28 profile pairs and none of the same-story or preview/report pairs.
PROFILE_TITLE = re.compile(r"\d+歳\s*$")


def is_profile_title(title):
    return bool(PROFILE_TITLE.search(unicodedata.normalize("NFKC", title or "")))


def blocked_by_profile(first_title, second_title):
    # A profile and the news about the same person are different stories; two profiles may be one.
    return is_profile_title(first_title) != is_profile_title(second_title)

def _bare(word):
    # "Kitada's" in one version and "Kitada" in the other are the same name.
    return re.sub(r"['’]s$", "", word)


def _month(word):
    return next(i for i, name in enumerate(MONTHS, 1) if name.startswith(word.lower().rstrip(".")[:3]))


def facts(text, names=True):
    found, spans = set(), []
    for match in DATE_DM.finditer(text):
        found.add(("date", _month(match.group(2)), int(match.group(1))))
        spans.append(match.span())
    for match in DATE_MD.finditer(text):
        found.add(("date", _month(match.group(1)), int(match.group(2))))
        spans.append(match.span())
    for match in TIME_12H.finditer(text):
        hour = int(match.group(1)) % 12 + (12 if match.group(3).lower().startswith("p") else 0)
        found.add(("time", hour, int(match.group(2) or 0)))
        spans.append(match.span())
    for match in TIME_24H.finditer(text):
        # "4:30" inside "4:30 p.m." is the same time, already counted as 16:30.
        if not any(a <= match.start() < b for a, b in spans):
            found.add(("time", int(match.group(1)), int(match.group(2))))
            spans.append(match.span())
    # Numbers inside a date or time are already counted as that date or time.
    rest = "".join(" " if any(a <= i < b for a, b in spans) else ch for i, ch in enumerate(text))
    found |= {("number", n.replace(",", "")) for n in NUMBER.findall(rest)}
    if names:
        initial = {m.start(1) for m in SENTENCE_START.finditer(text)}
        found |= {("name", _bare(m.group())) for m in CAPITALISED.finditer(text)
                  if m.start() not in initial and _bare(m.group()) not in NOT_NAMES}
    return found


def _label(fact):
    if fact[0] == "date":
        return f"date {fact[2]}/{fact[1]}"
    if fact[0] == "time":
        return f"time {fact[1]}:{fact[2]:02d}"
    return f"{fact[0]} {fact[1]}"


def missing_facts(old, new, exempt=frozenset()):
    # Names come from the old lede and body only: a Title Case title would make every word a name.
    old_body = validate.drop_cut_off_narration(old["body"])
    required = (facts(old["title"], names=False) | facts(f"{old['lede']} {old_body}")) - set(exempt)
    new_text = f"{new['title']}. {new['lede']} {new['body']}"
    present = facts(new_text, names=False)
    # A day-only date ("on the 12th") is a number in the old text and part of a date in a rewrite.
    days = {("number", str(f[2])) for f in present if f[0] == "date"}
    hours = {("number", str(n)) for f in present if f[0] == "time" for n in (f[1], f[1] % 12 or 12)}
    present |= days | hours
    # A name may change case or position ("Festival" to "the festival"); a dropped one is there in no case at all.
    # A closing quote, plural possessive or hyphen after a word is not part of the name.
    words = {_bare(word.rstrip("'’-")).lower() for word in WORD.findall(new_text)}
    # "late-Edo" holds the name "Edo".
    words |= {part.lower() for word in words for part in word.split("-")}
    missing = [f for f in required if f[0] != "name" and f not in present]
    # A hyphenated name ("AI-based" out of "generative-AI-based") is there if every part is.
    missing += [f for f in required if f[0] == "name" and not all(part in words for part in f[1].lower().split("-"))]
    return sorted(_label(f) for f in missing)


def _value_numbers(value):
    # Each number as its alternatives: a p.m. hour may be written 2 or 14 in the source.
    groups = []
    for kind, *parts in facts(value, names=False):
        if kind == "time":
            hour, minute = parts
            groups.append({str(hour), str(hour % 12 or 12)})
            if minute:
                groups.append({str(minute)})
        elif kind == "date":
            groups.append({str(parts[1])})
        else:
            groups.append({parts[0]})
    return groups


# A correction needs the source to say so. Counted in the live feeds and post titles on
# 2026-10-16: neither word appeared outside a correction; 誤り, 変更 and 延期 did, so they
# are left out. Without a marker every disagreement is a conflict and the post names both sources.
CORRECTION_MARKERS = ("訂正", "正しくは")


def accepted_corrections(corrections, source_text):
    text = unicodedata.normalize("NFKC", source_text)
    if not any(marker in text for marker in CORRECTION_MARKERS):
        return []
    source = {n.replace(",", "") for n in NUMBER.findall(text)}
    accepted = []
    for item in corrections if isinstance(corrections, list) else []:
        if not (isinstance(item, dict) and isinstance(item.get("old"), str) and isinstance(item.get("new"), str)):
            continue
        new, old = _value_numbers(item["new"]), _value_numbers(item["old"])
        # A value with no digits (a name, a place) cannot be checked against the source.
        if not new or not old:
            continue
        # Both numbers in the source means it states both (doors 9:00, start 10:00): not a correction.
        if all(group & source for group in new) and not any(group & source for group in old):
            accepted.append(item)
    return accepted


def exempt_facts(accepted):
    return set().union(*(facts(item["old"], names=False) for item in accepted))


# English names for the merge prompt and for conflicts named in post text.
SOURCE_NAMES_EN = {
    "湘南・横須賀イベント＆ニュース": "Shonan Yokosuka Events & News",
    "湘南経済新聞": "Shonan Keizai Shimbun",
    "鎌倉経済新聞": "Kamakura Keizai Shimbun",
    "横須賀経済新聞": "Yokosuka Keizai Shimbun",
    "逗子葉山経済新聞": "Zushi Hayama Keizai Shimbun",
    "タウンニュース（横須賀・三浦）": "Town News (Yokosuka and Miura)",
    "タウンニュース（逗子・葉山）": "Town News (Zushi and Hayama)",
    "タウンニュース（藤沢）": "Town News (Fujisawa)",
    "タウンニュース（鎌倉）": "Town News (Kamakura)",
    "タウンニュース（茅ヶ崎・寒川）": "Town News (Chigasaki and Samukawa)",
    "タウンニュース（平塚・大磯・二宮・中井）": "Town News (Hiratsuka, Oiso, Ninomiya and Nakai)",
}


def english_source_name(name):
    return SOURCE_NAMES_EN.get(name or "", "another local source")


def parse_corrections(raw):
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    value = data.get("corrections") if isinstance(data, dict) else None
    return value if isinstance(value, list) else []


@dataclass
class MergeOutcome:
    kind: str
    reason: str = None
    title: str = None
    lede: str = None
    summary: str = None
    event_date: str = None
    corrections: list = field(default_factory=list)
    missing: list = field(default_factory=list)


def merge_into(post, title, description, source_name, source_date, today, readings, create_fn, event_date_fn):
    source = f"{title} {description}"

    def call():
        return llm.call_merge(create_fn, post.front, post.body, title, description, source_name, today, readings)

    # Same one retry as a new post. An LLMCallError propagates, so the caller can leave the item for the next run.
    raw = call()
    result = validate.validate_response(raw, source)
    if not result.ok or result.japanese:
        retry_raw = call()
        retry = validate.validate_response(retry_raw, source)
        if retry.ok or not result.ok:
            raw, result = retry_raw, retry
    if not result.ok:
        return MergeOutcome("link_only", reason="validation")
    lede = weekdays.restore_weekdays(result.lede, source, source_date)
    summary = weekdays.restore_weekdays(result.summary, source, source_date)
    accepted = accepted_corrections(parse_corrections(raw), f"{title}\n{description}")
    old = {"title": post.front.get("title", ""), "lede": post.front.get("lede") or "", "body": post.body}
    missing = missing_facts(old, {"title": result.title, "lede": lede, "body": summary}, exempt_facts(accepted))
    if missing:
        # The text is kept for the shadow review: a missing value may be a parsing artefact.
        return MergeOutcome("link_only", reason="additive_check", title=result.title, lede=lede, summary=summary,
                            missing=missing, corrections=accepted)
    # Keep the post's date; add one only when the new source corroborates it; change it only
    # through an accepted correction, which the additive check has already let through.
    existing = str(post.front["event_date"])[:10] if post.front.get("event_date") else None
    corrected = existing and ("date", int(existing[5:7]), int(existing[8:10])) in exempt_facts(accepted)
    if existing and not corrected:
        event_date = existing
    else:
        event_date = event_date_fn(result, title, description, source_date) or existing
    return MergeOutcome("merged", title=result.title, lede=lede, summary=summary, event_date=event_date,
                        corrections=accepted)
