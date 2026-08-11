#!/usr/bin/env python3
"""suggest_register_rows.py (stdlib only) - direction two of the pipeline.

The board pulls feeds most days. The private tracker is worked in sessions. Left alone the
fast store fills with material the slow store never sees. This closes that gap without
letting either store write to the other.

⛔ IT NOMINATES. IT DOES NOT DECIDE, AND IT MUST NEVER WRITE TO THE TRACKER.
A §DR or §RC row is a judgement. This emits candidates into a dated markdown file that a
human reads and acts on, or ignores. It touches no register, no tracker and no page.

⛔ IT MUST NEVER PROPOSE THE CORRECTED FIGURE. The deflation is the call. A model emitting
both an error and its correction is the cascade trap in a format that looks audited: the
reviewer would be judging a paraphrase of a source neither of them checked. Every line below
is either a verbatim span or a label the board already carries.

WHAT QUALIFIES, AND WHY THOSE RULES
-----------------------------------
  §DR candidate   a verbatim figure span from source class 4 or 5, on an item whose
                  denominator_stated is N. That is a quantitative claim from a tool vendor,
                  vendor publication or press office with no stated base. Nothing is asserted
                  about whether the figure is wrong.

  §RC candidate   a sentence naming a future date AND a scheduled event (expiry, deadline,
                  effective date, auction, hearing, ruling). §RC rows are dated moments when
                  a question resolves.

⛔ THE §RC SCREEN CANNOT READ article_spans.json, AND THIS IS BY CONSTRUCTION, NOT A BUG.
Spans are sentences containing a FIGURE, and extract_spans.py deliberately filters dates out
of its figure set because most digits in an article are dates and version numbers. A sentence
like "the consultation closes on 16 September" usually carries no other number, so it never
becomes a span. Measured 2026-07-31 over the whole span store: 46 spans matched a date
pattern, 2 contained a scheduled-event word, and 0 contained both.

⇒ the §RC screen reads article_text.json, the local fetch cache, instead. That file is
gitignored because it holds third-party article bodies in full, so this screen only works on
a machine that has run extract_spans.py. If the cache is absent the screen reports that it
skipped, rather than silently returning nothing.

⚠️ The output states the denominator evidence method and coverage. A deterministic label
and a local-model label are not the same evidence.

    python3 suggest_register_rows.py            # print candidates
    python3 suggest_register_rows.py --write    # also write register_candidates_<date>.md
    python3 suggest_register_rows.py --days 14  # only items seen in the last N days
"""
import argparse
import datetime as dt
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
FEED = os.path.join(HERE, "feed_items.json")
SPANS = os.path.join(HERE, "article_spans.json")
TEXT = os.path.join(HERE, "article_text.json")   # gitignored fetch cache, local only

# A sentence, roughly. Good enough to quote from; the URL is always given alongside.
SENTENCE = re.compile(r"(?<=[.!?])\s+")

# Source classes where a quantitative claim is worth a second look.
HIGH_STAKE_SOURCE_CLASSES = (4, 5)

MONTHS = ("January|February|March|April|May|June|July|August|September|October|November|"
          "December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec")
DATED = re.compile(rf"\b(?:{MONTHS})\b\s+\d{{1,2}}(?:,)?\s+(20\d\d)|"
                   rf"\b\d{{1,2}}\s+(?:{MONTHS})\b\s+(20\d\d)|"
                   rf"\b(?:by|before|from|in|until|through|starting)\s+(20\d\d)\b|"
                   rf"\bQ[1-4]\s+(20\d\d)\b", re.I)
SCHEDULED = re.compile(r"\b(expir\w+|deadline|effective date|takes? effect|comes? into force|"
                       r"auction|hearing|ruling|verdict|comment period|consultation closes|"
                       r"moratorium|sunset|lock-?up|due to report|scheduled for)\b", re.I)


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def items_of(feed):
    return feed if isinstance(feed, list) else feed.get("items", [])


def primary_source(it):
    """URL and source tier live in the item's `sources` list, not at the top level.

    ⚠️ An item can carry several sources. The first is the one the board renders and the one
    article_spans.json is keyed on, so it is the one a candidate must quote.
    """
    src = (it.get("sources") or [{}])[0]
    return src.get("url", ""), src.get("name", ""), src.get("source_tier")


def seen_date(it):
    """Feed dates are RFC-822 ("Fri, 31 Jul 2026"), not ISO.

    Returns None when the date will not parse, and the caller keeps the item. A date filter
    that silently drops what it cannot read would hide new items rather than old ones.
    """
    raw = (it.get("date") or "").strip()
    for fmt in ("%a, %d %b %Y", "%d %b %Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def future_years(now):
    return {str(now.year), str(now.year + 1), str(now.year + 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="write the dated candidates file")
    ap.add_argument("--days", type=int, default=30, help="only items seen in the last N days")
    args = ap.parse_args()

    now = dt.date.today()
    cutoff = now - dt.timedelta(days=args.days)
    spans = load(SPANS)
    texts = load(TEXT) if os.path.isfile(TEXT) else {}
    dr, rc = [], []
    years = future_years(now)

    for it in items_of(load(FEED)):
        url, name, tier = primary_source(it)
        rec = spans.get(url)
        if not rec or not rec.get("spans"):
            continue
        seen = seen_date(it)
        if seen and seen < cutoff:
            continue
        common = {"headline": it.get("headline", ""), "url": url,
                  "source": name or rec.get("source", ""), "tier": tier,
                  "entity": it.get("entity", ""),
                  "date": seen.isoformat() if seen else "",
                  "evidence_method": it.get("evidence_method", "unassessed"),
                  "evidence_coverage": it.get("evidence_coverage") or {},
                  "label_evidence": it.get("label_evidence", "")}

        if tier in HIGH_STAKE_SOURCE_CLASSES and it.get("denominator_stated") == "N":
            for sp in rec["spans"][:3]:
                dr.append(dict(common, span=sp["sentence"], figures=sp.get("figures", [])))

        body = (texts.get(url) or {}).get("text") or ""
        for sent in SENTENCE.split(body):
            sent = " ".join(sent.split())
            if len(sent) > 400 or not SCHEDULED.search(sent):
                continue
            m = DATED.search(sent)
            hit_year = next((g for g in (m.groups() if m else ()) if g), None)
            if hit_year in years:
                rc.append(dict(common, span=sent))
                break

    def block(title, rows, note):
        out = [f"## {title} ({len(rows)})", "", note, ""]
        for r in rows:
            coverage = r.get("evidence_coverage") or {}
            prov = (f"{r.get('evidence_method', 'unassessed')} label, "
                    f"{coverage.get('seen', 0)}/{coverage.get('total', 0)} spans"
                    + (f", {r['label_evidence']}" if r.get("label_evidence") else ""))
            out += [f"- **{r['headline']}**",
                    f"  - span: \"{r['span'].strip()}\"",
                    f"  - source: {r['source']} (source class {r['tier']}) · {prov}",
                    f"  - {r['url']}", ""]
        return "\n".join(out)

    doc = "\n".join([
        f"# Register candidates, {now.isoformat()}",
        "",
        "Nominations only. Nothing here is a register row, a correction or a decision.",
        "Each line is either a verbatim span from the article or a label the board already",
        "carries. Copy what is worth having into the tracker by hand, and write the",
        "correction yourself: this file deliberately does not propose one.",
        "",
        block("Deflation register candidates", dr,
              "A figure from a source with an incentive, with no stated base. That makes it "
              "worth checking. It does not make it wrong."),
        block("Resolution calendar candidates", rc,
              "A sentence naming a future date and a scheduled event. The observable still has "
              "to be written by hand: a date is not a question."
              if texts else
              "SKIPPED: article_text.json is absent. This screen reads the local fetch cache, "
              "not the spans, because span sentences must contain a figure and a scheduled "
              "date rarely comes with one. Run extract_spans.py first."),
    ])
    print(doc)
    if args.write:
        out = os.path.join(HERE, f"register_candidates_{now.isoformat()}.md")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(doc)
        print(f"\nwritten: {out}")


if __name__ == "__main__":
    main()
