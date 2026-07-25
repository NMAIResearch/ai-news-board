#!/usr/bin/env python3
"""
autolabel_crosscheck.py - a SECOND labeller over the same items, to triage the review.

WHAT THIS IS FOR
----------------
autolabel.py fills claim_type and denominator on unreviewed items with one local model.
That leaves a human staring at every item with no idea which ones are actually doubtful.

This runs a different model over the identical prompt and compares. Where the two agree,
the item drops down the review queue. Where they disagree, the item is flagged: two readers
looking at the same headline reached different conclusions, so it is genuinely ambiguous and
worth a human minute.

It does NOT decide who is right. On disagreement it keeps the FIRST model's label and records
the second one alongside. The board renders the disagreement; you resolve it.

⚠️ AGREEMENT IS NOT PROOF. Two language models are correlated readers, not independent ones.
They can share a systematic blind spot, and on this task both may under-detect a missing
denominator in the same way. Agreement lowers review PRIORITY. It does not certify a label,
and it never sets reviewed=True. Nothing here converts a machine guess into a human check.

WHY TWO MODELS RATHER THAN THE BEST ONE
---------------------------------------
On the Model Dependency paper's extraction task, gemma3:27b and qwen3.6:27b tie at ceiling:
60/66 correct, zero misattribution, zero inventions each. There is no accuracy basis for
preferring one. And that task was numeric extraction from SEC tables, not headline
classification, so carrying a ranking across would be the generalisation that paper's
section 6.3 dismantles. Two readers finding the hard cases is the defensible use.

USAGE
-----
    QWEN_MODEL=gemma3:27b python3 autolabel_crosscheck.py
    python3 autolabel_crosscheck.py --report      # print the disagreements, change nothing

Run after autolabel.py. Requires a local Ollama.
"""
import argparse
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from autolabel import CLAIM, DENOM, FEED, HOST, INSTRUCT, NUM_CTX  # identical prompt, by import

MODEL = os.environ.get("QWEN_MODEL", "gemma3:27b")


def call(prompt):
    payload = json.dumps({
        "model": MODEL, "prompt": prompt, "stream": False,
        "options": {"num_ctx": NUM_CTX, "temperature": 0.1},
    }).encode()
    req = urllib.request.Request(HOST + "/api/generate", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        return json.loads(r.read()).get("response", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true",
                    help="print existing disagreements without calling the model")
    args = ap.parse_args()

    data = json.load(open(FEED))
    items = data["items"]

    if args.report:
        dis = [it for it in items if (it.get("crosscheck") or {}).get("agrees") is False]
        print(f"{len(dis)} item(s) where the two labellers disagree:")
        for it in dis:
            c = it["crosscheck"]
            print(f"\n  {it.get('headline','')[:88]}")
            print(f"    {c.get('model_a','A')}: {it.get('claim_type')} / "
                  f"{it.get('denominator_stated')}")
            print(f"    {c.get('model_b','B')}: {c.get('claim_type')} / {c.get('denominator')}")
        return

    # Only items a human has not signed off. An item with reviewed=True is settled and a
    # second machine opinion on it would be noise.
    todo = [(n, it) for n, it in enumerate(items) if it.get("reviewed") is False]
    if not todo:
        print("nothing unreviewed to cross-check")
        return

    lines = [f'{k+1}. [{it.get("entity","?")}] {it.get("headline","")}'
             for k, (_, it) in enumerate(todo)]
    raw = call(INSTRUCT + "\n\nITEMS:\n" + "\n".join(lines))
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        print("no JSON array parsed; nothing written. model said:\n", raw[:300])
        return
    try:
        by_i = {int(o["i"]): o for o in json.loads(m.group(0)) if "i" in o}
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        print(f"could not parse the model's array ({e}); nothing written")
        return

    agree = disagree = 0
    for k, (_, it) in enumerate(todo):
        o = by_i.get(k + 1)
        if not o:
            continue
        ct = str(o.get("claim_type", "")).strip().lower()
        dn = str(o.get("denominator", "")).strip().lower()
        if ct not in CLAIM or dn not in DENOM:
            continue
        dn = DENOM[dn]
        same = (ct == it.get("claim_type") and dn == it.get("denominator_stated"))
        # The first model's label stands. This records a second reading beside it; it does
        # not overwrite, because there is no accuracy basis for preferring either.
        it["crosscheck"] = {
            "model_a": it.get("auto_labelled_by", "model A"), "model_b": MODEL,
            "claim_type": ct, "denominator": dn, "agrees": same,
        }
        agree, disagree = (agree + 1, disagree) if same else (agree, disagree + 1)

    json.dump(data, open(FEED, "w"), indent=2, ensure_ascii=False)
    total = agree + disagree
    print(f"cross-checked {total} item(s) with {MODEL}: {agree} agree, {disagree} disagree"
          f"{f' ({100*disagree/total:.0f}% need a human eye)' if total else ''}.")
    print("reviewed stays False on all of them. Run build.py, then review the disagreements:")
    print("  python3 autolabel_crosscheck.py --report")


if __name__ == "__main__":
    main()
