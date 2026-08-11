#!/usr/bin/env python3
"""label_items.py - denominator labels from complete verbatim figure-sentence sets.

Replaces autolabel.py's headline-only guess. Reads feed_items.json and article_spans.json;
answers what the spans settle deterministically and asks a model only for the rest.

  denominator_stated  rule where every span settles it, local model otherwise
  entity              NOT set here; resolve_entity.py owns it

⛔ claim_type is RETIRED (2026-07-31) and is neither set here nor rendered by build.py.

Every field carries `evidence_method`, `evidence_coverage`, `label_evidence`, the article
content hash, the extracted-evidence hash and the label schema version.

⛔ Never overwrites an item whose label_source is "human". reviewed stays False throughout:
the board keeps their machine provenance visible.

  python3 label_items.py               # deterministic + model for the remainder
  python3 label_items.py --rules-only  # no model call at all
  python3 label_items.py --dry-run     # decide and print, write nothing
  python3 label_items.py --report      # tier breakdown of the current labels

Run order: fetch_feeds -> carry_reviews -> extract_spans -> label_items -> build.
"""
import argparse
import collections
import json
import os
import time

from llm_client import DENOM, HOST, MODEL, NUM_CTX, NUM_PREDICT, call, parse_labels, retry_call

HERE = os.path.dirname(os.path.abspath(__file__))
FEED = os.path.join(HERE, "feed_items.json")
SPANS = os.path.join(HERE, "article_spans.json")

BATCH = int(os.environ.get("LABEL_BATCH", "4"))
LEAD_CHARS = 400          # opening of the article, for context on the figures
LABEL_SCHEMA_VERSION = 2
# Reserve the configured generation allowance and 2,000 tokens for framing. Three
# characters per token is conservative for this English and JSON task.
PROMPT_CHAR_BUDGET = int(os.environ.get(
    "LABEL_PROMPT_CHAR_BUDGET", str(max(12_000, (NUM_CTX - NUM_PREDICT - 2_000) * 3))))

DENOM_VALUES = {"Y", "partial", "N", "n/a"}

# ⛔ claim_type RETIRED 2026-07-31, his call. Two readers at full coverage over 38 items
# scored kappa 0.52 on headlines and 0.56 given the article opening plus figure spans, so
# article context did not fix it and no ground truth exists to score against. The model is
# now asked only what the spans could not settle.
INSTRUCT = (
    "You read AI-news items for a media-literacy board. Each item gives a HEADLINE, the "
    "article's OPENING, and FIGURE SENTENCES quoted verbatim from the article.\n"
    "denominator answers, for the FIGURE SENTENCES only: does the article say what its "
    "figures are out of?\n"
    "  Y = every figure states its base; partial = some do; N = none do; "
    "n/a = there are no figures.\n"
    "A base is what a figure is measured against: '40% OF USERS', '2,000 out of 90,000', "
    "'up from $1bn last year'. A plain amount with nothing to compare it to (a purchase "
    "price, a headcount, a number of actions) has no base, so answer N for it.\n"
    "⛔ Judge only the text shown. Do not use outside knowledge about the companies.\n"
    "Return ONLY a JSON array like "
    "[{\"i\":1,\"denominator\":\"N\"}]."
)


def tier1_denominator(rec):
    """(value, evidence, settled) from spans alone. settled=False means ask a model."""
    if rec is None or rec.get("fetch") != "ok":
        why = "no article" if rec is None else rec["fetch"]
        return None, f"article not fetched ({why})", False
    spans = rec["spans"]
    if not spans:
        return "n/a", f"no figure in {rec['n_chars']} chars of article text", True
    based = [s for s in spans if s["base_cue"]]
    if len(based) == len(spans):
        return "Y", f"all {len(spans)} figure-sentence(s) state a base", True
    # Absence of a regex cue is weak evidence. Any unsettled span sends the complete set to
    # the model, including spans where a cue was found, so the article-level aggregate is
    # never inferred from a sample.
    return None, f"{len(based)} of {len(spans)} figure-sentence(s) matched a base cue", False


def item_block(n, it, rec, lead):
    out = [f"{n}. HEADLINE: {it.get('headline','')}"]
    if lead:
        out.append(f"   OPENING: {lead[:LEAD_CHARS]}")
    spans = (rec or {}).get("spans", [])
    for s in spans:
        out.append(f"   FIGURE SENTENCE: {s['sentence']}")
    if not spans:
        out.append("   FIGURE SENTENCE: (none found in the article)")
    return "\n".join(out)


def current_machine_label(item, record):
    """True only when the label schema and article evidence hash both still match."""
    return bool(item.get("label_schema_version") == LABEL_SCHEMA_VERSION
                and item.get("evidence_method")
                and record and record.get("content_hash")
                and record.get("evidence_hash")
                and item.get("content_hash") == record.get("content_hash")
                and item.get("evidence_hash") == record.get("evidence_hash"))


def do_report(items):
    methods = collections.Counter(it.get("evidence_method", "unset") for it in items)
    dens = collections.Counter(it.get("denominator_stated") for it in items)

    print(f"items: {len(items)}")
    print(f"  evidence method: {dict(sorted(methods.items(), key=lambda t: str(t[0])))}")
    print(f"  denominator: {dict(dens)}")
    ev = [it for it in items if it.get("label_evidence")]
    print(f"  with evidence recorded: {len(ev)}/{len(items)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules-only", "--tier1-only", dest="rules_only", action="store_true",
                    help="no model call")
    ap.add_argument("--dry-run", action="store_true", help="decide and print, write nothing")
    ap.add_argument("--report", action="store_true", help="summarise current labels")
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--force", action="store_true", help="relabel machine-labelled items too")
    a = ap.parse_args()

    data = json.load(open(FEED))
    items = data["items"]
    if a.report:
        return do_report(items)

    spans = json.load(open(SPANS)) if os.path.exists(SPANS) else {}
    text = {}
    cache_path = os.path.join(HERE, "article_text.json")
    if os.path.exists(cache_path):
        text = json.load(open(cache_path))

    def url_of(it):
        for s in it.get("sources", []):
            if s.get("url", "").startswith("http"):
                return s["url"]
        return ""

    todo, settled, prompt_sizes = [], 0, {}
    for it in items:
        if it.get("label_source") == "human":
            continue
        rec = spans.get(url_of(it))
        if current_machine_label(it, rec) and not a.force:
            continue
        it.pop("label_tier", None)
        it.pop("auto_labelled_by", None)
        it.pop("review_stale", None)
        if rec is None or rec.get("fetch") != "ok":
            why = "no stored article" if rec is None else f"article not fetched ({rec['fetch']})"
            it["denominator_stated"] = "?"
            it["evidence_method"] = "unassessed"
            it["evidence_coverage"] = {"seen": 0, "total": 0}
            it["label_evidence"] = why
            it["content_hash"] = (rec or {}).get("content_hash", "")
            it["evidence_hash"] = (rec or {}).get("evidence_hash", "")
            it["label_schema_version"] = LABEL_SCHEMA_VERSION
            it["auto_labelled"] = True
            it["label_source"] = "deterministic"
            continue
        body = (text.get(url_of(it)) or {}).get("text", "")
        block_chars = len(item_block(1, it, rec, body[:LEAD_CHARS])) + 20
        if len(INSTRUCT) + block_chars > PROMPT_CHAR_BUDGET:
            total = len(rec.get("spans", []))
            it["denominator_stated"] = "?"
            it["evidence_method"] = "unassessed"
            it["evidence_coverage"] = {"seen": 0, "total": total}
            it["label_evidence"] = (
                f"complete figure evidence needs {len(INSTRUCT) + block_chars} prompt "
                f"characters, above the {PROMPT_CHAR_BUDGET}-character review budget")
            it["content_hash"] = rec.get("content_hash", "")
            it["evidence_hash"] = rec.get("evidence_hash", "")
            it["label_schema_version"] = LABEL_SCHEMA_VERSION
            it["auto_labelled"] = True
            it["label_source"] = "deterministic"
            continue
        val, why, ok = tier1_denominator(rec)
        if ok:
            it["denominator_stated"] = val
            it["evidence_method"] = "rule"
            it["evidence_coverage"] = {"seen": len(rec["spans"]), "total": len(rec["spans"])}
            it["label_evidence"] = why
            it["content_hash"] = rec.get("content_hash", "")
            it["evidence_hash"] = rec.get("evidence_hash", "")
            it["label_schema_version"] = LABEL_SCHEMA_VERSION
            it["auto_labelled"] = True
            it["label_source"] = "deterministic"
            settled += 1
        else:
            it["_pending"] = why
            prompt_sizes[id(it)] = block_chars
            # ⛔ Only unsettled items reach the model. Sending Tier 1 items too wasted 8 of
            # 20 calls on 2026-07-31 and stamped auto_labelled_by on 14 regex-derived
            # labels, so the record named a model the label never used.
            todo.append(it)

    print(f"rules settled the denominator on {settled} item(s); "
          f"{len(todo)} escalated to {MODEL}")
    if a.rules_only:
        for it in todo:
            it.pop("_pending", None)
            it["denominator_stated"] = "?"
            it["evidence_method"] = "unassessed"
            rec = spans.get(url_of(it)) or {}
            total = len(rec.get("spans", []))
            it["evidence_coverage"] = {"seen": 0, "total": total}
            it["label_evidence"] = "model review skipped; regex did not settle every figure-sentence"
            it["content_hash"] = rec.get("content_hash", "")
            it["evidence_hash"] = rec.get("evidence_hash", "")
            it["label_schema_version"] = LABEL_SCHEMA_VERSION
            it["auto_labelled"] = True
            it["label_source"] = "deterministic"
        if not a.dry_run:
            json.dump(data, open(FEED, "w"), indent=1)
            print("written (rule-set denominators only; unresolved items remain unassessed)")
        return

    if a.batch < 1:
        ap.error("--batch must be at least 1")
    batches, chunk, chunk_chars = [], [], len(INSTRUCT) + 20
    for it in todo:
        size = prompt_sizes[id(it)]
        if chunk and (len(chunk) >= a.batch or chunk_chars + size > PROMPT_CHAR_BUDGET):
            batches.append(chunk)
            chunk, chunk_chars = [], len(INSTRUCT) + 20
        chunk.append(it)
        chunk_chars += size
    if chunk:
        batches.append(chunk)
    nb = len(batches)
    changed = failed = 0
    for b, chunk in enumerate(batches):
        blocks = []
        for k, it in enumerate(chunk):
            u = url_of(it)
            body = (text.get(u) or {}).get("text", "")
            blocks.append(item_block(k + 1, it, spans.get(u), body[:LEAD_CHARS]))
        prompt = INSTRUCT + "\n\nITEMS:\n" + "\n".join(blocks)
        t0 = time.time()
        try:
            raw = retry_call(lambda: call(prompt))
        except Exception as e:
            print(f"  batch {b+1}/{nb}: FAILED after {time.time()-t0:.0f}s ({e})")
            failed += len(chunk)
            continue
        by_i = parse_labels(raw)
        if not by_i:
            print(f"  batch {b+1}/{nb}: no JSON parsed")
            failed += len(chunk)
            continue
        n = 0
        for k, it in enumerate(chunk):
            o = by_i.get(k + 1)
            if not o:
                continue
            pending = it.pop("_pending", None)
            if pending:
                dn = str(o.get("denominator", "")).strip()
                dn = DENOM.get(dn.lower(), dn if dn in DENOM_VALUES else None)
                rec = spans.get(url_of(it)) or {}
                total = len(rec.get("spans", []))
                if dn == "n/a" and total:
                    dn = None
                if dn:
                    n += 1
                    it["denominator_stated"] = dn
                    it["evidence_method"] = "local-model"
                    it["evidence_coverage"] = {"seen": total, "total": total}
                    it["label_evidence"] = f"model read all {total} figure-sentence(s); {pending}"
                    it["content_hash"] = rec.get("content_hash", "")
                    it["evidence_hash"] = rec.get("evidence_hash", "")
                    it["label_schema_version"] = LABEL_SCHEMA_VERSION
                else:
                    it["denominator_stated"] = "?"
                    it["evidence_method"] = "unassessed"
                    it["evidence_coverage"] = {"seen": 0, "total": total}
                    it["label_evidence"] = "model returned an invalid denominator label"
                    it["content_hash"] = rec.get("content_hash", "")
                    it["evidence_hash"] = rec.get("evidence_hash", "")
                    it["label_schema_version"] = LABEL_SCHEMA_VERSION
            # ⛔ Entity is NOT filled here. The model fabricated on 2026-07-31: 'None' x3,
            # 'Researchers', 'AI startups', 'x.com', 'Christian & Timbers' (a firm quoted in
            # the piece, not its subject). resolve_entity.py decides it deterministically or
            # leaves it blank.
            it["auto_labelled"] = True
            it["auto_labelled_by"] = MODEL
            it["label_source"] = "machine"
            changed += 1
        print(f"  batch {b+1}/{nb}: {n}/{len(chunk)} in {time.time()-t0:.0f}s")

    for it in items:
        pending = it.pop("_pending", None)
        if pending:
            rec = spans.get(url_of(it)) or {}
            total = len(rec.get("spans", []))
            it["denominator_stated"] = "?"
            it["evidence_method"] = "unassessed"
            it["evidence_coverage"] = {"seen": 0, "total": total}
            it["label_evidence"] = "model review failed; denominator remains unassessed"
            it["content_hash"] = rec.get("content_hash", "")
            it["evidence_hash"] = rec.get("evidence_hash", "")
            it["label_schema_version"] = LABEL_SCHEMA_VERSION
            it["auto_labelled"] = True
            it["label_source"] = "deterministic"
    print(f"\nlabelled {changed}, failed {failed}. reviewed stays False on all of them.")
    if a.dry_run:
        print("dry run: nothing written")
        return
    json.dump(data, open(FEED, "w"), indent=1)
    print(f"written: {FEED}\nnow run build.py")


if __name__ == "__main__":
    main()
