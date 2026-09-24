import json
import logging
import re

MAX_SUMMARY_LENGTH = 2000
MAX_LEDE_WORDS = 30
# A sentence end, optionally inside closing quotes or a bracket. Missing means the
# model closed the JSON string early, where it meant to open a double-quoted name.
TERMINAL_PUNCTUATION = re.compile(r"[.!?]['\"’”)]*$")
# Two or more trailing dots mean the model copied the feed's own truncation rather
# than finishing the sentence. Town News cuts every description at 87 characters, so
# the shape is in front of the model every run. "The doors open at 5:00 p.m." ends in
# one dot and is fine; "to 5:00 p.m...." is not. A lone "…" needs no rule here: it is
# not terminal punctuation, so the check above already rejects it.
TRAILING_ELLIPSIS = re.compile(r"(?:\.{2,}|…)['\"’”)]*$")

# CLAUDE.md bans dashes in generated content and the model reaches for them anyway:
# 5 of 61 titles on 2026-09-18, and 2 of 8 posts on 2026-09-19. A prompt rule was
# measured instead and could not be scored at all, because none of the 30 sampled
# items provoked a dash; see the backend spec, "Dash normalisation". Doing it here
# is deterministic and costs no posts, where rejecting the response would drop one.
# Written as escapes so this file stays clean under a grep for literal dashes.
# An en dash between two alphanumerics is a compound or a range, so it becomes a
# hyphen ("public-private", "10-17"). Every other dash is parenthetical punctuation
# and becomes a comma, absorbing the space around it so none is left doubled.
EN_DASH_COMPOUND = re.compile(r"(?<=[0-9A-Za-z])\u2013(?=[0-9A-Za-z])")
PARENTHETICAL_DASH = re.compile(r"\s*(?:\u2014|\u2013|--)\s*")

# Only the month and day survive; the model's own year is discarded because it was
# wrong in almost every measured miss (2020 for a 2026 event), and source_date gives
# a better one. Strict on purpose: the junk the model actually returned in place of
# null was <unspecified>, [REDACTED], <null>, 202? and YYYY-10-10, and none of it
# matches this. See the backend spec, "Event-date extraction".
EVENT_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

# Town News heads its police safety-campaign series with 【STOP！交通事故】 and
# 【STOP！詐欺被害】, and the model carries the label into the English headline as
# "STOP! ...", which reads as hyperbole. Title only, and only at the start.
STOP_LABEL = re.compile(r"^\s*STOP[!\uFF01]\s*")

logger = logging.getLogger("shonannews")


def _normalize_dashes(text):
    return PARENTHETICAL_DASH.sub(", ", EN_DASH_COMPOUND.sub("-", text))


class ValidationResult:
    def __init__(self, ok, title=None, summary=None, lede=None, error=None, event_month_day=None):
        self.ok = ok
        self.title = title
        self.summary = summary
        self.lede = lede
        self.error = error
        self.event_month_day = event_month_day


def _ends_complete_sentence(text):
    return bool(TERMINAL_PUNCTUATION.search(text)) and not TRAILING_ELLIPSIS.search(text)


def _derive_lede(summary):
    # First sentence only: up to and including the first ./!/?, or the
    # whole summary if it has none. A false-positive split on an
    # abbreviation (e.g. "Mt. Fuji") is a known, low-frequency edge case,
    # accepted rather than worked around.
    match = re.search(r"[^.!?]*[.!?]", summary)
    return (match.group(0) if match else summary).strip()


def _extract_event_month_day(raw):
    if not isinstance(raw, str):
        return None
    match = EVENT_DATE.match(raw)
    if not match:
        return None
    month, day = int(match.group(2)), int(match.group(3))
    # Bounds only. 02-30 is impossible in every year but needs one to prove it, so
    # year derivation rejects it instead, where a real date can be constructed.
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return month, day


def validate_response(raw_text):
    try:
        data = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        return ValidationResult(ok=False, error="invalid_json")

    if not isinstance(data, dict):
        return ValidationResult(ok=False, error="not_an_object")

    title = data.get("title")
    summary = data.get("summary")

    # Stripped before the emptiness check, so a title that was only the label fails.
    if isinstance(title, str):
        title = STOP_LABEL.sub("", title)

    if not isinstance(title, str) or not title.strip():
        return ValidationResult(ok=False, error="missing_title")

    if not isinstance(summary, str) or not summary.strip():
        return ValidationResult(ok=False, error="missing_summary")

    if len(summary) > MAX_SUMMARY_LENGTH:
        return ValidationResult(ok=False, error="summary_too_long")

    title = _normalize_dashes(title).strip()
    summary = _normalize_dashes(summary).strip()

    if not _ends_complete_sentence(summary):
        return ValidationResult(ok=False, error="summary_truncated")

    raw_lede = data.get("lede")
    lede = _normalize_dashes(raw_lede).strip() if isinstance(raw_lede, str) else ""

    # _derive_lede's output is never itself word-capped: a long-but-complete
    # first sentence reads better than one truncated mid-word, and the
    # 30-word rule exists to keep the model's own ledes tight, not to
    # constrain a fallback that's already the best available substitute.
    if not lede:
        logger.warning("lede missing or empty; deriving from summary's first sentence")
        lede = _derive_lede(summary)
    elif len(lede.split()) > MAX_LEDE_WORDS:
        logger.warning("lede exceeds %d words; deriving from summary's first sentence", MAX_LEDE_WORDS)
        lede = _derive_lede(summary)
    elif lede == title:
        logger.warning("lede identical to title; deriving from summary's first sentence")
        lede = _derive_lede(summary)
    elif not _ends_complete_sentence(lede):
        logger.warning("lede cut off mid-sentence; deriving from summary's first sentence")
        lede = _derive_lede(summary)

    return ValidationResult(
        ok=True,
        title=title,
        summary=summary,
        lede=lede,
        event_month_day=_extract_event_month_day(data.get("event_date")),
    )
