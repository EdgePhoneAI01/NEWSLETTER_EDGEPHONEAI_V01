#!/usr/bin/env python3
"""
Fetch Edge AI headlines from Google News RSS and update index.html.

Usage:
    python scripts/update_newsletter.py
"""

import html
import re
import sys
import urllib.parse
from datetime import datetime, timezone

import feedparser

RSS_URL = (
    "https://news.google.com/rss/search"
    "?q=edge+AI+OR+on-device+AI+OR+edge+computing+AI"
    "&hl=en-US&gl=US&ceid=US:en"
)
INDEX_HTML = "index.html"
MIN_ARTICLES = 5
MAX_ARTICLES = 10
USER_AGENT = "Mozilla/5.0 (compatible; EdgePhone-Newsletter/1.0)"


def strip_html(text):
    """Remove HTML tags from a string."""
    return re.sub(r"<[^>]+>", "", text or "").strip()


def get_source_info(entry):
    """Return (source_name, source_domain) from a feedparser entry."""
    source_name = ""
    source_domain = ""

    source = entry.get("source") or {}
    if isinstance(source, dict):
        source_name = source.get("title", "")
        source_href = source.get("href", "") or source.get("link", "")
        if source_href:
            parsed = urllib.parse.urlparse(source_href)
            source_domain = parsed.netloc

    # Fallback: Google News RSS titles are formatted as "Headline - Source"
    title = entry.get("title", "")
    if not source_name and " - " in title:
        source_name = title.rsplit(" - ", 1)[-1].strip()

    return source_name, source_domain or "news.google.com"


def fetch_articles():
    """Fetch and return up to MAX_ARTICLES from the Google News RSS feed."""
    print(f"Fetching RSS feed: {RSS_URL}")
    try:
        feed = feedparser.parse(RSS_URL, agent=USER_AGENT)
    except Exception as exc:
        print(f"ERROR: Failed to parse RSS feed: {exc}")
        return []

    if feed.bozo and not feed.entries:
        print(f"ERROR: Feed parse error: {feed.bozo_exception}")
        return []

    if not feed.entries:
        print("ERROR: No entries found in RSS feed.")
        return []

    articles = []
    for entry in feed.entries[:MAX_ARTICLES]:
        title_full = strip_html(entry.get("title", "")).strip()
        link = entry.get("link", "").strip()
        summary = strip_html(entry.get("summary", "")).strip()
        source_name, source_domain = get_source_info(entry)

        # Use the full "Title - Source" string as the display title
        # (Google News RSS already formats it this way)
        display_title = title_full
        if source_name and not title_full.endswith(f" - {source_name}"):
            display_title = f"{title_full} - {source_name}"

        # If summary is identical to the title, leave it as-is
        # (Google News often duplicates the headline in the description)

        articles.append(
            {
                "title": display_title,
                "link": link,
                "summary": summary or display_title,
                "domain": source_domain,
            }
        )

    print(f"Found {len(articles)} articles.")
    return articles


def build_featured_card(article):
    """Return HTML string for a featured card article."""
    title_esc = html.escape(article["title"])
    link_esc = html.escape(article["link"])
    summary_esc = html.escape(article["summary"])
    domain_esc = html.escape(article["domain"])

    return (
        '      <article class="featured-card">\n'
        '        <span class="featured-banner">Featured</span>\n'
        '        <div class="featured-visual">\n'
        f'          <img src="https://www.google.com/s2/favicons?sz=256&amp;domain={domain_esc}"'
        ' alt="" loading="lazy" width="640" height="360" />\n'
        "        </div>\n"
        '        <div class="featured-body">\n'
        f'          <h3><a href="{link_esc}" target="_blank"'
        f' rel="noopener noreferrer">{title_esc}</a></h3>\n'
        f"          <p>{summary_esc}</p>\n"
        f'          <a class="read-link" href="{link_esc}" target="_blank"'
        ' rel="noopener noreferrer">Read article \u2192</a>\n'
        "        </div>\n"
        "      </article>"
    )


def build_list_item(article, rank):
    """Return HTML string for an ordered-list article item."""
    title_esc = html.escape(article["title"])
    link_esc = html.escape(article["link"])
    summary_esc = html.escape(article["summary"])

    return (
        "      <li>\n"
        f'        <span class="rank">{rank}</span>\n'
        '        <div class="item-main">\n'
        f'          <h4><a href="{link_esc}" target="_blank"'
        f' rel="noopener noreferrer">{title_esc}</a></h4>\n'
        f"          <p>{summary_esc}</p>\n"
        f'          <div class="item-meta"><a href="{link_esc}" target="_blank"'
        ' rel="noopener noreferrer">Read article</a></div>\n'
        "        </div>\n"
        "      </li>"
    )


def update_html(articles, date_str):
    """Read index.html, replace news sections and date, then write it back."""
    with open(INDEX_HTML, "r", encoding="utf-8") as fh:
        content = fh.read()

    # --- 1. Update <time> element with today's date -------------------------
    content = re.sub(
        r'<time datetime="[^"]*">[^<]*</time>',
        f'<time datetime="{date_str}">{date_str}</time>',
        content,
    )

    # --- 2. Replace the featured-grid section -------------------------------
    # Pattern: from <div class="featured-grid"> through the last </article>
    # and its immediately following </div> (the grid's closing tag).
    # Non-greedy [\s\S]*? ensures we stop at the LAST </article>\s*</div>
    # pair that closes the grid (no </div> follows the first </article>).
    featured_cards = "\n\n".join(
        build_featured_card(a) for a in articles[:2]
    )
    new_featured_grid = (
        '<div class="featured-grid">\n'
        + featured_cards
        + "\n    </div>"
    )

    featured_pattern = re.compile(
        r'<div class="featured-grid">[\s\S]*?</article>\s*</div>',
    )
    if not featured_pattern.search(content):
        print("WARNING: Could not locate featured-grid section; skipping replacement.")
    else:
        content = featured_pattern.sub(new_featured_grid, content, count=1)

    # --- 3. Replace the article-list (More headlines) section ---------------
    list_items = "\n\n".join(
        build_list_item(a, i + 3) for i, a in enumerate(articles[2:])
    )
    new_article_list = (
        '<ol class="article-list">\n'
        + list_items
        + "\n    </ol>"
    )

    list_pattern = re.compile(
        r'<ol class="article-list">[\s\S]*?</ol>',
    )
    if not list_pattern.search(content):
        print("WARNING: Could not locate article-list section; skipping replacement.")
    else:
        content = list_pattern.sub(new_article_list, content, count=1)

    with open(INDEX_HTML, "w", encoding="utf-8") as fh:
        fh.write(content)

    print(f"Updated {INDEX_HTML} with date={date_str} and {len(articles)} articles.")


def main():
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"EdgePhone Daily Newsletter updater — {date_str}")

    articles = fetch_articles()

    if len(articles) < MIN_ARTICLES:
        print(
            f"ERROR: Only {len(articles)} articles found "
            f"(minimum required: {MIN_ARTICLES}). Exiting without updating."
        )
        sys.exit(0)

    update_html(articles, date_str)
    print("Done.")


if __name__ == "__main__":
    main()
