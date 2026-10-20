import re
from pathlib import Path

# Public by design: the search engine checks it against the file of the same name at the site root.
KEY = "b5f95a0660fce5ce51defc9980ce4b9b"
SITE_URL = "https://shonannews.com"
# The file names Jekyll reads as posts; anything else in _posts it skips, so this does too.
POST_NAME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-(.+)\.md$")


def post_paths(posts_dir):
    return sorted(path for path in Path(posts_dir).rglob("*.md") if POST_NAME.match(path.name))


def post_url(path):
    # Month folders add nothing to the URL: Jekyll only reads categories from folders above _posts.
    year, month, day, slug = POST_NAME.match(Path(path).name).groups()
    return f"{SITE_URL}/{year}/{month}/{day}/{slug}.html"


def seed_urls(posts_dir):
    return [f"{SITE_URL}/", f"{SITE_URL}/archive/"] + sorted(post_url(path) for path in post_paths(posts_dir))
