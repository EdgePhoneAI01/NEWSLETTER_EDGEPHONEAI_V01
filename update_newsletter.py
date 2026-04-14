#!/usr/bin/env python3
"""
update_newsletter.py – Fetch Edge AI news from Google News RSS and update index.html.

Usage:
    python update_newsletter.py

Requires:
    feedparser, requests (see requirements.txt)
"""

import os
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

try:
    import feedparser
except ImportError:
    print("Missing 'feedparser'. Run: pip install feedparser", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HTML_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")

# Google News RSS search terms – ordered by relevance preference
SEARCH_QUERIES = [
    "edge+AI",
    "on-device+AI",
    "mobile+AI+inference",
    "edge+computing+AI",
    "on-device+machine+learning",
    "AI+inference+edge",
]

RSS_TEMPLATE = (
    "https://news.google.com/rss/search"
    "?q={query}&hl=en-US&gl=US&ceid=US:en"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _he(text: str) -> str:
    """Minimal HTML-escape for attribute values and text content."""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _domain(url: str) -> str:
    """Extract bare domain from a URL (strips leading www.)."""
    try:
        return urlparse(url).netloc.removeprefix("www.")
    except Exception:
        return "news.google.com"


def _clean_summary(raw: str, title: str) -> str:
    """Strip HTML tags and truncate to ≤200 characters."""
    text = re.sub(r"<[^>]+>", "", raw).strip()
    if not text:
        return title
    if len(text) > 200:
        text = text[:200].rsplit(" ", 1)[0] + "\u2026"
    return text


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def fetch_articles(want: int = 12) -> list:
    """Fetch up to *want* unique Edge AI articles from Google News RSS feeds."""
    seen: set = set()
    articles: list = []

    for query in SEARCH_QUERIES:
        if len(articles) >= want:
            break
        url = RSS_TEMPLATE.format(query=query)
        try:
            feed = feedparser.parse(url)
        except Exception as exc:
            print(f"  WARNING: feed error for '{query}': {exc}", file=sys.stderr)
            continue

        for entry in feed.entries:
            if len(articles) >= want:
                break

            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            summary = entry.get("summary", "").strip()

            if not title or not link:
                continue

            # Deduplicate by normalised title prefix
            key = re.sub(r"\s+", " ", title.lower())[:80]
            if key in seen:
                continue
            seen.add(key)

            articles.append(
                {
                    "title": title,
                    "link": link,
                    "summary": _clean_summary(summary, title),
                    "domain": _domain(link),
                }
            )

    return articles


# ---------------------------------------------------------------------------
# HTML builders
# ---------------------------------------------------------------------------


def _featured_card(article: dict) -> str:
    """Return the HTML for one featured-card <article> element."""
    t = _he(article["title"])
    s = _he(article["summary"])
    lnk = article["link"]
    dom = _he(article["domain"])
    return (
        '      <article class="featured-card">\n'
        '        <span class="featured-banner">Featured</span>\n'
        '        <div class="featured-visual">\n'
        f'          <img src="https://www.google.com/s2/favicons?sz=256&amp;domain={dom}"'
        ' alt="" loading="lazy" width="640" height="360" />\n'
        "        </div>\n"
        '        <div class="featured-body">\n'
        f'          <h3><a href="{lnk}" target="_blank" rel="noopener noreferrer">{t}</a></h3>\n'
        f"          <p>{s}</p>\n"
        f'          <a class="read-link" href="{lnk}" target="_blank" rel="noopener noreferrer">Read article \u2192</a>\n'
        "        </div>\n"
        "      </article>"
    )


def _article_item(article: dict, rank: int) -> str:
    """Return the HTML for one <li> article item."""
    t = _he(article["title"])
    s = _he(article["summary"])
    lnk = article["link"]
    return (
        "      <li>\n"
        f'        <span class="rank">{rank}</span>\n'
        '        <div class="item-main">\n'
        f'          <h4><a href="{lnk}" target="_blank" rel="noopener noreferrer">{t}</a></h4>\n'
        f"          <p>{s}</p>\n"
        f'          <div class="item-meta"><a href="{lnk}" target="_blank" rel="noopener noreferrer">Read article</a></div>\n'
        "        </div>\n"
        "      </li>"
    )


# ---------------------------------------------------------------------------
# HTML update
# ---------------------------------------------------------------------------


def update_html(articles: list) -> str:
    """Patch index.html in-place and return the ISO date string used."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with open(HTML_FILE, encoding="utf-8") as fh:
        html = fh.read()

    original = html

    # 1. Update the date pill
    html = re.sub(
        r'<span class="pill"><time datetime="[^"]*">[^<]*</time> \u00b7 Daily edition</span>',
        f'<span class="pill"><time datetime="{today}">{today}</time> \u00b7 Daily edition</span>',
        html,
    )

    # 2. Replace featured-grid content (articles 1 & 2)
    #    Anchor the end of the match on the closing </div> that is immediately
    #    followed by a blank line and the "More headlines" <h2>.  The non-greedy
    #    .*? + DOTALL ensures we match the outermost featured-grid </div>.
    featured_block = "\n".join(_featured_card(a) for a in articles[:2])
    html = re.sub(
        r'(<div class="featured-grid">).*?(</div>\s+<h2\s+class="section-title">More headlines</h2>)',
        lambda m: (
            m.group(1)
            + "\n"
            + featured_block
            + "\n    "
            + m.group(2)
        ),
        html,
        flags=re.DOTALL,
    )

    # 3. Replace article-list content (articles 3–10)
    #    The non-greedy .*? matches the first </ol> (no nested <ol> in this file).
    items_block = "\n\n".join(
        _article_item(a, i + 3) for i, a in enumerate(articles[2:10])
    )
    html = re.sub(
        r'(<ol class="article-list">)(.*?)(</ol>)',
        lambda m: m.group(1) + "\n" + items_block + "\n    " + m.group(3),
        html,
        flags=re.DOTALL,
    )

    if html == original:
        print("No changes detected in index.html.")
    else:
        with open(HTML_FILE, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"index.html updated for {today}.")

    return today


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("Fetching Edge AI news\u2026")
    articles = fetch_articles(want=12)

    if len(articles) < 3:
        print(
            f"ERROR: Only {len(articles)} article(s) fetched (minimum 3 required). Aborting.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Fetched {len(articles)} articles:")
    for i, a in enumerate(articles, 1):
        print(f"  {i:2}. {a['title'][:90]}")

    update_html(articles)


if __name__ == "__main__":
    main()
