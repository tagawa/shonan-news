import json
import logging
import os
import sys
from pathlib import Path

import feedparser
import openai

from . import pipeline

logger = logging.getLogger("shonannews")

FEEDS_PATH = Path("_data/feeds.json")
STATE_PATH = Path("data/state.json")
POSTS_DIR = Path("_posts")


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    api_key = os.environ["OPENAI_API_KEY"]
    client = openai.OpenAI(api_key=api_key)

    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

    feeds = json.loads(FEEDS_PATH.read_text(encoding="utf-8"))

    exit_codes = []
    for feed in feeds:
        try:
            code = pipeline.run(
                feed_url=feed["url"],
                source_name=feed["name"],
                state_path=STATE_PATH,
                posts_dir=POSTS_DIR,
                parse_fn=feedparser.parse,
                create_fn=client.chat.completions.create,
            )
        except Exception:
            logger.error("Unhandled error processing feed %s", feed["url"], exc_info=True)
            code = 1
        exit_codes.append(code)

    sys.exit(1 if any(exit_codes) else 0)


if __name__ == "__main__":
    main()
