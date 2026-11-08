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

Hugging Face `/api/models` again for the AUDIO AND VIDEO engine makers, kept apart in
`av_releases` with its own window and its own counts. The AV_ORGS block below carries why it
is a maker list and not a modality query, and names the makers that publish no keyless
release route at all, which is most of the music market.

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
UA = {"User-Agent": "Mozilla/5.0 (NMAI Research board)"}
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


# --------------------------------------------------------------- audio and video engines
# Audio and video engine releases, kept in their own list (`av_releases`) and shown as their
# own section.
#
# ⛔ Do not merge these rows into `releases`. That list is deduped against OpenRouter on one
# window and these rows come from a different route with a different window, so one count
# over both would be two things added together. The reason the set is added rather than the
# existing one widened: of the 95 rows `releases` carried on 2026-11-08, 2 named an audio or
# video word and neither was an engine release (IBM's granite-speech ONNX export and Nvidia's
# InternVideo2 anomaly-detection repo), and a `releases` row carries no modality field.
#
# ⚠️ WHY A MAKER LIST AND NOT A MODALITY QUERY. The keyless Hugging Face pipeline queries
# (`text-to-video`, `text-to-audio`) return the newest uploads by anyone. Measured 2026-11-08:
# 10 of the 10 newest rows across both lists were hobby uploads or fine-tunes from six
# uploaders, none of them an engine's maker. A modality query would publish a community
# fine-tune as an engine release.
#
# ⛔ WHAT THIS CANNOT SEE, and it is most of the music market. Checked 2026-11-08, each answer
# kept as bytes with its digest: Suno's changelog answered 404; Suno's organisation list
# carries only the 2023 `bark` speech repositories, not the music engine; ElevenLabs' and
# Mureka's organisation lists are empty; the ElevenLabs docs feed path serves the docs app,
# not a feed; and the Mureka and Sonauto front pages carry no changelog or feed. So this
# section is open-weights-heavy by construction, and AV_NO_ROUTE is published beside it so the
# gap is stated on the page rather than left for a reader to mistake for an absence of
# releases.
AV_WINDOW_DAYS = int(os.environ.get("AV_RELEASE_MAX_AGE_DAYS", "180"))
# 180 days, not 60. These engines ship far less often than text models: with a 60-day window,
# 8 of the 11 organisations below had nothing at all on 2026-11-08. The section states its own
# window, and `av_counts` is never to be added to `counts`.
AV_LIMIT = 20
# 20, not the 5 of HF_ORGS. One request either way, and five newest repositories can be five
# text or image repositories from a maker whose audio release sits sixth: MiniMax's own list
# put its music model second of five on 2026-11-08. A maker publishing more than 20
# repositories inside the window is still undercounted, which the disclosure states.
AV_ORGS = [("MiniMaxAI", "MiniMax"), ("Lightricks", "Lightricks"), ("tencent", "Tencent"),
           ("Wan-AI", "Alibaba (Wan)"), ("genmo", "Genmo"), ("stabilityai", "Stability AI"),
           ("riffusion", "Riffusion"), ("ACE-Step", "ACE Studio"), ("suno", "Suno"),
           ("mureka", "Mureka"), ("elevenlabs", "ElevenLabs")]

# Makers whose releases cannot reach this section, with how each was checked. ⚠️ This is a
# hand-written limit statement, not a release list, and it is dated: recheck it before trusting
# it, because a maker can publish a feed at any time.
AV_NO_ROUTE = [
    {"maker": "Suno (music engine)",
     "note": "changelog answered 404 and the organisation list carries only the 2023 bark "
             "speech repositories", "checked": "2026-11-08"},
    {"maker": "Mureka",
     "note": "organisation list empty and the front page carries no changelog or feed",
     "checked": "2026-11-08"},
    {"maker": "ElevenLabs",
     "note": "organisation list empty and the docs feed path serves HTML; only the client "
             "library publishes releases, which is not the engine", "checked": "2026-11-08"},
    {"maker": "Sonauto",
     "note": "front page carries no changelog or feed", "checked": "2026-11-08"},
]

# A repository counts as audio or video by a word in its own name, matched with a boundary each
# side so that a three-letter token is not found inside another word. ⛔ Never relax this to a
# plain substring test: measured in a comparable check on 2026-11-08, "elo" as a substring was
# counted 2,376 times inside words such as "below" and "develop". Video wins when a name
# carries both.
AV_VIDEO_WORDS = ("video", "ltx", "wan", "mochi", "hunyuan", "veo", "sora", "kling",
                  "seedance", "vidu", "cogvideo", "animate", "animatediff", "i2v", "t2v",
                  "svd")
AV_AUDIO_WORDS = ("audio", "music", "speech", "voice", "vocal", "tts", "asr", "song", "sound",
                  "singing", "bark", "acestep", "ace-step", "riffusion", "suno", "mureka",
                  "lyria", "musicgen", "audiogen", "audiocraft", "whisper")


# ⛔ A maker-owned repository is not automatically the release of an engine, and the maker
# filter alone does not catch this. Measured 2026-11-08: of the 34 rows these 11 organisations
# gave over 180 days, 16 were LTX control adapters (IC-LoRA-Deblur, -Colorization,
# -Clean-Plate and so on), which would have published as 16 video engines from one maker
# inside two months. Adapters and auxiliary parts are dropped by a word in the repository's
# own name.
AV_SKIP_WORDS = ("lora", "adapter", "controlnet", "vae", "tokenizer", "scheduler", "dataset",
                 "benchmark", "demo")
# A Diffusers, ONNX, GGUF, MLX or quantised copy is the same release packaged again, not a
# second release. These words are removed before rows are grouped, so such a copy folds into
# the earliest row for its base and the row carries how many folded in. This is the rule the
# OpenRouter side already applies to serving variants, applied to artefact packaging.
AV_PACKAGING_WORDS = ("diffusers", "distilled", "onnx", "gguf", "mlx", "optimized",
                      "quantized", "awq", "gptq", "fp8", "fp16", "bf16", "int8", "nvfp4")
# ⛔ A pretrained base checkpoint published beside its fine-tuned sibling is the same release,
# not a second one. Measured 2026-11-08: Stable Audio 3 arrived as 7 repositories over three
# days, of which 3 were the `-base` twins of `-medium`, `-small-music` and `-small-sfx`, so
# without this fold the section read as 7 audio engines from one maker in one week. Size and
# purpose variants (`-medium`, `-small-music`, `-small-sfx`) are NOT folded: those are
# different weights a reader may want, and each keeps its own row.
AV_VARIANT_WORDS = ("base",)
AV_FOLD_WORDS = AV_PACKAGING_WORDS + AV_VARIANT_WORDS


def _av_pattern(words):
    return re.compile("|".join(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z])" for w in words))


AV_VIDEO = _av_pattern(AV_VIDEO_WORDS)
AV_AUDIO = _av_pattern(AV_AUDIO_WORDS)
AV_SKIP = _av_pattern(AV_SKIP_WORDS)
AV_VIDEO_SET = frozenset(AV_VIDEO_WORDS)
AV_AUDIO_SET = frozenset(AV_AUDIO_WORDS)

# ⚠️ A word can be joined to the next with no separator. `HunyuanVideo-Avatar` is Tencent's
# own name for a video engine, and the boundary rule above reads it as neither audio nor
# video, because "hunyuan" is followed by a letter and "video" is preceded by one. So a name
# is also split into its own words at case changes, and a hit on either test counts. Measured
# 2026-11-08: this adds no row today, because Tencent's newest 20 repositories carry no
# HunyuanVideo at all, but it is what stops the next one being missed. The separator rule
# stays, because `i2v` and `t2v` are words only when a separator sits each side of them.
_AV_TOKEN = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|[0-9]+(?:\.[0-9]+)*")


def av_words_of(name):
    """The name's own words, so a compound such as HunyuanVideo is read as two."""
    return {t.lower() for t in _AV_TOKEN.findall(name or "")}


# ⛔ A maker's own pipeline declaration beats a word in a repository name, and a bare tag is
# worse than both. Measured 2026-11-08 over these 11 organisation lists: taking any `video`
# or `audio` tag as the kind added 11 rows, most of them text models, because
# MiniMaxAI/MiniMax-M3.1-Flash is `image-text-to-text` with a `video` capability tag and
# tencent/WeVisCut is a `video-editing` agent built on a text model. Taking only the name
# missed MiniMaxAI/MiniMax-H3, which declares `image-text-to-video` and had 6,429,606
# downloads, and tencent/Hy-Nomas, tagged `video-generation` with 87,132. So a pipeline-shaped
# signal decides first and the name is the fallback: Wan-AI/Wan2.2-Animate-2-14B carries no
# tag but arxiv, licence and region, so the name is all there is for it.
AV_VIDEO_TASK_WORDS = ("to-video", "video-generation")
AV_AUDIO_TASK_WORDS = ("to-audio", "to-speech", "to-music", "audio-generation",
                       "music-generation", "speech-generation")
# ⚠️ Tags for something that is not an engine release, where the name cannot show it.
# Lightricks/LTX-2-Marking is tagged `watermarking`, `videoseal` and `audioseal`, carries no
# pipeline_tag and had 0 downloads and 0 likes, and it was the newest row in this section
# until this list existed. stabilityai/SAME-L and SAME-S are `autoencoder`, which is the same
# auxiliary part that `vae` catches in a name.
AV_SKIP_TAG_WORDS = ("watermark", "autoencoder")


def av_task_kind(pipeline_tag, tags):
    """"video", "audio" or None, from the maker's own pipeline declaration."""
    fields = [pipeline_tag or ""] + [t for t in (tags or []) if isinstance(t, str)]
    text = " ".join(fields).lower()
    if any(w in text for w in AV_VIDEO_TASK_WORDS):
        return "video"
    if any(w in text for w in AV_AUDIO_TASK_WORDS):
        return "audio"
    return None


def av_skipped_by_tags(tags):
    """True when the maker's own tags say this is not an engine release."""
    text = " ".join(t for t in (tags or []) if isinstance(t, str)).lower()
    return any(w in text for w in AV_SKIP_TAG_WORDS)


def av_base_of(name):
    """The release a repository belongs to: its own name less the packaging words."""
    parts = [p for p in re.split(r"[^a-z0-9.]+", (name or "").lower()) if p]
    kept = [p for p in parts if p not in AV_FOLD_WORDS]
    return "-".join(kept) or (name or "").lower()


def av_fold(rows):
    """One row per release. The earliest row for a base is kept, copies fold into it.

    The earliest is the release and a later packaging copy is not a second one, so `folded`
    counts the copies rather than hiding them.
    """
    best = {}
    # Same-day ties go to the shorter name, then alphabetically: a family published in one day
    # then keeps `stable-audio-3-medium` rather than whichever of its twins the API happened to
    # return first, so two runs of this file on the same data give the same rows.
    for row in sorted(rows, key=lambda r: (r["date"], len(r["model"]), r["model"])):
        key = (row["lab"], av_base_of(row["model"]))
        if key in best:
            best[key]["folded"] += 1
            continue
        best[key] = dict(row, folded=0)
    out = list(best.values())
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def av_kind_of(name):
    """"video", "audio" or None, from the repository's own name."""
    n = (name or "").lower()
    words = av_words_of(name)
    if AV_VIDEO.search(n) or (words & AV_VIDEO_SET):
        return "video"
    if AV_AUDIO.search(n) or (words & AV_AUDIO_SET):
        return "audio"
    return None


def av_in_window(rows, cutoff):
    """The folded rows whose own release date is inside the window.

    ⛔ This runs AFTER av_fold(), never before. A packaging copy can be created months after
    the release it packages: measured 2026-11-08, ACE Studio's acestep-v15-xl-base-diffusers
    was created 2026-06-01 for a release whose own repository is of 2026-04-02, so windowing
    first published the Diffusers copy as a June engine release. Folding first means the copy
    folds into its release and the release's own date decides, which drops that maker from the
    section rather than dating it wrongly. The section therefore undercounts in one more way,
    and the disclosure says so.
    """
    out = []
    for row in rows:
        try:
            d = datetime.strptime(row.get("date", ""), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if d >= cutoff:
            out.append(row)
    return out


def av_rows_from_hf(data, org, lab):
    """Every audio or video row in one organisation's payload, with no window applied.

    Pure: no network, so it is testable on fixtures. The window is applied by av_in_window()
    after the fold, for the reason stated there.
    """
    rows = []
    if not isinstance(data, list):
        return rows
    for m in data:
        if not isinstance(m, dict):
            continue
        mid = m.get("id") or ""
        name = mid.split("/")[-1]
        kind = av_task_kind(m.get("pipeline_tag"), m.get("tags"))
        kind_from = "pipeline" if kind else "name"
        kind = kind or av_kind_of(name)
        if not kind:
            continue
        if AV_SKIP.search(name.lower()) or av_skipped_by_tags(m.get("tags")):
            continue
        created = (m.get("createdAt") or "")[:10]
        try:
            datetime.strptime(created, "%Y-%m-%d")
        except ValueError:
            continue
        rows.append({
            "kind": kind,
            "kind_from": kind_from,
            "lab": lab,
            "model": name,
            "id": mid,
            "date": created,
            "url": f"https://huggingface.co/{mid}",
            "evidence": "open-weights",
            "evidence_note": "weights on Hugging Face; downloadable and hashable",
            "hf_id": mid,
            "source": (f"Hugging Face API, the {org} organisation list capped at {AV_LIMIT} "
                       f"repositories; date is repo creation, not necessarily release"),
        })
    return rows


def from_av(cutoff):
    rows, errors = [], []
    for org, lab in AV_ORGS:
        q = urllib.parse.urlencode({"author": org, "sort": "createdAt",
                                    "direction": -1, "limit": AV_LIMIT})
        try:
            data = get_json(f"https://huggingface.co/api/models?{q}")
        except Exception as e:
            errors.append(f"av {org}: {str(e)[:60]}")
            continue
        rows.extend(av_rows_from_hf(data, org, lab))
    # Fold first, window second, and both calls are needed. av_fold() keeps the earliest row
    # for each (lab, base), counts the packaging copies in each row's `folded` and sorts
    # newest first: without it a Diffusers, ONNX or quantised copy reads as a second release,
    # which a print-only run showed as LTX-2.5 twice and Wan2.2-Animate-2-14B three times.
    # av_in_window() then drops a release whose own date is outside the window, including one
    # reached only through a copy created inside it.
    return av_in_window(av_fold(rows), cutoff), errors


def fetch_av():
    cutoff = datetime.now(timezone.utc) - timedelta(days=AV_WINDOW_DAYS)
    return from_av(cutoff)


AV_DISCLOSURE = (
    "Audio and video engine releases, taken from the makers' own Hugging Face organisation "
    "lists: 11 organisations, each capped at 20 repositories. Whether a repository is audio "
    "or video is taken from the maker's own pipeline declaration where there is one, and from "
    "a word in the repository's name otherwise, which each row records as kind_from. A bare "
    "capability tag does not count, because a text model's tags can name video. The window is "
    "180 days, not the 60 of the model release "
    "list, because these engines ship far less often, so the two totals are not comparable "
    "and are not added together. Every row here is an open-weights repository and the date is "
    "repo creation, which can sit either side of a public release. One launch published as "
    "several repositories reads as one row: a packaging copy (Diffusers, ONNX, GGUF, MLX, a "
    "quantised build) and a pretrained base twin fold into the earliest repository of that "
    "release and are counted in its folded field, while size and purpose variants such as "
    "medium and small-sfx keep their own rows. Control adapters, LoRAs and auxiliary parts "
    "are dropped, and so is a repository its own maker tags as watermarking or as an "
    "autoencoder, because a maker-owned repository is not automatically an engine release. "
    "A release whose own repository is older than the window is not shown even when a copy of "
    "it was published inside the window, so this is a count of releases and not of repository "
    "activity. "
    "The closed engines are "
    "missing by construction rather than by omission: Suno's music engine, Mureka, ElevenLabs "
    "and Sonauto published no keyless machine-readable release route when this was checked, "
    "which is listed beside the rows. A name-word filter also undercounts, because a release "
    "whose repository name carries no audio or video word is not shown, and a maker list "
    "cannot show a maker who is not on it. No benchmark scores, by choice."
)


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


DISCLOSURE = ("Models that reached OpenRouter or the Hugging Face API in the "
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
              "appear in any release list, including this one.")


def av_counts_of(av_rows):
    """Counts for the section.

    ⚠️ `labs` is how many makers have a row, which is not how many are watched. On
    2026-11-08, 11 organisations were watched and 5 had a release inside the window, so a
    page saying "from 11 makers" above 15 rows would mislead. `folded` is how many packaging
    or base copies went into those rows, kept visible rather than dropped silently.
    """
    return {"total": len(av_rows),
            "audio": sum(1 for r in av_rows if r.get("kind") == "audio"),
            "video": sum(1 for r in av_rows if r.get("kind") == "video"),
            "folded": sum(r.get("folded", 0) for r in av_rows),
            "labs": len({r.get("lab") for r in av_rows}),
            "orgs_watched": len(AV_ORGS)}


def payload_of(rows, av_rows, errors, generated=None):
    """The written object. Pure, so the shape is testable without a fetch or a write.

    ⛔ `counts` and `av_counts` stay separate keys for the reason given in the AV block:
    two routes, two windows. Never sum them into one total.
    """
    closed = sum(1 for r in rows if r.get("evidence") == "closed")
    return {
        "generated": generated or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "window_days": MAX_AGE_DAYS,
        "counts": {"total": len(rows), "closed": closed, "open_weights": len(rows) - closed},
        "releases": rows,
        "av_window_days": AV_WINDOW_DAYS,
        "av_counts": av_counts_of(av_rows),
        "av_releases": av_rows,
        "av_no_route": AV_NO_ROUTE,
        "av_disclosure": AV_DISCLOSURE,
        "errors": errors,
        "disclosure": DISCLOSURE,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="print only, write nothing")
    a = ap.parse_args()
    rows, errors = fetch()
    av_rows, av_errors = fetch_av()
    errors = errors + av_errors
    closed = sum(1 for r in rows if r["evidence"] == "closed")
    av_counts = av_counts_of(av_rows)
    if a.show:
        print(f"{len(rows)} release(s) in {MAX_AGE_DAYS}d: {closed} closed, "
              f"{len(rows)-closed} open-weight. {len(errors)} error(s)")
        for r in rows[:28]:
            tag = "CLOSED" if r["evidence"] == "closed" else "open  "
            print(f"  {r['date']}  {tag}  {r['lab']:18} {r['model'][:46]}")
        # ⚠️ Printed apart, and never added to the line above: different route, different
        # window.
        print(f"{av_counts['total']} audio or video release(s) in {AV_WINDOW_DAYS}d: "
              f"{av_counts['audio']} audio, {av_counts['video']} video, from "
              f"{av_counts['labs']} of {av_counts['orgs_watched']} organisation(s) watched; "
              f"{av_counts['folded']} packaging or base copy(s) folded in; "
              f"{len(AV_NO_ROUTE)} maker(s) have no keyless route at all")
        for r in av_rows[:28]:
            print(f"  {r['date']}  {r['kind']:6} {r['lab']:18} {r['model'][:46]}")
        for e in errors:
            print("  ERROR", e)
        return
    payload = payload_of(rows, av_rows, errors)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
    print(f"written: {OUT}  ({len(rows)} releases: {closed} closed, {len(rows)-closed} "
          f"open-weight; {av_counts['total']} audio or video over {AV_WINDOW_DAYS}d, counted "
          f"separately; {len(errors)} error(s)). Now run: python3 build.py")


if __name__ == "__main__":
    main()
