#!/usr/bin/env python3
"""Compatibility runner for continuous Sovereign Watch surveillance.

The shared Sovereign Watch implementation owns network intake, evaluation,
validated alert writes, bulletins, notifications and local rebuilds. This
entry point adds monitoring of the local jurisdiction-pack files used by the
legacy continuous runner.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import time
from typing import Any, Dict, List, Tuple

import sovereign_watch
from board_checks import (
    ALERT_SCHEMA_VERSION,
    evaluated_alert_priority,
    validate_regulatory_alerts,
)


HERE = pathlib.Path(__file__).resolve().parent
WORKSPACE_ROOT = HERE.parent
REGULATIONS_DIR = WORKSPACE_ROOT / "AI Regulations"
ALERTS_LOG = HERE / "data" / "live_alerts.jsonl"

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("SURVEILLANCE_MODEL", "gemma4:12b")


def load_store() -> Dict[str, Any]:
    return sovereign_watch.load_store()


def save_store(store: Dict[str, Any]) -> None:
    sovereign_watch.save_store(store)


def load_alerts() -> List[Dict[str, Any]]:
    return sovereign_watch.load_alerts()


def save_alerts(alerts: List[Dict[str, Any]]) -> None:
    sovereign_watch.save_alerts(alerts)


def analyze_item_with_model(
    title: str,
    summary: str,
    source_name: str,
    url: str,
) -> Dict[str, Any]:
    return sovereign_watch.analyze_item_with_model(
        title,
        summary,
        source_name,
        url,
        model=DEFAULT_MODEL,
    )


def sweep_sovereign_gazettes(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    return sovereign_watch.sweep_sovereign_gazettes(store, model=DEFAULT_MODEL)


def _local_diff_alert(
    *,
    alert_id: str,
    source: str,
    jurisdiction: str,
    title: str,
    path: pathlib.Path,
    queue_priority: int,
    statutory_reference: str,
    summary: str,
    actionable_trigger: str,
) -> Dict[str, Any]:
    return {
        "id": alert_id,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "alert_schema_version": ALERT_SCHEMA_VERSION,
        "source": source,
        "jurisdiction": jurisdiction,
        "title": title,
        "url": str(path),
        "source_queue_priority": queue_priority,
        "substantive_priority": None,
        "is_operator_duty_shift": False,
        "duty_type": "none",
        "statutory_reference": statutory_reference,
        "summary": summary,
        "denominator_disclosed": "unassessed",
        "actionable_trigger": actionable_trigger,
        "evaluation_method": "unassessed",
        "model": None,
        "reviewed": False,
    }


def sweep_local_regulations_packs(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Record local pack changes as unassessed intake, never as legal findings."""
    new_alerts: List[Dict[str, Any]] = []
    if not REGULATIONS_DIR.exists():
        return new_alerts

    jurisdiction_hashes = store.setdefault("jurisdiction_hashes", {})
    manifest_csv = REGULATIONS_DIR / "pipeline_manifest.csv"

    if manifest_csv.exists():
        manifest_hash = hashlib.sha256(manifest_csv.read_bytes()).hexdigest()
        previous_hash = jurisdiction_hashes.get("pipeline_manifest.csv")
        if previous_hash and manifest_hash != previous_hash:
            new_alerts.append(_local_diff_alert(
                alert_id=f"reg_manifest_diff_{int(time.time())}",
                source="AI Regulations Pipeline Manifest",
                jurisdiction="Multi-Jurisdiction Pipeline",
                title="Pipeline manifest updated",
                path=manifest_csv,
                queue_priority=1,
                statutory_reference="pipeline_manifest.csv",
                summary="The local jurisdiction manifest changed. Its substantive effect is unassessed.",
                actionable_trigger="Review the manifest change and re-run jurisdiction-pack integrity checks.",
            ))
        jurisdiction_hashes["pipeline_manifest.csv"] = manifest_hash

    for pack_dir in sorted(REGULATIONS_DIR.glob("*_monitor")):
        for filename in ("clauses.csv", "sources.csv", "findings.md"):
            path = pack_dir / filename
            if not path.exists():
                continue
            file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            key = f"{pack_dir.name}/{filename}"
            previous_hash = jurisdiction_hashes.get(key)
            if previous_hash and previous_hash != file_hash:
                new_alerts.append(_local_diff_alert(
                    alert_id=f"pack_diff_{int(time.time())}_{pack_dir.name[:10]}",
                    source=f"Local Pack: {pack_dir.name}",
                    jurisdiction=pack_dir.name.split("_")[0].capitalize(),
                    title=f"Local regulatory input changed: {key}",
                    path=path,
                    queue_priority=2,
                    statutory_reference=key,
                    summary=f"The local regulatory input {key} changed. Its substantive effect is unassessed.",
                    actionable_trigger=f"Review {key} before assigning a duty or substantive priority.",
                ))
            jurisdiction_hashes[key] = file_hash

    if new_alerts:
        validate_regulatory_alerts(new_alerts)
    return new_alerts


def write_alert_bulletin(alerts: List[Dict[str, Any]]) -> pathlib.Path:
    return sovereign_watch.write_alert_bulletin(alerts)


def run_surveillance_pass(trigger_rebuild: bool = True) -> Tuple[int, int]:
    """Run shared sovereign intake plus local-pack change detection."""
    store = load_store()
    existing_alerts = load_alerts()

    gazette_alerts = sweep_sovereign_gazettes(store)
    pack_alerts = sweep_local_regulations_packs(store)
    new_alerts = gazette_alerts + pack_alerts

    store["last_run"] = dt.datetime.now(dt.timezone.utc).isoformat()
    save_store(store)

    if new_alerts:
        updated_alerts = (new_alerts + existing_alerts)[:250]
        save_alerts(updated_alerts)

        ALERTS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ALERTS_LOG.open("a", encoding="utf-8") as handle:
            for item in new_alerts:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")

        write_alert_bulletin(updated_alerts)
        evaluated_p1 = sum(evaluated_alert_priority(item) == 1 for item in new_alerts)
        print(
            f"[{dt.datetime.now().strftime('%H:%M:%S')}] "
            f"Discovered {len(new_alerts)} new surveillance items "
            f"(evaluated P1: {evaluated_p1})"
        )
        if trigger_rebuild:
            sovereign_watch.run_rebuilds()
        total_alerts = len(updated_alerts)
    else:
        print(
            f"[{dt.datetime.now().strftime('%H:%M:%S')}] "
            "Surveillance pass clean. All gazettes and packs steady."
        )
        total_alerts = len(existing_alerts)

    return len(new_alerts), total_alerts


def run_daemon_loop(interval_seconds: int = 1800) -> None:
    """Run surveillance passes continuously at the configured interval."""
    print("AI Surveillance Daemon started")
    print(f"Polling interval: {interval_seconds}s")
    print(f"Local model: {DEFAULT_MODEL} @ {OLLAMA_HOST}")
    try:
        while True:
            run_surveillance_pass(trigger_rebuild=True)
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("Daemon terminated cleanly by user.")


def show_status() -> None:
    store = load_store()
    alerts = load_alerts()
    p1_count = sum(evaluated_alert_priority(item) == 1 for item in alerts)
    p2_count = sum(evaluated_alert_priority(item) == 2 for item in alerts)
    unassessed_count = sum(evaluated_alert_priority(item) is None for item in alerts)
    print("AI Surveillance status")
    print(f"Last pass timestamp: {store.get('last_run', 'Never')}")
    print(f"Tracked document hashes: {len(store.get('seen_hashes', {}))}")
    print(
        f"Total banked alerts: {len(alerts)} "
        f"(evaluated P1: {p1_count}, evaluated P2: {p2_count}, "
        f"unassessed: {unassessed_count})"
    )
    print(f"Local model target: {DEFAULT_MODEL} ({OLLAMA_HOST})")


def show_alerts() -> None:
    alerts = load_alerts()
    print(f"Recent surveillance alerts (top 15 of {len(alerts)})")
    for alert in alerts[:15]:
        priority = evaluated_alert_priority(alert)
        if alert.get("evaluation_method") == "legacy-unassessed":
            label = f"Legacy unassessed, raw P{alert.get('legacy_raw_priority')}"
        elif priority is None:
            label = "Unassessed"
        else:
            label = f"Evaluated P{priority}"
        print(
            f"[{alert['timestamp'][:16]}] {label} "
            f"[{alert['jurisdiction']}] {alert['source']}: {alert['title']}"
        )
        print(f"   Duty: {alert.get('duty_type')} | Ref: {alert.get('statutory_reference')}")
        print(f"   Summary: {alert.get('summary')}\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compatibility runner for continuous Sovereign Watch surveillance"
    )
    parser.add_argument("--once", action="store_true", help="run one surveillance pass")
    parser.add_argument("--daemon", action="store_true", help="run continuous surveillance")
    parser.add_argument("--interval", type=int, default=1800, help="polling interval in seconds")
    parser.add_argument("--status", action="store_true", help="display surveillance status")
    parser.add_argument("--alerts", action="store_true", help="display recent alerts")
    parser.add_argument("--test-model", action="store_true", help="test the configured local model")
    parser.add_argument("--no-rebuild", action="store_true", help="skip local rebuilds")
    args = parser.parse_args()

    if args.status:
        show_status()
        return 0
    if args.alerts:
        show_alerts()
        return 0
    if args.test_model:
        result = analyze_item_with_model(
            "Fixture regulatory notice",
            "A fixture for checking structured local-model output.",
            "Fixture source",
            "https://example.test/fixture",
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.daemon:
        run_daemon_loop(args.interval)
        return 0

    run_surveillance_pass(trigger_rebuild=not args.no_rebuild)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
