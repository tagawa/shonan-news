# Checks the official site links in _data/official_sites.json, since a council page that moves
# leaves every post naming that place with a dead link and nothing else notices. The after-fetch
# check runs it on Saturday's run (scripts/after_fetch.py); see the backend spec, "After-fetch check".
#
# Only a link that is certainly gone is reported as gone (404, 410, or a domain that no longer
# resolves, each seen twice). A refusal, rate limit or timeout is "unsure", since a site that
# blocks scripts or is down for an hour has not moved.
#
# Run from the project root to check now, whatever the date:
#   .venv/bin/python3 -B -m scripts.check_links

import socket
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from shonannews.official_sites import load_sites

USER_AGENT = "shonannews-linkcheck/1.0"
GONE = {404, 410}


def collect_urls(sites: list) -> dict[str, list[str]]:
    """Each URL, with the first English name of every place that links to it."""
    urls: dict[str, list[str]] = {}
    for site in sites:
        if "url" in site:
            urls.setdefault(site["url"], []).append(site["en"][0])
    return {url: sorted(names) for url, names in urls.items()}


def verdict(status: int | None, dns_failed: bool) -> str:
    """'ok', 'dead' or 'unsure'. status is None when no answer came back."""
    if dns_failed or status in GONE:
        return "dead"
    if status is not None and status < 400:
        return "ok"
    return "unsure"


def live_fetch(url: str) -> tuple[int | None, bool]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, False
    except urllib.error.HTTPError as error:
        return error.code, False
    except urllib.error.URLError as error:
        return None, isinstance(error.reason, socket.gaierror)
    except OSError:
        return None, False


def check(urls: dict[str, list[str]], fetch=live_fetch, pause: float = 30) -> dict[str, list[str]]:
    def judge(url):
        return verdict(*fetch(url))

    with ThreadPoolExecutor(max_workers=8) as pool:
        first = dict(zip(urls, pool.map(judge, urls)))
    # A second look before calling anything gone, in case the first was a passing outage.
    suspects = [url for url, result in first.items() if result == "dead"]
    if suspects:
        time.sleep(pause)
    return {"dead": sorted(url for url in suspects if judge(url) == "dead"),
            "unsure": sorted(url for url, result in first.items() if result == "unsure")}


def report(urls: dict[str, list[str]], result: dict[str, list[str]]) -> list[str]:
    lines = [f"  {len(urls)} link(s) checked, {len(result['dead'])} gone, {len(result['unsure'])} unsure"]
    lines += [f"  GONE {url} ({', '.join(urls[url])})" for url in result["dead"]]
    if result["dead"]:
        lines.append("  Fix the list, then run scripts.backfill_sites with no name to mend the posts already written.")
    lines += [f"  unsure {url} ({', '.join(urls[url])})" for url in result["unsure"]]
    return lines


def main() -> int:
    urls = collect_urls(load_sites())
    result = check(urls)
    print("\n".join(report(urls, result)))
    return 1 if result["dead"] else 0


if __name__ == "__main__":
    sys.exit(main())
