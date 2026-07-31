#!/usr/bin/env python3
"""article_evidence.py - per-article facts that replace the retired claim_type judgement.

Computes four countable properties from the cached article text, links and figure spans.
Nothing here is a judgement and nothing calls a model: every count points at spans or URLs
the reader can check.

  attribution     who the article's claims are attributed to, and how many of those
                  attributions are to a party to the claim itself
  primary_links   does an article describing a filing/paper/docket link to one
  figure_source   of the extracted figures, how many name a source in the same sentence
  motive_tier     claim-relative, from stake_map.json: the publisher's relationship to the
                  ENTITY the claim is about, not its domain type alone

⚠️ `motive_tier` needs `stake_map.json` to be curated. An unlisted publisher keeps its
source-type tier and is marked `tier_basis: "source-type"`, never guessed.

  python3 article_evidence.py            # compute -> article_evidence.json
  python3 article_evidence.py --report   # summarise
  python3 article_evidence.py --check N  # print every span for item N, to audit by eye

Run after extract_spans.py, before build.py.
"""
import argparse
import json
import os
import re
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
FEED = os.path.join(HERE, "feed_items.json")
SPANS = os.path.join(HERE, "article_spans.json")
TEXTS = os.path.join(HERE, "article_text.json")
STAKES = os.path.join(HERE, "stake_map.json")
OUT = os.path.join(HERE, "article_evidence.json")

# Domains whose documents are the record itself, not reporting about it.
PRIMARY_DOMAINS = (
    "sec.gov", "federalregister.gov", "regulations.gov", "ftc.gov", "justice.gov",
    "courtlistener.com", "supremecourt.gov", "uspto.gov", "nist.gov", "gao.gov",
    "gov.uk", "legislation.gov.uk", "ofgem.gov.uk", "parliament.uk",
    "europa.eu", "eur-lex.europa.eu", "arxiv.org", "doi.org", "zenodo.org",
    "nasa.gov", "bls.gov", "federalreserve.gov", "imf.org", "oecd.org", "iea.org",
)

ATTRIB = re.compile(
    r"\b(?:said|says|told|according to|confirmed|announced|wrote|claimed|"
    r"estimates?|reported|argues?|added|noted)\b", re.I)
# An attribution with no named human or organisation behind it.
UNNAMED = re.compile(
    r"\b(?:sources?|people familiar|insiders?|a person|someone|reports?|it is understood|"
    r"rumou?rs?|leaks?)\b", re.I)
SPOKES = re.compile(r"\b(?:a )?spokes(?:person|man|woman)\b", re.I)


def load(p, default=None):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else (default or {})


def url_of(it):
    for s in it.get("sources", []):
        if s.get("url", "").startswith("http"):
            return s["url"]
    return ""


# Reuse the sentence splitter from extract_spans. Splitting on newlines here made every
# "sentence" a whole paragraph, so "the subject is named in this sentence" silently became
# "somewhere in this paragraph".
from extract_spans import sentences as sentences_of  # noqa: E402


# An entity value the tier and attribution logic must refuse to act on. Garbage in this
# field produces a confident tier on a subject that does not exist.
BAD_ENTITY = re.compile(
    r"^(none|null|n/?a|unknown|researchers?|scientists?|artists?|experts?|users?|"
    r"ai (?:startups?|researchers?|companies|industry)|startups?|the )\.?$", re.I)


def usable_entity(e):
    if not e or len(e) < 2 or BAD_ENTITY.match(e.strip()):
        return False
    return "." not in e or e.count(" ") > 0     # a bare domain is not an entity


def entity_aliases(entity, stakes):
    """Surface forms to look for when asking 'is the subject named in this sentence'."""
    if not entity:
        return []
    al = {entity, entity.split()[0]}
    al |= set(stakes.get("aliases", {}).get(entity, []))
    return [a for a in al if len(a) > 2]


def attribution(text, entity, stakes):
    """Attribution sentences, split by whether the subject of the claim is the source."""
    al = entity_aliases(entity, stakes)
    party, other, unnamed = [], [], []
    for sent, off in sentences_of(text):
        if not ATTRIB.search(sent) or len(sent) < 30:
            continue
        rec = {"sentence": sent[:300], "offset": off}
        if UNNAMED.search(sent) and not any(a in sent for a in al):
            unnamed.append(rec)
        elif al and (any(a in sent for a in al) or SPOKES.search(sent)):
            party.append(rec)
        else:
            other.append(rec)
    return party, other, unnamed


def link_kinds(links, entity, stakes):
    own = stakes.get("entity_domains", {}).get(entity, [])
    kinds = {"primary": [], "subject_own": [], "other": []}
    for u in links:
        net = urllib.parse.urlsplit(u).netloc.replace("www.", "").lower()
        if any(net == d or net.endswith("." + d) for d in PRIMARY_DOMAINS):
            kinds["primary"].append(u)
        elif any(net == d or net.endswith("." + d) for d in own):
            kinds["subject_own"].append(u)
        else:
            kinds["other"].append(u)
    return kinds


def claim_relative_tier(item, entity, stakes):
    """(tier, basis). Falls back to the source-type tier when the publisher is unlisted."""
    src = (item.get("sources") or [{}])[0]
    base = src.get("motive_tier", 3)
    net = urllib.parse.urlsplit(src.get("url", "")).netloc.replace("www.", "").lower()
    owners = stakes.get("publisher_owner", {})
    owner = next((o for d, o in owners.items() if net == d or net.endswith("." + d)), None)
    if owner is None:
        return base, "source-type"
    if entity and owner.lower() == entity.lower():
        return 5, f"publisher is the subject ({owner})"
    held = stakes.get("stakes", {}).get(owner, [])
    if entity and any(entity.lower() == h.lower() for h in held):
        return 4, f"publisher owner {owner} holds a stake in {entity}"
    return base, f"publisher owner {owner}, no recorded stake in {entity or 'the subject'}"


def canon(u):
    return u.rstrip("/").split("?")[0].replace("https://www.", "https://")


def story_chains(items, texts):
    """{url: {"cites": [...], "cited_by": [...]}} from one article linking to another.

    ⛔ An edge means A LINKS TO B. It does not mean A restates B, and the board must not say
    so. Absence of an edge says nothing either: a paywalled or link-averse outlet produces
    no edge whether or not it is reporting someone else's claim.

    Text similarity was measured and rejected: on 44 items, shared headline words found 1
    pair and shared outbound links 11 mostly incidental ones, while citation edges found 7,
    5 of them across tiers. A link is also checkable by clicking it.
    """
    url_of_item = {}
    for it in items:
        u = next((s["url"] for s in it.get("sources", []) if s.get("url")), "")
        if u:
            url_of_item[canon(u)] = it
    chains = {u: {"cites": [], "cited_by": []} for u in url_of_item}
    for u, it in url_of_item.items():
        links = {canon(x) for x in (texts.get(
            next(s["url"] for s in it["sources"] if s.get("url"))) or {}).get("links", [])}
        for other in links & set(url_of_item):
            if other == u:
                continue
            tgt = url_of_item[other]
            chains[u]["cites"].append({
                "url": other, "name": tgt["sources"][0].get("name", ""),
                "tier": int(tgt["sources"][0].get("motive_tier", 3)),
                "entity": tgt.get("entity", ""), "headline": tgt.get("headline", "")})
            chains[other]["cited_by"].append({
                "url": u, "name": it["sources"][0].get("name", ""),
                "tier": int(it["sources"][0].get("motive_tier", 3)),
                "entity": it.get("entity", ""), "headline": it.get("headline", "")})
    return chains


def compute():
    items = load(FEED, {"items": []})["items"]
    spans, texts, stakes = load(SPANS), load(TEXTS), load(STAKES)
    chains = story_chains(items, texts)
    out = {}
    for it in items:
        u = url_of(it)
        rec, txt = spans.get(u) or {}, texts.get(u) or {}
        entity = it.get("entity", "")
        if not usable_entity(entity):
            entity = ""          # measures that need a subject report "unknown", not a guess
        body = txt.get("text", "")
        party, other, unnamed = attribution(body, entity, stakes)
        kinds = link_kinds(txt.get("links", []), entity, stakes)
        figs = rec.get("spans", [])
        attributed = [s for s in figs if ATTRIB.search(s["sentence"])]
        tier, basis = claim_relative_tier(it, entity, stakes)
        out[u] = {
            "headline": it.get("headline", ""),
            "entity": entity,
            "entity_usable": bool(entity),
            "fetched": txt.get("status") == "ok",
            "attribution": {
                "to_subject": len(party), "to_others": len(other),
                "unnamed": len(unnamed),
                "spans": {"to_subject": party[:6], "to_others": other[:6],
                          "unnamed": unnamed[:6]},
            },
            "links": {k: len(v) for k, v in kinds.items()},
            "primary_link_examples": kinds["primary"][:4],
            "figures": {"total": len(figs), "with_named_source": len(attributed)},
            "motive_tier": tier, "tier_basis": basis,
            "chain": chains.get(canon(u), {"cites": [], "cited_by": []}),
        }
    json.dump(out, open(OUT, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return out


def report(ev):
    ok = [v for v in ev.values() if v["fetched"]]
    print(f"articles: {len(ok)}/{len(ev)} fetched")
    # ⚠️ The subject/other split is only meaningful where the entity is usable. Reporting it
    # over all items would divide by a denominator that includes items with no subject.
    sub = [v for v in ok if v.get("entity_usable")]
    print(f"usable entity: {len(sub)}/{len(ok)}  "
          f"(the subject/other split below is over these only)\n")
    onlyself = [v for v in sub if v["attribution"]["to_subject"] and
                not v["attribution"]["to_others"]]
    noattrib = [v for v in ok if not any(v["attribution"][k]
                                         for k in ("to_subject", "to_others", "unnamed"))]
    print("ATTRIBUTION")
    print(f"  every attribution is to the subject of the claim: {len(onlyself)}/{len(sub)}")
    print(f"  no attributed statement found at all:             {len(noattrib)}/{len(ok)}")
    print(f"  articles citing unnamed sources:                  "
          f"{sum(1 for v in ok if v['attribution']['unnamed'])}/{len(ok)}")
    print("\nPRIMARY LINKS")
    withp = [v for v in ok if v["links"]["primary"]]
    print(f"  link to at least one primary document:            {len(withp)}/{len(ok)}")
    print(f"  link to the subject's own site:                   "
          f"{sum(1 for v in ok if v['links']['subject_own'])}/{len(ok)}")
    print("\nFIGURES")
    f = [v for v in ok if v["figures"]["total"]]
    tot = sum(v["figures"]["total"] for v in f)
    att = sum(v["figures"]["with_named_source"] for v in f)
    print(f"  figures: {tot}, of which {att} name a source in the same sentence "
          f"({100*att/tot:.0f}%)" if tot else "  no figures")
    ch = [v for v in ok if v.get("chain", {}).get("cites") or v.get("chain", {}).get("cited_by")]
    cross = [v for v in ok for c in v.get("chain", {}).get("cites", [])
             if c["tier"] != v["motive_tier"]]
    print("\nSTORY CHAINS")
    print(f"  items in a citation chain:                        {len(ch)}/{len(ok)}")
    print(f"  citations that cross a tier:                      {len(cross)}")
    print("\nMOTIVE TIER")
    bas = {}
    for v in ok:
        bas[v["tier_basis"].split("(")[0].strip()] = bas.get(
            v["tier_basis"].split("(")[0].strip(), 0) + 1
    for k, n in sorted(bas.items(), key=lambda t: -t[1]):
        print(f"  {n:3d}  {k}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--check", type=int, default=-1, help="print all spans for item N")
    a = ap.parse_args()
    ev = load(OUT) if (a.report or a.check >= 0) and os.path.exists(OUT) else compute()
    if a.check >= 0:
        v = list(ev.values())[a.check]
        print(f"{v['headline']}\n  entity: {v['entity']}  tier {v['motive_tier']} "
              f"({v['tier_basis']})")
        for k, sp in v["attribution"]["spans"].items():
            for s in sp:
                print(f"  [{k}] @{s['offset']}: {s['sentence'][:150]}")
        for u in v["primary_link_examples"]:
            print(f"  [primary link] {u}")
        return
    if a.report:
        return report(ev)
    report(ev)
    print(f"\nwritten: {OUT}")


if __name__ == "__main__":
    main()
