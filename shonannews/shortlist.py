# Possible duplicates: recent posts whose English text is close to a new one.
# See the backend spec, "Story merge shadow".
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# Set in the offline threshold round; see the backend spec, "Story merge shadow".
SHORTLIST_THRESHOLD = 0.31
# Same tokens and stop words as the duplicate measurement, so its threshold carries over.
STOP = set("the a an and of in to for on at with by from is are will be was were its it as this that city town held "
           "hold holds event events new first year years japan kanagawa prefecture".split())
TOKEN = re.compile(r"[a-z][a-z'-]+|\d+")


@dataclass
class Post:
    path: Path
    front: dict
    body: str
    source_day: date


def post_text(title, lede, body):
    return f"{title} {lede or ''} {body}"


def _tokens(text):
    return Counter(w for w in TOKEN.findall(text.lower()) if w not in STOP and len(w) > 2)


def _vector(counts, idf):
    vec = {w: c * idf[w] for w, c in counts.items()}
    norm = math.sqrt(sum(x * x for x in vec.values())) or 1.0
    return {w: x / norm for w, x in vec.items()}


def score_candidates(new_text, new_source_day, posts, days=35):
    window = [p for p in posts if abs((p.source_day - new_source_day).days) <= days]
    if not window:
        return []
    docs = [_tokens(new_text)] + [_tokens(post_text(p.front.get("title", ""), p.front.get("lede"), p.body))
                                  for p in window]
    # IDF over the window plus the new post: exactly what the offline threshold round uses.
    df = Counter(w for d in docs for w in d)
    idf = {w: math.log(len(docs) / n) for w, n in df.items()}
    new_vec = _vector(docs[0], idf)
    scored = []
    for counts, post in zip(docs[1:], window):
        vec = _vector(counts, idf)
        scored.append((sum(x * vec.get(w, 0.0) for w, x in new_vec.items()), post))
    return sorted(scored, key=lambda pair: -pair[0])


def shortlist(new_text, new_source_day, posts, threshold=SHORTLIST_THRESHOLD, top=3):
    return [pair for pair in score_candidates(new_text, new_source_day, posts) if pair[0] >= threshold][:top]
