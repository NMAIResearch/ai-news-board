#!/usr/bin/env python3
"""
autolabel.py - OPTIONAL local-model categoriser for AnchorAI feed items.

Fills claim_type and denominator_stated on items that are NOT human-reviewed,
using a local Ollama model (default qwen3.6:27b). It NEVER sets reviewed=True:
the board keeps flagging these as "auto-tagged, unreviewed", so a machine guess
is never passed off as a human check. Run it after carry_reviews.py / before
build.py. Requires a local Ollama; it is not part of the stdlib core pipeline.

  python3 autolabel.py                      # default: qwen2.5:14b, 32k ctx
  QWEN_MODEL=qwen2.5:7b python3 autolabel.py # faster fallback if 14b not pulled

claim_type vocab:  announced | assertion | target | prediction | measurement
denominator vocab: Y | partial | N
"""
import argparse, json, os, re, time, urllib.request

HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MODEL = os.environ.get("QWEN_MODEL", "qwen2.5:14b")
NUM_CTX = int(os.environ.get("QWEN_CTX", "32768"))
# Batch size is the cost control, not context. The 36-item prompt is ~1,010 tokens against a
# 32,768 window; what times out is OUTPUT. Reasoning models spend ~400 discarded thinking
# tokens per headline (measured 2026-07-30: 1,643 out for 60 tokens of JSON on 4 items), so
# one all-items call generates ~14k tokens and dies whole. Small batches keep each trace
# short and each write durable.
BATCH = int(os.environ.get("LABEL_BATCH", "6"))
TIMEOUT = int(os.environ.get("LABEL_TIMEOUT", "300"))
# ⛔ DO NOT downgrade the reader models to make this faster. HIS CALL, 2026-07-30.
# The 27-30B readers exceed 16 GB VRAM (RTX 4070 Ti SUPER) and spill to system RAM; the
# machine has 64 GB DDR5 provisioned for exactly that. Slow runs are accepted; a weaker
# reader is not. Batching is the fix for the timeouts, not a smaller model.
FEED = os.path.join(os.path.dirname(__file__), "feed_items.json")

CLAIM = {"announced", "assertion", "target", "prediction", "measurement"}
DENOM = {"y": "Y", "partial": "partial", "n": "N"}

INSTRUCT = (
    "You classify AI-news headlines for a media-literacy board. For each numbered "
    "item return claim_type and denominator.\n"
    "claim_type is the rhetorical form of the claim:\n"
    "  announced  = a launch/partnership/deal stated as done\n"
    "  assertion  = an opinion or capability claim asserted without a figure\n"
    "  target     = a future goal or plan ('will', 'aims to', 'by 2030')\n"
    "  prediction = a forecast about what will happen\n"
    "  measurement= reports a measured result or number that already happened\n"
    "denominator is whether the headline states the base rate the number is out of:\n"
    "  Y = a rate/share with its base is given; partial = a number but no clear base; "
    "N = no quantity, or a bare figure with no denominator.\n"
    "Return ONLY a JSON array like [{\"i\":1,\"claim_type\":\"announced\",\"denominator\":\"N\"}]."
)


def call(prompt, timeout=TIMEOUT):
    payload = json.dumps({
        "model": MODEL, "prompt": prompt, "stream": False,
        # ⛔ Do not vary num_ctx between calls: ollama reloads the model when it changes.
        # Measured 2026-07-30: same 4-item prompt took 33s at 32768 and 232s at 8192,
        # returning nothing at all on the smaller window.
        "options": {"num_ctx": NUM_CTX, "temperature": 0.1},
    }).encode()
    req = urllib.request.Request(HOST + "/api/generate", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read()).get("response", "")


def parse_labels(raw):
    """Return {index: label} from a model response, or {} if none parses.

    Reasoning models emit a thinking trace that can itself contain brackets, so match the
    LAST array in the response rather than the first.
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
    return {int(o["i"]): o for o in (best or []) if isinstance(o, dict) and "i" in o}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=BATCH, help=f"items per call (default {BATCH})")
    ap.add_argument("--force", action="store_true",
                    help="re-label items already auto-labelled (default: skip them)")
    a = ap.parse_args()

    data = json.load(open(FEED))
    items = data["items"]
    todo = [it for it in items
            if it.get("reviewed") is False and (a.force or not it.get("auto_labelled"))]
    if not todo:
        print("nothing to label (use --force to re-label auto-labelled items)")
        return

    changed = failed = 0
    nbatch = (len(todo) + a.batch - 1) // a.batch
    for b in range(nbatch):
        chunk = todo[b * a.batch:(b + 1) * a.batch]
        lines = [f'{k+1}. [{it.get("entity") or "?"}] {it.get("headline","")}'
                 for k, it in enumerate(chunk)]
        t0 = time.time()
        try:
            raw = call(INSTRUCT + "\n\nITEMS:\n" + "\n".join(lines))
        except Exception as e:
            print(f"  batch {b+1}/{nbatch}: FAILED after {time.time()-t0:.0f}s ({e}); "
                  f"{len(chunk)} item(s) left unlabelled")
            failed += len(chunk)
            continue
        by_i = parse_labels(raw)
        if not by_i:
            print(f"  batch {b+1}/{nbatch}: no JSON parsed; model said: {raw[:120]!r}")
            failed += len(chunk)
            continue
        n = 0
        for k, it in enumerate(chunk):
            o = by_i.get(k + 1)
            if not o:
                continue
            ct = str(o.get("claim_type", "")).strip().lower()
            dn = str(o.get("denominator", "")).strip().lower()
            if ct in CLAIM:
                it["claim_type"] = ct
            if dn in DENOM:
                it["denominator_stated"] = DENOM[dn]
            it["auto_labelled"] = True   # data trail; reviewed stays False
            it["auto_labelled_by"] = MODEL
            n += 1
        changed += n
        # Write after EVERY batch. A later timeout must not cost the batches already done.
        json.dump(data, open(FEED, "w"), indent=2, ensure_ascii=False)
        print(f"  batch {b+1}/{nbatch}: {n}/{len(chunk)} labelled in {time.time()-t0:.0f}s")

    print(f"auto-labelled {changed}/{len(todo)} items with {MODEL} in {nbatch} batch(es)"
          + (f", {failed} left unlabelled" if failed else "")
          + ". reviewed stays False; the board still flags them unreviewed. Now run build.py")


if __name__ == "__main__":
    main()
