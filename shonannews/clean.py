import html as html_module
import re
from html.parser import HTMLParser


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def strip_html(raw_html):
    if not raw_html:
        return ""
    parser = _TextExtractor()
    parser.feed(raw_html)
    text = "".join(parser.parts)
    text = html_module.unescape(text)
    return " ".join(text.split())


def truncate(text, max_chars):
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip()


_BOILERPLATE = re.compile(
    r"\s*(?:The post\b.*?\b(?:appeared first|first appeared)\s+on\b.*?[.]"
    r"|投稿\s*.*?は.*?に最初に表示されました。"
    r"|\[(?:…|\.\.\.)\]|Continue reading\.?|続きを読む。?)\s*$",
    re.IGNORECASE,
)


def strip_feed_boilerplate(text):
    # WordPress excerpt feeds append a truncation marker, then a separate
    # "first appeared on" sentence. A single sub() only strips whichever one
    # sits at the current end of string, so this loops until nothing changes.
    for _ in range(5):
        stripped = _BOILERPLATE.sub("", text)
        if stripped == text:
            break
        text = stripped
    return text
