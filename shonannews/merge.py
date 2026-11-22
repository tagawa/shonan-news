# The story merge trial's guards: when two similar posts are still different stories. The
# after-fetch check lists possible duplicates with them. See the backend spec, "Story merge shadow".
import re
import unicodedata
from datetime import date

MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december")
MONTH_WORD = (r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?"
              r"|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?")
DATE_DM = re.compile(rf"\b(\d{{1,2}})\s+{MONTH_WORD}(?![a-z])", re.I)
DATE_MD = re.compile(rf"\b{MONTH_WORD}\s+(\d{{1,2}})\b(?!:)", re.I)


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
        for month, day_of_month in stated_dates(text):
            day = _nearest_day(month, day_of_month, earlier)
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


def _month(word):
    return next(i for i, name in enumerate(MONTHS, 1) if name.startswith(word.lower().rstrip(".")[:3]))


def stated_dates(text):
    # (month, day) for each English date, in either order: 12 September, September 12, 12 Sept.
    return ({(_month(m.group(2)), int(m.group(1))) for m in DATE_DM.finditer(text)}
            | {(_month(m.group(1)), int(m.group(2))) for m in DATE_MD.finditer(text)})
