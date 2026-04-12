#!/usr/bin/env python3
"""
Daily EdgePhone newsletter generator.
Fetches articles via RSS (Google News) and optionally NewsAPI.org, ranks by keyword
relevance, renders newsletter_template.jinja.html, and writes index.html.
"""

from __future__ import annotations

import html
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import quote_plus

import feedparser
import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

KEYWORDS: list[str] = [
    "Edge AI",
    "On-device AI",
    "Phone-first AI",
    "Offline AI",
    "Local AI processing",
    "On-device inference",
    "Lightweight AI models",
    "Low-latency AI",
    "Privacy-first AI",
    "Zero-latency AI",
    "Mobile machine learning",
    "Edge ML",
    "Battery-efficient AI",
    "Secure mobile AI",
    "Offline voice processing",
    "On-device computer vision",
    "Sensor fusion",
    "Mobile AI APIs",
    "Edge computing for IoT",
    "Local inference",
    "Data minimization AI",
    "Privacy-by-default AI",
    "Zero round-trip AI",
]

# Google News RSS search queries (broad coverage, no API key)
GOOGLE_NEWS_QUERIES: list[str] = [
    "Edge AI OR on-device AI",
    "mobile machine learning OR edge ML",
    "privacy-first AI OR local inference",
    "offline AI OR lightweight neural network",
    "TensorFlow Lite OR Core ML OR ONNX mobile",
]

SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATE_NAME = "newsletter_template.jinja.html"
DEFAULT_OUTPUT = SCRIPT_DIR / "index.html"

USER_AGENT = (
    "EdgePhoneDailyNewsletter/1.0 (+https://www.edgephone.ai/) "
    "Python-requests compatible curator"
)


@dataclass
class Article:
    title: str
    url: str
    snippet: str
    image_url: str | None = None
    score: float = 0.0
    sources: set[str] = field(default_factory=set)


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _snippet(text: str, max_len: int = 200) -> str:
    t = _strip_html(text)
    if len(t) <= max_len:
        return t
    return t[: max_len - 1].rsplit(" ", 1)[0] + "…"


def _score_text(text: str) -> float:
    if not text:
        return 0.0
    lower = text.lower()
    score = 0.0
    for kw in KEYWORDS:
        k = kw.lower()
        if k in lower:
            # Longer phrases are slightly more specific
            score += 1.0 + min(len(k), 40) / 80.0
    return score


def _feed_image(entry) -> str | None:
    if hasattr(entry, "media_content") and entry.media_content:
        for m in entry.media_content:
            u = m.get("url")
            if u:
                return u
    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        return entry.media_thumbnail[0].get("url")
    if entry.get("enclosures"):
        for enc in entry.enclosures:
            if enc.get("type", "").startswith("image/") and enc.get("href"):
                return enc["href"]
    return None


def fetch_google_news_rss(session: requests.Session) -> list[Article]:
    articles: list[Article] = []
    base = "https://news.google.com/rss/search"
    for q in GOOGLE_NEWS_QUERIES:
        params = f"q={quote_plus(q)}&hl=en-US&gl=US&ceid=US:en"
        url = f"{base}?{params}"
        try:
            r = session.get(url, timeout=25)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"[warn] RSS fetch failed ({q[:40]}…): {e}", file=sys.stderr)
            continue
        feed = feedparser.parse(r.content)
        for e in feed.entries:
            title = _strip_html(e.get("title", ""))
            link = e.get("link", "").strip()
            if not title or not link:
                continue
            summary = e.get("summary", e.get("description", ""))
            img = _feed_image(e)
            articles.append(
                Article(
                    title=title,
                    url=link,
                    snippet=_snippet(summary),
                    image_url=img,
                    sources={"google_news_rss"},
                )
            )
    return articles


def fetch_newsapi(session: requests.Session, api_key: str) -> list[Article]:
    # OR-join a subset of keywords to stay within URL limits
    core_terms = [
        '"edge AI"',
        '"on-device"',
        "mobile machine learning",
        "TensorFlow Lite",
        "Core ML",
        "privacy AI",
    ]
    q = " OR ".join(core_terms)
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": q,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 50,
        "apiKey": api_key,
    }
    try:
        r = session.get(url, params=params, timeout=25)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        print(f"[warn] NewsAPI request failed: {e}", file=sys.stderr)
        return []
    if data.get("status") != "ok":
        print(f"[warn] NewsAPI error: {data.get('message', data)}", file=sys.stderr)
        return []
    out: list[Article] = []
    for a in data.get("articles", []):
        title = _strip_html(a.get("title") or "")
        link = (a.get("url") or "").strip()
        if not title or not link:
            continue
        desc = a.get("description") or a.get("content") or ""
        img = a.get("urlToImage")
        out.append(
            Article(
                title=title,
                url=link,
                snippet=_snippet(desc),
                image_url=img,
                sources={"newsapi"},
            )
        )
    return out


def _normalize_key(url: str) -> str:
    u = url.split("?", 1)[0].rstrip("/")
    return u.lower()


def merge_and_rank(raw: Iterable[Article]) -> list[Article]:
    by_key: dict[str, Article] = {}
    for a in raw:
        key = _normalize_key(a.url)
        if not key:
            continue
        blob = f"{a.title} {a.snippet}"
        s = _score_text(blob)
        if key in by_key:
            existing = by_key[key]
            if s > existing.score:
                existing.score = s
            if a.image_url and not existing.image_url:
                existing.image_url = a.image_url
            existing.sources |= a.sources
        else:
            a.score = s
            by_key[key] = a

    ranked = sorted(by_key.values(), key=lambda x: x.score, reverse=True)
    # Prefer articles that matched at least one keyword; fill remainder by order
    with_kw = [x for x in ranked if x.score > 0]
    without = [x for x in ranked if x.score <= 0]
    merged = with_kw + without
    return merged[:10]


def render_html(
    featured: list[Article],
    standard: list[Article],
    output_path: Path,
) -> None:
    env = Environment(
        loader=FileSystemLoader(str(SCRIPT_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tpl = env.get_template(TEMPLATE_NAME)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def pack(a: Article) -> dict:
        return {
            "title": a.title,
            "url": a.url,
            "snippet": a.snippet,
            "image_url": a.image_url,
        }

    html_out = tpl.render(
        generated_date=generated,
        featured=[pack(a) for a in featured],
        standard=[pack(a) for a in standard],
    )
    output_path.write_text(html_out, encoding="utf-8")
    print(f"Wrote {output_path}")


def main() -> int:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    collected: list[Article] = []
    collected.extend(fetch_google_news_rss(session))

    news_key = os.environ.get("NEWS_API_KEY", "").strip()
    if news_key:
        collected.extend(fetch_newsapi(session, news_key))
    else:
        print(
            "[info] NEWS_API_KEY not set — using RSS only. "
            "Set NEWS_API_KEY for NewsAPI.org coverage.",
            file=sys.stderr,
        )

    top = merge_and_rank(collected)
    if len(top) < 10:
        print(
            f"[warn] Only {len(top)} articles after merge; page may have fewer slots filled.",
            file=sys.stderr,
        )

    featured = top[:2]
    standard = top[2:10]

    out = Path(os.environ.get("OUTPUT_HTML", str(DEFAULT_OUTPUT))).resolve()
    render_html(featured, standard, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
