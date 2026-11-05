"""Bounded feed intake, source text extraction and durable processing primitives."""

from __future__ import annotations

import contextlib
import bisect
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import ipaddress
import http.client
from pathlib import Path
import tempfile
from html.parser import HTMLParser
from urllib.parse import urlparse
import xml.etree.ElementTree as ET


ATOM = "{http://www.w3.org/2005/Atom}"
MAX_FEED_PAGES = 5
LOOKBACK_DAYS = 30
MAX_SOURCE_BYTES = 4_000_000
MAX_TEXT_CHARS = 120_000
PASSAGE_SEPARATOR = "\n[... omitted source text ...]\n"
CAPTURE_FAILURE_RUNS = 3
END_STATE_RECHECK_RUNS = 7
ASSESSMENT_END_REASONS = {"no AI keyword match", "input budget too small", "model assessment unsuccessful"}
END_REASONS = ASSESSMENT_END_REASONS | {
    "insufficient source text", "source response exceeds byte limit", "source response is not UTF-8",
    "source returned an error or access challenge", "source document is unavailable", "source capture failed",
} | {f"source HTTP status {code}" for code in range(400, 600)}
# Passage vocabulary is separate from the feed filter.
PASSAGE_TERMS = (
    (3, r"artificial[ -]intelligence|machine[ -]learning|(?:foundation|frontier|large language)[ -]models?|generative(?:[ -]AI)?|neural[ -]networks?"),
    (2, r"AIs?|A\.I\.?|LLMs?|chatbots?|deepfakes?|automated[ -]decisions?(?:[ -]making)?|automated[ -]systems?|algorithm\w*|GPUs?|data[ -]cent(?:re|er)s?|semiconductors?|export[ -]controls?|biometrics?|OpenAI|Anthropic|Nvidia|DeepMind|watermark\w*"),
    (1, r"compute|transparency|high-risk|ADM"),
)
PASSAGE_PATTERNS = [(weight, re.compile(r"\b(?:" + pattern + r")\b", re.I))
                    for weight, pattern in PASSAGE_TERMS]
PASSAGE_KEYWORDS = re.compile(r"\b(?:" + "|".join(p for _, p in PASSAGE_TERMS) + r")\b", re.I)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def public_url(url):
    if not isinstance(url, str) or re.search(r"[\s\x00-\x1f\x7f]", url):
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return False
    if parsed.hostname.lower() in {"localhost", "localhost.localdomain"}:
        return False
    try:
        return ipaddress.ip_address(parsed.hostname).is_global
    except ValueError:
        return True


def source_document_url(url):
    """Use the Federal Register's document-body endpoint to exclude page furniture."""
    parsed = urlparse(url)
    match = re.match(r"^/documents/(\d{4}/\d{2}/\d{2})/(\d{4}-\d+)(?:/|$)", parsed.path)
    if parsed.hostname == "www.federalregister.gov" and match:
        return f"https://www.federalregister.gov/documents/full_text/html/{match[1]}/{match[2]}.html"
    return url


def atomic_json(path, value):
    """Replace a complete JSON file after flushing and validating the staged bytes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".sw-", delete=False) as f:
            name = Path(f.name)
            f.write(encoded)
            f.flush()
            os.fsync(f.fileno())
        if name.read_bytes() != encoded:
            raise OSError("staged JSON bytes differ")
        json.loads(name.read_bytes())
        os.replace(name, path)
        name = None
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if name is not None:
            name.unlink(missing_ok=True)


def immutable_text(path, value):
    """Publish a complete new capture without replacing existing evidence."""
    path = Path(path)
    encoded = value.encode("utf-8")
    if path.exists():
        if path.read_bytes() != encoded:
            raise ValueError("source cache integrity mismatch")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".capture-", delete=False) as handle:
            staged = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        if staged.read_bytes() != encoded:
            raise OSError("incomplete staged source capture")
        try:
            os.link(staged, path)
        except FileExistsError:
            if path.read_bytes() != encoded:
                raise ValueError("source cache integrity mismatch")
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


@contextlib.contextmanager
def writer_lock(path):
    """Share one non-blocking lease between the sweep and daily publisher."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another board writer is running") from exc
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def parse_feed(raw, target):
    """Return every entry in the response and a same-origin continuation URL."""
    entries = []
    next_url = None
    if target["format"] == "json_fedreg":
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise ValueError("missing Federal Register results array")
        for doc in data["results"]:
            if not isinstance(doc, dict):
                raise ValueError("feed entry must be an object")
            entries.append({"title": doc.get("title", ""),
                            "summary": doc.get("abstract") or doc.get("title", ""),
                            "url": doc.get("html_url", ""),
                            "publication_date": doc.get("publication_date", "")})
        next_url = data.get("next_page_url")
    else:
        root = ET.fromstring(raw)
        if root.tag not in ("rss", ATOM + "feed", "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF"):
            raise ValueError("response is not an RSS or Atom feed")
        for namespace in ("", "{http://purl.org/rss/1.0/}"):
            for item in root.findall(".//" + namespace + "item"):
                entries.append({"title": item.findtext(namespace + "title", ""),
                                "summary": item.findtext(namespace + "description", ""),
                                "url": item.findtext(namespace + "link", ""),
                                "publication_date": item.findtext(namespace + "pubDate", "")})
        for item in root.findall(".//" + ATOM + "entry"):
            links = item.findall(ATOM + "link")
            link = next((x.get("href", "") for x in links if x.get("rel", "alternate") == "alternate"), "")
            entries.append({"title": item.findtext(ATOM + "title", ""),
                            "summary": item.findtext(ATOM + "summary", ""),
                            "url": link,
                            "publication_date": item.findtext(ATOM + "updated", "")})
    if any(not isinstance(e["title"], str) or not e["title"].strip() or
           not isinstance(e["summary"], str) or not isinstance(e["publication_date"], str) or
           not public_url(e["url"]) for e in entries):
        raise ValueError("feed entry lacks a title or an HTTPS document URL")
    if next_url and (not public_url(next_url) or urlparse(next_url).netloc != urlparse(target["url"]).netloc):
        raise ValueError("unsafe feed continuation URL")
    return entries, next_url


def collect_feeds(store, targets, fetch, keywords):
    """Queue discovered records, retaining failures and explicit pagination limits."""
    pending = store.setdefault("document_states", {})
    health = store.setdefault("source_states", {})
    cutoff = (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=LOOKBACK_DAYS)).isoformat()
    for target in targets:
        state = {"checked_at": now(), "status": "failed", "name": target["name"], "entries": 0, "queued": 0,
                 "window_days": LOOKBACK_DAYS if target["format"] == "json_fedreg" else None}
        old = health.get(target["id"], {})
        if old.get("last_success"):
            state["last_success"] = old["last_success"]
        url = target["url"]
        visited = set()
        current_ids = set()
        try:
            for _ in range(MAX_FEED_PAGES):
                if url in visited:
                    raise ValueError("feed pagination cycle")
                visited.add(url)
                raw = fetch(url)
                if not raw:
                    raise ValueError("empty or unavailable feed")
                entries, next_url = parse_feed(raw, target)
                if not entries:
                    raise ValueError("empty feed does not establish source recovery")
                state["entries"] += len(entries)
                reached_cutoff = False
                for entry in entries:
                    if target["format"] == "json_fedreg" and entry["publication_date"] and entry["publication_date"] < cutoff:
                        reached_cutoff = True
                        continue
                    if target.get("filter_ai") and not keywords.search(entry["title"] + " " + entry["summary"]):
                        continue
                    identity = digest(entry["url"])
                    current_ids.add(identity)
                    record = pending.setdefault(identity, {"status": "pending", "attempts": 0})
                    record.update({"item": entry, "target": target, "active": True})
                    state["queued"] += 1
                if not next_url or reached_cutoff:
                    state["status"] = "ok"
                    state["last_success"] = state["checked_at"]
                    break
                url = next_url
            else:
                state["status"] = "limited"
                state["error"] = "page limit reached before the declared lookback boundary"
        except (ValueError, TypeError, KeyError, OSError, http.client.HTTPException, ET.ParseError) as exc:
            state["error"] = f"{type(exc).__name__}: {exc}"
            if target.get("failure_coverage"):
                state["status"] = "limited"
                state["limitation"] = target["failure_coverage"]
        health[target["id"]] = state
        if state["status"] == "ok":
            for identity, record in pending.items():
                if record["target"]["id"] == target["id"] and identity not in current_ids:
                    record["active"] = False
    return pending


def source_health_text(health):
    """Describe unavailable coverage without exposing transport error details."""
    return " ".join(
        f"{state.get('name', identity)}: {state.get('status', 'unverified')}. "
        f"{state.get('limitation', '')} Last success: {state.get('last_success', 'not recorded')}."
        for identity, state in health.get("source_states", {}).items()
        if state.get("status") != "ok"
    )


class DocumentText(HTMLParser):
    """Extract visible text, preferring the document's main or article element."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.main_parts = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        if tag not in {"br", "hr", "img", "input", "meta", "link", "wbr", "source", "area", "base", "embed", "param", "track", "col"}:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.stack:
            self.stack = self.stack[:len(self.stack) - 1 - self.stack[::-1].index(tag)]

    def handle_data(self, data):
        if not any(x in self.stack for x in ("script", "style", "nav", "header", "footer", "noscript", "head")):
            self.parts.append(data)
            if "main" in self.stack or "article" in self.stack:
                self.main_parts.append(data)


def document_text(raw):
    parser = DocumentText()
    parser.feed(raw)
    parser.close()
    main = " ".join(" ".join(parser.main_parts).split())
    text = main if len(main) >= 100 else " ".join(" ".join(parser.parts).split())
    if len(text) < 100:
        raise ValueError("insufficient source text")
    if (any(x in text[:1000].lower() for x in ("access denied", "page not found", "verify you are human", "request an unblock")) or
            re.match(r"request access\b", text, re.I)):
        raise ValueError("source returned an error or access challenge")
    return text


def sentence_ends(text):
    """Keep common legal abbreviations and initials inside their sentence window."""
    ends = {0, len(text)}
    for match in re.finditer(r'[.!?][\"\u201d\u2019\)]*(?=\s|$)', text):
        if match.group()[0] == ".":
            token = re.search(r"[\w.]+$", text[max(0, match.start() - 64):match.start() + 1])
            word = token.group().lower() if token else ""
            if (word in {"sec.", "secs.", "art.", "arts.", "no.", "nos.", "para.", "paras.",
                         "vol.", "ch.", "pt.", "mr.", "mrs.", "dr.", "etc.", "vs.", "v.", "fig.", "al."} or
                    re.fullmatch(r"(?:[a-z]\.)+", word)):
                continue
        ends.add(match.end())
    return sorted(ends)


def select_passages(text, keywords, byte_budget, *, details=False):
    """Keep the opening, then strongest complete sentence windows, in source order.

    Counts include the opening and every non-overlapping candidate window. Sentence
    boundaries use punctuation with common abbreviations retained. This is a heuristic,
    not a linguistic guarantee. A window that cannot fit is left unread, never byte-cut.
    """
    matches = list(keywords.finditer(text))
    ends = sentence_ends(text)
    def window(start, end):
        start = ends[max(0, bisect.bisect_right(ends, start) - 1)]
        end = ends[min(len(ends) - 1, bisect.bisect_left(ends, end))]
        return [start, end]
    merged = [window(0, min(500, len(text)))]
    for match in matches:
        start, end = window(max(0, match.start() - 500), min(len(text), match.end() + 500))
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    windows = []
    for start, end in merged:
        while start < end:
            stop = min(end, ends[min(len(ends) - 1, bisect.bisect_left(ends, start + 1200))])
            piece = text[start:stop]
            if start == 0 or keywords.search(piece):
                windows.append([start, stop])
            start = stop
    def strength(span):
        piece = text[span[0]:span[1]]
        return max((weight for weight, pattern in PASSAGE_PATTERNS if pattern.search(piece)), default=0)
    ranked = sorted(windows, key=lambda span: (span[0] != 0, -strength(span), span[0]))
    if not matches:
        counts = {"passages_total": len(windows), "passages_read": 0,
                  "passages_left": len(windows), "matched": False}
        return "", [], counts if details else False
    ranges = []
    remaining = byte_budget
    for start, end in ranked:
        cost = len(text[start:end].encode("utf-8")) + (len(PASSAGE_SEPARATOR.encode("utf-8")) if ranges else 0)
        if cost > remaining:
            if start == 0:
                break
            continue
        ranges.append([start, end])
        remaining -= cost
    ranges.sort()
    selected = PASSAGE_SEPARATOR.join(text[a:b] for a, b in ranges)
    counts = {"passages_total": len(windows), "passages_read": len(ranges),
              "passages_left": len(windows) - len(ranges), "matched": bool(matches)}
    return selected, ranges, counts if details else bool(matches)


def coverage_text(record):
    """Describe the exact model input scope separately from any substantive finding."""
    coverage = record.get("assessment_coverage")
    if not coverage:
        return ""
    ranges = ", ".join(f"[{start}, {end})" for start, end in coverage["ranges"]) or "none"
    return (
        f"Coverage: {coverage['scope']}; {coverage['selection_status']}. "
        f"Passages read: {coverage['passages_read']}; left: {coverage['passages_left']}. "
        f"{('Reason: ' + record.get('assessment_error', record.get('error', 'assessment unavailable')) + '. ') if coverage['scope'] == 'unassessed' else ''}"
        f"Assessed character ranges (zero-based, end-exclusive): {ranges}; "
        f"extracted text length: {coverage['text_chars']}. "
        f"Raw document SHA-256: {record['source_sha256']}; "
        f"extracted text SHA-256: {record['source_text_sha256']}; "
        f"selected text SHA-256: {coverage['selected_text_sha256']}."
    )


def run_coverage_text(progress):
    reasons = progress.get("not_evaluated_by_reason")
    listed = ("; ".join(f"{reason}: {count}" for reason, count in sorted(reasons.items())) or "none") if isinstance(reasons, dict) else "unverified"
    return (f"Passages read: {progress.get('passages_read', 'unverified')}; left: {progress.get('passages_left', 'unverified')}. "
            f"Passages-only documents: {progress.get('passages_only_documents', 'unverified')}; "
            f"documents with passages left: {progress.get('documents_with_passages_left', 'unverified')}; "
            f"evaluated documents without passage counts: {progress.get('coverage_not_recorded', 'unverified')}. "
            f"Not evaluated by reason: {listed}. "
            "Passage counts cover recorded selections in the retained queue, including unassessed selections. "
            "For long documents, candidates are the opening and AI keyword windows; other omitted text is unassessed.")


def valid_end_state(record):
    state = record.get("end_state", {})
    history = record.get("failure_history", {})
    if (record.get("status") != "not_evaluated" or not isinstance(state, dict) or
            state.get("reason") not in END_REASONS or
            type(state.get("checked_run")) is not int or state["checked_run"] < 1 or
            type(state.get("next_check_run")) is not int or
            state.get("next_check_run") != state["checked_run"] + END_STATE_RECHECK_RUNS or
            not isinstance(history, dict) or history.get("reason") != state["reason"]):
        return False
    runs = history.get("runs", [])
    if not (isinstance(runs, list) and len(runs) >= CAPTURE_FAILURE_RUNS and
            all(type(n) is int and n > 0 for n in runs) and runs == sorted(set(runs)) and
            runs[-1] == state["checked_run"]):
        return False
    if state["reason"] in ASSESSMENT_END_REASONS:
        text_hash = state.get("text_sha256")
        return (isinstance(text_hash, str) and bool(re.fullmatch(r"[0-9a-f]{64}", text_hash)) and
                text_hash == history.get("text_sha256") == record.get("source_text_sha256"))
    return history.get("text_sha256") is None and "text_sha256" not in state


def run_is_complete(health):
    """Cross-check a complete claim against its counts and retained document states."""
    progress = health.get("last_pass", {})
    sources = health.get("source_states", {})
    records = health.get("document_states")
    if (not isinstance(progress, dict) or not isinstance(sources, dict) or
            not isinstance(records, dict) or any(not isinstance(s, dict) for s in sources.values())):
        return False
    if (not sources or any(s.get("status") != "ok" for s in sources.values()) or
            health.get("local_inputs_status") != "ok" or health.get("pending_notifications") or
            progress.get("unhealthy_sources") != []):
        return False
    if any(type(s.get("entries")) is not int or s["entries"] <= 0 for s in sources.values()):
        return False
    for key in ("pending_evaluations", "manual_review_required", "documents_deferred", "pending_notifications"):
        if type(progress.get(key)) is not int or progress[key] != 0:
            return False
    reasons = {}
    for record in records.values():
        if not isinstance(record, dict):
            return False
        if valid_end_state(record):
            number = health.get("pass_number")
            if (type(number) is not int or number < record["end_state"]["checked_run"] or
                    number >= record["end_state"]["next_check_run"]):
                return False
            reason = record["end_state"]["reason"]
            reasons[reason] = reasons.get(reason, 0) + 1
        elif record.get("status") != "evaluated":
            return False
    return progress.get("not_evaluated_by_reason") == reasons


def run_health_text(health):
    progress = health.get("last_pass", {})
    status = health.get("last_run_status", "unverified legacy run")
    if status == "complete" and not run_is_complete(health):
        status = "incomplete"
    return (
        f"Last sweep: {health.get('last_run') or 'not recorded'}; status: {status}. "
        f"Failed or limited sources: {len(progress['unhealthy_sources']) if isinstance(progress.get('unhealthy_sources'), list) else 'unverified'}; "
        f"pending evaluations: {progress.get('pending_evaluations', 'unverified')}; "
        f"manual review required: {progress.get('manual_review_required', 'unverified')}; "
        f"deferred document checks: {progress.get('documents_deferred', 'unverified')}; "
        f"pending notifications: {progress.get('pending_notifications', 'unverified')}. "
        + run_coverage_text(progress)
    )
