# Puts back a weekday the source states but the English dropped: the place readings prompt drops
# them more often than the prompt without readings did, and both drop some. See the backend
# spec, "Weekday restoration".

import re
import unicodedata

WEEKDAYS = "月火水木金土日"
ENGLISH = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")
# Every 「M月D日」 or bare 「D日」, so a range's second date (「～9日(金)」) inherits the month
# even when the first date carries no weekday. Digits before 日 keep 「(日)」 from counting.
SOURCE_DATE = re.compile(r"(?:(\d{1,2})\s*月\s*)?(\d{1,2})\s*日(?:\s*\(([月火水木金土日])(・祝)?\))?")


def source_weekdays(source, reference):
    from .pipeline import _derive_event_date  # here, not at the top: pipeline imports this module

    stated, month = {}, None
    for match in SOURCE_DATE.finditer(unicodedata.normalize("NFKC", source)):
        month = int(match.group(1)) if match.group(1) else month
        if month is None or not match.group(3):
            continue
        day = int(match.group(2))
        when = _derive_event_date((month, day), reference)
        weekday = WEEKDAYS.index(match.group(3))
        # A source weekday the calendar contradicts is a typo or a different year; a wrong
        # weekday is worse than a missing one, so it is never copied.
        if when is None or when.weekday() != weekday:
            continue
        stated[(month, day)] = ENGLISH[weekday] + (", public holiday" if match.group(4) else "")
    return stated


def restore_weekdays(text, source, reference):
    for (month, day), weekday in source_weekdays(source, reference).items():
        name = MONTHS[month - 1]
        matches = list(re.finditer(rf"(?<!\d)(?:{day} {name}|{name} {day})(?!\d)", text))
        # Twice in one field is left alone, as is a date already followed by a parenthesis.
        if len(matches) != 1 or re.match(r"\s*\(", text[matches[0].end():]):
            continue
        end = matches[0].end()
        text = f"{text[:end]} ({weekday}){text[end:]}"
    return text
