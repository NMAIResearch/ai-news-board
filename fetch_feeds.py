#!/usr/bin/env python3
"""
AI News Reality Board - fetch_feeds.py (stdlib only).

Pulls AI-news RSS/Atom feeds and auto-tags ONLY the automatable fields: source_type
from the domain, a default motive_tier from that type, and the entity if a known
vendor is named in the headline. It deliberately does NOT set claim_type or
denominator_stated: those are the call, left for a human or LLM review pass. So every
fetched item is written with reviewed=false, claim_type "announced" and denominator
"?" until someone reviews it. That is "automate the plumbing, not the call" in code.

Run:  python3 fetch_feeds.py     # writes feed_items.json, then re-run build.py
Edit FEEDS below to change sources. Network required; a feed that fails is skipped.
"""
import json, os, re, sys, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "feed_items.json")

FEEDS = [
    # trade press, AI sections
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://venturebeat.com/category/ai/feed/",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://arstechnica.com/ai/feed/",
    # primary / lab
    "https://deepmind.google/blog/rss.xml",
    # aggregator / community
    "https://hnrss.org/newest?q=AI+OR+LLM+OR+OpenAI+OR+Anthropic&points=50",
]

# domain fragment -> source_type. A lab's own blog about AI is the party selling
# the topic (vendor-own); a regulator/court/agency is a primary record.
DOMAIN_TYPE = [
    ("sec.gov", "primary-record"), ("ftc.gov", "primary-record"),
    ("courtlistener.com", "primary-record"), ("regulations.gov", "primary-record"),
    ("europa.eu", "primary-record"), ("uspto.gov", "primary-record"),
    ("openai.com", "vendor-own"), ("anthropic.com", "vendor-own"),
    ("deepmind.google", "vendor-own"), ("blog.google", "vendor-own"),
    ("ai.googleblog", "vendor-own"), ("microsoft.com", "vendor-own"),
    ("about.fb.com", "vendor-own"), ("meta.com", "vendor-own"),
    ("techcrunch.com", "trade-press"), ("venturebeat.com", "trade-press"),
    ("theverge.com", "trade-press"), ("arstechnica.com", "trade-press"),
    ("wired.com", "trade-press"), ("reuters.com", "trade-press"),
    ("bloomberg.com", "trade-press"), ("ft.com", "trade-press"),
    ("news.ycombinator.com", "aggregator"), ("ycombinator.com", "aggregator"),
    ("reddit.com", "aggregator"), ("news.google.com", "aggregator"),
]
# canonical distance tier: 1 = least incentive ... 5 = sells the thing
TYPE_TIER = {"primary-record": 1, "independent": 2, "trade-press": 3,
             "aggregator": 3, "vendor-own": 5, "other": 3}
VENDORS = ["OpenAI", "Anthropic", "Google DeepMind", "DeepMind", "Google",
           "Microsoft", "Meta", "Nvidia", "Amazon", "Salesforce", "Snap",
           "xAI", "Apple", "Mistral", "Cohere", "Perplexity"]


def source_type(url):
    for dom, t in DOMAIN_TYPE:
        if dom in url:
            return t
    return "other"   # unknown domain: do not assert 'trade press'; the unreviewed flag covers it


def entity_of(title):
    for v in VENDORS:
        if re.search(r"\b" + re.escape(v) + r"\b", title, re.I):
            return v
    return ""


def domain(url):
    m = re.match(r"https?://([^/]+)/?", url or "")
    return m.group(1).replace("www.", "") if m else (url or "")


def parse(xmlbytes):
    out, root = [], ET.fromstring(xmlbytes)
    items = list(root.iter("item"))
    if items:                                   # RSS
        for it in items:
            out.append(((it.findtext("title") or "").strip(),
                        (it.findtext("link") or "").strip(),
                        (it.findtext("pubDate") or "").strip()))
    else:                                       # Atom
        ns = "{http://www.w3.org/2005/Atom}"
        for e in root.iter(ns + "entry"):
            le = e.find(ns + "link")
            out.append(((e.findtext(ns + "title") or "").strip(),
                        (le.get("href") if le is not None else "").strip(),
                        (e.findtext(ns + "updated") or "").strip()))
    return out


def main():
    per_feed, collected = 6, []
    for f in FEEDS:
        try:
            req = urllib.request.Request(
                f, headers={"User-Agent": "Mozilla/5.0 (NM AI Research board)"})
            raw = urllib.request.urlopen(req, timeout=20).read()
            rows = parse(raw)[:per_feed]
        except Exception as e:
            print(f"skip {domain(f)}: {e}", file=sys.stderr)
            continue
        for title, link, date in rows:
            if not title:
                continue
            st = source_type(link or f)
            collected.append({
                "entity": entity_of(title) or domain(link or f),
                "headline": title,
                "date": date[:16] if date else "",
                "topic": "",
                "claim_type": "announced",
                "denominator_stated": "?",
                "reviewed": False,
                "sources": [{"name": domain(link or f), "url": link,
                             "source_type": st, "motive_tier": TYPE_TIER.get(st, 4)}],
            })
    json.dump({"fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
               "items": collected}, open(OUT, "w", encoding="utf-8"), indent=1)
    print(f"written: {OUT}  ({len(collected)} items). Now run: python3 build.py")


if __name__ == "__main__":
    main()
