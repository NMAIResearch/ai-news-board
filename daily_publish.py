#!/usr/bin/env python3
"""Publish a bounded daily board refresh after deterministic integrity checks."""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import fnmatch
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request
from typing import Iterable

from board_checks import BoardIntegrityError, validate_regulatory_alerts as validate_regulatory_alert_records


REPO = pathlib.Path(__file__).resolve().parent
LOCK_PATH = pathlib.Path("/tmp/nmai-news-board-daily.lock")
PAGES_URL = "https://nmairesearch.github.io/ai-news-board/index.html"

PRE_SWEEP_PATTERNS = (
    "data/regulatory_alerts.json",
    "data/surveillance_store.json",
    "index.html",
)

PUBLISH_PATTERNS = (
    "archive.json",
    "article_evidence.json",
    "article_spans.json",
    "data/*.json",
    "feed_items.json",
    "index.html",
    "releases.json",
    "reviews_store.json",
    "upcoming_models.json",
    "vendor_titles.json",
)


class PublishError(RuntimeError):
    """Raised when automatic publication cannot prove its preconditions."""


def run(args: list[str], *, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=REPO,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.stdout:
        print(result.stdout, end="")
    if check and result.returncode:
        raise PublishError(f"command failed ({result.returncode}): {' '.join(args)}")
    return result


def git(*args: str, check: bool = True) -> str:
    return run(["git", *args], check=check).stdout.rstrip("\n")


def status_paths(raw: str) -> list[str]:
    """Extract paths from porcelain v1 output and reject rename ambiguity."""
    paths = []
    for line in raw.splitlines():
        if not line:
            continue
        if len(line) < 4:
            raise PublishError(f"unrecognised git status record: {line!r}")
        status = line[:2]
        if "R" in status or "C" in status:
            raise PublishError(f"rename or copy is outside the daily publisher: {line}")
        path = line[3:]
        if path.startswith('"') and path.endswith('"'):
            path = json.loads(path)
        paths.append(path)
    return paths


def changed_paths() -> list[str]:
    return status_paths(git("status", "--porcelain=v1", "--untracked-files=all"))


def matches_any(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def require_allowed(paths: Iterable[str], patterns: Iterable[str], label: str) -> list[str]:
    paths = list(paths)
    blocked = [path for path in paths if not matches_any(path, patterns)]
    if blocked:
        raise PublishError(f"{label} includes paths outside the allowlist: {', '.join(blocked)}")
    return paths


def require_today(paths: Iterable[str], today: dt.date | None = None) -> None:
    today = today or dt.datetime.now().astimezone().date()
    stale = []
    for relative in paths:
        path = REPO / relative
        if not path.exists() or dt.datetime.fromtimestamp(path.stat().st_mtime).astimezone().date() != today:
            stale.append(relative)
    if stale:
        raise PublishError(f"pre-existing generated changes are not from today: {', '.join(stale)}")


def validate_json_files(paths: Iterable[str]) -> None:
    for relative in paths:
        if relative.endswith(".json"):
            json.loads((REPO / relative).read_text(encoding="utf-8"))
        elif relative.endswith(".jsonl"):
            for line_number, line in enumerate((REPO / relative).read_text(encoding="utf-8").splitlines(), 1):
                if line.strip():
                    try:
                        json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise PublishError(f"invalid JSONL in {relative}:{line_number}: {exc}") from exc


def validate_machine_review_flags() -> None:
    feed = json.loads((REPO / "feed_items.json").read_text(encoding="utf-8"))
    items = feed.get("items", []) if isinstance(feed, dict) else feed
    invalid = [
        item.get("headline", item.get("title", "untitled"))
        for item in items
        if item.get("reviewed") is True
        and item.get("label_source") in {"machine", "deterministic"}
    ]
    if invalid:
        raise PublishError(f"machine-labelled items claim human review: {', '.join(invalid[:10])}")


def validate_regulatory_alerts() -> None:
    path = REPO / "data" / "regulatory_alerts.json"
    if not path.exists():
        return
    alerts = json.loads(path.read_text(encoding="utf-8"))
    try:
        validate_regulatory_alert_records(alerts)
    except BoardIntegrityError as exc:
        raise PublishError(str(exc)) from exc


def verify_pages(local_path: pathlib.Path, attempts: int = 18, delay: int = 10) -> None:
    expected = hashlib.sha256(local_path.read_bytes()).hexdigest()
    for attempt in range(attempts):
        url = f"{PAGES_URL}?v={int(time.time())}"
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "NM-AI-Research-Daily-Publisher/1.0"})
            with urllib.request.urlopen(request, timeout=20) as response:
                observed = hashlib.sha256(response.read()).hexdigest()
            if observed == expected:
                print(f"Verified live index hash: {expected}")
                return
        except Exception as exc:
            print(f"Live verification attempt {attempt + 1} failed: {exc}")
        if attempt + 1 < attempts:
            time.sleep(delay)
    raise PublishError("GitHub Pages did not serve the committed index bytes within the verification window")


def check_repository_start() -> list[str]:
    if git("branch", "--show-current") != "main":
        raise PublishError("daily publication requires the main branch")
    run(["git", "fetch", "origin"])
    if git("rev-parse", "HEAD") != git("rev-parse", "@{u}"):
        raise PublishError("local HEAD and its upstream differ; no merge or rebase is automated")
    pre_existing = require_allowed(changed_paths(), PRE_SWEEP_PATTERNS, "pre-existing change set")
    require_today(pre_existing)
    return pre_existing


def run_gates(paths: list[str]) -> None:
    validate_json_files(paths)
    validate_machine_review_flags()
    validate_regulatory_alerts()
    run([sys.executable, "board_checks.py"])
    run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"])
    run(["git", "diff", "--check"])


def publish() -> None:
    check_repository_start()
    env = os.environ.copy()
    env.setdefault("LABEL_MODEL", "gemma4:12b")
    result = run(["bash", "refresh.sh"], check=False, env=env)
    if result.returncode:
        raise PublishError("refresh.sh failed")
    if any(line.lstrip().startswith("!") for line in result.stdout.splitlines()):
        raise PublishError("refresh.sh reported a failed stage")

    paths = require_allowed(changed_paths(), PUBLISH_PATTERNS, "post-refresh change set")
    if not paths:
        print("No generated changes to publish.")
        return
    run_gates(paths)

    run(["git", "add", "--", *paths])
    run(["git", "diff", "--cached", "--check"])
    stamp = dt.datetime.now().astimezone().date().isoformat()
    message = (
        f"Refresh AI News Board and Sovereign Watch ({stamp})\n\n"
        "Feed labels: local model or deterministic rules, visibly unreviewed.\n"
        "Regulatory classifications: unverified machine candidates."
    )
    run(["git", "commit", "-m", message])
    run(["git", "push", "origin", "HEAD:main"])
    verify_pages(REPO / "index.html")


def check_only() -> None:
    check_repository_start()
    paths = require_allowed(changed_paths(), PUBLISH_PATTERNS, "current change set")
    run_gates(paths)
    print("Daily publisher preconditions and local gates passed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="run preconditions and gates without refreshing, committing or pushing")
    args = parser.parse_args()
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PublishError("another daily publisher is running") from exc
        if args.check_only:
            check_only()
        else:
            publish()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PublishError as exc:
        print(f"Daily publication stopped: {exc}", file=sys.stderr)
        raise SystemExit(1)
