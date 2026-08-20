#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sovereign_watch.py - Sovereign Watch: Global AI Regulatory Radar (L8 Pipeline).

Continuous regulatory intelligence engine:
1. Ingests sovereign gazettes (US Federal Register, EU AI Office, UK CMA/Ofgem, 29 jurisdiction packs).
2. Performs hash-diffing against surveillance_store.json.
3. Filters administrative noise (Unified Agenda forward plans, voluntary RFIs, procedural meeting notices).
4. Routes new/substantive items to local Qwen 3.8 (27B) via Ollama chat API for deep legal evaluation.
5. Emits real-time alerts to data/regulatory_alerts.json, alerts/bulletin_YYYY-MM-DD.md, and desktop notifications.
6. Rebuilds AI News Board and Mission Control command deck.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

HERE = pathlib.Path(__file__).resolve().parent
WORKSPACE_ROOT = HERE.parent
REGULATIONS_DIR = WORKSPACE_ROOT / "AI Regulations"
DATA_DIR = HERE / "data"
ALERTS_DIR = HERE / "alerts"
LOGS_DIR = HERE / "logs"
STORE_FILE = DATA_DIR / "surveillance_store.json"
ALERTS_FILE = DATA_DIR / "regulatory_alerts.json"
ALERTS_LOG = DATA_DIR / "live_alerts.jsonl"

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("SURVEILLANCE_MODEL", "qwen3.8:latest")

USER_AGENT = "NM-AI-Research-Sovereign-Watch/2.0 (+https://nmairesearch.github.io)"

# Filter patterns for non-substantive administrative notices
ADMIN_NOISE_PATTERNS = [
    re.compile(r"\b(Unified Agenda of Federal Regulatory|Introduction to the Unified Agenda)\b", re.I),
    re.compile(r"\b(Renewal of the Innovation Advisory|Innovation Advisory Committee Meeting)\b", re.I),
    re.compile(r"\b(Community Outreach Office Locations|Substance Use Primary Prevention Month|Purple Heart Day)\b", re.I),
    re.compile(r"\b(Airworthiness Directives|Drug Interdiction Assistance|Military Spouse Commission)\b", re.I),
]

REGULATORY_TARGETS = [
    {
        "id": "us_fed_reg_ai",
        "name": "US Federal Register (AI Rules & Notices)",
        "jurisdiction": "United States",
        "type": "regulatory_gazette",
        "url": "https://www.federalregister.gov/api/v1/documents.json?conditions%5Bterm%5D=artificial+intelligence&order=newest",
        "format": "json_fedreg",
        "priority_base": 1
    },
    {
        "id": "us_fed_reg_eo",
        "name": "US Federal Register (Executive Orders)",
        "jurisdiction": "United States",
        "type": "executive_order",
        "url": "https://www.federalregister.gov/api/v1/documents.json?conditions%5Btype%5D%5B%5D=PRESDOCU&order=newest",
        "format": "json_fedreg",
        "priority_base": 1
    },
    {
        "id": "eu_ai_office",
        "name": "EU AI Office & Digital Strategy",
        "jurisdiction": "European Union",
        "type": "regulator_feed",
        "url": "https://digital-strategy.ec.europa.eu/en/feed",
        "format": "rss",
        "filter_ai": True,
        "priority_base": 1
    },
    {
        "id": "uk_cma_news",
        "name": "UK Competition and Markets Authority (AI Mergers & Foundation Models)",
        "jurisdiction": "United Kingdom",
        "type": "regulator_feed",
        "url": "https://www.gov.uk/search/news-and-communications.atom?organisations%5B%5D=competition-and-markets-authority",
        "format": "atom",
        "filter_ai": True,
        "priority_base": 2
    },
    {
        "id": "uk_ofgem_queue",
        "name": "UK Ofgem (Grid Queue & Regulatory Reform)",
        "jurisdiction": "United Kingdom",
        "type": "regulator_feed",
        "url": "https://www.gov.uk/search/news-and-communications.atom?organisations%5B%5D=ofgem",
        "format": "atom",
        "filter_ai": True,
        "priority_base": 2
    },
    {
        "id": "nist_ai_notices",
        "name": "NIST AI Safety Institute & Risk Framework",
        "jurisdiction": "United States",
        "type": "standard_body",
        "url": "https://www.nist.gov/news-events/news/rss.xml",
        "format": "rss",
        "filter_ai": True,
        "priority_base": 2
    },
    {
        "id": "sec_press_releases",
        "name": "US SEC (Enforcement & Regulatory Actions)",
        "jurisdiction": "United States",
        "type": "regulator_feed",
        "url": "https://www.sec.gov/news/pressreleases.rss",
        "format": "rss",
        "filter_ai": True,
        "priority_base": 2
    },
    {
        "id": "ftc_press_releases",
        "name": "US FTC (Consumer Protection & AI Claims)",
        "jurisdiction": "United States",
        "type": "regulator_feed",
        "url": "https://www.ftc.gov/feeds/press-release.xml",
        "format": "rss",
        "filter_ai": True,
        "priority_base": 2
    }
]

AI_KEYWORDS = re.compile(
    r"\b(artificial intelligence|machine learning|algorithm\w*|deepfake|watermark\w*|"
    r"transparency|foundation model|frontier model|high-risk|automated decision|ADM|"
    r"data centre|compute|semiconductor|export control|GPU|Nvidia|OpenAI|Anthropic|DeepMind)\b",
    re.IGNORECASE
)


def load_store() -> Dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if STORE_FILE.exists():
        try:
            return json.loads(STORE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"seen_hashes": {}, "last_run": None, "source_states": {}, "jurisdiction_hashes": {}}


def save_store(store: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STORE_FILE.write_text(json.dumps(store, indent=2), encoding="utf-8")


def load_alerts() -> List[Dict[str, Any]]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if ALERTS_FILE.exists():
        try:
            return json.loads(ALERTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def save_alerts(alerts: List[Dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ALERTS_FILE.write_text(json.dumps(alerts, indent=2), encoding="utf-8")


def fetch_url_text(url: str, timeout: int = 25) -> Optional[str]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = response.read()
            return data.decode("utf-8", errors="replace")
    except Exception:
        return None


def call_local_model(prompt: str, model: str = DEFAULT_MODEL, timeout: int = 240) -> Optional[Dict[str, Any]]:
    """Queries local Ollama instance (Qwen 3.8 / Nemotron / Gemma) via chat API."""
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a regulatory legal auditor. Respond strictly with a raw JSON object matching the requested schema. Do not output conversational filler."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "stream": False,
        "options": {
            "temperature": 0.05
        }
    }
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            content = res_data.get("message", {}).get("content", "")
            return parse_llm_json_response(content)
    except Exception as exc:
        print(f"  [Model Warning] Ollama query failed: {exc}")
        return None


def parse_llm_json_response(raw: str) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if match:
        raw_json = match.group(1)
    else:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw_json = raw[start:end+1]
        else:
            return None
    try:
        return json.loads(raw_json)
    except Exception:
        return None


def is_administrative_noise(title: str, summary: str) -> bool:
    text = title + " " + summary
    for pat in ADMIN_NOISE_PATTERNS:
        if pat.search(text):
            return True
    return False


def analyze_item_with_model(title: str, summary: str, source_name: str, url: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Evaluates document against statutory operator duty criteria."""
    # Fast path for known administrative noise
    if is_administrative_noise(title, summary):
        return {
            "is_operator_duty_shift": False,
            "duty_type": "none",
            "statutory_reference": None,
            "summary_finding": f"Administrative or procedural notice from {source_name}; imposes zero legal obligations on private AI operators.",
            "quantitative_claim_present": False,
            "denominator_disclosed": "n/a",
            "priority_score": 5,
            "actionable_trigger": "Archive as non-substantive administrative notice."
        }

    prompt = f"""You are the NM AI Research Sovereign Regulatory Evaluator.
Analyse the following official regulatory or industry update:

Source: {source_name}
Title: {title}
Summary/Snippet: {summary}
URL: {url}

Evaluate and return ONLY a valid JSON object with these exact keys:
{{
  "is_operator_duty_shift": true/false (true if a binding legal duty, transparency obligation, labelling mandate, or ADM explanation requirement is created, amended, or enforced),
  "duty_type": "transparency" | "labelling_watermark" | "adm_explanation" | "risk_assessment" | "merger_control" | "technical_release" | "none",
  "statutory_reference": "citation or clause number if mentioned, else null",
  "summary_finding": "1-2 sentences in measured UK English explaining the exact operational impact",
  "quantitative_claim_present": true/false,
  "denominator_disclosed": "yes" | "no" | "partial" | "n/a",
  "priority_score": 1 to 5 (1=Binding statute/court order, 2=Proposed rule/binding guidance, 3=Major lab release, 4=Academic audit, 5=Routine notice),
  "actionable_trigger": "specific next step or monitoring milestone"
}}
"""
    parsed = call_local_model(prompt, model=model)
    if parsed:
        return parsed

    # Deterministic fallback
    is_duty = bool(re.search(r"\b(rule|order|decree|enforce|duty|mandate|article|regulation|clause|transparency|watermark)\b", title + summary, re.I))
    return {
        "is_operator_duty_shift": is_duty,
        "duty_type": "transparency" if is_duty else "none",
        "statutory_reference": None,
        "summary_finding": f"Automated capture from {source_name}: {title}",
        "quantitative_claim_present": bool(re.search(r"\b\d+(?:\.\d+)?%|\$\d+", summary)),
        "denominator_disclosed": "partial",
        "priority_score": 2 if is_duty else 4,
        "actionable_trigger": "Review primary source for binding operator duties."
    }


def send_desktop_notification(title: str, body: str, urgency: str = "normal") -> None:
    """Dispatches desktop alert via notify-send on Linux."""
    if "DISPLAY" in os.environ or "WAYLAND_DISPLAY" in os.environ:
        try:
            subprocess.run(
                ["notify-send", "-a", "Sovereign Watch", "-u", urgency, title, body],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False
            )
        except Exception:
            pass


def send_pre_warning() -> None:
    """Sends desktop warning 5 minutes before scheduled 06:00 AM Qwen execution."""
    msg = "Qwen 3.8 (27B) will engage GPU VRAM in 5 minutes (06:00 AM). Please ensure gaming / heavy GPU loads are paused."
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] ⚡ Dispatching 5-minute GPU pre-warning...")
    send_desktop_notification("⚡ Sovereign Watch: GPU Pre-Warning (5m)", msg, urgency="critical")


def sweep_sovereign_gazettes(store: Dict[str, Any], model: str = DEFAULT_MODEL) -> List[Dict[str, Any]]:
    """Polls Federal Register, EU, UK, and standard bodies for newly gazetted documents."""
    new_alerts = []
    seen_hashes = store.setdefault("seen_hashes", {})

    for target in REGULATORY_TARGETS:
        t_id = target["id"]
        t_name = target["name"]
        raw_text = fetch_url_text(target["url"])
        if not raw_text:
            continue

        items_to_evaluate = []

        if target["format"] == "json_fedreg":
            try:
                data = json.loads(raw_text)
                for doc in data.get("results", [])[:10]:
                    doc_id = doc.get("document_number", doc.get("title", ""))
                    doc_title = doc.get("title", "Untitled Notice")
                    doc_abstract = doc.get("abstract", "") or doc_title
                    doc_url = doc.get("html_url", "")
                    doc_hash = hashlib.sha256(f"{doc_id}_{doc_title}".encode()).hexdigest()

                    if doc_hash not in seen_hashes:
                        seen_hashes[doc_hash] = dt.datetime.now(dt.timezone.utc).isoformat()
                        items_to_evaluate.append((doc_title, doc_abstract, doc_url, target["priority_base"]))
            except Exception:
                pass

        elif target["format"] in ("rss", "atom"):
            try:
                root = ET.fromstring(raw_text)
                for item in root.findall(".//item")[:10]:
                    title_el = item.find("title")
                    link_el = item.find("link")
                    desc_el = item.find("description")
                    title = title_el.text if title_el is not None and title_el.text else ""
                    link = link_el.text if link_el is not None and link_el.text else ""
                    desc = desc_el.text if desc_el is not None and desc_el.text else title

                    if target.get("filter_ai") and not AI_KEYWORDS.search(title + " " + desc):
                        continue

                    item_hash = hashlib.sha256(f"{link}_{title}".encode()).hexdigest()
                    if item_hash not in seen_hashes:
                        seen_hashes[item_hash] = dt.datetime.now(dt.timezone.utc).isoformat()
                        items_to_evaluate.append((title, desc, link, target["priority_base"]))

                for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry")[:10]:
                    title_el = entry.find("{http://www.w3.org/2005/Atom}title")
                    link_el = entry.find("{http://www.w3.org/2005/Atom}link")
                    summary_el = entry.find("{http://www.w3.org/2005/Atom}summary")
                    title = title_el.text if title_el is not None and title_el.text else ""
                    link = link_el.get("href", "") if link_el is not None else ""
                    summary = summary_el.text if summary_el is not None and summary_el.text else title

                    if target.get("filter_ai") and not AI_KEYWORDS.search(title + " " + summary):
                        continue

                    item_hash = hashlib.sha256(f"{link}_{title}".encode()).hexdigest()
                    if item_hash not in seen_hashes:
                        seen_hashes[item_hash] = dt.datetime.now(dt.timezone.utc).isoformat()
                        items_to_evaluate.append((title, summary, link, target["priority_base"]))
            except Exception:
                pass

        for title, summary, link, p_base in items_to_evaluate:
            analysis = analyze_item_with_model(title, summary, t_name, link, model=model)
            # The evaluated score governs; priority_base is only a fallback when the
            # model returned nothing. It was previously combined with min(), and since
            # lower means higher priority, a feed with priority_base 1 (the US Federal
            # Register) forced every item to P1 regardless of what the model read,
            # including airworthiness directives and office relocations. Fixed 2026-08-20.
            priority = analysis.get("priority_score") or p_base

            alert = {
                "id": f"alert_{int(time.time())}_{hashlib.md5(title.encode()).hexdigest()[:6]}",
                "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
                "source": t_name,
                "jurisdiction": target.get("jurisdiction", "Global"),
                "title": title,
                "url": link,
                "priority": priority,
                "is_operator_duty_shift": analysis.get("is_operator_duty_shift", False),
                "duty_type": analysis.get("duty_type", "none"),
                "statutory_reference": analysis.get("statutory_reference"),
                "summary": analysis.get("summary_finding", summary[:200]),
                "denominator_disclosed": analysis.get("denominator_disclosed", "n/a"),
                "actionable_trigger": analysis.get("actionable_trigger", "Review source document.")
            }
            new_alerts.append(alert)

            if priority in (1, 2) and alert["is_operator_duty_shift"]:
                send_desktop_notification(f"🚨 Sovereign Alert [{target.get('jurisdiction')}]: {title[:40]}...", alert["summary"], urgency="critical")

    return new_alerts


def write_alert_bulletin(alerts: List[Dict[str, Any]]) -> pathlib.Path:
    ALERTS_DIR.mkdir(parents=True, exist_ok=True)
    today_str = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    bulletin_path = ALERTS_DIR / f"sovereign_bulletin_{today_str}.md"

    lines = [
        f"# Sovereign Watch: AI Regulatory Bulletin ({today_str})",
        "",
        "**Global AI Regulatory Radar (L8 Continuous Stream)**",
        "",
        f"Total Active Alerts Banked: {len(alerts)}",
        "",
        "| Time (UTC) | Priority | Jurisdiction | Source | Finding & Duty | Statutory Ref |",
        "|---|---|---|---|---|---|"
    ]

    for a in alerts[:50]:
        # P5 was missing from this chain, so every routine notice rendered as P4.
        # Fixed 2026-08-20, same pass as the priority_base inflation fix.
        _p = a.get("priority", 4)
        pri_badge = {1: "🔴 P1", 2: "🟠 P2", 3: "🟡 P3", 4: "⚪ P4"}.get(_p, "⚪ P5")
        ref_text = f"[{a.get('statutory_reference') or 'Link'}]({a['url']})" if a.get('url') else (a.get('statutory_reference') or "Primary")
        clean_summary = a["summary"].replace("|", "/")
        lines.append(f"| {a['timestamp'][:16]} | {pri_badge} | **{a['jurisdiction']}** | {a['source']} | {clean_summary} | {ref_text} |")

    bulletin_path.write_text("\n".join(lines), encoding="utf-8")
    return bulletin_path


def run_surveillance_pass(model: str = DEFAULT_MODEL, trigger_rebuild: bool = True) -> Tuple[int, int]:
    store = load_store()
    existing_alerts = load_alerts()

    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] Executing Sovereign Watch pass with {model}...")
    t0 = time.time()
    gazette_alerts = sweep_sovereign_gazettes(store, model=model)
    new_alerts = gazette_alerts

    store["last_run"] = dt.datetime.now(dt.timezone.utc).isoformat()
    save_store(store)

    elapsed = time.time() - t0

    if new_alerts:
        updated_alerts = new_alerts + existing_alerts
        updated_alerts = updated_alerts[:250]
        save_alerts(updated_alerts)

        with ALERTS_LOG.open("a", encoding="utf-8") as f:
            for item in new_alerts:
                f.write(json.dumps(item) + "\n")

        write_alert_bulletin(updated_alerts)
        print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] 🚨 Discovered {len(new_alerts)} new surveillance items in {elapsed:.1f}s")
    else:
        print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] ✓ Sovereign Watch pass clean in {elapsed:.1f}s. All gazettes steady.")

    if trigger_rebuild:
        build_py = HERE / "build.py"
        if build_py.exists():
            subprocess.run([sys.executable, str(build_py)], cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        deck_py = WORKSPACE_ROOT / "Scripts" / "build_command_deck.py"
        if deck_py.exists():
            subprocess.run([sys.executable, str(deck_py)], cwd=deck_py.parent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    send_desktop_notification("✓ Sovereign Watch Complete", f"Daily regulatory sweep finished in {elapsed:.1f}s. GPU VRAM released.", urgency="normal")
    return len(new_alerts), len(existing_alerts) + len(new_alerts)


def main():
    parser = argparse.ArgumentParser(description="Sovereign Watch: Global AI Regulatory Radar")
    parser.add_argument("--sweep", action="store_true", help="Execute single surveillance pass")
    parser.add_argument("--pre-warn", action="store_true", help="Send 5-minute GPU pre-warning desktop notification")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help=f"Ollama model target (default: {DEFAULT_MODEL})")
    parser.add_argument("--status", action="store_true", help="Display current Sovereign Watch status")
    parser.add_argument("--alerts", action="store_true", help="Display recent high-priority alerts")
    args = parser.parse_args()

    if args.pre_warn:
        send_pre_warning()
        return

    if args.status:
        store = load_store()
        alerts = load_alerts()
        p1_cnt = len([a for a in alerts if a.get("priority") == 1])
        p2_cnt = len([a for a in alerts if a.get("priority") == 2])
        print("=== Sovereign Watch: Status & Health ===")
        print(f"Last pass timestamp: {store.get('last_run', 'Never')}")
        print(f"Tracked Document Hashes: {len(store.get('seen_hashes', {}))}")
        print(f"Total Banked Alerts: {len(alerts)} (Critical P1: {p1_cnt}, High P2: {p2_cnt})")
        print(f"Default Model Target: {DEFAULT_MODEL} ({OLLAMA_HOST})")
        return

    if args.alerts:
        alerts = load_alerts()
        print(f"=== Recent Sovereign Alerts (Top 15 of {len(alerts)}) ===")
        for a in alerts[:15]:
            pri = "🔴 P1" if a["priority"] == 1 else ("🟠 P2" if a["priority"] == 2 else "⚪ P3")
            print(f"[{a['timestamp'][:16]}] {pri} [{a['jurisdiction']}] {a['source']}: {a['title']}")
            print(f"   Duty: {a.get('duty_type')} | Ref: {a.get('statutory_reference')}")
            print(f"   Summary: {a.get('summary')}\n")
        return

    run_surveillance_pass(model=args.model)


if __name__ == "__main__":
    main()
