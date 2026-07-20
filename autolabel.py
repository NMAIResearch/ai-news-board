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
import json, os, re, urllib.request

HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MODEL = os.environ.get("QWEN_MODEL", "qwen2.5:14b")
NUM_CTX = int(os.environ.get("QWEN_CTX", "32768"))
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


def call(prompt):
    payload = json.dumps({
        "model": MODEL, "prompt": prompt, "stream": False,
        "options": {"num_ctx": NUM_CTX, "temperature": 0.1},
    }).encode()
    req = urllib.request.Request(HOST + "/api/generate", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(r.read()).get("response", "")


def main():
    data = json.load(open(FEED))
    items = data["items"]
    todo = [(n, it) for n, it in enumerate(items) if it.get("reviewed") is False]
    if not todo:
        print("nothing unreviewed to label")
        return
    lines = [f'{k+1}. [{it.get("entity","?")}] {it.get("headline","")}'
             for k, (_, it) in enumerate(todo)]
    prompt = INSTRUCT + "\n\nITEMS:\n" + "\n".join(lines)
    raw = call(prompt)
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        print("no JSON array parsed; leaving defaults. model said:\n", raw[:300])
        return
    labels = json.loads(m.group(0))
    by_i = {int(o["i"]): o for o in labels if "i" in o}
    changed = 0
    for k, (idx, it) in enumerate(todo):
        o = by_i.get(k + 1)
        if not o:
            continue
        ct = str(o.get("claim_type", "")).strip().lower()
        dn = str(o.get("denominator", "")).strip().lower()
        if ct in CLAIM:
            it["claim_type"] = ct
        if dn in DENOM:
            it["denominator_stated"] = DENOM[dn]
        it["auto_labelled"] = True  # data trail; reviewed stays False
        changed += 1
    json.dump(data, open(FEED, "w"), indent=2, ensure_ascii=False)
    print(f"auto-labelled {changed}/{len(todo)} unreviewed items with {MODEL} "
          f"(reviewed stays False; board still flags them unreviewed). Now run build.py")


if __name__ == "__main__":
    main()
