#!/usr/bin/env python3
"""
AnchorAI - apply_ratings.py (stdlib only). SEPARATE adapter.

Reads the canonical source ratings (a local ratings file, the same file
watch_routine.py uses) and annotates feed_items.json with a reliability mark. It
reuses his TRUSTED / CAUTION / BLOCKED judgements WITHOUT touching watch_routine.py
and WITHOUT importing his interest watchlist, so the board's topic intake stays
neutral (broad AI news in) while gaining his source-quality axis.

Reliability (track record) is a SECOND axis, orthogonal to motive_tier (incentive):
the two are kept separate so a source's past accuracy is not confused with its
incentive on a given claim. Blocked sources are dropped;
trusted get a star, caution get a warning plus the note. Matches on source name +
URL (domain/author), never on the headline, so an article that merely mentions a
blocked name is not dropped.

Run order:  fetch_feeds.py  ->  apply_ratings.py  ->  build.py
"""
import json, os
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
FEED = os.path.join(HERE, "feed_items.json")
SOURCES = Path.home() / "Desktop" / "Scripts" / "sources.md"


def read_sources(p):
    r = {"trusted": [], "caution": [], "blocked": []}
    cur = None
    if not p.exists():
        return r
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        u = s.upper()
        if u.startswith("## TRUSTED"): cur = "trusted"
        elif u.startswith("## CAUTION"): cur = "caution"
        elif u.startswith("## BLOCKED"): cur = "blocked"
        elif s.startswith("- ") and not s.startswith("- <") and cur:
            m, _, note = s[2:].partition("::")
            m = m.strip().lower()
            if m:
                r[cur].append((m, note.strip()))
    return r


def rate(hay, src):
    for m, _ in src["blocked"]:
        if m in hay: return "blocked", ""
    for m, note in src["caution"]:
        if m in hay: return "caution", note
    for m, _ in src["trusted"]:
        if m in hay: return "trusted", ""
    return "ok", ""


def main():
    if not os.path.isfile(FEED):
        print("no feed_items.json; run fetch_feeds.py first"); return
    src = read_sources(SOURCES)
    d = json.load(open(FEED, encoding="utf-8"))
    kept, dropped = [], 0
    for it in d.get("items", []):
        hay = " ".join([s.get("name", "") for s in it["sources"]]
                       + [s.get("url", "") for s in it["sources"]]).lower()
        verdict, note = rate(hay, src)
        if verdict == "blocked":
            dropped += 1
            continue
        it["rating"] = verdict
        if note:
            it["rating_note"] = note
        kept.append(it)
    d["items"] = kept
    d["rated_against"] = str(SOURCES)
    json.dump(d, open(FEED, "w", encoding="utf-8"), indent=1)
    star = sum(1 for i in kept if i.get("rating") == "trusted")
    caut = sum(1 for i in kept if i.get("rating") == "caution")
    print(f"rated {len(kept)} items against {SOURCES.name} "
          f"({dropped} blocked dropped, {star} trusted, {caut} caution). Now run build.py")


if __name__ == "__main__":
    main()
