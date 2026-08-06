USER_AGENT = "ShonanNewsBot/1.0 (+https://github.com/kyokodaniel/shonannews)"


class FetchError(Exception):
    pass


def fetch_feed(parse_fn, url, etag=None, modified=None, user_agent=USER_AGENT):
    parsed = parse_fn(url, etag=etag, modified=modified, agent=user_agent)

    status = parsed.get("status")
    if status == 304:
        return None

    if parsed.get("bozo") and not parsed.get("entries"):
        raise FetchError(f"Feed unreachable or unparseable: {parsed.get('bozo_exception')}")

    if status is not None and status >= 400:
        raise FetchError(f"Feed returned HTTP {status}")

    return parsed
