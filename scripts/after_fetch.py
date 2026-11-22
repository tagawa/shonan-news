# The checks of a pipeline run that need nothing local: guids without a post, the text sweeps,
# place flags, possible duplicates and the live site. GitHub runs them after every fetch
# (.github/workflows/after-fetch.yml) and scripts.morning imports them, so one copy serves both.
# Public: uploaded to the live repo, unlike the rest of scripts/. See the backend spec,
# "Morning check script".

import collections
import sys
import datetime
import io
import json
import os
import re
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from scripts import check_links
from scripts.gazetteer import REPO, USER_AGENT, _get, fetch_feeds, flag_lines, flag_posts, posts_in_tarball
from shonannews import identity, merge, shortlist
from shonannews.names import CANONICAL
from shonannews.official_sites import load_sites, unlink
from shonannews.places import load_places
from shonannews.pipeline import _is_serial, _skip_tag, feed_description
from shonannews.validate import ACCENTED_WORD, LONG_VOWEL, japanese_runs

API = f"https://api.github.com/repos/{REPO}"
FEEDS_PATH = Path("_data/feeds.json")
# Reported as a count: dozens on a Friday, and never a defect on their own.
COUNT_ONLY = "tag skip: an advertisement"
SITE = "https://shonannews.com"
JST = datetime.timezone(datetime.timedelta(hours=9))
# GitHub Pages builds the site in an Actions run of this name, readable without credentials.
PAGES_RUN = "pages build and deployment"
FIXED_PAGES = ("/", "/feed.xml", "/sitemap.xml", "/llms.txt", "/robots.txt", "/archive/")
# Feed names live posts may carry without a feed: a feed since dropped, and posts written before
# source_name existed. Anything else is a renamed feed. See the backend spec, "Morning check script".
RETIRED_SOURCE_NAMES = {"湘南人", None}
DASH = re.compile("\u2014|\u2013|--")
WEEKDAY = r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)"
DOUBLED_WEEKDAY = re.compile(rf"\b(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day\b\W{{0,3}}\({WEEKDAY}[^)]*\)"
                             rf"|\(({WEEKDAY})[^)]*\)\s*\(\1[^)]*\)")
# One text each sweep must fire on, checked before any post is read: a sweep that cannot fire
# would report every post clean.
PLANTED = {"dash": "a \u2014 b", "japanese": "at 鎌倉芸術館", "macron": "Kamakura K\u014den", "doubled weekday": "Saturday (Sat)"}
# By email: the owner's uploads and hand edits outnumber pipeline commits, so on 2026-10-17
# the 50 latest commits held only one, and filtering by the login returns nothing.
CHECK_RUN_NAME = "Check of fetch run {}"
PLANTED_FINDING = "PLANTED: proving run, not a real finding"
# On since 2026-11-22, when a run from GitHub gave the same verdicts as a local one: Japanese municipal
# sites may block overseas cloud servers, which would have made every Saturday a false alarm.
SCHEDULED_LINK_CHECK = True
# Every heading of the findings report, in order. Only "links unsure" never counts as a finding.
SECTIONS = ("planted", "site build", "unposted", "unavailable feeds", "sweeps", "place flags", "duplicates", "pages",
            "listings", "feed names", "links gone", "links unsure")
NOT_FINDINGS = {"links unsure"}
BOT_COMMITS = f"{API}/commits?author=github-actions%5Bbot%5D%40users.noreply.github.com&per_page=30"


def _utc(stamp):
    return datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def added_guids(before, after):
    # Feed entries are the top-level dicts holding `processed`; the other keys are global lists.
    added = {}
    for feed, value in after.items():
        if not isinstance(value, dict) or "processed" not in value:
            continue
        old = set(before.get(feed, {}).get("processed", []))
        new = [key for key in value["processed"] if key not in old]
        if new:
            added[feed] = new
    return added


def new_posts(before_posts, after_posts):
    return {guid: post["path"] for guid, post in after_posts.items() if guid not in before_posts}


def _listed(before, after, list_key, value):
    if value in before.get(list_key, []):
        return "an earlier post"
    if value in after.get(list_key, []):
        return "a post in this run"
    return None


def classify(entry, feed_url, before, after, unavailable=()):
    # Mirrors the order of the skips in pipeline.run, so the first match is the one that fired.
    if entry is None:
        if feed_url in unavailable:
            return "feed unavailable, cannot tell"
        return "gone from the feed, cannot tell"
    reason = _skip_tag(entry)
    if reason:
        return f"tag skip: {reason}"
    if _is_serial(entry, feed_url):
        return "serial skip"
    where = _listed(before, after, "posted_source_titles", identity.normalize_title(entry.get("title", "")))
    if where:
        return f"title dedup: {where}"
    where = _listed(before, after, "posted_source_descriptions", identity.description_key(feed_description(entry)))
    if where:
        return f"description dedup: {where}"
    return "no skip matched: a validation drop?"


def _tarball(sha):
    data = _get(f"https://codeload.github.com/{REPO}/tar.gz/{sha}")
    archive = tarfile.open(fileobj=io.BytesIO(data))
    member = next(m for m in archive.getmembers() if m.name.endswith("/data/state.json"))
    return posts_in_tarball(data), json.loads(archive.extractfile(member).read())


def _feed_entries():
    feeds, unavailable = fetch_feeds(json.loads(FEEDS_PATH.read_text(encoding="utf-8")))
    entries = {(feed_url, identity.identity_key(entry)): entry
               for feed_url, found in feeds for entry in found}
    return entries, unavailable


def post_url(path):
    name = Path(path).name
    return f"/{name[:4]}/{name[5:7]}/{name[8:10]}/{name[11:-3]}.html"


def site_pages(paths):
    months = sorted({Path(path).name[:7] for path in paths})
    return [*FIXED_PAGES, *(f"/archive/{month}/" for month in months)]


def bad_pages(pages, status):
    return [(page, code) for page, code in ((page, status(page)) for page in pages) if code != 200]


def missing_from_listings(urls, listings):
    return [(url, name) for url in urls for name, text in listings.items() if url not in text]


def _macrons(text):
    # The same rule as validate: o and u only, in a word with no other accent, bar canonical names.
    return [word for word in ACCENTED_WORD.findall(text)
            if word.translate(LONG_VOWEL).isascii() and not any(word in name for name in CANONICAL.values())]


def sweep(text):
    text = unlink(text)
    found = [("dash", match.group()) for match in DASH.finditer(text)]
    found += [("japanese", run) for run in japanese_runs(text)]
    found += [("macron", word) for word in _macrons(text)]
    found += [("doubled weekday", match.group()) for match in DOUBLED_WEEKDAY.finditer(text)]
    return found


def prove_sweeps():
    for category, text in PLANTED.items():
        assert category in [found for found, _ in sweep(text)], f"the {category} sweep did not fire on its planted text"


def _shortlist_post(post):
    front = {key: post[key] for key in ("title", "lede", "source_title", "event_date")}
    return shortlist.Post(Path(post["path"]), front, unlink(post["body"]),
                          datetime.date.fromisoformat(post["source_date"]), "")


def possible_duplicates(new, posts):
    # What the story merge trial's guards let through, with no paid judge: an agent reads these.
    # Earlier posts only, so a pair is not reported from both sides. See the backend spec, "Story merge shadow".
    name = Path(new["path"]).name
    earlier = [_shortlist_post(post) for post in posts.values() if Path(post["path"]).name < name]
    text = shortlist.post_text(new["title"], new["lede"], unlink(new["body"]))
    day = datetime.date.fromisoformat(new["source_date"])
    event = datetime.date.fromisoformat(new["event_date"]) if new["event_date"] else None
    found = []
    for score, post in shortlist.shortlist(text, day, earlier):
        old_event = post.front["event_date"]
        old_event = datetime.date.fromisoformat(old_event[:10]) if old_event else None
        old_text = shortlist.post_text(post.front["title"], post.front["lede"], post.body)
        if not (merge.blocked_by_event_date(post.source_day, old_event, day, event)
                or merge.blocked_by_stated_dates(old_text, post.source_day, text, day)
                or merge.blocked_by_profile(post.front["source_title"], new["source_title"] or "")):
            found.append((round(score, 3), post.path.name))
    return found


def unmatched_source_names(posts, feed_names):
    # The site gives a post its area from its feed's name, so a renamed feed silently strips the
    # area from every old post. See the frontend spec, "Areas".
    return collections.Counter(post["source_name"] for post in posts.values()
                               if post["source_name"] not in feed_names | RETIRED_SOURCE_NAMES)


def api_request(url: str, token: str | None) -> urllib.request.Request:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def api_get(url: str) -> bytes:
    # On a GitHub runner the token lifts the shared 60-an-hour limit; locally there is none, as before.
    with urllib.request.urlopen(api_request(url, os.environ.get("GITHUB_TOKEN")), timeout=120) as response:
        return response.read()


def fetch_commit(bot_commits: list[dict], head_sha: str) -> dict | None:
    # The fetch pushes with a plain `git push`, so its commit sits directly on the commit it started from.
    return next((commit for commit in bot_commits if commit["parents"][0]["sha"] == head_sha), None)


def build_state(commit_sha: str, pages_runs: list[dict], contains: Callable[[str, str], bool]) -> tuple[str, str | None]:
    # An upload during the build can make Pages skip the bot commit and build only the newer one,
    # which still shows the bot's posts, so a successful build of any commit containing it counts.
    for run in pages_runs:
        if run["status"] == "completed" and run["conclusion"] == "success":
            if run["head_sha"] == commit_sha or contains(commit_sha, run["head_sha"]):
                return "built", run["head_sha"]
    own = [run for run in pages_runs if run["head_sha"] == commit_sha]
    running = any(run["status"] != "completed" for run in pages_runs)
    if any(run["conclusion"] == "failure" for run in own) and not running:
        return "failed", None
    return "waiting", None


def contains_via_api(base: str, head: str) -> bool:
    return json.loads(api_get(f"{API}/compare/{base}...{head}"))["status"] in ("ahead", "identical")


def pages_runs() -> list[dict]:
    runs = json.loads(api_get(f"{API}/actions/runs?per_page=30"))["workflow_runs"]
    return [run for run in runs if run["name"] == PAGES_RUN]


def wait_for_build(commit_sha: str, get_runs: Callable[[], list[dict]], contains: Callable[[str, str], bool],
                   sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                   timeout: float = 1800, poll: float = 30) -> tuple[str, str | None]:
    # Running out of time is a result of its own, never a pass: a quiet night must mean the site was checked.
    start = clock()
    while True:
        state = build_state(commit_sha, get_runs(), contains)
        if state[0] != "waiting":
            return state
        if clock() - start >= timeout:
            return "timed out", None
        sleep(poll)


def _status(page: str, version: str) -> int | str:
    # A query string Fastly has not seen bypasses its cache, which can serve a page minutes stale.
    request = urllib.request.Request(f"{SITE}{page}?v={version}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except OSError as error:
        return str(error)


def unknown_flags(argv: list[str], known: set[str]) -> str | None:
    # A mistyped flag would otherwise be ignored and the script run without it, silently.
    unknown = [arg for arg in argv if arg.startswith("-") and arg not in known]
    return f"Unknown option(s): {', '.join(unknown)}. Known: {', '.join(sorted(known))}" if unknown else None


def load_feed_names() -> dict[str, str]:
    return {feed["url"]: feed["name"] for feed in json.loads(FEEDS_PATH.read_text(encoding="utf-8"))}


def run_items(commit: dict, entries: dict, unavailable: set, feed_names: dict, current_posts: dict):
    """One pipeline commit: (unposted, items, guids added). unposted holds (reason, feed, key, title);
    each item pairs a new post's pipeline text with its current text (None once deleted) and source."""
    before_posts, before = _tarball(commit["parents"][0]["sha"])
    after_posts, after = _tarball(commit["sha"])
    posts = new_posts(before_posts, after_posts)
    added = added_guids(before, after)
    unposted, items = [], []
    for feed, keys in added.items():
        for key in keys:
            entry = entries.get((feed, key))
            if key not in posts:
                unposted.append((classify(entry, feed, before, after, unavailable), feed, key,
                                 entry.get("title", "") if entry else ""))
                continue
            items.append({"guid": key, "feed_name": feed_names.get(feed, feed),
                          "source_title": entry.get("title", "") if entry else None,
                          "description": feed_description(entry) if entry else None,
                          "pipeline": after_posts[key], "current": current_posts.get(key)})
    return unposted, items, sum(len(keys) for keys in added.values())


def post_checks(items: list[dict], current_posts: dict) -> list[dict]:
    """Flags, duplicates and sweeps for each item, sorted by file name."""
    # A post the owner has since deleted has no live page or listing to check, and needs no flags.
    readable = [{**item, "source_title": item["source_title"] or "", "description": item["description"] or ""}
                for item in items if item["current"]]
    flags = {result[0]: result for result in flag_posts(readable, "0000", load_places(), load_sites())} if readable else {}
    checked = []
    for item in sorted(items, key=lambda item: Path((item["current"] or item["pipeline"])["path"]).name):
        post = item["current"] or item["pipeline"]
        name = Path(post["path"]).name
        lines = flag_lines(flags[name]) if name in flags else []
        checked.append({"item": item, "name": name, "flag_lines": lines,
                        "flagged": len(lines) > 1 or bool(lines and lines[0].startswith("FLAG")),
                        "duplicates": possible_duplicates(post, current_posts) if item["current"] else [],
                        "sweeps": sweep(" ".join([post["title"], post["lede"], post["body"]]))})
    return checked


def site_problems(paths: list[str], version: str) -> tuple[list, list, int]:
    """(pages not serving, (url, listing) gaps, pages checked) for these posts, bypassing the cache."""
    urls = [post_url(path) for path in paths]
    pages = site_pages(paths)
    bad = bad_pages([*pages, *urls], lambda page: _status(page, version))
    listings = {page: _get(f"{SITE}{page}?v={version}").decode("utf-8") for page in pages
                if page == "/sitemap.xml" or page.startswith("/archive/2")}
    missing = [(url, page) for url, page in missing_from_listings(urls, listings)
               if page == "/sitemap.xml" or page[9:16] == url[1:8].replace("/", "-")]
    return bad, missing, len(pages) + len(urls)


def needs_look(reason: str) -> bool:
    # Every other reason is a skip the pipeline meant to make.
    return reason.startswith(("no skip matched", "gone from the feed", "feed unavailable"))


def gone_links(result: dict[str, list[str]]) -> list[str]:
    return result["dead"]


def findings_report(sections: dict[str, list[str]], header: str) -> tuple[str, bool]:
    # The header says what was checked: a report of nothing but "none" must not look like one that checked nothing.
    lines = [header]
    for key in SECTIONS:
        lines.append(f"## {key}")
        lines += [f"  {line}" for line in sections[key]] or ["  none"]
    found = any(sections[key] for key in SECTIONS if key not in NOT_FINDINGS)
    return "\n".join(lines) + "\n", found


def run_findings(fetch_run: dict, plant: bool, links: bool) -> tuple[str, bool]:
    prove_sweeps()
    sections = {key: [] for key in SECTIONS}
    if plant:
        sections["planted"].append(PLANTED_FINDING)
    feed_names = load_feed_names()
    commit = fetch_commit(json.loads(api_get(BOT_COMMITS)), fetch_run["head_sha"])
    posts = 0
    if commit is None:
        # The run committed nothing: no posts to read, so only the site's fixed pages and feed names.
        current_posts = _tarball(fetch_run["head_sha"])[0]
        version = fetch_run["head_sha"]
        sections["pages"] = [f"{code} {page}" for page, code in bad_pages(FIXED_PAGES, lambda page: _status(page, version))]
        header = f"No commit from this run: {len(FIXED_PAGES)} page(s) checked"
    else:
        state, built = wait_for_build(commit["sha"], pages_runs, contains_via_api)
        if state != "built":
            sections["site build"].append(f"the site build for {commit['sha'][:7]}: {state}")
        current_posts = _tarball(built if built else commit["sha"])[0]
        entries, unavailable = _feed_entries()
        sections["unavailable feeds"] = sorted(feed_names.get(feed, feed) for feed in unavailable)
        unposted, items, guids = run_items(commit, entries, unavailable, feed_names, current_posts)
        checked = 0
        posts = len(items)
        sections["unposted"] = [f"{reason} | {feed_names.get(feed, feed)} | {key} | {title}"
                                for reason, feed, key, title in sorted(unposted) if needs_look(reason)]
        for check in post_checks(items, current_posts):
            if check["flagged"]:
                sections["place flags"] += check["flag_lines"]
            sections["duplicates"] += [f"{check['name']} / {other} (score {score})" for score, other in check["duplicates"]]
            sections["sweeps"] += [f"{check['name']}: {category}: {text}" for category, text in check["sweeps"]]
        live = [item["current"]["path"] for item in items if item["current"]]
        if built and live:
            bad, missing, checked = site_problems(live, built)
            sections["pages"] = [f"{code} {page}" for page, code in bad]
            sections["listings"] = [f"{url} is not in {page}" for url, page in missing]
        header = (f"Commit {commit['sha'][:7]} (built {built[:7] if built else 'never'}): {posts} new post(s), "
                  f"{guids} guid(s), {checked} page(s) checked")
    sections["feed names"] = [f"{name}: {count}" for name, count in
                              unmatched_source_names(current_posts, set(feed_names.values())).most_common()]
    if links or (SCHEDULED_LINK_CHECK and weekly_read_due(fetch_run, posts)):
        urls = check_links.collect_urls(load_sites())
        result = check_links.check(urls)
        sections["links gone"] = [f"{url} ({', '.join(urls[url])})" for url in gone_links(result)]
        sections["links unsure"] = [f"{url} ({', '.join(urls[url])})" for url in result["unsure"]]
    return findings_report(sections, header)


def weekly_read_due(fetch_run: dict, posts: int) -> bool:
    # Saturday's run carries the Friday Town News batch. The cron fires on Friday in UTC, so the day
    # is taken in JST. A manual run never counts, and a run with nothing to read asks for nothing.
    created = _utc(fetch_run["created_at"]).astimezone(JST)
    return fetch_run["event"] == "schedule" and created.weekday() == 5 and posts >= 1


def run_commit_and_posts(fetch_run: dict) -> tuple[dict | None, int]:
    commit = fetch_commit(json.loads(api_get(BOT_COMMITS)), fetch_run["head_sha"])
    if commit is None:
        return None, 0
    before_posts = _tarball(commit["parents"][0]["sha"])[0]
    return commit, len(new_posts(before_posts, _tarball(commit["sha"])[0]))


def _option(argv: list[str], name: str) -> str:
    return argv[argv.index(name) + 1]


def main(argv: list[str]) -> int:
    known = {"findings": {"--fetch-run", "--plant", "--links"}, "weekly-read": {"--fetch-run", "--plant"},
             "proof": {"--this-run"}}
    if not argv or argv[0] not in known:
        print(f"Usage: python -m scripts.after_fetch {'|'.join(known)} [options]", file=sys.stderr)
        return 2
    command, options = argv[0], argv[1:]
    if error := unknown_flags(options, known[command]):
        print(error, file=sys.stderr)
        return 2
    if command == "proof":
        return run_proof(int(_option(options, "--this-run")))
    fetch_run = json.loads(api_get(f"{API}/actions/runs/{_option(options, '--fetch-run')}"))
    if command == "weekly-read":
        commit, posts = run_commit_and_posts(fetch_run)
        if "--plant" in options or weekly_read_due(fetch_run, posts):
            sha = commit["sha"][:7] if commit else "none"
            print(f"::error title=Weekly read due::Read the {posts} post(s) of commit {sha} against their sources"
                  " (morning-check skill)")
            return 1
        print("No weekly read due for this run.")
        return 0
    text, found = run_findings(fetch_run, "--plant" in options, "--links" in options)
    print(text)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(text)
    if found:
        print("::error title=Findings::The after-fetch check found something to look at; see the job summary.")
    return 1 if found else 0


def previous_check_problem(this_run_id: int, fetch_runs: list[dict], check_runs: list[dict],
                           check_workflow_created_at: str) -> str | None:
    # Tied to the previous fetch run's ID, not to "last night": runs start hours late and some are manual.
    this = next(run for run in fetch_runs if run["id"] == this_run_id)
    earlier = [run for run in fetch_runs if run["run_number"] < this["run_number"]]
    if not earlier:
        return None
    previous = max(earlier, key=lambda run: run["run_number"])
    if _utc(previous["created_at"]) < _utc(check_workflow_created_at):
        return None  # the first fetch after deploy: no check existed for the one before
    name = CHECK_RUN_NAME.format(previous["id"])
    # Only a check started by the fetch finishing counts; a manual dispatch of the same name could
    # otherwise stand in for one that never ran. A running one is bounded by its own time limit.
    if any(run["event"] == "workflow_run" and run["display_title"] == name for run in check_runs):
        return None
    return f"the check of fetch run {previous['id']} never ran"


def check_runs_url(since: str) -> str:
    return f"{API}/actions/workflows/after-fetch.yml/runs?per_page=100&created=>={since}"


def run_proof(this_run_id: int) -> int:
    fetch_runs = json.loads(api_get(f"{API}/actions/workflows/fetch.yml/runs?per_page=10"))["workflow_runs"]
    # A 404 here means the check workflow is gone: raised, never read as "nothing to prove".
    created = json.loads(api_get(f"{API}/actions/workflows/after-fetch.yml"))["created_at"]
    this = next(run for run in fetch_runs if run["id"] == this_run_id)
    earlier = [run for run in fetch_runs if run["run_number"] < this["run_number"]]
    since = min(run["created_at"] for run in earlier) if earlier else this["created_at"]
    check_runs = json.loads(api_get(check_runs_url(since)))["workflow_runs"]
    problem = previous_check_problem(this_run_id, fetch_runs, check_runs, created)
    if problem:
        print(f"::error title=After-fetch check missing::{problem}")
        return 1
    print("The previous fetch run's check ran.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
