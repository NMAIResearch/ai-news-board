#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ai_surveillance_daemon.py - L8 Autonomous Continuous Surveillance Daemon.

Monitors:
1. Sovereign regulatory gazettes, legislative feeds, and regulator notices (US, EU, UK, CA, CN, Global 29-pack).
2. Frontier AI lab newsrooms and technical release feeds.
3. High-signal research streams (arXiv, Hugging Face, academic institutes).

Pipeline:
- Content ingestion -> SHA-256 hash-diffing against surveillance_store.json.
- Delta extraction -> local Ollama model prompt (gemma4:12b / qwen3.8:27b).
- Structured scoring: Operator duties, statutory citations, denominator audit, priority score (1 to 5).
- Real-time alerting: data/regulatory_alerts.json, live desktop notification, and markdown bulletin.
- Autonomous rebuild: Triggers build.py and Scripts/build_command_deck.py.
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
STORE_FILE = DATA_DIR / "surveillance_store.json"
ALERTS_FILE = DATA_DIR / "regulatory_alerts.json"
ALERTS_LOG = DATA_DIR / "live_alerts.jsonl"

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("SURVEILLANCE_MODEL", "gemma4:12b")

USER_AGENT = "NM-AI-Research-Surveillance-Daemon/1.0 (+https://nmairesearch.github.io)"

# Priority 1: Binding Sovereign Law / Regulator Order
# Priority 2: Formal Proposed Rule / Binding Guidance / High-Severity Audit
# Priority 3: Frontier Lab Technical Release / Weight Drop
# Priority 4: Independent Research & Chokepoint Analysis
# Priority 5: Vendor PR & Routine Announcements

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

FRONTIER_LAB_TARGETS = [
    {
        "id": "deepmind_blog",
        "name": "Google DeepMind Blog",
        "type": "vendor_own",
        "url": "https://deepmind.google/blog/rss.xml",
        "format": "rss",
        "priority_base": 3
    },
    {
        "id": "openai_news",
        "name": "OpenAI Newsroom & Research",
        "type": "vendor_own",
        "url": "https://openai.com/news/rss.xml",
        "format": "rss",
        "priority_base": 3
    },
    {
        "id": "cset_georgetown",
        "name": "CSET Georgetown AI Policy",
        "type": "independent_research",
        "url": "https://cset.georgetown.edu/feed/",
        "format": "rss",
        "priority_base": 3
    },
    {
        "id": "ainow_institute",
        "name": "AI Now Institute",
        "type": "independent_research",
        "url": "https://ainowinstitute.org/feed",
        "format": "rss",
        "priority_base": 3
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
    except Exception as exc:
        return None


def call_local_model(prompt: str, model: str = DEFAULT_MODEL, timeout: int = 180) -> Optional[str]:
    """Queries local Ollama instance for structured JSON delta analysis."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.05,
            "num_predict": 1200
        }
    }
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            return res_data.get("response", "")
    except Exception as exc:
        return None


def parse_llm_json_response(raw: str) -> Optional[Dict[str, Any]]:
    """Extracts the first valid JSON block from a model output."""
    if not raw:
        return None
    # Strip markdown code fencing if present
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if match:
        raw_json = match.group(1)
    else:
        # Match outermost braces
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


def analyze_item_with_model(title: str, summary: str, source_name: str, url: str) -> Dict[str, Any]:
    """Evaluates a document against legal operator duty and claim criteria using local model."""
    prompt = f"""You are the NM AI Research L8 Autonomous Surveillance Evaluator.
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
  "priority_score": 1 to 5 (1=Binding statute/court order, 2=Proposed rule/binding guidance, 3=Major lab release, 4=Academic audit, 5=Routine PR),
  "actionable_trigger": "specific next step or monitoring milestone"
}}
"""
    raw_response = call_local_model(prompt)
    if raw_response:
        parsed = parse_llm_json_response(raw_response)
        if parsed:
            return parsed

    # Deterministic heuristic fallback if model is offline
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


def send_desktop_notification(title: str, body: str) -> None:
    """Dispatches desktop alert via notify-send on Linux if display is active."""
    if "DISPLAY" in os.environ or "WAYLAND_DISPLAY" in os.environ:
        try:
            subprocess.run(
                ["notify-send", "-a", "AI Surveillance Daemon", "-u", "critical", title, body],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False
            )
        except Exception:
            pass


def sweep_sovereign_gazettes(store: Dict[str, Any]) -> List[Dict[str, Any]]:
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
                # Handle standard RSS items
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

                # Handle standard Atom entries
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

        # Evaluate new items with local model
        for title, summary, link, p_base in items_to_evaluate:
            analysis = analyze_item_with_model(title, summary, t_name, link)
            priority = min(p_base, analysis.get("priority_score", p_base))
            
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

            if priority in (1, 2):
                send_desktop_notification(f"🚨 Regulatory Alert [{target.get('jurisdiction')}]: {title[:40]}...", alert["summary"])

    return new_alerts


def sweep_local_regulations_packs(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Monitors the 29 jurisdiction packs in 'AI Regulations' for local statute / manifest file diffs."""
    new_alerts = []
    if not REGULATIONS_DIR.exists():
        return new_alerts

    jurisdiction_hashes = store.setdefault("jurisdiction_hashes", {})
    manifest_csv = REGULATIONS_DIR / "pipeline_manifest.csv"

    if manifest_csv.exists():
        m_hash = hashlib.sha256(manifest_csv.read_bytes()).hexdigest()
        prev_hash = jurisdiction_hashes.get("pipeline_manifest.csv")
        if prev_hash and m_hash != prev_hash:
            alert = {
                "id": f"reg_manifest_diff_{int(time.time())}",
                "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
                "source": "AI Regulations Pipeline Manifest",
                "jurisdiction": "Multi-Jurisdiction Pipeline",
                "title": "Pipeline Manifest Updated (New Jurisdiction / Instrument Added)",
                "url": str(manifest_csv),
                "priority": 1,
                "is_operator_duty_shift": True,
                "duty_type": "statutory_manifest_update",
                "statutory_reference": "pipeline_manifest.csv",
                "summary": "The master jurisdiction manifest was modified, indicating newly tracked statutory obligations or deposit updates.",
                "denominator_disclosed": "yes",
                "actionable_trigger": "Run verify_jurisdiction_packs.py to re-validate integrity."
            }
            new_alerts.append(alert)
        jurisdiction_hashes["pipeline_manifest.csv"] = m_hash

    # Check individual monitor directories for newly created evidence or csv rows
    for pack_dir in sorted(REGULATIONS_DIR.glob("*_monitor")):
        for target_file in ("clauses.csv", "sources.csv", "findings.md"):
            fp = pack_dir / target_file
            if fp.exists():
                f_hash = hashlib.sha256(fp.read_bytes()).hexdigest()
                key = f"{pack_dir.name}/{target_file}"
                prev = jurisdiction_hashes.get(key)
                if prev and prev != f_hash:
                    alert = {
                        "id": f"pack_diff_{int(time.time())}_{pack_dir.name[:10]}",
                        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
                        "source": f"Local Pack: {pack_dir.name}",
                        "jurisdiction": pack_dir.name.split("_")[0].capitalize(),
                        "title": f"Regulatory Delta: {target_file} updated in {pack_dir.name}",
                        "url": str(fp),
                        "priority": 2,
                        "is_operator_duty_shift": True,
                        "duty_type": "local_evidence_delta",
                        "statutory_reference": key,
                        "summary": f"Local regulatory pack {pack_dir.name} received empirical updates in {target_file}.",
                        "denominator_disclosed": "yes",
                        "actionable_trigger": f"Audit {pack_dir.name} changes and regenerate comparative tools."
                    }
                    new_alerts.append(alert)
                jurisdiction_hashes[key] = f_hash

    return new_alerts


def write_alert_bulletin(alerts: List[Dict[str, Any]]) -> pathlib.Path:
    """Writes a dated Markdown bulletin in alerts/ summarizing recent alerts."""
    ALERTS_DIR.mkdir(parents=True, exist_ok=True)
    today_str = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    bulletin_path = ALERTS_DIR / f"regulatory_bulletin_{today_str}.md"

    lines = [
        f"# AI Regulatory and Surveillance Bulletin: {today_str}",
        "",
        "**Autonomous Continuous Surveillance Feed (L8 Stream)**",
        "",
        f"Total Active Alerts Banked: {len(alerts)}",
        "",
        "| Time (UTC) | Priority | Jurisdiction | Source | Finding & Duty | Reference |",
        "|---|---|---|---|---|---|"
    ]

    for a in alerts[:50]:
        pri_badge = "🔴 P1" if a["priority"] == 1 else ("🟠 P2" if a["priority"] == 2 else ("🟡 P3" if a["priority"] == 3 else "⚪ P4"))
        ref_text = f"[{a.get('statutory_reference') or 'Link'}]({a['url']})" if a.get('url') else (a.get('statutory_reference') or "Primary")
        clean_summary = a["summary"].replace("|", "/")
        lines.append(f"| {a['timestamp'][:16]} | {pri_badge} | **{a['jurisdiction']}** | {a['source']} | {clean_summary} | {ref_text} |")

    bulletin_path.write_text("\n".join(lines), encoding="utf-8")
    return bulletin_path


def run_surveillance_pass(trigger_rebuild: bool = True) -> Tuple[int, int]:
    """Executes a single end-to-end surveillance sweep."""
    store = load_store()
    existing_alerts = load_alerts()

    gazette_alerts = sweep_sovereign_gazettes(store)
    pack_alerts = sweep_local_regulations_packs(store)
    new_alerts = gazette_alerts + pack_alerts

    store["last_run"] = dt.datetime.now(dt.timezone.utc).isoformat()
    save_store(store)

    if new_alerts:
        updated_alerts = new_alerts + existing_alerts
        # Keep latest 250 alerts
        updated_alerts = updated_alerts[:250]
        save_alerts(updated_alerts)

        # Append to live alerts jsonl
        with ALERTS_LOG.open("a", encoding="utf-8") as f:
            for item in new_alerts:
                f.write(json.dumps(item) + "\n")

        write_alert_bulletin(updated_alerts)
        print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] 🚨 Discovered {len(new_alerts)} new surveillance items (P1: {len([a for a in new_alerts if a['priority']==1])})")

        if trigger_rebuild:
            # Trigger build.py in Project AI News Board
            build_py = HERE / "build.py"
            if build_py.exists():
                subprocess.run([sys.executable, str(build_py)], cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # Trigger build_command_deck.py in Scripts
            deck_py = WORKSPACE_ROOT / "Scripts" / "build_command_deck.py"
            if deck_py.exists():
                subprocess.run([sys.executable, str(deck_py)], cwd=deck_py.parent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] ✓ Surveillance pass clean. All gazettes and packs steady.")

    return len(new_alerts), len(existing_alerts) + len(new_alerts)


def run_daemon_loop(interval_seconds: int = 1800) -> None:
    """Continuous daemon loop running surveillance passes at configured intervals."""
    print(f"=== AI Surveillance Daemon (L8 Continuous Stream) Started ===")
    print(f"Polling interval: {interval_seconds}s ({interval_seconds / 60:.1f} min)")
    print(f"Local Model: {DEFAULT_MODEL} @ {OLLAMA_HOST}")
    print(f"Regulatory targets: {len(REGULATORY_TARGETS)} feeds | 29 Jurisdiction Packs")
    print("Press Ctrl+C to terminate.\n")

    try:
        while True:
            run_surveillance_pass(trigger_rebuild=True)
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("\nDaemon terminated cleanly by user.")


def main():
    parser = argparse.ArgumentParser(description="L8 Autonomous Regulatory & AI News Surveillance Daemon")
    parser.add_argument("--once", action="store_true", help="Run a single surveillance sweep and exit")
    parser.add_argument("--daemon", action="store_true", help="Run continuously as background daemon")
    parser.add_argument("--interval", type=int, default=1800, help="Polling interval in seconds for daemon (default: 1800s / 30m)")
    parser.add_argument("--status", action="store_true", help="Display current surveillance engine status")
    parser.add_argument("--alerts", action="store_true", help="Display recent high-priority alerts")
    parser.add_argument("--test-model", action="store_true", help="Test local Ollama model evaluation on a sample statute")
    parser.add_argument("--no-rebuild", action="store_true", help="Skip automatic rebuild of web dashboards")
    args = parser.parse_args()

    if args.status:
        store = load_store()
        alerts = load_alerts()
        p1_cnt = len([a for a in alerts if a.get("priority") == 1])
        p2_cnt = len([a for a in alerts if a.get("priority") == 2])
        print("=== NM AI Research: L8 Surveillance Status ===")
        print(f"Last pass timestamp: {store.get('last_run', 'Never')}")
        print(f"Tracked Document Hashes: {len(store.get('seen_hashes', {}))}")
        print(f"Total Banked Alerts: {len(alerts)} (Critical P1: {p1_cnt}, High P2: {p2_cnt})")
        print(f"Local Model Target: {DEFAULT_MODEL} ({OLLAMA_HOST})")
        return

    if args.alerts:
        alerts = load_alerts()
        print(f"=== Recent Surveillance Alerts (Top 15 of {len(alerts)}) ===")
        for a in alerts[:15]:
            pri = "🔴 P1" if a["priority"] == 1 else ("🟠 P2" if a["priority"] == 2 else "⚪ P3")
            print(f"[{a['timestamp'][:16]}] {pri} [{a['jurisdiction']}] {a['source']}: {a['title']}")
            print(f"   Duty: {a.get('duty_type')} | Ref: {a.get('statutory_reference')}")
            print(f"   Summary: {a.get('summary')}\n")
        return

    if args.test_model:
        print("Testing local Ollama model connection...")
        sample_title = "EU AI Office publishes final conformity guidance on Article 50 marking duties"
        sample_snippet = "The European AI Office issued binding technical specifications requiring providers to mark synthetic audio-visual outputs under Article 50(2) starting 2 December 2026."
        res = analyze_item_with_model(sample_title, sample_snippet, "EU Official Journal", "https://digital-strategy.ec.europa.eu")
        print("Model Structured Output:")
        print(json.dumps(res, indent=2))
        return

    if args.daemon:
        run_daemon_loop(args.interval)
    else:
        run_surveillance_pass(trigger_rebuild=not args.no_rebuild)


if __name__ == "__main__":
    main()
