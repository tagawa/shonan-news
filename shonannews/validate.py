import json
import logging
import re

from shonannews.names import enforce_canonical

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
# A dash just before a closing quote or bracket is dropped, not turned into a comma, or a
# subtitle set off by dashes comes out "'HEAT, Painting, '" (2026-10-16). A straight quote
# counts as closing only when no letter follows it, since a dash before 'Breathing Garden'
# opens one.
CLOSING_DASH = re.compile(r"\s*(?:\u2014|\u2013|--)\s*(?=[\u2019\u201d)\]]|['\"](?!\w))")

# Plain Hepburn, owner decision 2026-10-12; 5 macrons still slipped through on 2026-10-16.
# Only o and u, the long vowels Hepburn marks, and only in a word with no other accented
# letter, so "Maori" and a Lithuanian surname in a live post keep theirs. Folded before
# canonical names, which put back the one exception, Saburosuke's.
LONG_VOWEL = str.maketrans("\u014d\u016b\u014c\u016a", "ouOU")
ACCENTED_WORD = re.compile(r"\w*[^\W\d_A-Za-z]\w*")

# Only the month and day survive; the model's own year is discarded because it was
# wrong in almost every measured miss (2020 for a 2026 event), and source_date gives
# a better one. Strict on purpose: the junk the model actually returned in place of
# null was <unspecified>, [REDACTED], <null>, 202? and YYYY-10-10, and none of it
# matches this. See the backend spec, "Event-date extraction".
EVENT_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

# The only subjects a post may be labelled with. Anything else the model returns
# means no label, never a failure. See the backend spec, "Item labels".
LABELS = ("sport", "safety", "politics")

# Town News heads its police safety-campaign series with 【STOP！交通事故】 and
# 【STOP！詐欺被害】, and the model carries the label into the English headline as
# "STOP! ...", which reads as hyperbole. Title only, and only at the start.
STOP_LABEL = re.compile(r"^\s*STOP[!\uFF01]\s*")

# The fidelity rule tells the model its input is cut off, and it says so in the
# summary: "The description is cut off and provides no further details." 25 of 69
# posts on 2026-09-25. See the backend spec, "Cut-off narration strip". Only a
# "cut off" with a source noun before it counts, so a road cut off by a typhoon stays.
CUT_OFF = re.compile(r"\bcuts? off\b")
SOURCE_NOUN = re.compile(r"\b(?:description|source|text|announcement|article|notice)\b")
# Where narration joins real content: "Activities run from 10:00 to 15:00, and the
# description provided is cut off before listing programs."
NARRATION_JOIN = re.compile(r"(?:;|,? (?:and|but|before|with)) ")
# A capital after the break, so "a.m. to" stays one sentence; a false split on
# "Mt. Fuji" is harmless, since the pieces are rejoined with the same space.
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")

# Source narration: a sentence about the feed text instead of the news ("The title says",
# "is named in the announcement", "ends mid-sentence", 'Poo...'). The cut-off strip above only
# catches the "cut off" shape. Fitted on 20 live sentences and scored on 23 later ones: 19
# caught, none of 729 other sentences flagged; over all 4,886 live sentences, every hit was
# narration. The pipeline retries on it. See the backend spec, "Narration retry".
_SOURCE = r"(?:title|headline|description|article|item|listing|announcement|source|text|notice|report|teaser|excerpt|feed)"
_NARRATING_VERB = (r"(?:says|said|notes|states|mentions|names|identifies|cites|lists|describes|reports|quotes|begins|"
                   r"ends|adds|refers|indicates|gives|does|doesn't|cuts|attributes|introduces|includes|highlights|"
                   r"suggests|focuses|calls)")
NARRATION = (
    # The source as the subject: "The title also notes", "the description names".
    re.compile(rf"\bthe {_SOURCE}(?: also| itself)? {_NARRATING_VERB}\b", re.I),
    # The source as where something appears: "is named in the announcement", "was also mentioned".
    re.compile(rf"\b(?:named|mentioned|listed|cited|described|given|stated|quoted|specified|cut off) in the "
               rf"{_SOURCE}\b|\b(?:is|are|was|were) (?:also )?mentioned\b", re.I),
    # The cut-off itself described.
    re.compile(r"\bmid-sentence\b|\btruncated\b|\bbegins to (?:describe|mention|identify|list|name|explain)\b", re.I),
    # A word the source cut off, kept with its ellipsis: 'Poo...', 'WORLD ONE Te...'.
    re.compile("\\w(?:\\.\\.\\.|…)"),
)
# Verbs whose object is a whole clause, so dropping "The title says (that)" leaves the fact as
# a sentence. "notes" and "reports" also take a noun ("The article reports her participation"),
# which would leave a fragment, so they count only with "that". Nouns after "cites" or
# "mentions" have no verb to stand on, so those sentences are dropped.
NARRATED_CLAUSE = re.compile(
    rf"^(?P<head>(?:.*?(?:;|,? and|,? but) )?)the {_SOURCE}(?: also)? "
    r"(?:(?:says|said)(?: that)?|(?:notes|reports|states|adds|indicates) that) (?P<clause>.+)$", re.I)
# A cut-off name after titled/named/called: "a lecture titled '91...'" keeps "a lecture".
_CUT_NAME = "\\s(?:titled|named|called)\\s['‘\"][^'’\"]*?(?:\\.\\.\\.|…)['’\"]"
CUT_OFF_NAME = re.compile(f",{_CUT_NAME},|{_CUT_NAME}")

# Kana and kanji the model left in its English. Shared with scripts/audit_names.py,
# so the offline audit and the pipeline agree on what counts.
JAPANESE_RUN = re.compile(r"[぀-ヿ一-鿿]+")
KANJI_ONLY = re.compile(r"^[一-鿿]+$")
PUNCTUATION_ONLY = re.compile(r"^[・ー〜]+$")

logger = logging.getLogger("shonannews")


def japanese_runs(text):
    runs = []
    for run in JAPANESE_RUN.findall(text):
        # A lone kana is debris from a half-romanised address, not a name worth reading.
        if run in runs or PUNCTUATION_ONLY.match(run) or (len(run) == 1 and not KANJI_ONLY.match(run)):
            continue
        runs.append(run)
    return runs


def _normalize_dashes(text):
    return PARENTHETICAL_DASH.sub(", ", CLOSING_DASH.sub("", EN_DASH_COMPOUND.sub("-", text)))


def _fold_long_vowels(text):
    def fold(match):
        word = match.group(0)
        folded = word.translate(LONG_VOWEL)
        return folded if folded.isascii() else word

    return ACCENTED_WORD.sub(fold, text)


def _clean(text, source):
    return enforce_canonical(_fold_long_vowels(_normalize_dashes(text)), source).strip()


def _news_before(sentence, joins):
    # What precedes the last of the joins, as a sentence, or "".
    head = sentence[: joins[-1].start()].rstrip() if joins else ""
    if not head:
        return ""
    return head if head.endswith((".", "!", "?")) else head + "."


def drop_cut_off_narration(summary):
    kept = []
    for sentence in SENTENCE_BREAK.split(summary):
        cut = CUT_OFF.search(sentence)
        nouns = list(SOURCE_NOUN.finditer(sentence, 0, cut.start())) if cut else []
        if not nouns:
            kept.append(sentence)
            continue
        # Cut at the join before the source noun, not the one before "cut off": in
        # "104-1; the description lists ... but is cut off" the narration starts at ";".
        head = _news_before(sentence, list(NARRATION_JOIN.finditer(sentence, 0, nouns[-1].start())))
        if head:
            kept.append(head)
    return " ".join(kept)


def _narration_start(sentence):
    starts = [match.start() for match in (pattern.search(sentence) for pattern in NARRATION) if match]
    return min(starts) if starts else None


def narration_sentences(text):
    return [sentence for sentence in SENTENCE_BREAK.split(text) if _narration_start(sentence) is not None]


def without_narration(text):
    kept = []
    for sentence in SENTENCE_BREAK.split(text):
        if _narration_start(sentence) is not None:
            clause = NARRATED_CLAUSE.match(sentence)
            if clause:
                fact = clause["clause"].replace(" and that ", " and ")
                sentence = clause["head"] + (fact if clause["head"] else fact[:1].upper() + fact[1:])
            sentence = CUT_OFF_NAME.sub("", sentence)
            start = _narration_start(sentence)
            if start is not None:
                # A semicolon ends a clause anywhere; "and" or "but" only right before the narration,
                # since in "its chair, vice chair, and secretariat were mentioned" it joins a list.
                joins = [join for join in NARRATION_JOIN.finditer(sentence, 0, start)
                         if join.group().startswith(";") or join.end() == start]
                sentence = _news_before(sentence, joins)
        if sentence:
            kept.append(sentence)
    return " ".join(kept)


def rewrite_narration(result):
    # For narration the retry did not fix. The title is left alone: none has narrated so far.
    # A summary that was all narration is kept, as a smaller defect than a post without one.
    result.summary = without_narration(result.summary) or result.summary
    result.lede = without_narration(result.lede) or _derive_lede(result.summary)
    return result


class ValidationResult:
    def __init__(self, ok, title=None, summary=None, lede=None, error=None, event_month_day=None, label=None,
                 japanese=(), narration=()):
        self.ok = ok
        self.title = title
        self.summary = summary
        self.lede = lede
        self.error = error
        self.event_month_day = event_month_day
        self.label = label
        # Japanese left in the English. Not a failure: the response is usable, and the
        # pipeline decides what to do. See the backend spec, "Japanese left in".
        self.japanese = list(japanese)
        # Sentences about the source text, per field. Also not a failure; the pipeline retries.
        self.narration = list(narration)


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


def _extract_label(raw):
    if isinstance(raw, str) and raw.strip().lower() in LABELS:
        return raw.strip().lower()
    if raw is not None:
        logger.warning("label %r is not one of %s; dropped", raw, LABELS)
    return None


def validate_response(raw_text, source=""):
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

    title = _clean(title, source)
    summary = drop_cut_off_narration(_clean(summary, source))

    # Narration was all there was; the retry may get a summary with content.
    if not summary:
        return ValidationResult(ok=False, error="missing_summary")

    if not _ends_complete_sentence(summary):
        return ValidationResult(ok=False, error="summary_truncated")

    raw_lede = data.get("lede")
    lede = _clean(raw_lede, source) if isinstance(raw_lede, str) else ""

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
        label=_extract_label(data.get("label")),
        japanese=japanese_runs(" ".join((title, lede, summary))),
        # Per field, so a title with no full stop does not run into the lede.
        narration=[sentence for field in (title, lede, summary) for sentence in narration_sentences(field)],
    )
