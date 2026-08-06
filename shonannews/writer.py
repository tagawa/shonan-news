import hashlib
import re
from pathlib import Path

import yaml


def slugify(title, fallback_key, max_length=60):
    ascii_title = title.encode("ascii", "ignore").decode("ascii")
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
                        image_url=None):
    head = {"layout": "post", "title": title, "date": date}
    tail = {
        "source_url": source_url,
        "source_title": source_title,
        "source_name": source_name,
    }
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
