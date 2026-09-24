"""Validate and render the dated watch calendar, with a deterministic iCalendar export."""

from datetime import date, timedelta
from html import escape
import json
from pathlib import Path
import re
from urllib.parse import urlsplit


class WatchDataError(ValueError):
    """Invalid watch data must stop the build before it replaces public output."""


WATCH_START = '<!-- generated-watch-start -->'
WATCH_END = '<!-- generated-watch-end -->'


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise WatchDataError(f"{label}: non-empty text required")
    return value


def _date(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise WatchDataError(f"{label}: YYYY-MM-DD required")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise WatchDataError(f"{label}: invalid date") from exc


def _links(ids, sources, label, required=False):
    if not isinstance(ids, list) or (required and not ids):
        raise WatchDataError(f"{label}: source list required")
    if any(not isinstance(sid, str) or sid not in sources for sid in ids):
        raise WatchDataError(f"{label}: unknown source")


def validate_watch(data):
    """Check structure and provenance links; this does not establish semantic support."""
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise WatchDataError("watch schema version must be 1")
    checked = _date(data.get("checked_at"), "checked_at")
    sources = data.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise WatchDataError("sources: non-empty object required")
    for sid, source in sources.items():
        if not isinstance(source, dict):
            raise WatchDataError(f"{sid}: source object required")
        url = _text(source.get("url"), sid)
        parts = urlsplit(url)
        if (parts.scheme != "https" or not parts.hostname or parts.username
                or parts.password or any(c.isspace() for c in url)):
            raise WatchDataError(f"{sid}: public HTTPS URL required")
        for field in ("locator", "kind"):
            _text(source.get(field), f"{sid}.{field}")
    ids = set()
    for group, date_field in (("events", "date"), ("watches", "next_review")):
        rows = data.get(group)
        if not isinstance(rows, list) or not rows:
            raise WatchDataError(f"{group}: non-empty list required")
        for row in rows:
            if not isinstance(row, dict):
                raise WatchDataError(f"{group}: row object required")
            rid = _text(row.get("id"), "id")
            if not re.fullmatch(r"[a-z][a-z0-9-]*", rid) or rid in ids:
                raise WatchDataError(f"{rid}: invalid or duplicate id")
            ids.add(rid)
            _date(row.get(date_field), f"{rid}.{date_field}")
            for field in ("title", "question", "inspect", "improves", "worsens", "limit"):
                _text(row.get(field), f"{rid}.{field}")
            _links(row.get("source_ids"), sources, rid, required=group == "events")
            if group == "events" and row.get("date_kind") != "published_schedule":
                raise WatchDataError(f"{rid}: event date must be a published schedule")
            if group == "watches":
                _text(row.get("cadence"), f"{rid}.cadence")
            if row.get("status") not in {"not_observed", "unresolved", "resolved"}:
                raise WatchDataError(f"{rid}: invalid outcome status")
            if row["status"] == "resolved":
                outcome = row.get("outcome")
                if not isinstance(outcome, dict):
                    raise WatchDataError(f"{rid}: resolution requires evidence")
                _text(outcome.get("finding"), f"{rid}.finding")
                _links(outcome.get("source_ids"), sources, rid, required=True)
                if _date(outcome.get("observed_at"), rid) > checked:
                    raise WatchDataError(f"{rid}: outcome after the check date")
    government = data.get("government")
    if not isinstance(government, dict):
        raise WatchDataError("government: object required")
    for field in ("title", "intro", "method", "limit", "coi"):
        _text(government.get(field), f"government.{field}")
    records = government.get("records")
    if not isinstance(records, list) or not records:
        raise WatchDataError("government.records: non-empty list required")
    for row in records:
        if not isinstance(row, dict):
            raise WatchDataError("government record must be an object")
        for field in ("title", "claim", "current_status"):
            _text(row.get(field), f"government.{field}")
        _date(row.get("source_date"), "source_date")
        _links(row.get("source_ids"), sources, "government", required=True)
    return data


def load_watch(path):
    """Load mandatory watch data, failing closed on missing or invalid inputs."""
    return validate_watch(json.loads(Path(path).read_text(encoding="utf-8")))


def _source_links(ids, sources):
    if not ids:
        return '<p class="watch-meta">Editorial question; no fixed external schedule.</p>'
    return '<ul class="watch-sources">' + ''.join(
        f'<li><a href="{escape(sources[sid]["url"], quote=True)}">{escape(sid)}</a>: '
        f'{escape(sources[sid]["locator"])} '
        f'<span class="watch-meta">({escape(sources[sid]["kind"])})</span></li>'
        for sid in ids) + '</ul>'


def _row(row, sources, event):
    stamp = row["date"] if event else row["next_review"]
    label = "Published date" if event else "Editorial review"
    status = "Resolved with cited evidence" if row["status"] == "resolved" else "Unresolved"
    content = ''.join(f'<dt>{heading}</dt><dd>{escape(row[field])}</dd>' for heading, field in (
        ("Inspect", "inspect"), ("Evidence of improvement", "improves"),
        ("Evidence of deterioration", "worsens"), ("Limits", "limit")))
    outcome = ""
    if row["status"] == "resolved":
        result = row["outcome"]
        outcome = (f'<p><strong>Recorded outcome ({escape(result["observed_at"])}):</strong> '
                   f'{escape(result["finding"])}</p>'
                   + _source_links(result["source_ids"], sources))
    cadence = '' if event else f'<p class="watch-meta">{escape(row["cadence"])}</p>'
    return (f'<details class="watch-row" id="watch-{escape(row["id"])}">'
            f'<summary><span class="watch-date">{label}: <time datetime="{stamp}">{stamp}</time>'
            f'</span><strong>{escape(row["title"])}</strong>'
            f'<span class="watch-status">{status}</span></summary>'
            f'<p>{escape(row["question"])}</p>{cadence}<dl>{content}</dl>{outcome}'
            f'{_source_links(row["source_ids"], sources)}</details>')


def render_watch(data):
    """Render source dates separately from review dates and outcome judgements."""
    validate_watch(data)
    government = data["government"]
    records = ''.join(
        f'<article class="watch-record"><h4>{escape(row["title"])}</h4>'
        f'<p>{escape(row["claim"])}</p><p class="watch-meta">Source date: '
        f'{escape(row["source_date"])}. {escape(row["current_status"])}</p>'
        f'{_source_links(row["source_ids"], data["sources"])}</article>'
        for row in government["records"])
    events = ''.join(_row(row, data["sources"], True)
                     for row in sorted(data["events"], key=lambda item: (item["date"], item["id"])))
    watches = ''.join(_row(row, data["sources"], False) for row in data["watches"])
    return (f'<div class="watch-view"><h2>Watch: evidence and upcoming decisions</h2>'
            f'<p>Source checks: <time datetime="{data["checked_at"]}">{data["checked_at"]}</time>. '
            'This calendar is manually maintained. Daily news refreshes do not update its evidence. '
            'A passed date does not resolve a question; all outcomes need a recorded source.</p>'
            f'<section class="watch-government"><h3>{escape(government["title"])}</h3>'
            f'<p>{escape(government["intro"])}</p><p>{escape(government["method"])}</p>'
            f'<p>{escape(government["limit"])}</p>{records}'
            f'<p class="watch-meta">Assistance and interests: {escape(government["coi"])}</p></section>'
            '<section><h3>Published dates</h3><p>Dates announced by the linked source. '
            'Schedules can change. These are opportunities to check evidence, not predictions of a crisis.</p>'
            '<p><a href="AI_OUTLOOK.ics" download>Download calendar (.ics)</a> '
            '· <a href="watch_calendar.json">Structured data</a>. '
            'The download contains published dates only, without alarms; it is not a live subscription.</p>'
            f'{events}</section><section><h3>Ongoing questions and longer horizons</h3>'
            '<p>Dates below are editorial checkpoints, not promised court decisions, earnings dates '
            f'or company deadlines.</p>{watches}</section></div>')


def watch_fragment(data):
    """Bound the generated view so a checker can compare its complete content."""
    return '\n'.join(line.rstrip() for line in
                     f'{WATCH_START}\n{render_watch(data)}\n{WATCH_END}'.splitlines())


def validate_watch_outputs(data, root):
    """Reject missing or stale exports without rewriting either public file."""
    root = Path(root)
    try:
        actual_ics = (root / 'AI_OUTLOOK.ics').read_bytes()
        page = (root / 'index.html').read_text(encoding='utf-8')
    except (OSError, UnicodeError) as exc:
        raise WatchDataError('Watch outputs unavailable; run python3 build.py') from exc
    if actual_ics != calendar_ics(data):
        raise WatchDataError('AI_OUTLOOK.ics differs from watch data; run python3 build.py')
    if page.count(WATCH_START) != 1 or page.count(WATCH_END) != 1:
        raise WatchDataError('Watch HTML markers missing or duplicated; run python3 build.py')
    start = page.index(WATCH_START)
    end = page.index(WATCH_END) + len(WATCH_END)
    if page[start:end] != watch_fragment(data):
        raise WatchDataError('Watch HTML differs from watch data; run python3 build.py')


def _ics_text(text):
    return text.replace('\\', '\\\\').replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,')


def _fold(line):
    """Fold content lines at 75 UTF-8 octets without splitting a character."""
    parts, part = [], ''
    for char in line:
        if len((part + char).encode('utf-8')) > 75:
            parts.append(part)
            part = ' '
        part += char
    parts.append(part)
    return '\r\n'.join(parts)


def calendar_ics(data):
    """Export only published schedules as all-day events without reminders."""
    validate_watch(data)
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//NM AI Research//Evidence watch//EN',
             'CALSCALE:GREGORIAN', 'METHOD:PUBLISH']
    for event in sorted(data['events'], key=lambda row: (row['date'], row['id'])):
        day = date.fromisoformat(event['date'])
        sources = '\n'.join(data['sources'][sid]['url'] for sid in event['source_ids'])
        description = '\n'.join([event['question'], 'Inspect: ' + event['inspect'],
                                 'Improvement: ' + event['improves'], 'Deterioration: ' + event['worsens'],
                                 'Limits: ' + event['limit'], 'Check date: ' + data['checked_at'],
                                 'Outcome status: ' + event['status'], sources])
        lines.extend(['BEGIN:VEVENT', f'UID:{event["id"]}-{day.year}@nmai-research-calendar',
                      'DTSTAMP:' + data['checked_at'].replace('-', '') + 'T000000Z',
                      'DTSTART;VALUE=DATE:' + day.strftime('%Y%m%d'),
                      'DTEND;VALUE=DATE:' + (day + timedelta(days=1)).strftime('%Y%m%d'),
                      'SUMMARY:' + _ics_text(event['title']),
                      'DESCRIPTION:' + _ics_text(description), 'TRANSP:TRANSPARENT', 'END:VEVENT'])
    lines.append('END:VCALENDAR')
    return ('\r\n'.join(_fold(line) for line in lines) + '\r\n').encode('utf-8')
