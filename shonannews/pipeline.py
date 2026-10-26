import calendar
import logging
import re
import unicodedata
from datetime import date, datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from . import (clean, event_town, fetch, identity, llm, merge, places, relative_days, shortlist, state as state_mod,
               validate, weekdays, writer)

logger = logging.getLogger("shonannews")

JST = ZoneInfo("Asia/Tokyo")
DESCRIPTION_MAX_CHARS = 600
IMAGE_MIN_WIDTH = 240
MAX_ITEMS_PER_RUN = 15
# Town News category terms skipped at intake, with the reason logged. Exact match after
# strip. Paid placements (advertorials, political opinion ads): no other spelling seen in
# any edition on 2026-09-17. Columns, serials and the weekly profile are features, not news
# or events (owner, 2026-10-16); あっとほーむデスク is the editor's column and 人物風土記 the
# profile. See the backend spec, "Tag skip".
SKIP_TAGS = {
    "ピックアップ（PR）": "an advertisement",
    "意見広告": "an advertisement",
    "コラム": "a column",
    "あっとほーむデスク": "a column",
    "人物風土記": "a profile",
}
# A volume number in a Town News title marks a serial, whatever its tags; the event blog
# numbers real concerts the same way, so only Town News is matched. Matched after NFKC.
# See the backend spec, "Serial skip".
SERIAL_TITLE = re.compile(r"(?<![a-z])vol\.?\s*\d", re.I)
SERIAL_HOST = "townnews.co.jp"
# Matched after NFKC. 3日間 is a duration, not a date.
FULL_DATE = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日(?!間)")
DAY_WITH_WEEKDAY = re.compile(r"(?<!\d)(\d{1,2})\s*日\s*\(([月火水木金土日])(?:・祝)?\)")


def _default_now():
    return datetime.now(JST)


def _corroborated_day(title, description, day):
    # The model's whole input is the title plus the description, so a day that does
    # not appear there was invented rather than read, and the key is dropped. This is
    # the only thing standing between a dateless source and a confident
    # "Coming up 1 October (Thu)". See the backend spec, "Fabrication guard".
    #
    # Lookbehind: day 9 must not match inside 19日. Lookahead: 3日間 is a duration,
    # not a date. NFKC first, because the sources mix full-width digits with ASCII
    # (35 of 230 live markers depend on that alone) and a few titles use the Kangxi
    # radicals U+2F49 and U+2F47, which render identically to 月 and 日.
    source = unicodedata.normalize("NFKC", f"{title}\n{description}")
    return bool(re.search(rf"(?<!\d){day}\s*\u65e5(?!\u9593)", source))


def _single_source_month_day(title, description):
    # A fallback for a null event_date, which gpt-6-luna returns on some future events
    # where gpt-5-mini never did. Only one stated date is safe to take: with two, which
    # one is the event is a judgement for the model. See the backend spec, "Event date fallback".
    source = unicodedata.normalize("NFKC", f"{title}\n{description}")
    found = {(int(m), int(d)) for m, d in FULL_DATE.findall(source)}
    if len(found) != 1:
        return None
    month_day = found.pop()
    # A different day-only date before it is the event, and this one a rain date or a
    # range's end (31日（土）… 荒天の場合は11月１日（日）に延期).
    first = FULL_DATE.search(source).start()
    if any(int(d) != month_day[1] for d, _ in DAY_WITH_WEEKDAY.findall(source[:first])):
        return None
    return month_day


def _weekday_month_day(title, description, source_date):
    # The fallback after _single_source_month_day, for 12日（月） with no month: the weekday
    # fixes the month within a month either side of the source date. Any full date makes the
    # day-only one a range's end (10月24日（土）・25日（日）), so it is never used then.
    # See the backend spec, "Event date fallback".
    source = unicodedata.normalize("NFKC", f"{title}\n{description}")
    if FULL_DATE.search(source):
        return None
    found = {(int(d), weekdays.WEEKDAYS.index(w)) for d, w in DAY_WITH_WEEKDAY.findall(source)}
    if len(found) != 1:
        return None
    day, weekday = found.pop()
    fits = []
    for offset in (-1, 0, 1):
        year, month = divmod(source_date.year * 12 + source_date.month - 1 + offset, 12)
        try:
            candidate = date(year, month + 1, day)
        except ValueError:
            continue
        if candidate.weekday() == weekday:
            fits.append((candidate.month, candidate.day))
    return fits[0] if len(fits) == 1 else None


def _stated_year(title, description, month_day, source_date):
    # The year the source writes directly before this date, or None. Nearest-year cannot
    # see 来年: a date more than about six months ahead is nearer last year's copy
    # (来年４月17日 from 29 September came out 2026-04-17, live 2026-09-29). Nor a
    # numbered year (２０２７年10月１日 came out 2026-10-01, live 2026-10-09), and a past
    # one would show a false "Coming up". A year elsewhere in the text says nothing about
    # this date, 再来年 is two years on, and 年度 is a fiscal year, never matched because
    # 度 sits between 年 and the month. See the backend spec, "Year derivation".
    month, day = month_day
    source = unicodedata.normalize("NFKC", f"{title}\n{description}")
    date_part = rf"年\s*の?\s*0?{month}\s*月\s*0?{day}\s*日"
    if re.search(rf"(?<!再)来{date_part}", source):
        return source_date.year + 1
    found = re.search(rf"(?<!\d)(\d{{4}})\s*{date_part}", source)
    if found:
        return int(found.group(1))
    found = re.search(rf"令和\s*(\d{{1,2}}|元)\s*{date_part}", source)
    if found:
        return 2018 + (1 if found.group(1) == "元" else int(found.group(1)))
    return None


def _derive_event_date(month_day, source_date, year=None):
    # The model's own year is discarded upstream: it was wrong in almost every
    # measured miss. The nearest year to the source date is right instead, and it
    # handles the December-to-January rollover without a special case.
    month, day = month_day
    if year:
        try:
            return date(year, month, day)
        except ValueError:
            return None
    candidates = []
    for year in (source_date.year - 1, source_date.year, source_date.year + 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue  # 29 February in a non-leap year, or an impossible day like 02-30
    if not candidates:
        return None
    source_day = source_date.date()
    # On an exact tie the later date, since a notice is far more often about
    # something ahead than something behind.
    return min(candidates, key=lambda c: (abs((c - source_day).days), -c.toordinal()))


def _event_date(result, title, description, source_date):
    # Only keep a date the source itself states: the model's input is exactly this
    # title and description, so an uncorroborated day was invented, not read.
    month_day = (result.event_month_day or _single_source_month_day(title, description)
                 or _weekday_month_day(title, description, source_date))
    if not (month_day and _corroborated_day(title, description, month_day[1])):
        return None
    derived = _derive_event_date(month_day, source_date, year=_stated_year(title, description, month_day, source_date))
    return derived.isoformat() if derived else None


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


def feed_description(entry):
    # The description exactly as the model sees it; offline scripts reuse this to join posts to it.
    raw = entry.get("summary") or entry.get("description") or ""
    return clean.truncate(clean.strip_feed_boilerplate(clean.strip_html(raw)), DESCRIPTION_MAX_CHARS)


def _skip_tag(entry):
    for tag in entry.get("tags", []):
        # term can be None: feedparser keeps a tag that has only a scheme or label.
        reason = SKIP_TAGS.get((tag.get("term") or "").strip())
        if reason:
            return reason
    return None


def _is_serial(entry, feed_url):
    host = urlsplit(feed_url).hostname or ""
    if host != SERIAL_HOST and not host.endswith("." + SERIAL_HOST):
        return False
    return bool(SERIAL_TITLE.search(unicodedata.normalize("NFKC", entry.get("title", ""))))


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


def _extract_thumb(entry):
    # The feed's own small thumbnail (blogspot's 72px crop), for the index only:
    # too small for the permalink image or a link preview, so it never becomes image_url.
    thumbnails = entry.get("media_thumbnail")
    if thumbnails:
        url = thumbnails[0].get("url")
        if url and url.startswith("https://"):
            return url
    return None


def _shadow(current_state, posts, new_path, key, title, description, source_name, source_date, date_str, readings,
            result, event_date, create_fn):
    # Release 1 of the story merge: decide and record, never write. See the backend spec, "Story merge shadow".
    base = {"guid": key, "post": new_path.name}
    try:
        text = shortlist.post_text(result.title, result.lede, result.summary)
        # The post just written is excluded before scoring: in the corpus it would skew the IDF.
        candidates = shortlist.shortlist(text, source_date.date(), [p for p in posts if p.path != new_path])
        new_event_day = date.fromisoformat(event_date) if event_date else None
        for score, post in candidates:
            entry = {**base, "candidate": post.path.name, "score": round(score, 3)}
            old_event = post.front.get("event_date")
            old_event_day = date.fromisoformat(str(old_event)[:10]) if old_event else None
            if merge.blocked_by_event_date(post.source_day, old_event_day, source_date.date(), new_event_day):
                entry["guard"] = "event_date"
            elif merge.blocked_by_stated_dates(shortlist.post_text(post.front.get("title", ""), post.front.get("lede"),
                                                                   post.body), post.source_day, text, source_date.date()):
                entry["guard"] = "stated_date"
            elif merge.blocked_by_profile(post.front.get("source_title"), title):
                entry["guard"] = "profile"
            else:
                entry["guard"] = None
            if entry["guard"]:
                state_mod.record_merge_shadow(current_state, entry)
                continue
            try:
                judge = lambda: llm.call_judge(create_fn, post.front, post.body, title, description,
                                               source_date.date(), event_date)
                verdict = llm.parse_judge(judge())
                if verdict is None:
                    verdict = llm.parse_judge(judge())
            except llm.LLMCallError:
                state_mod.record_merge_shadow(current_state, {**entry, "judge": "error"})
                return
            entry["judge"] = verdict
            if not verdict:
                state_mod.record_merge_shadow(current_state, entry)
                continue
            try:
                outcome = merge.merge_into(post, title, description, source_name, source_date, date_str, readings,
                                           create_fn, _event_date)
            except llm.LLMCallError:
                state_mod.record_merge_shadow(current_state, {**entry, "outcome": "merge_error"})
                return
            state_mod.record_merge_shadow(current_state, {**entry, "outcome": outcome.kind, "reason": outcome.reason,
                                                          "missing": outcome.missing, "title": outcome.title,
                                                          "lede": outcome.lede, "summary": outcome.summary,
                                                          "event_date": outcome.event_date,
                                                          "corrections": outcome.corrections})
            return
    except Exception as exc:  # the shadow must never cost a post
        logger.warning("Merge shadow failed for %s: %s", key, exc)
        state_mod.record_merge_shadow(current_state, {**base, "outcome": "error", "error": repr(exc)})


def run(feed_url, source_name, state_path, posts_dir, parse_fn, create_fn, now_fn=_default_now, towns=()):
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

    gazetteer = places.load_places()
    # A feed's own towns scope its place readings; an empty list (no fixed area) keeps them all.
    edition = {places.MUNICIPALITIES[town] for town in towns}

    new_count = 0
    capped = False
    posts = None
    # Feeds list newest-first; process oldest-first so the newest item gets the latest timestamp.
    for entry in reversed(parsed.get("entries", [])):
        if new_count >= MAX_ITEMS_PER_RUN:
            capped = True
            break

        key = identity.identity_key(entry)
        if state_mod.is_processed(current_state, feed_url, key):
            continue

        skip_reason = _skip_tag(entry)
        if skip_reason:
            logger.info("Skipping %s: tagged as %s", key, skip_reason)
            state_mod.mark_processed(current_state, feed_url, key)
            continue

        if _is_serial(entry, feed_url):
            logger.info("Skipping %s: a numbered serial", key)
            state_mod.mark_processed(current_state, feed_url, key)
            continue

        title = entry.get("title", "")
        normalized_title = identity.normalize_title(title)
        if state_mod.is_source_title_posted(current_state, normalized_title):
            logger.info("Skipping %s: source title already posted via another feed", key)
            state_mod.mark_processed(current_state, feed_url, key)
            continue

        description = feed_description(entry)
        # Catches a retitled copy that title dedup misses. See the backend spec, "Description dedup".
        description_key = identity.description_key(description)
        if state_mod.is_source_description_posted(current_state, description_key):
            logger.info("Skipping %s: source description already posted", key)
            state_mod.mark_processed(current_state, feed_url, key)
            continue

        run_time = now_fn()
        date_str = run_time.strftime("%Y-%m-%d")
        source_date = _derive_source_date(entry, run_time)
        # What the model and every check against the source read; source_title and the dedup
        # keys stay raw. See the backend spec, "Relative days".
        model_title = relative_days.resolve(title, source_date)
        model_description = relative_days.resolve(description, source_date)

        # The model's whole input, so a canonical name is only enforced where the source has it.
        source = f"{model_title} {model_description}"

        # Official readings of the districts the source names. See the backend spec, "Place readings".
        readings = places.scoped_hints(source, gazetteer, edition)

        # One retry on a bad response: the observed failure (a string closed early) is
        # intermittent per item, so a second identical call often succeeds. Japanese left
        # in the English and source narration get the same retry. See the backend spec,
        # "Japanese left in" and "Narration retry".
        try:
            result = validate.validate_response(
                llm.call_llm(create_fn, model_title, model_description, date_str, readings=readings), source)
            if not result.ok or result.japanese or result.narration:
                reason = result.error or ("japanese_left_in" if result.japanese else "source_narration")
                logger.warning("Validation failed for %s: %s; retrying once", key, reason)
                retry = validate.validate_response(
                    llm.call_llm(create_fn, model_title, model_description, date_str, readings=readings), source)
                # A usable first response is only given up for another usable one.
                if retry.ok or not result.ok:
                    result = retry
        except llm.LLMCallError as exc:
            logger.warning("LLM call failed for %s: %s", key, exc)
            continue

        if not result.ok:
            logger.error("Validation failed for %s: %s", key, result.error)
            state_mod.mark_processed(current_state, feed_url, key)
            continue

        # Published anyway: a stray Japanese word is a smaller defect than a lost story.
        if result.japanese:
            logger.warning("Publishing %s with Japanese left in: %s", key, " ".join(result.japanese))

        # Narration the retry did not fix: keep each fact where code can, drop the rest.
        if result.narration:
            logger.warning("Rewriting source narration in %s: %s", key, " | ".join(result.narration))
            result = validate.rewrite_narration(result)

        # Puts back a weekday the source states and the model dropped. See the backend spec,
        # "Weekday restoration".
        result.lede = weekdays.restore_weekdays(result.lede, source, source_date)
        result.summary = weekdays.restore_weekdays(result.summary, source, source_date)

        event_date = _event_date(result, model_title, model_description, source_date)
        # Only What's on shows a town, and it lists only posts with an event date.
        town = event_town.find(result.title, result.lede, result.summary, title, towns, description) if event_date else None

        source_url = _prefer_https(entry.get("link", ""))
        image_url = _extract_image(entry)
        thumb_url = None if image_url else _extract_thumb(entry)
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
            thumb_url=thumb_url,
            event_date=event_date,
            label=result.label,
            town=town,
        )
        body = writer.build_body(result.summary)
        writer.write_post(path, front_matter, body)

        state_mod.mark_source_title_posted(current_state, normalized_title)
        state_mod.mark_source_description_posted(current_state, description_key)
        state_mod.mark_processed(current_state, feed_url, key)
        # Loaded once per feed (the first load includes this post); later items add only their own file.
        if posts is None:
            posts = shortlist.load_posts(posts_dir)
        else:
            posts += [post for post in [shortlist.load_post(path)] if post]
        _shadow(current_state, posts, path, key, model_title, model_description, source_name, source_date, date_str,
                readings, result, event_date, create_fn)
        new_count += 1

    # A capped run keeps the old validators: new ones would get a 304 next run, stranding
    # the items left over until the feed changes. See the backend spec, "Pipeline stages", step 3.
    if not capped:
        feed_state["etag"] = parsed.get("etag") or feed_state.get("etag")
        feed_state["modified"] = parsed.get("modified") or feed_state.get("modified")

    state_mod.save_state(state_path, current_state)
    logger.info("Run complete: %d new posts.", new_count)
    return 0
