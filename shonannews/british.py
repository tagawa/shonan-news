# British spelling for the model's English, which comes out American: 625 of 1,923 live posts had an
# American spelling on 2026-11-22. Code, not a prompt rule, since the fix needs nothing the code lacks.
# Derived from posts before October and scored on later ones; see the backend spec, "British spelling".
import re

# Names whose owners spell them the American way (global CLAUDE.md, the originator's spelling).
# Matched case-sensitively, so only the name is kept, not the same word elsewhere in the text.
AMERICAN_NAMES = (
    # kamakura-kpac.jp/en/, checked 2026-11-22. The model's shortening keeps its owner's spelling too.
    "Kamakura Performing Arts Center", "Kamakura Arts Center",
    "World Health Organization",
    "Ministry of Defense", "Department of Defense", "National Defense Academy", "Self-Defense",
    "Pearl Harbor", "Ofuna Flower Center",
)
NAMES = re.compile("|".join(re.escape(name) for name in AMERICAN_NAMES))
ADDRESS = re.compile(r"(?:https?://|www\.)\S+|\S+@\S+")
WORD = re.compile(r"[A-Za-z]+")

# -ize and -yze take s. These end the same way but have no -ise form.
IZE = re.compile(r"(\w+)([iy])z(e|es|ed|ing|ation|ations|ational|er|ers)")
NOT_IZE = {"prize", "prizes", "prized", "seize", "seizes", "seized", "seizing",
           "capsize", "capsized", "capsizes", "capsizing", "maize", "baize"}
# A word ending in size is a compound of it (midsize, undersized), unless its stem is one of the
# -ize verbs that happen to end that way (emphasize).
SIZE = re.compile(r"(\w*)siz(?:e|es|ed|ing)")
SIZE_VERBS = {"empha", "synthe", "hypothe", "fanta", "metasta", "parenthe", "photosynthe"}
# -or takes u. The endings are listed so honorary, humorous, vigorous and laboratory stay, and so
# does Japanese: odori, odorou.
OUR = re.compile(
    r"((?:water|multi|dis|mis|un|tri)?"
    r"(?:colo|hono|labo|harbo|favo|flavo|behavio|neighbo|humo|rumo|vapo|endeavo|savio|armo|parlo|odo|vigo"
    r"|splendo|cando|clamo|ardo|valo|rigo|tumo))r"
    r"(s|ed|ing|ful|fully|less|able|ably|ite|ites|er|ers|hood|hoods|al|ally|ist|ists)?"
)
# -er takes -re. Bare meter is a length only after a number (see LENGTH), since a water meter is a meter.
RE = re.compile(
    r"((?:epi|hypo)?cent|theat|fib|lust|spect|somb|sab|calib|(?:kilo|centi|milli)met|(?:milli)?lit)"
    r"er(s|ed|ing|goer|goers)?"
)
RE_ENDINGS = {None: "re", "s": "res", "ed": "red", "ing": "ring", "goer": "regoer", "goers": "regoers"}
LENGTH = re.compile(r"(?:(?<=\d)|(?<=\d )|(?<=\d-)|(?<=square )|(?<=cubic ))meters?\b", re.I)
WORDS = {
    "canceled": "cancelled", "canceling": "cancelling", "cancelation": "cancellation",
    "traveled": "travelled", "traveling": "travelling", "traveler": "traveller", "travelers": "travellers",
    "signaled": "signalled", "signaling": "signalling", "modeled": "modelled", "modeling": "modelling",
    "remodeled": "remodelled", "remodeling": "remodelling", "totaled": "totalled", "totaling": "totalling",
    "counseling": "counselling", "counselor": "counsellor", "counselors": "counsellors",
    "trialed": "trialled", "trialing": "trialling", "labeled": "labelled", "labeling": "labelling",
    "fueled": "fuelled", "fueling": "fuelling", "leveled": "levelled", "leveling": "levelling",
    "marveled": "marvelled", "marvelous": "marvellous", "jeweled": "jewelled", "dialed": "dialled",
    "dialing": "dialling", "channeled": "channelled", "tunneled": "tunnelled", "equaled": "equalled",
    "rivaled": "rivalled", "quarreled": "quarrelled", "worshiped": "worshipped", "worshiping": "worshipping",
    "enrollment": "enrolment", "enrollments": "enrolments", "fulfillment": "fulfilment",
    "installment": "instalment", "installments": "instalments", "skillful": "skilful",
    "skillfully": "skilfully", "willful": "wilful", "jewelry": "jewellery",
    "program": "programme", "programs": "programmes",
    "defense": "defence", "offense": "offence", "pretense": "pretence",
    "catalog": "catalogue", "catalogs": "catalogues", "aluminum": "aluminium", "pajamas": "pyjamas",
    "maneuver": "manoeuvre", "maneuvers": "manoeuvres", "maneuvered": "manoeuvred", "maneuvering": "manoeuvring",
}
# A computer program is a program in British English too.
COMPUTER = re.compile(r"(?:computer|software) $", re.I)


def _british(word):
    # Lower case in; the British spelling, or None when there is nothing to change.
    if word in WORDS:
        return WORDS[word]
    if word == "gray":
        return "grey"
    match = IZE.fullmatch(word)
    size = SIZE.fullmatch(word)
    if match and word not in NOT_IZE and (not size or size[1] in SIZE_VERBS):
        return f"{match[1]}{match[2]}s{match[3]}"
    match = OUR.fullmatch(word)
    if match:
        return f"{match[1]}ur{match[2] or ''}"
    match = RE.fullmatch(word)
    if match:
        return match[1] + RE_ENDINGS[match[2]]
    return None


def _cased(british, original):
    return british[0].upper() + british[1:] if original[0].isupper() else british


def respell(text):
    kept = [match.span() for pattern in (NAMES, ADDRESS) for match in pattern.finditer(text)]
    lengths = {match.start() for match in LENGTH.finditer(text)}

    def replace(match):
        word = match.group(0)
        start, end = match.span()
        # A word in capitals is the source's own branding; Gray with a capital is likelier a surname.
        if any(a < end and start < b for a, b in kept) or (len(word) > 1 and word.isupper()) or word == "Gray":
            return word
        lower = word.lower()
        if lower in ("meter", "meters"):
            return _cased("metre" + lower[5:], word) if start in lengths else word
        if lower in ("program", "programs") and COMPUTER.search(text, 0, start):
            return word
        british = _british(lower)
        return _cased(british, word) if british else word

    return WORD.sub(replace, text)
