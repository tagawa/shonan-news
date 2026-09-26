import hashlib
import re
import unicodedata
from datetime import date
from pathlib import Path

import yaml

FRONT_MATTER = re.compile(r"---\n(.*?)\n---", re.DOTALL)
# Reads the written digits, not a parsed instant: the pipeline writes JST, and the site renders JST.
SOURCE_MONTH = re.compile(r"^source_date:\s*'?(\d{4}-\d{2})", re.MULTILINE)
DATE_MONTH = re.compile(r"^date:\s*'?(\d{4}-\d{2})", re.MULTILINE)


def slugify(title, fallback_key, max_length=60):
    # NFKD first splits ō into o plus a combining macron, so only the macron is dropped.
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")
    if not slug:
        slug = fallback_key.replace(":", "-")
    return slug[:max_length].rstrip("-")


def build_filename(date_str, slug, posts_dir, identity_key):
    posts_dir = Path(posts_dir)
    base = f"{date_str}-{slug}"
    path = posts_dir / f"{base}.md"
    if path.exists():
        suffix = hashlib.sha256(identity_key.encode("utf-8")).hexdigest()[:8]
        path = posts_dir / f"{base}-{suffix}.md"
    return path


def build_front_matter(title, date, source_date, source_url, source_title, source_name, lede, guid,
                        image_url=None, event_date=None, label=None):
    head = {"layout": "post", "title": title, "date": date}
    tail = {
        "source_url": source_url,
        "source_title": source_title,
        "source_name": source_name,
    }
    # An ISO string, never a date object: safe_dump quotes the string and leaves a
    # date bare, and the quoted form is what Jekyll's date filter was verified against.
    # Omitted when absent, so nothing downstream has to tell "none" from "not stated".
    if event_date:
        tail["event_date"] = event_date
    # Omitted when absent, like event_date: an unlabelled post asserts nothing.
    if label:
        tail["label"] = label
    if image_url:
        tail["image_url"] = image_url
    tail["lede"] = lede
    tail["guid"] = guid
    dump_kwargs = dict(sort_keys=False, allow_unicode=True, default_flow_style=False)
    return (
        yaml.safe_dump(head, **dump_kwargs)
        + f"source_date: '{source_date}'\n"
        + yaml.safe_dump(tail, **dump_kwargs)
    )


def build_body(summary):
    return f"{summary}\n"


def write_post(path, front_matter, body):
    content = f"---\n{front_matter}---\n\n{body}\n"
    Path(path).write_text(content, encoding="utf-8")


def _post_month(text):
    front_matter = FRONT_MATTER.match(text).group(1)
    match = SOURCE_MONTH.search(front_matter) or DATE_MONTH.search(front_matter)
    return match.group(1)


def ensure_archive_stubs(posts_dir, archive_dir):
    months = {_post_month(path.read_text(encoding="utf-8")) for path in Path(posts_dir).glob("*.md")}
    archive_dir = Path(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)
    for month in sorted(months):
        path = archive_dir / f"{month}.md"
        # Existing stubs are left alone, so a hand edit survives the next run.
        if path.exists():
            continue
        # %B is English regardless of the runner: Python keeps LC_TIME at the C locale unless told otherwise.
        title = date(int(month[:4]), int(month[5:]), 1).strftime("%B %Y")
        path.write_text(
            f"---\nlayout: archive-month\ntitle: {title}\nmonth: '{month}'\npermalink: /archive/{month}/\n---\n",
            encoding="utf-8",
        )
