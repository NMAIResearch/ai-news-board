#!/usr/bin/env python3
"""fetch_vendor_news.py - vendor newsrooms that publish no RSS, via their sitemaps.

The board tiers a vendor's own claims at 5, the party selling the thing, but until
2026-07-31 it watched exactly one vendor blog (DeepMind). Anthropic and OpenAI both serve
no usable RSS (anthropic.com/rss.xml 404s, openai.com/news/rss.xml redirects to an empty
document) and both publish sitemaps carrying <lastmod>, which is enough to find what is new.

Sitemaps give URLs and dates but no titles, so each NEW url costs one page fetch for its
<title>. Titles are cached in vendor_titles.json, so a run only pays for what changed.

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
from fetch_feeds import TYPE_TIER, domain, entity_of, source_type, too_old

HERE = os.path.dirname(os.path.abspath(__file__))
FEED = os.path.join(HERE, "feed_items.json")
TITLES = os.path.join(HERE, "vendor_titles.json")

UA = "Mozilla/5.0 (NM AI Research board; +https://nmairesearch.github.io/ai-news-board)"
PER_VENDOR = 3   # per VENDOR, not per sitemap: OpenAI splits one newsroom across several
DELAY = 1.5

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


def title_of(url):
    raw = get(url)
    m = OGTITLE.search(raw) or TITLE.search(raw)
    if not m:
        return ""
    return SUFFIX.sub("", html.unescape(re.sub(r"\s+", " ", m.group(1))).strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--per-vendor", type=int, default=PER_VENDOR)
    a = ap.parse_args()

    data = json.load(open(FEED, encoding="utf-8")) if os.path.exists(FEED) else {"items": []}
    known = {s["url"] for it in data["items"] for s in it.get("sources", []) if s.get("url")}
    titles = json.load(open(TITLES, encoding="utf-8")) if os.path.exists(TITLES) else {}
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

    added, skipped_old, seen = [], 0, set()
    for label, posts_map in by_vendor.items():
        posts = sorted(posts_map.items(), key=lambda t: t[1], reverse=True)[:a.per_vendor]
        print(f"  {label}: taking {len(posts)} most recent")
        for url, lastmod in posts:
            if url in known or url in seen:
                continue
            seen.add(url)
            if too_old(lastmod, now, "vendor-own"):
                skipped_old += 1
                continue
            if url not in titles:
                if a.dry_run:
                    titles[url] = "(title not fetched in dry run)"
                else:
                    try:
                        time.sleep(DELAY)
                        titles[url] = title_of(url)
                    except Exception as e:
                        print(f"    no title for {url.split('/')[-1]}: {e}")
                        continue
            t = titles[url]
            if not t:
                continue
            st = source_type(url)
            added.append({
                "entity": entity_of(t) or label,
                "headline": t,
                "date": lastmod[:10],
                "topic": "",
                "claim_type": "unclassified",
                "denominator_stated": "?",
                "reviewed": False,
                "sources": [{"name": domain(url), "url": url, "source_type": st,
                             "motive_tier": TYPE_TIER.get(st, 5)}],
            })
            print(f"    + tier {TYPE_TIER.get(st, 5)}  {lastmod[:10]}  {t[:62]}")

    print(f"\n{len(added)} new vendor post(s), {skipped_old} dropped as stale")
    if a.dry_run:
        print("dry run: nothing written")
        return
    if added:
        data["items"] = data["items"] + added
        json.dump(data, open(FEED, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        json.dump(titles, open(TITLES, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print(f"written: {FEED} ({len(data['items'])} items). Now run carry_reviews.py")


if __name__ == "__main__":
    main()
