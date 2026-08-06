import json
import logging
import re

MAX_SUMMARY_LENGTH = 2000
MAX_LEDE_WORDS = 30

logger = logging.getLogger("shonannews")


class ValidationResult:
    def __init__(self, ok, title=None, summary=None, lede=None, error=None):
        self.ok = ok
        self.title = title
        self.summary = summary
        self.lede = lede
        self.error = error


def _derive_lede(summary):
    # First sentence only: up to and including the first ./!/?, or the
    # whole summary if it has none. A false-positive split on an
    # abbreviation (e.g. "Mt. Fuji") is a known, low-frequency edge case,
    # accepted rather than worked around.
    match = re.search(r"[^.!?]*[.!?]", summary)
    return (match.group(0) if match else summary).strip()


def validate_response(raw_text):
    try:
        data = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        return ValidationResult(ok=False, error="invalid_json")

    if not isinstance(data, dict):
        return ValidationResult(ok=False, error="not_an_object")

    title = data.get("title")
    summary = data.get("summary")

    if not isinstance(title, str) or not title.strip():
        return ValidationResult(ok=False, error="missing_title")

    if not isinstance(summary, str) or not summary.strip():
        return ValidationResult(ok=False, error="missing_summary")

    if len(summary) > MAX_SUMMARY_LENGTH:
        return ValidationResult(ok=False, error="summary_too_long")

    title = title.strip()
    summary = summary.strip()

    raw_lede = data.get("lede")
    lede = raw_lede.strip() if isinstance(raw_lede, str) else ""

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

    return ValidationResult(ok=True, title=title, summary=summary, lede=lede)
