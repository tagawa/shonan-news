# Place-name readings from Japan Post's postcode data, and an offline check of whether a
# post's English carries the official reading of each place its source names.
# See the backend spec, "Place reading audit". The runtime half, which the pipeline uses to
# give the model readings, is shonannews/places.py.
#
# Run from the project root:
#   python3 -m scripts.gazetteer build      writes data/gazetteer.json
#   python3 -m scripts.gazetteer snapshot   writes docs/gazetteer-snapshot.json (feed bodies; never upload)
#   python3 -m scripts.gazetteer flag [YYYY-MM-DD]
#       checks the snapshot's posts dated that day or later (default: the newest day) against their sources

import csv
import datetime
import io
import json
import re
import sys
import tarfile
import unicodedata
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import yaml

from shonannews.official_sites import load_sites, misses
from shonannews.places import (
    GAZETTEER_PATH,
    MIN_KEY,
    MUNICIPALITIES,
    SPELLING,
    TOWN_SUFFIXES,
    acceptable_readings,
    english_runs,
    find_keys,
    fold,
    load_places,
    named_as_place,
    romanise,
)

KEN_ALL_URL = "https://www.post.japanpost.jp/service/search/zipcode/download/utf/zip/utf_ken_all.zip"
REPO = "tagawa/shonan-news"
USER_AGENT = "shonannews-audit/1.0"
SNAPSHOT_PATH = Path("docs/gazetteer-snapshot.json")
BOT = "github-actions[bot]"

PLACEHOLDERS = ("以下に掲載がない場合", "の次に番地がくる場合", "一円")
PARENTHETICAL = re.compile(r"（.*?）|\(.*?\)|（.*$")
DIRECTION_PREFIXES = {"東": "ヒガシ", "西": "ニシ", "南": "ミナミ", "北": "キタ"}


def parse_records(rows, municipalities=frozenset(MUNICIPALITIES.values())):
    records = []
    for r in rows:
        if r[6] != "神奈川県" or r[7] not in municipalities or any(p in r[8] for p in PLACEHOLDERS):
            continue
        kanji = unicodedata.normalize("NFKC", PARENTHETICAL.sub("", r[8])).translate(SPELLING)
        kana = unicodedata.normalize("NFKC", PARENTHETICAL.sub("", r[5]))
        if not kanji:
            continue
        records.append((r[7], kanji, kana))
    return records


def _stems(kanji, kana):
    forms = [(kanji, kana)]
    for suffix, readings in TOWN_SUFFIXES.items():
        for reading in readings:
            if kanji.endswith(suffix) and kana.endswith(reading):
                forms.append((kanji[:-1], kana[:-len(reading)]))
    for form_kanji, form_kana in list(forms):
        prefix_kana = DIRECTION_PREFIXES.get(form_kanji[:1])
        if prefix_kana and form_kana.startswith(prefix_kana):
            forms.append((form_kanji[1:], form_kana[len(prefix_kana):]))
    return [(k, r) for k, r in forms if len(k) >= MIN_KEY and r]


def build_places(records):
    places = {}
    for municipality, kanji, kana in records:
        for key, reading in _stems(kanji, kana):
            readings = places.setdefault(key, {}).setdefault(municipality, [])
            if reading not in readings:
                readings.append(reading)
    return places


def flag(source, english, places):
    runs = english_runs(english)
    found, _ = find_keys(source, places)
    return [(key, kana) for key, kana in found
            if named_as_place(key, source) and not acceptable_readings(key, kana) & runs]


def flag_posts(items, since, places, sites):
    posts = [(Path(item["current"]["path"]).name, item) for item in items]
    since = since or max(name[:10] for name, _ in posts)
    results = []
    for name, item in sorted(posts, key=lambda pair: pair[0]):
        if name[:10] < since:
            continue
        source = f"{item['source_title']} {item['description']}"
        current = item["current"]
        english = " ".join([current["title"], current["lede"], current["body"]])
        missed = misses(english, source, sites)
        # Spelled in the title or lede only: links go in the body, so the post has none. An entry
        # without a url is never linked, so it cannot miss one.
        linkable = [site for site in sites if "url" in site]
        unlinked = [ja for ja in misses(current["body"], source, linkable) if ja not in missed]
        results.append((name, find_keys(source, places)[0], flag(source, english, places), missed, unlinked))
    return results


def first_versions(commits_newest_first, guids, load):
    # A post's first appearance is in the bot commit that wrote it, so walking back until a
    # commit holds none of the guids finds every pipeline-written text without the whole history.
    versions = {}
    for sha in commits_newest_first:
        posts = load(sha)
        present = guids & posts.keys()
        if not present:
            break
        for guid in present:
            versions[guid] = (sha, posts[guid])
    missing = guids - versions.keys()
    if missing:
        raise LookupError(f"never found in a bot commit: {sorted(missing)}")
    return versions


def _get(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(request, timeout=120).read()


def fetch_feeds(feeds, get=_get):
    # One feed down (all four Keizai feeds 503'd on 2026-10-22) must not stop the check of the
    # rest; it is returned by name so the report says which feeds it could not see.
    import feedparser

    entries, unavailable = [], {}
    for feed in feeds:
        try:
            data = get(feed["url"])
        except urllib.error.HTTPError as exc:
            unavailable[feed["url"]] = f"HTTP {exc.code}"
            continue
        except OSError as exc:  # URLError, timeouts, dropped connections
            unavailable[feed["url"]] = str(exc) or type(exc).__name__
            continue
        entries.append((feed["url"], feedparser.parse(data).entries))
    return entries, unavailable


def print_unavailable(unavailable):
    for url, reason in unavailable.items():
        print(f"UNAVAILABLE {url}: {reason}; its items are missing from this report")


def build():
    archive = zipfile.ZipFile(io.BytesIO(_get(KEN_ALL_URL)))
    rows = csv.reader(io.TextIOWrapper(archive.open(archive.namelist()[0]), encoding="utf-8"))
    places = build_places(parse_records(rows))
    GAZETTEER_PATH.write_text(json.dumps({
        "source": KEN_ALL_URL,
        "downloaded": datetime.date.today().isoformat(),
        "places": dict(sorted(places.items())),
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(places)} keys written to {GAZETTEER_PATH}")


# Read by the morning check beside the text; absent ones stay None, so no key needs guarding.
POST_FIELDS = ("source_name", "source_title", "source_url", "event_date", "on_until", "label", "town", "place_photo", "thumb_url", "image_url")


def posts_in_tarball(data):
    posts = {}
    archive = tarfile.open(fileobj=io.BytesIO(data))
    for member in archive.getmembers():
        if "/_posts/" not in member.name or not member.name.endswith(".md"):
            continue
        raw = archive.extractfile(member).read().decode("utf-8")
        _, front_matter, body = raw.split("---", 2)
        fields = yaml.load(front_matter, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader)) or {}
        posts[str(fields.get("guid", ""))] = {
            "path": member.name.split("/", 1)[1],
            "title": str(fields.get("title", "")),
            "lede": str(fields.get("lede", "")),
            "body": body.strip(),
            "source_date": str(fields.get("source_date") or fields.get("date"))[:10],
            **{key: str(fields[key]) if fields.get(key) else None for key in POST_FIELDS},
            "raw": raw,
        }
    return posts


def _bot_commits():
    shas = []
    for page in range(1, 4):
        commits = json.loads(_get(f"https://api.github.com/repos/{REPO}/commits?per_page=100&page={page}"))
        shas += [c["sha"] for c in commits if (c.get("author") or {}).get("login") == BOT
                 or c["commit"]["author"]["name"] == BOT]
        if len(commits) < 100:
            break
    return shas


def snapshot():
    from shonannews import identity
    from shonannews.pipeline import feed_description

    items = {}
    feeds, unavailable = fetch_feeds(json.loads(Path("_data/feeds.json").read_text(encoding="utf-8")))
    print_unavailable(unavailable)
    for feed_url, entries in feeds:
        for entry in entries:
            items[identity.identity_key(entry)] = {
                "feed": feed_url,
                "source_title": entry.get("title", ""),
                "description": feed_description(entry),
            }
    current = posts_in_tarball(_get(f"https://codeload.github.com/{REPO}/tar.gz/refs/heads/main"))
    published = items.keys() & current.keys()
    versions = first_versions(_bot_commits(), set(published),
                              lambda sha: posts_in_tarball(_get(f"https://codeload.github.com/{REPO}/tar.gz/{sha}")))
    out = [{**items[g], "guid": g, "source_date": current[g]["source_date"], "commit": versions[g][0],
            "pipeline": versions[g][1], "current": current[g]} for g in sorted(published)]
    SNAPSHOT_PATH.write_text(json.dumps({"taken": datetime.datetime.now().isoformat(timespec="minutes"),
                                         "feed_items": len(items), "unavailable": unavailable, "items": out},
                                        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(items)} feed items, {len(out)} published, written to {SNAPSHOT_PATH}")


def flag_lines(result):
    name, found, flagged, missed, unlinked = result
    places = ", ".join(f"{key} {kana}" for key, kana in found) or "no places"
    lines = [f"{'FLAG' if flagged else 'ok  '} {name}: {places}"]
    lines += [f"     {key} should read {romanise(kana)}" for key, kana in flagged]
    # The source names a listed site but the post has none of its spellings, so no link was made.
    lines += [f"     LINK MISS {ja}: no English spelling in the post; add one to _data/official_sites.json"
              for ja in missed]
    lines += [f"     NO LINK {ja}: named in the title or lede only; add the linked name to the body by hand"
              for ja in unlinked]
    return lines


def flag_snapshot():
    items = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))["items"]
    results = flag_posts(items, sys.argv[2] if len(sys.argv) > 2 else None, load_places(), load_sites())
    for result in results:
        print("\n".join(flag_lines(result)))
    print(f"{len(results)} post(s), {sum(len(f) for _, f, *_ in results)} place(s) checked, "
          f"{sum(len(f) for _, _, f, _, _ in results)} flagged, {sum(len(m) for *_, m, _ in results)} link miss(es), "
          f"{sum(len(u) for *_, u in results)} unlinked")


if __name__ == "__main__":
    {"build": build, "snapshot": snapshot, "flag": flag_snapshot}[sys.argv[1]]()
