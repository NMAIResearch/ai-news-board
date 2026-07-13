#!/usr/bin/env python3
"""
carry_reviews.py (stdlib only) - keep review labels across feed refreshes.

fetch_feeds.py overwrites feed_items.json with a fresh pull (all unreviewed). This
script remembers prior reviews in reviews_store.json, keyed by source URL, and:
  1) HARVEST any reviewed items currently in feed_items.json into the store,
  2) APPLY the store back onto the feed, so previously-seen items keep their
     entity / claim_type / denominator_stated / topic / reviewed=True, and only
     GENUINELY NEW items are left flagged unreviewed.

Net effect: you never re-digest the whole feed, only what is actually new.

Run order:  fetch_feeds.py -> carry_reviews.py -> apply_ratings.py -> fetch_scholar.py -> build.py
Also safe to run after any manual review so the new labels are remembered.
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
FEED = os.path.join(HERE, "feed_items.json")
STORE = os.path.join(HERE, "reviews_store.json")
FIELDS = ("entity", "claim_type", "denominator_stated", "topic", "_note")


def url_of(it):
    for s in it.get("sources", []):
        if s.get("url"):
            return s["url"]
    return ""


def main():
    if not os.path.isfile(FEED):
        print("no feed_items.json; run fetch_feeds.py first"); return
    store = json.load(open(STORE, encoding="utf-8")) if os.path.isfile(STORE) else {}
    d = json.load(open(FEED, encoding="utf-8"))
    items = d.get("items", [])

    # 1) HARVEST: remember reviews present in the current feed
    harvested = 0
    for it in items:
        u = url_of(it)
        if u and it.get("reviewed"):
            store[u] = {k: it[k] for k in FIELDS if k in it}
            store[u]["reviewed"] = True
            harvested += 1

    # 2) APPLY: refill not-yet-reviewed items from the store
    applied = 0
    for it in items:
        u = url_of(it)
        if u in store and not it.get("reviewed"):
            it.update(store[u]); applied += 1

    json.dump(store, open(STORE, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    json.dump(d, open(FEED, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    still_new = sum(1 for it in items if not it.get("reviewed"))
    print(f"carry_reviews: harvested {harvested}, re-applied {applied} "
          f"({len(store)} remembered). {still_new} item(s) still need review.")


if __name__ == "__main__":
    main()
