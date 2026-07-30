#!/usr/bin/env python3
"""archive.py (stdlib only) - permanent record of every item ever fetched, plus the
revisit queue that scores announcements against what actually happened.

WHY THIS EXISTS
---------------
The board's lens is announced-versus-delivered, but until now it could only ever show the
announcement. Items rolled off: measured 2026-07-30 over the git history of feed_items.json,
121 unique URLs were captured across 18 days and each fetch replaced the last, so nothing
could be asked again later. The archive keeps them; the queue asks the second question.

WHAT IS AUTOMATED AND WHAT IS NOT
---------------------------------
Automated: capture, the due date, the ranking, the cap. Not automated: `outcome`. Whether a
thing was delivered is the call, and a model must not make it. Rule: automate the plumbing,
never the call.

THE CAP IS THE DESIGN, NOT A LIMITATION
---------------------------------------
Intake runs ~6.7 new items/day (~200/month). An exhaustive queue would put 100+ items in
front of a human every 90 days, which nobody sustains, and an abandoned ledger is worse than
none because its gaps look like findings. So `--due` returns a RANKED, CAPPED slice: the
default 5 is about 20 items a month. Everything else stays archived and searchable and never
asks for attention.

RANKING SIGNALS, all computable, no judgement:
    stated figure or date in the headline   a claim with a number is checkable later
    claim_type == target                    carries its own deadline
    motive_tier == 5                        the party selling the thing said it
    has a reality anchor                    the portfolio already holds a base rate

OUTCOME VOCABULARY (set by hand, in archive.json):
    delivered | partial | not_delivered | abandoned | unresolvable
`unresolvable` is load-bearing and will be the most common. Report it as the headline, never
bury it: a ledger that only records resolvable cases is a flattering selection, not a record.

⚠️ COVERAGE IS NOT A SAMPLE. Six feeds capped at six items each is an editorial slice. This
ledger describes what this board saw. It does not describe the industry, and any published
figure from it must say so.

Run:
    python3 archive.py              # capture current feed into archive.json
    python3 archive.py --due        # print the revisit queue (default 5)
    python3 archive.py --due -n 10  # a longer sitting
    python3 archive.py --stats      # coverage and outcome counts
"""
import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
FEED = os.path.join(HERE, "feed_items.json")
ARCHIVE = os.path.join(HERE, "archive.json")

# Days before a claim is asked again. A measurement has already happened, so it is never
# queued; an assertion has no event to check.
HORIZON = {"announced": 90, "target": 180, "prediction": 180}
REVISITABLE = set(HORIZON)
OUTCOMES = ("delivered", "partial", "not_delivered", "abandoned", "unresolvable")

FIGURE = re.compile(r"\b(\d[\d,.]*\s*(%|percent|bn|billion|m|million|k|gw|mw|twh|tokens?)|"
                    r"\$\d|£\d|€\d|20\d\d|by \d{4})\b", re.I)


def now():
    return datetime.now(timezone.utc)


def today():
    return now().strftime("%Y-%m-%d")


def url_of(it):
    for s in it.get("sources", []):
        if s.get("url"):
            return s["url"]
    return ""


def load(path, default):
    if not os.path.isfile(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def claim_date(it):
    """The date the CLAIM was published, for the revisit clock.

    ⛔ Do NOT use the capture date for the horizon. The clock has to run from when the claim
    was made, not from when this board started recording; otherwise every item already in
    the feed on the day the archive was created gets its deadline pushed out by however long
    the archive happened to be late. Falls back to capture date when the feed date does not
    parse.
    """
    try:
        from fetch_feeds import item_date
        d = item_date(it.get("date", ""))
        if d:
            return d.strftime("%Y-%m-%d")
    except Exception:
        pass
    return today()


def capture():
    """Fold the current feed into the archive. Never overwrites a human outcome."""
    feed = load(FEED, {"items": []})
    arc = load(ARCHIVE, {})
    added = updated = 0
    for it in feed.get("items", []):
        u = url_of(it)
        if not u:
            continue
        tiers = [int(s["motive_tier"]) for s in it.get("sources", []) if s.get("motive_tier")]
        row = {
            "headline": it.get("headline", ""),
            "entity": it.get("entity", ""),
            "date": it.get("date", ""),
            "claim_type": it.get("claim_type", "unclassified"),
            "denominator_stated": it.get("denominator_stated", "?"),
            "topic": it.get("topic", ""),
            "min_tier": min(tiers) if tiers else None,
            "max_tier": max(tiers) if tiers else None,
            "reviewed": bool(it.get("reviewed")),
            "auto_labelled": bool(it.get("auto_labelled")),
            "source": (it.get("sources") or [{}])[0].get("name", ""),
            "last_seen": today(),
        }
        if u in arc:
            # ⛔ Preserve everything a human set. Re-capture refreshes the observed fields
            # only; outcome, outcome_note and first_seen are never touched here.
            keep = {k: arc[u][k] for k in ("first_seen", "outcome", "outcome_note",
                                           "outcome_date") if k in arc[u]}
            if arc[u].get("reviewed") and not row["reviewed"]:
                row["reviewed"] = True
                for f in ("claim_type", "denominator_stated", "topic", "entity"):
                    row[f] = arc[u].get(f, row[f])
            arc[u].update(row)
            arc[u].update(keep)
            updated += 1
        else:
            row["first_seen"] = claim_date(it)
            row["captured"] = today()
            row["outcome"] = ""
            row["outcome_note"] = ""
            row["outcome_date"] = ""
            arc[u] = row
            added += 1
    with open(ARCHIVE, "w", encoding="utf-8") as fh:
        json.dump(arc, fh, indent=1, ensure_ascii=False, sort_keys=True)
    print(f"archive: {added} new, {updated} refreshed, {len(arc)} total -> {ARCHIVE}")


def score(row):
    """Revisit-worthiness. Computable only; nothing here is a judgement about truth."""
    s = 0
    if FIGURE.search(row.get("headline", "")):
        s += 3
    if row.get("claim_type") == "target":
        s += 2
    if row.get("max_tier") == 5:
        s += 2
    if row.get("topic"):
        s += 2
    if row.get("reviewed"):
        s += 1
    return s


def due_rows(arc):
    out = []
    n = now()
    for u, r in arc.items():
        if r.get("outcome"):
            continue
        ct = r.get("claim_type", "")
        if ct not in REVISITABLE:
            continue
        try:
            seen = datetime.strptime(r.get("first_seen", ""), "%Y-%m-%d").replace(
                tzinfo=timezone.utc)
        except ValueError:
            continue
        if n - seen < timedelta(days=HORIZON[ct]):
            continue
        out.append((score(r), u, r, (n - seen).days))
    out.sort(key=lambda x: (-x[0], x[3]))
    return out


def show_due(limit):
    arc = load(ARCHIVE, {})
    rows = due_rows(arc)
    if not rows:
        pend = sum(1 for r in arc.values()
                   if r.get("claim_type") in REVISITABLE and not r.get("outcome"))
        print(f"nothing due yet. {len(arc)} archived, {pend} revisitable claim(s) still "
              f"inside their horizon (announced 90d, target/prediction 180d).")
        return
    print(f"{len(rows)} due; showing top {min(limit, len(rows))} by revisit-worthiness.\n"
          f"Set outcome in archive.json: {' | '.join(OUTCOMES)}\n")
    for sc, u, r, age in rows[:limit]:
        print(f"[{sc:>2}] {age:>4}d  {r.get('entity') or 'entity not identified'} "
              f"({r.get('claim_type')}, tier {r.get('max_tier')})")
        print(f"        {r.get('headline','')[:96]}")
        print(f"        {u}\n")
    if len(rows) > limit:
        print(f"{len(rows) - limit} more held back. The cap is deliberate: an abandoned "
              f"ledger is worse than none, because its gaps read as findings.")


def show_stats():
    arc = load(ARCHIVE, {})
    if not arc:
        print("archive is empty; run: python3 archive.py")
        return
    ct = {}
    oc = {}
    for r in arc.values():
        ct[r.get("claim_type", "?")] = ct.get(r.get("claim_type", "?"), 0) + 1
        k = r.get("outcome") or "(not scored)"
        oc[k] = oc.get(k, 0) + 1
    firsts = sorted(r.get("first_seen", "") for r in arc.values() if r.get("first_seen"))
    print(f"archived: {len(arc)} items, first seen {firsts[0] if firsts else '?'} "
          f"to {firsts[-1] if firsts else '?'}")
    print("\nclaim types:")
    for k, v in sorted(ct.items(), key=lambda kv: -kv[1]):
        print(f"  {k:14} {v:>5}")
    print("\noutcomes:")
    for k, v in sorted(oc.items(), key=lambda kv: -kv[1]):
        print(f"  {k:14} {v:>5}")
    scored = sum(v for k, v in oc.items() if k != "(not scored)")
    if scored:
        unres = oc.get("unresolvable", 0)
        print(f"\nscored {scored}, of which unresolvable {unres} "
              f"({unres/scored:.0%}). Report that share as the headline, not a footnote.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--due", action="store_true", help="print the revisit queue")
    ap.add_argument("-n", type=int, default=5, help="how many due items to show (default 5)")
    ap.add_argument("--stats", action="store_true", help="coverage and outcome counts")
    a = ap.parse_args()
    if a.due:
        show_due(a.n)
    elif a.stats:
        show_stats()
    else:
        capture()


if __name__ == "__main__":
    main()
