#!/usr/bin/env python3
"""fetch_releases.py (stdlib only) - model releases, open and closed, with evidence class.

WHAT THIS IS
------------
A feed of models that came out recently. That is the whole job.

    OPEN WEIGHTS    the file is published; it can be downloaded, hashed and run later.
                    Detected by OpenRouter reporting a `hugging_face_id`, and supplemented
                    by a direct Hugging Face query for labs whose research models never
                    reach a reseller.
    API ONLY        served over an API, nothing to download.

⛔ Do not treat API only as a lesser release. It is shipped and serving traffic. Whether the
weights can be downloaded later is an auditability question; it belongs in the Model
Dependency work, not in a list of what came out.

⛔ Do not present the open and API-only totals as a ratio. OpenRouter is taken in full;
Hugging Face is HF_ORGS, a hand-written list capped at five repositories per org, four of
which sat on the cap on 2026-07-31. OpenRouter rows are deduped to a base model, Hugging Face
rows are not. Such a ratio moves with the org list, not with the world.

⚠️ The two dates differ in kind. An OpenRouter date is a listing observed by a third party. A
Hugging Face `createdAt` is repo creation and can sit either side of the public release.

⛔ NOT HAND-CURATED, deliberately. An earlier version of this file kept a hand-written list
of closed releases. It was replaced 2026-07-30 because it lagged: llm-stats and
aireleasetracker.com both carried Grok 4.5, Kimi K3 and three Gemini Flash variants that the
hand list did not. A list maintained by hand will always trail the sites that automate it.

SOURCES AND WHAT EACH ONE ACTUALLY TELLS YOU
--------------------------------------------
OpenRouter `/api/v1/models` (no key). 367 models on 2026-07-30, every one carrying a `created`
timestamp, and `hugging_face_id` present or null gives the open/closed split without a
judgement call. ⚠️ OpenRouter is a RESELLER, tier 4 on this board's scale. `created` is when
the model reached OpenRouter, which tracks the vendor release date closely but is not it.
Spot-checked 2026-07-30 against llm-stats: claude-opus-5 2026-07-24 and gemini-3.6-flash
2026-07-21 agree on both.

Hugging Face `/api/models` for a curated org list. Direct from the artefact host.
⚠️ `createdAt` is repo creation; a repo can be created private and made public later.

⛔ WHAT THIS CANNOT SEE, and it matters more than what it can:
  - A model announced but never shipped never appears, because it is served nowhere. Gemini
    3.5 Pro is the live case on 2026-07-30: announced, three target dates passed, absent
    here. A release list structurally cannot show a non-release.
  - A restricted model (Claude Mythos 5) is served to an access list, not to a reseller.
  - Coverage is whatever OpenRouter chose to carry.

⛔ NO BENCHMARK SCORES, EVER. That is a leaderboard, llm-stats and aireleasetracker already
occupy it, and a percentage with no stated denominator is the defect this board flags
elsewhere.

Run:
    python3 fetch_releases.py          # writes releases.json
    python3 fetch_releases.py --show   # print only
"""
import argparse
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "releases.json")
UA = {"User-Agent": "Mozilla/5.0 (NM AI Research board)"}
MAX_AGE_DAYS = int(os.environ.get("RELEASE_MAX_AGE_DAYS", "60"))
OPENROUTER = "https://openrouter.ai/api/v1/models"

# Supplement only: labs whose research releases do not reach a reseller.
HF_ORGS = ["meta-llama", "mistralai", "Qwen", "google", "deepseek-ai", "allenai",
           "microsoft", "openai", "zai-org", "nvidia", "ibm-granite", "CohereLabs",
           "moonshotai"]

LAB = {"meta-llama": "Meta", "mistralai": "Mistral", "qwen": "Alibaba (Qwen)",
       "google": "Google", "deepseek-ai": "DeepSeek", "deepseek": "DeepSeek",
       "allenai": "Ai2", "microsoft": "Microsoft", "openai": "OpenAI",
       "zai-org": "Z.ai", "nvidia": "Nvidia", "ibm-granite": "IBM",
       "coherelabs": "Cohere", "cohere": "Cohere", "moonshotai": "Moonshot",
       "anthropic": "Anthropic", "x-ai": "xAI", "meta": "Meta",
       "thinkingmachines": "Thinking Machines", "poolside": "Poolside"}

# Serving variants of one model, not separate releases.
VARIANT = re.compile(r"(:free|:batch|:thinking|:extended|:online|:nitro|:floor)$", re.I)

# Moving pointers, not releases. OpenRouter carries entries such as `~x-ai/grok-latest` and
# `~anthropic/claude-fable-latest`. Their `created` is when the ALIAS was made; the target
# changes underneath the name with no new date, so each duplicates a versioned row already
# in the list (grok-latest 14:02 vs grok-4.5 15:05 on 2026-07-08; claude-fable-latest 18:32
# vs claude-fable-5 12:18 on 2026-06-09). Exclude them.
ALIAS = re.compile(r"^~|-latest$")


def get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.loads(r.read())


def lab_of(vendor):
    return LAB.get(vendor.lower(), vendor.replace("-", " ").title())


def from_openrouter(cutoff):
    rows, err = [], None
    try:
        data = get_json(OPENROUTER).get("data", [])
    except Exception as e:
        return [], f"openrouter: {str(e)[:70]}"
    best = {}
    for m in data:
        mid = m.get("id") or ""
        created = m.get("created")
        if not mid or not created:
            continue
        d = datetime.fromtimestamp(created, timezone.utc)
        if d < cutoff:
            continue
        base = VARIANT.sub("", mid)
        # The reseller's own routing products are not model releases.
        if base.split("/")[0].lower() in ("openrouter", "auto"):
            continue
        # Nor are moving pointers (see ALIAS above).
        # ⛔ Do NOT add `canonical_slug != id` as a second alias test. It looks right and is
        # wrong: measured 2026-07-31, 41 of the 41 in-window OpenRouter rows have a DATED
        # canonical slug behind an undated public id (`anthropic/claude-opus-5` ->
        # `anthropic/claude-opus-5-20260723`), so that rule deletes the entire list.
        if ALIAS.search(base):
            continue
        # Keep the EARLIEST timestamp per base model: a variant added later is not a
        # second release.
        if base not in best or d < best[base][0]:
            best[base] = (d, m)
    for base, (d, m) in best.items():
        vendor = base.split("/")[0]
        hf = m.get("hugging_face_id")
        rows.append({
            "lab": lab_of(vendor),
            "model": m.get("name") or base,
            "id": base,
            "date": d.strftime("%Y-%m-%d"),
            "url": f"https://openrouter.ai/{base}",
            "context_length": m.get("context_length"),
            "evidence": "open-weights" if hf else "closed",
            "evidence_note": (f"weights published at huggingface.co/{hf}; downloadable and "
                              f"hashable" if hf else
                              "served over an API only; no artefact to inspect"),
            "hf_id": hf or "",
            "source": "OpenRouter (reseller, tier 4); date is when the model reached OpenRouter",
        })
    return rows, err


def from_huggingface(cutoff):
    rows, errors = [], []
    for org in HF_ORGS:
        q = urllib.parse.urlencode({"author": org, "sort": "createdAt",
                                    "direction": -1, "limit": 5})
        try:
            data = get_json(f"https://huggingface.co/api/models?{q}")
        except Exception as e:
            errors.append(f"hf {org}: {str(e)[:60]}")
            continue
        for m in data:
            created = (m.get("createdAt") or "")[:10]
            try:
                d = datetime.strptime(created, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if d < cutoff:
                continue
            rows.append({
                "lab": lab_of(org),
                "model": (m.get("id") or "").split("/")[-1],
                "id": m.get("id", ""),
                "date": created,
                "url": f"https://huggingface.co/{m.get('id','')}",
                "context_length": None,
                "evidence": "open-weights",
                "evidence_note": "weights on Hugging Face; downloadable and hashable",
                "hf_id": m.get("id", ""),
                "source": "Hugging Face API; date is repo creation, not necessarily release",
            })
    return rows, errors


def fetch():
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    errors = []
    orr, orerr = from_openrouter(cutoff)
    if orerr:
        errors.append(orerr)
    hfr, hferr = from_huggingface(cutoff)
    errors.extend(hferr)

    # Dedup across sources on the HF id, which is the artefact identity. OpenRouter wins,
    # because it carries the serving date rather than the repo-creation date.
    seen_hf = {r["hf_id"].lower() for r in orr if r.get("hf_id")}
    merged = orr + [r for r in hfr if r["hf_id"].lower() not in seen_hf]
    merged.sort(key=lambda r: r["date"], reverse=True)
    return merged, errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="print only, write nothing")
    a = ap.parse_args()
    rows, errors = fetch()
    closed = sum(1 for r in rows if r["evidence"] == "closed")
    if a.show:
        print(f"{len(rows)} release(s) in {MAX_AGE_DAYS}d: {closed} closed, "
              f"{len(rows)-closed} open-weight. {len(errors)} error(s)")
        for r in rows[:28]:
            tag = "CLOSED" if r["evidence"] == "closed" else "open  "
            print(f"  {r['date']}  {tag}  {r['lab']:18} {r['model'][:46]}")
        for e in errors:
            print("  ERROR", e)
        return
    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "window_days": MAX_AGE_DAYS,
        "counts": {"total": len(rows), "closed": closed, "open_weights": len(rows) - closed},
        "releases": rows,
        "errors": errors,
        "disclosure": ("Models that reached OpenRouter or the Hugging Face API in the "
                       "window. Each row says whether the weights are published, which is "
                       "an attribute of the release rather than a grade: an API-only model "
                       "is shipped and serving traffic, it is simply not downloadable. "
                       "Dates are when the model reached the source, not the vendor's own "
                       "announcement date, and the Hugging Face dates are repo creation, "
                       "which can sit either side of a public release. The two sides are "
                       "not counted the same way, so the open and API-only totals are not "
                       "comparable: OpenRouter is taken in full, while Hugging Face is a "
                       "fixed list of labs capped at five repositories each. No benchmark "
                       "scores, by choice. A model announced but never shipped cannot "
                       "appear in any release list, including this one."),
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
    print(f"written: {OUT}  ({len(rows)} releases: {closed} closed, {len(rows)-closed} "
          f"open-weight; {len(errors)} error(s)). Now run: python3 build.py")


if __name__ == "__main__":
    main()
