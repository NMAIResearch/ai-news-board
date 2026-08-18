#!/usr/bin/env python3
"""fetch_vendor_news.py - vendor newsrooms that publish no RSS, via their sitemaps.

The board tiers a vendor's own claims at 5, the party selling the thing, but until
2026-07-31 it watched exactly one vendor blog (DeepMind). Anthropic and OpenAI both serve
no usable RSS (anthropic.com/rss.xml 404s, openai.com/news/rss.xml redirects to an empty
document). Both publish sitemaps carrying <lastmod>, which identifies pages worth checking
but does not establish when an article was published.

Each recently modified URL is fetched once for its title and publication date. The metadata
is cached in vendor_titles.json, so later runs fetch only unseen candidate pages. Ranking,
the freshness cutoff and the displayed date all use the page publication date, never
<lastmod>.

Appends to feed_items.json, deduped by URL, so the rest of the pipeline treats these like
any other item. Run directly after fetch_feeds.py and before carry_reviews.py.

  python3 fetch_vendor_news.py            # append new vendor posts
  python3 fetch_vendor_news.py --dry-run  # list what it would add
"""
import argparse
import html
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_feeds import (TYPE_TIER, domain, entity_of, publication_date_from_html,
                         source_type, too_old)
from url_identity import canonical_url

HERE = os.path.dirname(os.path.abspath(__file__))
FEED = os.path.join(HERE, "feed_items.json")
TITLES = os.path.join(HERE, "vendor_titles.json")

UA = "Mozilla/5.0 (NM AI Research board; +https://nmairesearch.github.io/ai-news-board)"
PER_VENDOR = 3   # per VENDOR, not per sitemap: OpenAI splits one newsroom across several
DELAY = 1.5
CACHE_PURPOSE = (
    "Caches vendor page titles and publication dates so sitemap modification times are "
    "used only to discover pages that may need checking."
)

# (label, sitemap url, path fragment identifying a post)
SITEMAPS = [
    ("Anthropic", "https://www.anthropic.com/sitemap.xml", "/news/"),
    ("OpenAI", "https://openai.com/sitemap.xml/release/", "/index/"),
    ("OpenAI", "https://openai.com/sitemap.xml/research/", "/index/"),
    ("OpenAI", "https://openai.com/sitemap.xml/safety/", "/index/"),
]

URLDATE = re.compile(r"<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>", re.S)
OGTITLE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']', re.I)
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
# Publishers append their own name to <title>; it is already the source chip.
SUFFIX = re.compile(r"\s*[|\\•·-]\s*(Anthropic|OpenAI)\s*$", re.I)


def get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")


def title_from_html(raw):
    m = OGTITLE.search(raw) or TITLE.search(raw)
    if not m:
        return ""
    return SUFFIX.sub("", html.unescape(re.sub(r"\s+", " ", m.group(1))).strip())


def metadata_of(url):
    raw = get(url)
    return title_from_html(raw), publication_date_from_html(raw)


def load_cache():
    if not os.path.exists(TITLES):
        return {}
    with open(TITLES, encoding="utf-8") as handle:
        raw = json.load(handle)
    cache = {}
    for url, value in raw.items():
        if not url.startswith(("http://", "https://")):
            continue
        if isinstance(value, str):
            cache[url] = {"title": value}
        elif isinstance(value, dict):
            cache[url] = {
                "title": value.get("title", ""),
                "published": value.get("published", ""),
            }
    return cache


def save_cache(cache):
    payload = {"_purpose": CACHE_PURPOSE}
    payload.update({url: cache[url] for url in sorted(cache)})
    with open(TITLES, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--per-vendor", type=int, default=PER_VENDOR)
    a = ap.parse_args()

    if os.path.exists(FEED):
        with open(FEED, encoding="utf-8") as handle:
            data = json.load(handle)
    else:
        data = {"items": []}
    known = {canonical_url(s["url"]) for it in data["items"] for s in it.get("sources", []) if s.get("url")}
    cache = load_cache()
    now = datetime.now(timezone.utc)

    # Merge every sitemap belonging to a vendor before ranking, or a vendor that splits its
    # newsroom across several sitemaps gets several times the quota.
    by_vendor = {}
    for label, sm, frag in SITEMAPS:
        try:
            rows = URLDATE.findall(get(sm))
        except Exception as e:
            print(f"  skip {label} {domain(sm)}: {e}")
            continue
        hits = [(u, d) for u, d in rows if frag in u]
        by_vendor.setdefault(label, {}).update(dict(hits))
        print(f"  {label:10s} {domain(sm)}: {len(rows)} urls, {len(hits)} posts")

    added, skipped_old, missing_date, seen, cache_changed = [], 0, 0, set(), False
    for label, posts_map in by_vendor.items():
        posts = sorted(posts_map.items(), key=lambda t: t[1], reverse=True)
        candidates = []
        for url, lastmod in posts:
            canon = canonical_url(url)
            if canon in known or canon in seen:
                continue
            seen.add(canon)
            meta = cache.get(url, {})
            if not meta.get("published"):
                # A page cannot have been published after its own modification timestamp.
                # Old unseen sitemap rows therefore need no page fetch.
                if too_old(lastmod, now, "vendor-own"):
                    skipped_old += 1
                    continue
                try:
                    time.sleep(DELAY)
                    title, published = metadata_of(url)
                except Exception as e:
                    print(f"    no metadata for {url.split('/')[-1]}: {e}")
                    continue
                if not published:
                    missing_date += 1
                    print(f"    no publication date for {url.split('/')[-1]}")
                    continue
                meta = {"title": title, "published": published}
                cache[url] = meta
                cache_changed = True

            title = meta.get("title", "")
            published = meta.get("published", "")
            if not title or not published:
                continue
            if too_old(published, now, "vendor-own"):
                skipped_old += 1
                continue
            candidates.append((published, lastmod, url, title))

        candidates.sort(reverse=True)
        selected = candidates[:a.per_vendor]
        print(f"  {label}: taking {len(selected)} most recent by publication date")
        for published, lastmod, url, title in selected:
            st = source_type(url)
            added.append({
                "entity": entity_of(title) or label,
                "headline": title,
                "date": published,
                "topic": "",
                "claim_type": "unclassified",
                "denominator_stated": "?",
                "reviewed": False,
                "sources": [{"name": domain(url), "url": url, "source_type": st,
                             "source_tier": TYPE_TIER.get(st, 3)}],
            })
            print(f"    + tier {TYPE_TIER.get(st, 5)}  {published}  {title[:62]}")

    print(f"\n{len(added)} new vendor post(s), {skipped_old} dropped as stale"
          + (f", {missing_date} without a publication date" if missing_date else ""))
    if a.dry_run:
        print("dry run: nothing written")
        return
    if added:
        data["items"] = data["items"] + added
        with open(FEED, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1, ensure_ascii=False)
        print(f"written: {FEED} ({len(data['items'])} items). Now run carry_reviews.py")
    if cache_changed:
        save_cache(cache)
        print(f"metadata cache written: {TITLES} ({len(cache)} pages)")


if __name__ == "__main__":
    main()
