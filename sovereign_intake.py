"""Bounded feed intake, source text extraction and durable processing primitives."""

from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import ipaddress
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


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def public_url(url):
    parsed = urlparse(url)
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
            entries.append({"title": doc.get("title", ""),
                            "summary": doc.get("abstract") or doc.get("title", ""),
                            "url": doc.get("html_url", ""),
                            "publication_date": doc.get("publication_date", "")})
        next_url = data.get("next_page_url")
    else:
        root = ET.fromstring(raw)
        if root.tag not in ("rss", ATOM + "feed", "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF"):
            raise ValueError("response is not an RSS or Atom feed")
        for item in root.findall(".//item"):
            entries.append({"title": item.findtext("title", ""),
                            "summary": item.findtext("description", ""),
                            "url": item.findtext("link", ""),
                            "publication_date": item.findtext("pubDate", "")})
        for item in root.findall(".//" + ATOM + "entry"):
            links = item.findall(ATOM + "link")
            link = next((x.get("href", "") for x in links if x.get("rel", "alternate") == "alternate"), "")
            entries.append({"title": item.findtext(ATOM + "title", ""),
                            "summary": item.findtext(ATOM + "summary", ""),
                            "url": link,
                            "publication_date": item.findtext(ATOM + "updated", "")})
    if any(not e["title"].strip() or not public_url(e["url"]) for e in entries):
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
        state = {"checked_at": now(), "status": "failed", "entries": 0, "queued": 0,
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
        except (ValueError, TypeError, KeyError, OSError, ET.ParseError) as exc:
            state["error"] = f"{type(exc).__name__}: {exc}"
        health[target["id"]] = state
        if state["status"] == "ok":
            for identity, record in pending.items():
                if record["target"]["id"] == target["id"] and identity not in current_ids:
                    record["active"] = False
    return pending


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
    text = " ".join(" ".join(parser.main_parts or parser.parts).split())
    if len(text) < 100:
        raise ValueError("insufficient source text")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError("document exceeds evaluation text limit; manual review required")
    if any(x in text[:1000].lower() for x in ("access denied", "page not found", "verify you are human", "request access", "request an unblock")):
        raise ValueError("source returned an error or access challenge")
    return text
