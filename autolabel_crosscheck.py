#!/usr/bin/env python3
"""
autolabel_crosscheck.py - extra labellers over the same items, to triage the review queue.

WHAT THIS IS FOR
----------------
autolabel.py fills claim_type and denominator with one local model, which leaves a human
facing every item with no signal about which are doubtful. This runs further models over the
IDENTICAL prompt (imported from autolabel, never copied, so the passes cannot drift) and
records where they differ.

Where all readers agree, the item drops down the queue. Where they split, the item is
genuinely ambiguous and worth a human minute.

⛔ WHAT IT DOES NOT DO
----------------------
It does not pick a winner and it does not vote. A 2-1 split is recorded as a 2-1 split, not
resolved to the majority, because these readers are NOT independent: two builds from one
family share a tokenizer and training lineage, so a shared error looks exactly like a
majority. Counting correlated readers as votes manufactures confidence that is not there.

It never sets reviewed=True. Agreement lowers review PRIORITY and certifies nothing.

CHOOSING READERS, AND THE TRADE-OFF IN THIS MODEL SET
-----------------------------------------------------
On the Model Dependency paper's extraction task, gemma3:27b, qwen3.6:27b and qwen3.6:35b tie
at ceiling (60/66, zero misattribution each), so there is no accuracy basis for ranking them.
But two of those three are the same family, so qwen3.6:35b beside qwen3.6:27b buys capability
and little independence.

⛔ An earlier version of this note said the only independent alternative was mistral:7b
(42/66, dissent too weak to weigh). That is WITHDRAWN: mistral-small:24b is pulled and is
capacity-matched, giving a genuine third lineage without dropping capability. Default now
includes it.

Each item records how many distinct families actually read it, so a unanimous verdict is
never mistaken for N independent confirmations.

⚠️ MEASURED, and it cuts against my own caution: on the first three-reader run the two qwen
builds did NOT clump. Dissent in the twelve 2-1 splits fell qwen3.6:27b 5, gemma3:27b 4,
qwen3.6:35b 3, against ~33% each under independence. n=12, so this settles nothing, but the
family-correlation worry is asserted rather than demonstrated and should be stated that way.

↻ [2026-07-30] glm-4.7-flash:q4_K_M ADDED as a fourth reader (lineages: gemma / qwen /
mistral / GLM). Added, not swapped for qwen3.6:35b: the MEASURED note above shows the qwen
pair did not clump, so there is no evidence to drop one on.

⚠️ READER CALIBRATION, as of 2026-07-30. Weigh dissent accordingly:
    SCORED on the Model Dependency extraction task: gemma3:27b, qwen3.6:27b, qwen3.6:35b
        (91%, 0 misattributions). glm-4.7-flash: 8/8 on condition A, n=8, too small to rank.
    NOT SCORED AT ALL: mistral-small:24b. It appears nowhere in that project. The only
        mistral scored there is mistral:7b at 42/66.
⛔ The WITHDRAWN note above therefore overstates its case: "capacity-matched ... without
dropping capability" substituted parameter count for accuracy. Do not present mistral-small
or glm as peers of the scored three until they are run.

⚠️ glm-4.7-flash and qwen3.6 are REASONING models. Measured 2026-07-30: 1,643 output tokens
to return 60 tokens of JSON on 4 items, ~96% discarded thinking. This is why the labelling
pass times out. Keep batches small; see autolabel.py.

USAGE
-----
    python3 autolabel_crosscheck.py                       # default readers, one command
    python3 autolabel_crosscheck.py --models a,b          # choose them
    python3 autolabel_crosscheck.py --report              # print splits, call nothing

Run after autolabel.py. Requires a local Ollama.
"""
import argparse
import collections
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from autolabel import (CLAIM, DENOM, FEED, HOST, INSTRUCT, NUM_CTX, NUM_PREDICT,
                       retry_call)

BATCH = int(os.environ.get("LABEL_BATCH", "6"))
SPANS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "article_spans.json")
TEXTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "article_text.json")
DEFAULT_MODELS = ["gemma3:27b", "qwen3.6:35b", "mistral-small:24b",
                  "glm-4.7-flash:q4_K_M"]
# Readers sharing a prefix share a lineage. Used only to annotate the output, never to
# discount a reading: the point is that the reader is told, not that the code decides.
FAMILY = lambda m: m.split(":")[0].rstrip("0123456789.")


def call(model, prompt):
    payload = json.dumps({
        "model": model, "prompt": prompt, "stream": False,
        "options": {"num_ctx": NUM_CTX, "temperature": 0.1,
                    "num_predict": NUM_PREDICT},
    }).encode()
    req = urllib.request.Request(HOST + "/api/generate", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=2400) as r:
        return json.loads(r.read()).get("response", "")


def parse_array(raw):
    """Last JSON array in a response, or None.

    Reasoning models emit a thinking trace that can itself contain brackets, so the LAST
    array is taken rather than the first, and any <think> block is stripped before matching.
    """
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S)
    best = None
    for m in re.finditer(r"\[.*?\]", raw, re.S):
        try:
            v = json.loads(m.group(0))
        except ValueError:
            continue
        if isinstance(v, list) and v:
            best = v
    if best is None:
        m = re.search(r"\[.*\]", raw, re.S)
        if m:
            try:
                best = json.loads(m.group(0))
            except ValueError:
                best = None
    return best


def article_lines(chunk):
    """Headline + article opening + verbatim figure sentences, per item.

    Used by --with-article to test whether claim_type disagreement is caused by starving
    the readers of input. Falls back to the headline where no article was fetched.
    """
    spans = json.load(open(SPANS)) if os.path.exists(SPANS) else {}
    text = json.load(open(TEXTS)) if os.path.exists(TEXTS) else {}
    out = []
    for k, (_, it) in enumerate(chunk):
        url = next((s["url"] for s in it.get("sources", [])
                    if s.get("url", "").startswith("http")), "")
        block = [f'{k+1}. HEADLINE: [{it.get("entity","?")}] {it.get("headline","")}']
        lead = (text.get(url) or {}).get("text", "")[:400]
        if lead:
            block.append(f"   OPENING: {lead}")
        for s in (spans.get(url) or {}).get("spans", [])[:4]:
            block.append(f"   FIGURE SENTENCE: {s['sentence'][:240]}")
        out.append("\n".join(block))
    return out


def label_pass(model, todo, batch=BATCH, lines_fn=None):
    """Return {item_index: (claim_type, denominator)} for one model.

    ⛔ BATCHED, and it must stay batched. Sending every item in one call is what killed the
    2026-07-29 pass: the prompt is small (~27 tokens/item) but reasoning readers emit ~400
    DISCARDED thinking tokens per headline, so a 38-item call generates ~15k tokens and
    overruns. Output is the constraint, never context. A batch that fails costs that batch
    only; partial results from a reader are kept and counted as far as they go.
    """
    out, failed = {}, 0
    nb = (len(todo) + batch - 1) // batch
    for b in range(nb):
        chunk = todo[b * batch:(b + 1) * batch]
        lines = (lines_fn(chunk) if lines_fn else
                 [f'{k+1}. [{it.get("entity","?")}] {it.get("headline","")}'
                  for k, (_, it) in enumerate(chunk)])
        t0 = time.time()
        try:
            raw = retry_call(
                lambda: call(model, INSTRUCT + "\n\nITEMS:\n" + "\n".join(lines)))
        except Exception as e:
            print(f"    {model} batch {b+1}/{nb}: FAILED after {time.time()-t0:.0f}s ({e})")
            failed += 1
            continue
        arr = parse_array(raw)
        if not arr:
            print(f"    {model} batch {b+1}/{nb}: no JSON parsed, skipped")
            failed += 1
            continue
        n = 0
        for o in arr:
            if not isinstance(o, dict) or "i" not in o:
                continue
            ct = str(o.get("claim_type", "")).strip().lower()
            dn = str(o.get("denominator", "")).strip().lower()
            # Indices are 1-based WITHIN the chunk; map back to the whole-run index.
            idx = b * batch + int(o["i"])
            if ct in CLAIM and dn in DENOM:
                out[idx] = (ct, DENOM[dn])
                n += 1
        print(f"    {model} batch {b+1}/{nb}: {n}/{len(chunk)} in {time.time()-t0:.0f}s")
    if failed:
        print(f"  ! {model}: {failed}/{nb} batch(es) failed; keeping the {len(out)} that landed")
    return out


def verdict(readings):
    """unanimous | majority | tied | split, from a list of (claim_type, denominator) tuples.

    "tied" exists because an EVEN number of readers can deadlock. With four readers a 2-2 is
    maximally ambiguous, yet a naive "not unanimous and not all-different" test would file it
    as a majority and under-flag the very items most in need of a human. A tie is closer to a
    split than to a majority and is ranked accordingly.
    """
    if len(readings) < 2:
        return "single"
    counts = collections.Counter(readings)
    if len(counts) == 1:
        return "unanimous"
    if len(counts) == len(readings):
        return "split"
    top = counts.most_common()
    return "majority" if top[0][1] > top[1][1] else "tied"


def report(items, field="crosscheck"):
    order = {"split": 0, "tied": 1, "majority": 2, "unanimous": 3, "single": 4}
    flagged = [it for it in items
               if (it.get(field) or {}).get("verdict") in ("split", "tied", "majority")]
    flagged.sort(key=lambda it: order[it[field]["verdict"]])
    print(f"{len(flagged)} item(s) where the readers do not all agree ({field}):\n")
    for it in flagged:
        c = it[field]
        print(f"  [{c['verdict'].upper():<9}] {it.get('headline','')[:80]}")
        for r in c["readers"]:
            print(f"      {r['model']:<16} {r['claim_type']:<12} {r['denominator']}")
        print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS),
                    help="comma-separated extra readers")
    ap.add_argument("--report", action="store_true")
    # ⛔ Writes to crosscheck_article, NOT crosscheck. The headline run is the baseline this
    # is compared against; overwriting it destroys the comparison.
    ap.add_argument("--with-article", action="store_true",
                    help="readers see article opening + figure spans, not the headline alone")
    args = ap.parse_args()

    field = "crosscheck_article" if args.with_article else "crosscheck"
    data = json.load(open(FEED))
    items = data["items"]
    if args.report:
        return report(items, field)

    todo = [(n, it) for n, it in enumerate(items) if it.get("reviewed") is False]
    if not todo:
        print("nothing unreviewed to cross-check")
        return

    extra = [m.strip() for m in args.models.split(",") if m.strip()]
    print(f"{len(todo)} item(s), {len(extra) + 1} readers "
          f"(1 from autolabel + {len(extra)} here). This is slow; one pass per reader.\n")

    passes = {}
    for model in extra:
        print(f"  running {model} ...", flush=True)
        got = label_pass(model, todo, lines_fn=article_lines if args.with_article else None)
        if got:
            passes[model] = got
    if not passes:
        print("no reader produced usable output; nothing written")
        return

    counts = {"unanimous": 0, "majority": 0, "tied": 0, "split": 0, "single": 0}
    for k, (_, it) in enumerate(todo):
        base = (it.get("claim_type"), it.get("denominator_stated"))
        readers = [{"model": it.get("auto_labelled_by", "autolabel"),
                    "claim_type": base[0], "denominator": base[1]}]
        readings = [base]
        for model, got in passes.items():
            if (r := got.get(k + 1)) is None:
                continue
            readers.append({"model": model, "claim_type": r[0], "denominator": r[1]})
            readings.append(r)
        v = verdict(readings)
        counts[v] += 1
        # A reader whose model was never recorded must NOT be counted as its own family.
        # It was, on 2026-07-25: the first pass predated model-name recording, so it
        # registered as the literal string "autolabel" and inflated the family count from
        # 3 to 4 — the precise over-claim this field exists to prevent.
        known = [r["model"] for r in readers if r.get("model") and ":" in r["model"]]
        unknown = len(readers) - len(known)
        fams = {FAMILY(m) for m in known}
        it[field] = {
            "verdict": v, "readers": readers,
            # Recorded so a unanimous verdict is not mistaken for independent confirmation.
            "independent_families": len(fams), "families": sorted(fams),
            **({"readers_of_unrecorded_provenance": unknown} if unknown else {}),
        }

    json.dump(data, open(FEED, "w"), indent=2, ensure_ascii=False)
    n = sum(counts.values())
    print(f"\n{n} item(s) cross-checked with {len(passes) + 1} readers:")
    for k in ("unanimous", "majority", "tied", "split"):
        if counts[k]:
            print(f"  {k:<10} {counts[k]:>3}  ({100*counts[k]/n:.0f}%)")
    print("\nreviewed stays False on all of them. A majority is NOT a resolution: readers "
          "from one family share a lineage, so a shared error looks like agreement.")
    print("  python3 autolabel_crosscheck.py --report")


if __name__ == "__main__":
    main()
