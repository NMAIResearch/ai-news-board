#!/usr/bin/env python3
"""llm_client.py - shared local-model (Ollama) client for the labelling pipeline.

The call / retry / parse helpers and their tuned constants, extracted from the retired
autolabel.py (now in archive/) so label_items.py is self-contained and nothing in the live
pipeline depends on an archived file. autolabel.py's headline-only labelling is NOT carried
over; only its model-call plumbing, which label_items.py still reuses.

Constants are overridable by environment variable. The comments record hard-won tuning
(VRAM limits, timeout behaviour, output caps); do not lower them casually.
"""
import json, os, re, time, urllib.request

HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MODEL = os.environ.get("LABEL_MODEL", os.environ.get("QWEN_MODEL", "gemma4:12b"))
NUM_CTX = int(os.environ.get("LABEL_CTX", os.environ.get("QWEN_CTX", "32768")))
# Output cap. Without it the only stop condition is filling NUM_CTX: a looping reader runs
# to 16k-28k tokens for a ~120-token answer (glm-4.7-flash, 5 batches at 11-19 min each,
# truncated and unparseable, 2026-07-30). 6000 clears the largest observed successful
# generation (qwen3.6:35b, 4,180 tokens on a 6-item batch). Do NOT lower toward the median:
# gemma3 and mistral finish under 350 tokens, but a cap that fits them truncates every qwen
# and glm batch. A truncated response is still unparseable; this bounds a runaway's cost.
NUM_PREDICT = int(os.environ.get("LABEL_NUM_PREDICT", "6000"))
TIMEOUT = int(os.environ.get("LABEL_TIMEOUT", "300"))
# The default changed after a measured local check on 2026-08-11. Gemma 4 12B returned valid
# structured output for 6/6 single-item requests, N=6, in 9-60 seconds each. Qwen 3.5 9B
# returned valid output for 4/8 two-item requests, N=8. Qwen 3.6 27B returned valid labels
# for 40/59 escalated items, N=59, and spilled into system RAM. These measurements establish
# speed and output compliance only. They do not establish label accuracy.

# denominator vocab: model output -> stored value
DENOM = {"y": "Y", "partial": "partial", "n": "N"}


def call(prompt, timeout=TIMEOUT):
    payload = json.dumps({
        "model": MODEL, "prompt": prompt, "stream": False,
        # Do not vary num_ctx between calls: ollama reloads the model when it changes.
        # Measured 2026-07-30: same 4-item prompt took 33s at 32768 and 232s at 8192,
        # returning nothing at all on the smaller window.
        "options": {"num_ctx": NUM_CTX, "temperature": 0.1, "num_predict": NUM_PREDICT},
    }).encode()
    req = urllib.request.Request(HOST + "/api/generate", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read()).get("response", "")


def retry_call(fn, tries=2, wait=5):
    """Call fn(), retrying once on any exception.

    llama-server can abort mid-request and return HTTP 500 (CUDA illegal memory access,
    2026-07-30). Ollama respawns it and the next call succeeds; without a retry the batch is
    dropped for a fault that has already cleared.
    """
    for t in range(tries):
        try:
            return fn()
        except Exception:
            if t == tries - 1:
                raise
            time.sleep(wait)


def parse_labels(raw):
    """Return {index: label-dict} from a model response, or {} if none parses.

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
