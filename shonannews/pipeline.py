import calendar
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import clean, fetch, identity, llm, state as state_mod, validate, writer

logger = logging.getLogger("shonannews")

JST = ZoneInfo("Asia/Tokyo")
DESCRIPTION_MAX_CHARS = 600
IMAGE_MIN_WIDTH = 240


def _default_now():
    return datetime.now(JST)


def _derive_source_date(entry, run_time):
    parsed = entry.get("published_parsed")
    if parsed is None:
        parsed = entry.get("updated_parsed")
    if parsed is None:
        return run_time
    epoch = calendar.timegm(parsed)
    return datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone(JST)


def _prefer_https(url):
    if url.startswith("http://"):
        return "https://" + url[len("http://"):]
    return url


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_image(entry):
    thumbnails = entry.get("media_thumbnail")
    if thumbnails:
        thumb = thumbnails[0]
        url = thumb.get("url")
        width = _parse_int(thumb.get("width"))
        if url and url.startswith("https://") and (width is None or width >= IMAGE_MIN_WIDTH):
            return url
    for link in entry.get("links", []):
        if link.get("rel") == "enclosure" and (link.get("type") or "").startswith("image/"):
            href = link.get("href")
            if href and href.startswith("https://"):
                return href
    return None


def run(feed_url, source_name, state_path, posts_dir, parse_fn, create_fn, now_fn=_default_now):
    try:
        current_state = state_mod.load_state(state_path)
    except state_mod.StateCorruptError as exc:
        logger.error(str(exc))
        return 1

    feed_state = state_mod.get_feed_state(current_state, feed_url)

    try:
        parsed = fetch.fetch_feed(parse_fn, feed_url, etag=feed_state.get("etag"), modified=feed_state.get("modified"))
    except Exception as exc:
        logger.error("Fetch failed: %s", exc)
        return 1

    if parsed is None:
        logger.info("Feed not modified since last run; zero new items.")
        return 0

    if parsed.get("bozo"):
        logger.warning("Feed parsed with warnings: %s", parsed.get("bozo_exception"))

    feed_state["etag"] = parsed.get("etag") or feed_state.get("etag")
    feed_state["modified"] = parsed.get("modified") or feed_state.get("modified")

    new_count = 0
    # Feeds list newest-first; process oldest-first so the newest item gets the latest timestamp.
    for entry in reversed(parsed.get("entries", [])):
        key = identity.identity_key(entry)
        if state_mod.is_processed(current_state, feed_url, key):
            continue

        title = entry.get("title", "")
        raw_description = entry.get("summary") or entry.get("description") or ""
        description = clean.truncate(
            clean.strip_feed_boilerplate(clean.strip_html(raw_description)),
            DESCRIPTION_MAX_CHARS,
        )

        run_time = now_fn()
        date_str = run_time.strftime("%Y-%m-%d")
        source_date = _derive_source_date(entry, run_time)

        try:
            raw_response = llm.call_llm(create_fn, title, description, date_str)
        except llm.LLMCallError as exc:
            logger.warning("LLM call failed for %s: %s", key, exc)
            continue

        result = validate.validate_response(raw_response)
        if not result.ok:
            logger.error("Validation failed for %s: %s", key, result.error)
            state_mod.mark_processed(current_state, feed_url, key)
            continue

        source_url = _prefer_https(entry.get("link", ""))
        image_url = _extract_image(entry)
        slug = writer.slugify(result.title, key)
        path = writer.build_filename(date_str, slug, posts_dir, key)
        front_matter = writer.build_front_matter(
            title=result.title,
            date=run_time.strftime("%Y-%m-%d %H:%M:%S %z"),
            source_date=source_date.strftime("%Y-%m-%d %H:%M:%S %z"),
            source_url=source_url,
            source_title=title,
            source_name=source_name,
            lede=result.lede,
            guid=key,
            image_url=image_url,
        )
        body = writer.build_body(result.summary)
        writer.write_post(path, front_matter, body)

        state_mod.mark_processed(current_state, feed_url, key)
        new_count += 1

    state_mod.save_state(state_path, current_state)
    logger.info("Run complete: %d new posts.", new_count)
    return 0
