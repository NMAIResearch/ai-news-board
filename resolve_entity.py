#!/usr/bin/env python3
"""resolve_entity.py - decide who a claim is ABOUT, deterministically, or leave it blank.

Replaces the model fill in label_items.py, which fabricated: 'None' x3, 'Researchers',
'AI startups', 'x.com', 'AI researcher', 'LLM Honeypot', 'Christian & Timbers' (a firm
quoted in the piece, not its subject).

Resolution order, first hit wins, and every result carries how it was reached:
  1 headline   an org in org_registry.json named in the headline, earliest position
  2 product    a product in the headline, mapped to whoever ships it
  3 tags       the publisher's own JSON-LD keywords, intersected with the registry
  4 site       the publisher's own site, when the headline names no other org
  5 (blank)    nothing resolved

⛔ Blank is a valid and common outcome. A piece about a labour market or a lawsuit trend
has no subject organisation, and the motive tier correctly falls back to source type.

  python3 resolve_entity.py            # write entity + entity_basis into feed_items.json
  python3 resolve_entity.py --dry-run  # print the table, write nothing
"""
import argparse
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
FEED = os.path.join(HERE, "feed_items.json")
TEXTS = os.path.join(HERE, "article_text.json")
REG = os.path.join(HERE, "org_registry.json")


def load(p, d=None):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else (d or {})


def url_of(it):
    for s in it.get("sources", []):
        if s.get("url", "").startswith("http"):
            return s["url"]
    return ""


def find_in(text, reg):
    """(position, canonical) for every registry surface form present in text."""
    hits = []
    for canon, forms in reg["orgs"].items():
        for f in forms:
            m = re.search(r"\b" + re.escape(f) + r"\b", text, re.I)
            if m:
                hits.append((m.start(), -len(f), canon))
    return hits


def resolve(it, texts, reg):
    head = it.get("headline", "")
    hits = find_in(head, reg)
    if hits:
        return min(hits)[2], "headline"

    for prod, owner in sorted(reg["products"].items(), key=lambda t: -len(t[0])):
        if re.search(r"\b" + re.escape(prod) + r"\b", head, re.I):
            return owner, f"product:{prod}"

    # Publisher tags resolve an entity ONLY when they name exactly one organisation.
    # The Verge emits alphabetical topic tags, so taking the first match returned Anthropic
    # for a piece on artists suing Anthropic, Google and OpenAI: an artefact of sort order.
    # Several tagged organisations means no single subject, which is a blank, not a pick.
    txt = texts.get(url_of(it)) or {}
    tagged = set()
    for tag in txt.get("publisher_tags", []):
        for canon, forms in reg["orgs"].items():
            if any(tag.strip().lower() == f.lower() for f in forms):
                tagged.add(canon)
    if len(tagged) == 1:
        return tagged.pop(), "tag"
    if len(tagged) > 1:
        return "", f"tags-name-{len(tagged)}-orgs"

    net = re.sub(r"^www\.", "", (url_of(it).split("/")[2:3] or [""])[0]).lower()
    for dom, org in reg["site_org"].items():
        if net == dom or net.endswith("." + dom):
            return org, ("site" if org else "site:no-subject")

    return "", "unresolved"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    data = load(FEED, {"items": []})
    texts, reg = load(TEXTS), load(REG)
    counts, resolved = {}, []
    for it in data["items"]:
        old = it.get("entity", "")
        ent, basis = resolve(it, texts, reg)
        resolved.append(ent)
        counts[basis.split(":")[0]] = counts.get(basis.split(":")[0], 0) + 1
        mark = " " if ent == old else ("+" if ent else "-")
        print(f" {mark} {(ent or '(blank)'):22s} {basis:18s} was {(old or '(blank)')[:20]:22s}"
              f" {it.get('headline','')[:44]}")
        if not a.dry_run:
            it["entity"] = ent
            it["entity_basis"] = basis

    print("\nby basis:", counts)
    filled = sum(1 for e in resolved if e)
    print(f"resolved {filled}/{len(resolved)}, blank {len(resolved) - filled}")
    if a.dry_run:
        print("dry run: nothing written")
        return
    json.dump(data, open(FEED, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"written: {FEED}")


if __name__ == "__main__":
    main()
