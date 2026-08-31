#!/usr/bin/env python3
"""Migrate Sovereign Watch alerts to schema version 2 with exact-byte recovery."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import pathlib
import tempfile
from collections.abc import Callable
from typing import Any

from board_checks import ALERT_SCHEMA_VERSION, validate_regulatory_alerts


HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_INPUT = HERE / "data" / "regulatory_alerts.json"

SOURCE_QUEUE_PRIORITIES = {
    "US Federal Register (AI Rules & Notices)": 1,
    "US Federal Register (Executive Orders)": 1,
    "EU AI Office & Digital Strategy": 1,
    "UK Competition and Markets Authority (AI Mergers & Foundation Models)": 2,
    "UK Ofgem (Grid Queue & Regulatory Reform)": 2,
    "NIST AI Safety Institute & Risk Framework": 2,
    "US SEC (Enforcement & Regulatory Actions)": 2,
    "US FTC (Consumer Protection & AI Claims)": 2,
}


class MigrationError(RuntimeError):
    """Raised when a migration cannot preserve the complete input state."""


def _valid_priority(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and 1 <= value <= 5


def _stored_priority(alert: dict[str, Any]) -> int:
    values = [alert[key] for key in ("priority", "priority_score") if key in alert]
    if not values or any(not _valid_priority(value) for value in values):
        raise MigrationError("record has invalid or missing stored priority")
    if len(set(values)) != 1:
        raise MigrationError("record has conflicting stored priority fields")
    return values[0]


def migrate_alert(alert: dict[str, Any]) -> dict[str, Any]:
    """Return one deterministic schema-versioned record without changing its input."""
    if not isinstance(alert, dict):
        raise MigrationError("record is not an object")
    if alert.get("alert_schema_version") == ALERT_SCHEMA_VERSION:
        return copy.deepcopy(alert)
    if "alert_schema_version" in alert:
        raise MigrationError("record has an unsupported alert schema version")

    migrated = copy.deepcopy(alert)
    raw_priority = _stored_priority(alert)
    source = alert.get("source")
    if source not in SOURCE_QUEUE_PRIORITIES:
        raise MigrationError(f"record has no declared source queue priority: {source!r}")

    method = alert.get("evaluation_method")
    migrated["alert_schema_version"] = ALERT_SCHEMA_VERSION
    migrated["source_queue_priority"] = SOURCE_QUEUE_PRIORITIES[source]

    if method is None:
        migrated["evaluation_method"] = "legacy-unassessed"
        migrated["model"] = None
        migrated["substantive_priority"] = None
        migrated["legacy_raw_priority"] = raw_priority
    elif method == "unassessed":
        migrated["substantive_priority"] = None
        migrated.pop("legacy_raw_priority", None)
    elif method in {"local-model", "administrative-noise-rule", "human"}:
        migrated["substantive_priority"] = raw_priority
        migrated.pop("legacy_raw_priority", None)
    else:
        raise MigrationError(f"record has unsupported evaluation method: {method!r}")

    return migrated


def migrate_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Migrate and validate a complete non-empty alert bank."""
    if not isinstance(records, list) or not records:
        raise MigrationError("input alert bank must be a non-empty list")
    migrated = []
    for index, record in enumerate(records):
        try:
            migrated.append(migrate_alert(record))
        except Exception as exc:
            raise MigrationError(f"record {index} migration failed: {exc}") from exc
    try:
        validate_regulatory_alerts(migrated)
    except Exception as exc:
        raise MigrationError(f"migrated bank failed validation: {exc}") from exc
    return migrated


def serialise_records(records: list[dict[str, Any]]) -> bytes:
    """Return deterministic UTF-8 JSON bytes for a validated bank."""
    validate_regulatory_alerts(records)
    return (json.dumps(records, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _write_verified_temporary(destination: pathlib.Path, payload: bytes) -> pathlib.Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb", dir=destination.parent, prefix=f".{destination.name}.", delete=False
    ) as temporary:
        temporary_path = pathlib.Path(temporary.name)
        temporary.write(payload)
        temporary.flush()
        os.fsync(temporary.fileno())
    if temporary_path.read_bytes() != payload:
        temporary_path.unlink(missing_ok=True)
        raise MigrationError(f"staged output verification failed for {destination}")
    return temporary_path


def migrate_path(
    input_path: pathlib.Path,
    backup_path: pathlib.Path,
    fault: Callable[[str, pathlib.Path], None] | None = None,
) -> dict[str, Any]:
    """Back up exact input bytes and atomically replace only verified migrated output."""
    input_path = pathlib.Path(input_path)
    backup_path = pathlib.Path(backup_path)
    if backup_path.exists():
        raise MigrationError(f"backup already exists: {backup_path}")

    original = input_path.read_bytes()
    if fault:
        fault("after_read", input_path)
    try:
        decoded = original.decode("utf-8")
        records = json.loads(decoded)
    except Exception as exc:
        raise MigrationError(f"input is not complete UTF-8 JSON: {exc}") from exc

    migrated = migrate_records(records)
    output = serialise_records(migrated)

    backup_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with backup_path.open("xb") as backup:
            backup.write(original)
            backup.flush()
            os.fsync(backup.fileno())
    except Exception as exc:
        raise MigrationError(f"cannot create exact-byte backup: {exc}") from exc
    if backup_path.read_bytes() != original:
        raise MigrationError("backup verification failed")

    temporary_path = _write_verified_temporary(input_path, output)
    try:
        if fault:
            fault("after_temp_write", temporary_path)
        observed = temporary_path.read_bytes()
        if observed != output:
            raise MigrationError("staged migration output is incomplete or changed")
        validate_regulatory_alerts(json.loads(observed.decode("utf-8")))
        os.replace(temporary_path, input_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    if input_path.read_bytes() != output:
        raise MigrationError("post-replacement migration verification failed")

    methods = {}
    for alert in migrated:
        method = alert["evaluation_method"]
        methods[method] = methods.get(method, 0) + 1
    return {
        "status": "applied",
        "alert_schema_version": ALERT_SCHEMA_VERSION,
        "records": len(migrated),
        "input_path": str(input_path),
        "backup_path": str(backup_path),
        "input_sha256": hashlib.sha256(original).hexdigest(),
        "output_sha256": hashlib.sha256(output).hexdigest(),
        "backup_sha256": hashlib.sha256(backup_path.read_bytes()).hexdigest(),
        "method_counts": methods,
        "reviewed_true": sum(item.get("reviewed") is True for item in migrated),
        "reviewed_false": sum(item.get("reviewed") is False for item in migrated),
        "reviewed_missing": sum("reviewed" not in item for item in migrated),
        "reversible_with_exact_byte_backup": True,
    }


def restore_path(input_path: pathlib.Path, backup_path: pathlib.Path) -> str:
    """Restore the exact backup bytes through a verified atomic replacement."""
    input_path = pathlib.Path(input_path)
    backup_path = pathlib.Path(backup_path)
    payload = backup_path.read_bytes()
    temporary_path = _write_verified_temporary(input_path, payload)
    try:
        os.replace(temporary_path, input_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    if input_path.read_bytes() != payload:
        raise MigrationError("restored bytes do not match the backup")
    return hashlib.sha256(payload).hexdigest()


def write_new_report(report_path: pathlib.Path, report: dict[str, Any]) -> None:
    """Create a separately verified migration report without overwriting prior evidence."""
    report_path = pathlib.Path(report_path)
    if report_path.exists():
        raise MigrationError(f"report already exists: {report_path}")
    payload = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary_path = _write_verified_temporary(report_path, payload)
    try:
        os.link(temporary_path, report_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    temporary_path.unlink(missing_ok=True)
    if report_path.read_bytes() != payload:
        raise MigrationError("migration report verification failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=pathlib.Path, default=DEFAULT_INPUT)
    parser.add_argument("--backup", type=pathlib.Path, required=True)
    parser.add_argument("--report", type=pathlib.Path)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()

    if args.write == args.restore:
        raise MigrationError("select exactly one of --write or --restore")
    if args.restore:
        restored_hash = restore_path(args.input, args.backup)
        print(json.dumps({"status": "restored", "sha256": restored_hash}, indent=2))
        return 0
    if args.report is None:
        raise MigrationError("--report is required with --write")

    report = migrate_path(args.input, args.backup)
    write_new_report(args.report, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
