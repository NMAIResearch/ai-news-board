#!/usr/bin/env python3
"""
AnchorAI - fetch_scholar.py (stdlib only).

Pulls the latest primary scholarship and public datasets so the board can point
readers to the primary literature rather than second-hand coverage of it. Papers come
from the arXiv API (cs.AI, cs.LG); datasets from the Hugging Face API. Writes
scholar_items.json. Network required; a source that fails is skipped.

NEUTRALITY (decided 2026-07-12): this deliberately queries arXiv by BROAD category,
not through watch_routine.py / watchlist.md. That personal watchlist is interest-
filtered and correct for private lead-hunting, but it would bias which papers a
PUBLIC board surfaces. A broad category pull keeps the scholarship section neutral.
This is the chosen source, not a placeholder for the private pipeline.

Run:  python3 fetch_scholar.py    # then re-run build.py
"""
import json, os, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "scholar_items.json")
ARXIV = ("http://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.LG"
         "&sortBy=submittedDate&sortOrder=descending&max_results=8")
HFDATA = "https://huggingface.co/api/datasets?sort=downloads&direction=-1&limit=8"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (NM AI Research board)"})
    return urllib.request.urlopen(req, timeout=25).read()


def papers():
    out = []
    try:
        root = ET.fromstring(get(ARXIV))
    except Exception as e:
        print("arxiv skip:", e); return out
    ns = "{http://www.w3.org/2005/Atom}"
    for e in root.iter(ns + "entry"):
        title = " ".join((e.findtext(ns + "title") or "").split())
        link = ""
        for l in e.iter(ns + "link"):
            if l.get("rel") == "alternate":
                link = l.get("href")
        authors = [a.findtext(ns + "name") for a in e.iter(ns + "author")]
        authors = [a for a in authors if a]
        by = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")
        out.append({"kind": "paper", "title": title, "url": link, "authors": by,
                    "date": (e.findtext(ns + "published") or "")[:10], "venue": "arXiv"})
    return out


def datasets():
    out = []
    try:
        data = json.loads(get(HFDATA))
    except Exception as e:
        print("hf skip:", e); return out
    for d in data[:8]:
        did = d.get("id", "")
        out.append({"kind": "dataset", "title": did,
                    "url": f"https://huggingface.co/datasets/{did}",
                    "authors": did.split("/")[0] if "/" in did else "",
                    "date": (d.get("lastModified", "") or "")[:10], "venue": "Hugging Face"})
    return out


def main():
    items = papers() + datasets()
    json.dump({"fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
               "items": items}, open(OUT, "w", encoding="utf-8"), indent=1)
    print(f"written: {OUT}  ({len(items)} items). Now run: python3 build.py")


if __name__ == "__main__":
    main()
