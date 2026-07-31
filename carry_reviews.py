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
FIELDS = ("entity", "entity_basis", "entity_source", "claim_type",
          "denominator_stated", "topic", "_note")
# Machine passes carry their own trail. Kept separate from FIELDS so a machine entry
# can never be mistaken for a human one on read-back.
MACHINE_FIELDS = FIELDS + ("auto_labelled", "auto_labelled_by", "crosscheck",
                           # Carry the tier and its evidence with the label. Without these a
                           # carried item shows a denominator while the page reports that
                           # none was derived, and label_items.py re-runs work already done.
                           "label_tier", "label_evidence")


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

    # 1) HARVEST both human reviews and machine labels.
    # Machine labels MUST be harvested here. autolabel.py never sets reviewed=True, so a
    # harvest gated on reviewed alone drops them and the next fetch_feeds.py destroys the
    # whole auto-label pass (happened 2026-07-29: a four-reader cross-check over 35 items
    # was lost and the board shipped with every card unlabelled).
    harvested = harvested_machine = 0
    for it in items:
        u = url_of(it)
        if not u:
            continue
        if it.get("reviewed"):
            # ⛔ reviewed=True does NOT establish who labelled the item. label_source was
            # added 2026-07-30; the 30 entries written on 2026-07-13 carry no provenance,
            # and assigning "human" here retroactively promoted them to ground truth on
            # evidence the file does not hold. Keep an existing source, otherwise record
            # "unattributed". Only an explicit human review may write "human".
            prior = store.get(u, {}).get("label_source")
            store[u] = {k: it[k] for k in FIELDS if k in it}
            store[u]["reviewed"] = True
            store[u]["label_source"] = prior or it.get("label_source") or "unattributed"
            harvested += 1
        elif it.get("auto_labelled"):
            # ⛔ Never downgrade: a hand-set entry outranks a machine pass over the same URL.
            # "unattributed" is protected too. Its provenance is unknown, which is not the
            # same as being machine output, and overwriting it would destroy the only
            # article-level labels the board has.
            if store.get(u, {}).get("label_source") in ("human", "unattributed"):
                continue
            store[u] = {k: it[k] for k in MACHINE_FIELDS if k in it}
            store[u]["reviewed"] = False
            store[u]["label_source"] = "machine"
            harvested_machine += 1

    # 2) APPLY: refill not-yet-reviewed items from the store.
    # reviewed stays whatever the store says, so a machine label comes back still flagged
    # unreviewed and the board keeps showing "auto-tagged, unreviewed" on it.
    applied = applied_machine = 0
    for it in items:
        u = url_of(it)
        if u in store and not it.get("reviewed"):
            it.update(store[u])
            if store[u].get("label_source") == "machine":
                applied_machine += 1
            else:
                applied += 1

    json.dump(store, open(STORE, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    json.dump(d, open(FEED, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    still_new = sum(1 for it in items
                    if not it.get("reviewed") and not it.get("auto_labelled"))
    print(f"carry_reviews: harvested {harvested} human + {harvested_machine} machine, "
          f"re-applied {applied} human + {applied_machine} machine "
          f"({len(store)} remembered). {still_new} item(s) have no label at all.")


if __name__ == "__main__":
    main()
