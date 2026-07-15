#!/usr/bin/env python3
"""
AI News Reality Board - build.py (stdlib only, no dependencies).
NM AI Research.

Reads items.json and renders a static index.html that sorts AI-news claims by
incentive rather than by political lean. The axis is MOTIVE: who is telling you
this and what they gain if you believe it. Each item shows a source distribution bar by
motive tier, a claim_type and denominator flag, and a "reality anchor" linking
the claim to a published base rate. FLAG, do not NARRATE: the tags speak.

Run:  python3 build.py   ->   writes index.html next to items.json
"""
import json, os, html

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "items.json")
OUT = os.path.join(HERE, "index.html")

# house palette
NAVY, SLATE, BODY, ALT, LINE = "#1a365d", "#4a5568", "#2d3748", "#f7fafc", "#e2e8f0"

# distance tier (canonical house scale, from the Source Incentive Map + working
# tracker): 1 = LEAST incentive to shade the claim ... 5 = the party selling the
# thing the claim is about. Claim-relative. It allocates verification effort; it is
# not a trust or quality score.
TIER = {
    1: ("#2f7d4f", "Primary record / regulator / adversarial process (least incentive)"),
    2: ("#6ba368", "Research institute or academia (credibility-aligned)"),
    3: ("#c7a53b", "Analyst house or trade press (sells reports, access or clicks)"),
    4: ("#cc7a33", "Tool or data vendor (product benefits from the framing)"),
    5: ("#b23b2e", "Party selling the thing the claim is about (own topic)"),
}
DENOM = {"y": ("#2f7d4f", "denominator stated"),
         "partial": ("#cc7a33", "partial denominator"),
         "n": ("#b23b2e", "no denominator"),
         "n/a": ("#64748b", "no quantitative claim"),
         "?": ("#94a3b8", "denominator: unreviewed")}
CLAIM = {"measurement": "#2f7d4f", "assertion": "#5b7fa6",
         "target": "#cc7a33", "prediction": "#cc7a33",
         "study": "#2f7d4f", "opinion": "#6b7280", "lawsuit": "#8a5a3b"}

# topic -> keywords, to auto-suggest a reality anchor for an unreviewed feed item.
# Order is priority: the first topic whose keyword matches the headline wins. This
# is plumbing (a keyword match), not the call: an auto-matched anchor is flagged as
# a machine suggestion, never asserted, and a human review can override the topic.
import re
TOPIC_KEYWORDS = [
    ("water", ["water", "cooling", "aquifer", "wastewater", "gallons", "hydro"]),
    ("self_improvement", ["self-improv", "self improv", "recursive", "superintelligence",
                          "automate ai research", "ai r&d", "ai r and d"]),
    ("code_automation", ["code", "coding", "programmer", "software engineer",
                         "developer", "copilot", "pull request"]),
    ("work_automation", ["layoff", "layoffs", "headcount", "workforce", "job cuts",
                         "replace workers", "automate the work"]),
    ("power_demand", ["gigawatt", "megawatt", "gw", "mw", "data center", "data centre",
                      "datacenter", "grid", "nuclear", "power plant", "capacity buildout"]),
    ("energy_forecast", ["energy demand", "electricity demand", "power consumption",
                         "terawatt", "twh", "energy forecast", "power forecast"]),
    ("cost", ["capex", "billion", "spend", "spending", "investment", "funding round",
              "valuation", "revenue"]),
]


TOPIC_LABELS = {
    "code_automation": "Code automation", "work_automation": "Work automation",
    "self_improvement": "Self-improvement", "water": "Water",
    "power_demand": "Power demand", "energy_forecast": "Energy forecast",
    "cost": "Cost / spend", "governance": "Politics / governance", "": "Untagged",
}


def tag_topic(headline):
    """Return the first topic whose keyword matches the headline, else '' (no anchor)."""
    hay = " " + (headline or "").lower() + " "
    for topic, kws in TOPIC_KEYWORDS:
        for kw in kws:
            if re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", hay):
                return topic
    return ""


esc = lambda s: html.escape(str(s), quote=True)


def bar(counts):
    """A stacked distribution bar keyed by motive tier -> proportion."""
    total = sum(counts.values()) or 1
    segs = []
    for t in sorted(counts):
        if counts[t] == 0:
            continue
        pct = 100.0 * counts[t] / total
        col = TIER[t][0]
        segs.append(f'<span title="tier {t}: {esc(TIER[t][1])} ({counts[t]})" '
                    f'style="display:inline-block;height:12px;width:{pct:.1f}%;'
                    f'background:{col}"></span>')
    return ('<span style="display:inline-block;width:100%;border-radius:3px;'
            'overflow:hidden;line-height:0">' + "".join(segs) + "</span>")


def item_card(it, anchors, plain=False):
    tiers = {}
    chips = []
    for s in it["sources"]:
        t = int(s["motive_tier"])
        tiers[t] = tiers.get(t, 0) + 1
        if plain:  # motive tiering off: neutral chip, no tier colour or tooltip
            chips.append(f'<span class="tierchip" style="display:inline-block;font-size:12px;'
                         f'padding:2px 8px;margin:2px 4px 2px 0;border-radius:10px;color:{BODY};'
                         f'background:#edf2f7;border:1px solid {LINE}">{esc(s["name"])}</span>')
            continue
        col = TIER[t][0]
        chips.append(f'<span class="tierchip" style="display:inline-block;font-size:12px;'
                     f'padding:2px 8px;margin:2px 4px 2px 0;border-radius:10px;color:#fff;background:{col}" '
                     f'title="tier {t}: {esc(TIER[t][1])}">{esc(s["name"])}</span>')
    # link the headline to its primary source when one exists (curated items have
    # no url, so they stay plain text rather than becoming a dead link)
    src_url = next((s.get("url", "") for s in it["sources"] if s.get("url")), "")
    headline_html = esc(it["headline"])
    if src_url:
        headline_html = (f'<a href="{esc(src_url)}" target="_blank" rel="noopener noreferrer" '
                         f'style="color:{NAVY};text-decoration:none">{esc(it["headline"])}</a>')
    d = it["denominator_stated"].strip().lower()
    dcol, dlabel = DENOM.get(d, DENOM["n"])
    ct = it["claim_type"].strip().lower()
    ccol = CLAIM.get(ct, SLATE)
    unreviewed = it.get("reviewed", True) is False
    flag = (f'<span style="display:inline-block;padding:2px 8px;margin-left:6px;'
            f'border-radius:4px;font-size:11px;color:{SLATE};background:#edf2f7;'
            f'border:1px dashed {SLATE}">auto-tagged, unreviewed</span>' if unreviewed else "")
    # reliability mark (second axis, from sources.md via apply_ratings.py)
    rating = it.get("rating", "")
    rmark = ""
    if rating == "trusted":
        rmark = (f'<span title="rated trusted in sources.md" style="display:inline-block;'
                 f'padding:2px 8px;margin-left:6px;border-radius:4px;font-size:11px;'
                 f'color:#fff;background:{TIER[2][0]}">track record: trusted</span>')
    elif rating == "caution":
        note = it.get("rating_note", "known recurring error to check")
        rmark = (f'<span title="{esc(note)}" style="display:inline-block;padding:2px 8px;'
                 f'margin-left:6px;border-radius:4px;font-size:11px;color:#fff;'
                 f'background:{TIER[4][0]}">track record: caution</span>')
    a = anchors.get(it.get("topic", ""), {})
    anchor_html = ""
    if a:
        auto = it.get("_auto_topic", False)
        head = ("Possible anchor (auto-matched, unreviewed)." if auto
                else "Reality anchor.")
        border = SLATE if auto else NAVY
        anchor_html = (
            f'<div style="margin-top:10px;padding:10px 12px;background:{ALT};'
            f'border-left:3px solid {border};font-size:13px;color:{BODY}">'
            f'<strong style="color:{NAVY}">{head}</strong> {esc(a["label"])} '
            f'<a href="{esc(a["url"])}" style="color:{NAVY}">'
            f'{esc(a.get("source",""))} (DOI)</a></div>')
    # disclosed-conflict flag: an INDEPENDENT facet from the tier. It marks a
    # checkable structural stake (a source that regulates, buys from, or owns the
    # subject of the claim), never an imputation of motive from party. Per-source
    # note, plus an optional item-level one.
    cnotes = []
    if it.get("conflict"):
        cnotes.append(it["conflict"])
    cnotes += [f'{s.get("name","")}: {s["conflict"]}' for s in it["sources"] if s.get("conflict")]
    conflict_html = ""
    if cnotes:
        lines = "".join(f'<div style="margin:2px 0">{esc(n)}</div>' for n in cnotes)
        conflict_html = (
            f'<div style="margin-top:8px;padding:8px 12px;background:#fffaf0;'
            f'border-left:3px solid {TIER[5][0]};font-size:12px;color:{BODY}">'
            f'<strong style="color:{TIER[5][0]}">Disclosed conflict.</strong> Structural stake, '
            f'not an accusation. {lines}</div>')

    # data-* for client-side search + filters (used by the sidebar JS)
    srcnames = " ".join(s.get("name", "") for s in it["sources"])
    blob = f'{it["entity"]} {it["headline"]} {srcnames} {" ".join(cnotes)}'.lower()
    tierlist = " ".join(str(x) for x in sorted(tiers))
    conflict_attr = ' data-conflict="1"' if cnotes else ""
    data = (f'class="card" data-search="{esc(blob)}" data-topic="{esc(it.get("topic",""))}" '
            f'data-tiers="{esc(tierlist)}"{conflict_attr}')
    return f"""
    <article {data} style="border:1px solid {LINE};border-radius:8px;padding:14px 16px;margin:0 0 14px">
      <div style="font-size:12px;color:{SLATE};margin-bottom:4px">
        {esc(it["entity"])} &middot; {esc(fmt_date(it.get("date", "")))}
      </div>
      <div style="font-size:16px;font-weight:600;color:{NAVY};line-height:1.35">{headline_html}</div>
      {'' if plain else f'<div class="motivebar" style="margin:10px 0 6px">{bar(tiers)}</div>'}
      <div style="margin:10px 0 6px">{''.join(chips)}</div>
      <div style="font-size:12px">
        <span style="display:inline-block;padding:2px 8px;margin-right:6px;border-radius:4px;
              color:#fff;background:{ccol}">{esc(it["claim_type"])}</span>
        <span style="display:inline-block;padding:2px 8px;border-radius:4px;
              color:#fff;background:{dcol}">{esc(dlabel)}</span>{rmark}{flag}
      </div>
      {conflict_html}
      {anchor_html}
    </article>"""


def legend():
    rows = "".join(
        f'<div style="display:flex;align-items:center;font-size:12px;color:{BODY};margin:2px 0">'
        f'<span style="display:inline-block;width:14px;height:14px;border-radius:3px;'
        f'background:{c};margin-right:8px"></span>Tier {t}: {esc(lbl)}</div>'
        for t, (c, lbl) in TIER.items())
    caveat = (f'<div style="font-size:11px;color:{SLATE};margin-top:8px">Colour is incentive '
              f'distance, not trust. A tier-5 source can be entirely correct; the tier says only '
              f'where an independent second source is worth the effort.</div>')
    return (f'<div style="border:1px solid {LINE};border-radius:8px;padding:12px 14px;'
            f'margin:0 0 18px;background:#fff"><div style="font-weight:600;color:{NAVY};'
            f'margin-bottom:6px">Motive key (who benefits if the claim is true)</div>{rows}{caveat}</div>')


def gov_conflict_panel(gc):
    """Render the disclosed-conflict panel for government-on-AI (data in gov_conflict.json).
    Flag, not narrate: a sourced, claim-relative structural conflict, not an accusation."""
    if not gc:
        return ""
    hats = "".join(
        f'<div style="margin:4px 0"><strong style="color:{NAVY}">{esc(h["hat"])}.</strong> {esc(h["detail"])}</div>'
        for h in gc.get("hats", []))
    rows = "".join(
        f'<tr><td style="padding:4px 10px;border-bottom:1px solid {LINE}">{esc(r["company"])}</td>'
        f'<td style="padding:4px 10px;border-bottom:1px solid {LINE};font-size:12px">{esc(r["position"])}</td>'
        f'<td style="padding:4px 10px;border-bottom:1px solid {LINE};text-align:center;font-size:12px">{esc(r["status"])}</td>'
        f'<td style="padding:4px 10px;border-bottom:1px solid {LINE};font-size:12px;color:{SLATE}">{esc(r["layer"])}</td></tr>'
        for r in gc.get("roster", []))
    sep = "".join(f'<li style="margin:2px 0">{esc(s)}</li>' for s in gc.get("separate", []))
    return (
        f'<details class="govconflict" style="border:1px solid {LINE};'
        f'border-radius:8px;padding:12px 16px;margin:0 0 18px;background:#fff">'
        f'<summary style="font-weight:600;color:{NAVY};cursor:pointer">{esc(gc.get("title",""))}</summary>'
        f'<div style="font-size:13px;color:{BODY};margin-top:10px">{esc(gc.get("intro",""))}</div>'
        f'<div style="font-size:13px;margin:10px 0">{hats}</div>'
        f'<div style="font-size:12px;color:{SLATE};margin:6px 0 8px">{esc(gc.get("roster_note",""))}</div>'
        f'<table style="border-collapse:collapse;width:100%;font-size:13px">'
        f'<thead><tr><th style="text-align:left;padding:4px 10px;color:{SLATE}">Company</th>'
        f'<th style="text-align:left;padding:4px 10px;color:{SLATE}">Government position</th>'
        f'<th style="padding:4px 10px;color:{SLATE}">Status</th>'
        f'<th style="text-align:left;padding:4px 10px;color:{SLATE}">Stack layer</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
        f'<div style="font-size:12px;color:{BODY};margin-top:10px"><strong>Kept separate (not equity):</strong>'
        f'<ul style="margin:4px 0 0 18px;padding:0">{sep}</ul></div>'
        f'<div style="font-size:11px;color:{SLATE};margin-top:10px">Sources: {esc(gc.get("sources",""))}</div>'
        f'<div style="font-size:11px;color:{SLATE};margin-top:6px"><strong>Conflict of interest:</strong> '
        f'{esc(gc.get("coi",""))}</div></details>')


def ai_watch_panel(reg):
    """AI Watch: a dated resolution calendar plus live gauges (registers.json), curated
    public rows extracted from the maintainer's working tracker. Static: values are as of
    the last build, so each gauge carries its own as-of date."""
    if not reg:
        return ""
    def anchor_bit(a):
        if not a:
            return ""
        return (f'<div style="font-size:11px;margin-top:3px"><a href="https://doi.org/{esc(a["doi"])}" '
                f'style="color:{NAVY}">Reality anchor: {esc(a["label"])} (DOI)</a></div>')
    rows = "".join(
        f'<tr><td style="padding:6px 10px;border-bottom:1px solid {LINE};white-space:nowrap;'
        f'vertical-align:top;font-weight:600;color:{NAVY}">{esc(r["label"])}</td>'
        f'<td style="padding:6px 10px;border-bottom:1px solid {LINE}">{esc(r["question"])}'
        f'<div style="font-size:12px;color:{SLATE};margin-top:2px">Settles on: {esc(r["settles"])}</div>'
        f'{anchor_bit(r.get("anchor"))}</td></tr>'
        for r in reg.get("rows", []))
    gauges = "".join(
        f'<div style="border:1px solid {LINE};border-radius:6px;padding:8px 12px;margin:6px 0;background:{ALT}">'
        f'<div style="font-weight:600;color:{NAVY}">{esc(g["name"])} '
        f'<span style="font-weight:400;color:{SLATE};font-size:11px">(as of {esc(g.get("as_of",""))})</span></div>'
        f'<div style="font-size:13px;margin-top:3px">{esc(g["reading"])}</div>'
        f'<div style="font-size:12px;color:{SLATE};margin-top:3px">Watch: {esc(g["watch"])}</div>'
        + (f'<div style="font-size:12px;color:{SLATE};margin-top:3px">{esc(g["context"])}</div>' if g.get("context") else "")
        + '</div>'
        for g in reg.get("gauges", []))
    gauge_block = (f'<div style="font-weight:600;color:{NAVY};font-size:13px;margin:12px 0 4px">'
                   f'Live gauges</div>{gauges}') if gauges else ""
    return (
        f'<details class="aiwatch" style="border:1px solid {LINE};border-radius:8px;'
        f'padding:12px 16px;margin:0 0 18px;background:#fff">'
        f'<summary style="font-weight:600;color:{NAVY};cursor:pointer">{esc(reg.get("title","AI Watch"))}</summary>'
        f'<div style="font-size:13px;color:{BODY};margin:10px 0">{esc(reg.get("intro",""))}</div>'
        f'<div style="font-weight:600;color:{NAVY};font-size:13px;margin:8px 0 4px">Resolution calendar</div>'
        f'<table style="border-collapse:collapse;width:100%;font-size:13px"><tbody>{rows}</tbody></table>'
        f'{gauge_block}'
        f'<div style="font-size:11px;color:{SLATE};margin-top:10px">{esc(reg.get("provenance",""))} '
        f'{esc(reg.get("note",""))}</div></details>')


def parse_date(s):
    """Best-effort parse of the mixed feed date formats (RFC-822, ISO, YYYY-MM, YYYY)
    to a sortable aware datetime. Undated sinks to the bottom."""
    from email.utils import parsedate_tz
    from datetime import datetime, timezone
    s = (s or "").strip()
    floor = datetime.min.replace(tzinfo=timezone.utc)
    if not s:
        return floor
    # ISO first: handles 2024-08-22 and 2026-07-10T09:59
    try:
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    # RFC-822 / feed dates, lenient (accepts date-only "Sat, 11 Jul 2026")
    t = parsedate_tz(s)
    if t is not None:
        try:
            return datetime(*t[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass
    # RFC-822 with weekday (feeds use date-only "Sat, 11 Jul 2026"), partial ISO, year-only
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S", "%a, %d %b %Y",
                "%d %b %Y", "%Y-%m", "%Y", "%b %Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return floor


def fmt_date(s):
    """Uniform display date; falls back to the original string if unparseable."""
    from datetime import datetime, timezone
    d = parse_date(s)
    if d == datetime.min.replace(tzinfo=timezone.utc):
        return s or ""
    return d.strftime("%d %b %Y")


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Render the AI News Reality Board.")
    ap.add_argument("--plain", action="store_true",
                    help="turn the motive tier OFF entirely: no tier colours, bars, key or "
                         "tier map. Sources shown plain. The other axes (denominator, claim "
                         "type, track record, anchors) are unaffected.")
    plain = ap.parse_args().plain

    data = json.load(open(SRC, encoding="utf-8"))
    anchors = data.get("anchors", {})
    reviewed = [dict(it, reviewed=it.get("reviewed", True)) for it in data["items"]]

    # neutrality disclosures + the contestable tier registry (tier_map.json)
    neutrality_html = tiermap_html = ""
    tm_path = os.path.join(HERE, "tier_map.json")
    if os.path.isfile(tm_path) and not plain:
        tm = json.load(open(tm_path, encoding="utf-8"))
        contest = tm.get("contest", {})
        disclosures = [
            "Tier is claim-relative and based on an observable fact (what an entity sells or is), not a truth or quality verdict.",
            "Colour is incentive distance, not trust: a tier-5 source can be entirely correct. The tier only says where an independent second source is worth the effort.",
            "One curator sets these tiers (assisted by an AI model), unlike aggregators that average several rater organisations. So every cell is published with its basis and is open to challenge.",
            "The reality anchor only covers topics this portfolio addresses, so claims near that work get more scrutiny than others. Most items carry no anchor, which is honest.",
        ]
        dl = "".join(f'<li style="margin:3px 0">{esc(x)}</li>' for x in disclosures)
        neutrality_html = (
            f'<section style="border:1px solid {LINE};border-radius:8px;padding:12px 16px;'
            f'margin:0 0 18px;background:{ALT}"><div style="font-weight:600;color:{NAVY};'
            f'margin-bottom:4px">How to read this, and where it is not neutral</div>'
            f'<ul style="margin:4px 0 0 18px;padding:0;font-size:13px;color:{BODY}">{dl}</ul>'
            f'<div style="font-size:12px;color:{SLATE};margin-top:8px">Conflict of interest: a '
            f'frontier-lab (Anthropic) model helped assign these tiers, including the tiers on '
            f'Anthropic and its rivals. It is tiered in its own map and not exempt.</div></section>')
        trows = "".join(
            f'<tr><td style="padding:4px 10px;border-bottom:1px solid {LINE};vertical-align:top">'
            f'<span style="display:inline-block;width:12px;height:12px;border-radius:2px;'
            f'background:{TIER[int(e["tier"])][0]};margin-right:6px"></span>{esc(e["entity"])}'
            f'{" &#9888;" if e.get("coi") else ""}</td>'
            f'<td style="padding:4px 10px;border-bottom:1px solid {LINE};text-align:center">{esc(e["tier"])}</td>'
            f'<td style="padding:4px 10px;border-bottom:1px solid {LINE};font-size:12px;color:{SLATE}">{esc(e["basis"])}</td></tr>'
            for e in tm.get("entities", []))
        contest_line = (f'Contest any cell: email <a href="mailto:{esc(contest.get("email",""))}" '
                        f'style="color:{NAVY}">{esc(contest.get("email",""))}</a> or fork '
                        f'<code>tier_map.json</code>. {esc(contest.get("how",""))}')
        tiermap_html = (
            f'<details style="border:1px solid {LINE};border-radius:8px;padding:10px 14px;'
            f'margin:0 0 18px;background:#fff"><summary style="font-weight:600;color:{NAVY};'
            f'cursor:pointer">Tier map: every tier with its basis (contest any cell)</summary>'
            f'<div style="font-size:12px;color:{SLATE};margin:6px 0 8px">{contest_line}</div>'
            f'<table style="border-collapse:collapse;width:100%;font-size:13px">'
            f'<thead><tr><th style="text-align:left;padding:4px 10px;color:{SLATE}">Entity</th>'
            f'<th style="padding:4px 10px;color:{SLATE}">Tier</th>'
            f'<th style="text-align:left;padding:4px 10px;color:{SLATE}">Observable basis</th></tr></thead>'
            f'<tbody>{trows}</tbody></table></details>')

    # merge the live feed if fetch_feeds.py has produced it
    feed_path = os.path.join(HERE, "feed_items.json")
    incoming = []
    fetched = ""
    if os.path.isfile(feed_path):
        feed = json.load(open(feed_path, encoding="utf-8"))
        fetched = feed.get("fetched", "")
        incoming = [dict(it, reviewed=it.get("reviewed", False)) for it in feed.get("items", [])]
        # auto-suggest a reality anchor for feed items with no topic yet (plumbing,
        # flagged as unreviewed so it is a suggestion, not an assertion)
        for it in incoming:
            # only suggest an anchor for items NOT yet human-reviewed; a reviewed
            # item with an empty topic means "reviewed, no honest anchor" and is left as-is
            if not it.get("topic") and not it.get("reviewed"):
                t = tag_topic(it.get("headline", ""))
                if t:
                    it["topic"], it["_auto_topic"] = t, True

        # freshest first: order the live feed by parsed date, newest at the top
        incoming.sort(key=lambda it: parse_date(it.get("date", "")), reverse=True)

    reviewed.sort(key=lambda it: parse_date(it.get("date", "")), reverse=True)
    items = reviewed + incoming

    # scholarship nudge: latest primary papers + datasets (fetch_scholar.py)
    scholar_path = os.path.join(HERE, "scholar_items.json")
    scholar_html = ""
    if os.path.isfile(scholar_path):
        sd = json.load(open(scholar_path, encoding="utf-8"))
        rows = []
        for s in sd.get("items", []):
            kind = "Dataset" if s.get("kind") == "dataset" else "Paper"
            meta = " &middot; ".join(x for x in [esc(s.get("venue","")), esc(s.get("authors","")),
                                                 esc(s.get("date",""))] if x)
            sblob = f'{s.get("title","")} {s.get("authors","")} {s.get("venue","")}'.lower()
            rows.append(
                f'<div class="scholarrow" data-search="{esc(sblob)}" '
                f'style="padding:8px 0;border-bottom:1px solid {LINE}">'
                f'<span style="display:inline-block;font-size:11px;padding:1px 7px;border-radius:4px;'
                f'color:#fff;background:{TIER[2][0]};margin-right:6px">{kind}</span>'
                f'<a href="{esc(s.get("url",""))}" style="color:{NAVY};font-weight:600;'
                f'font-size:14px;text-decoration:none">{esc(s.get("title",""))}</a>'
                f'<div style="font-size:12px;color:{SLATE};margin-top:2px">{meta}</div></div>')
        if rows:
            scholar_html = (
                f'<section style="border:1px solid {LINE};border-left:4px solid {TIER[2][0]};'
                f'border-radius:8px;padding:14px 16px;margin:0 0 18px;background:#fff">'
                f'<h2 style="color:{NAVY};font-size:18px;margin:0 0 2px">Primary sources</h2>'
                f'<div style="font-size:13px;color:{SLATE};margin-bottom:8px">Recent papers and '
                f'public datasets on AI, so a claim can be checked against the underlying research '
                f'rather than the coverage of it. Fetched {esc(sd.get("fetched",""))}.</div>'
                + "".join(rows) + "</section>")

    # board-level aggregates (over everything)
    all_tiers, entity_counts = {}, {}
    for it in items:
        entity_counts[it["entity"]] = entity_counts.get(it["entity"], 0) + 1
        for s in it["sources"]:
            t = int(s["motive_tier"])
            all_tiers[t] = all_tiers.get(t, 0) + 1

    movers = "".join(
        f'<tr><td style="padding:4px 10px;border-bottom:1px solid {LINE}">{esc(e)}</td>'
        f'<td style="padding:4px 10px;border-bottom:1px solid {LINE};text-align:right">{n}</td></tr>'
        for e, n in sorted(entity_counts.items(), key=lambda kv: -kv[1]))

    # freshest news leads; curated anchored examples (seed, some pre-2026) sit below.
    feed_block = ""
    if incoming:
        feed_block = (
            f'<h2 style="color:{NAVY};font-size:18px;margin:0 0 4px">Latest</h2>'
            f'<div style="color:{SLATE};font-size:13px;margin-bottom:12px">'
            f'Live pull, newest first. Auto-tagged: source type and motive tier are set from the '
            f'domain; claim type and denominator are left as "unreviewed" until a human pass. '
            f'Fetched {esc(fetched)}.</div>'
            + "".join(item_card(it, anchors, plain) for it in incoming))
    seed_block = (
        f'<h2 style="color:{NAVY};font-size:18px;margin:30px 0 4px">Anchored examples</h2>'
        f'<div style="color:{SLATE};font-size:13px;margin-bottom:12px">'
        f'Curated claims each carried against a published base rate, kept for reference. '
        f'Newest first; some predate 2026.</div>'
        + "".join(item_card(it, anchors, plain) for it in reviewed))
    cards = feed_block + seed_block

    # motive-tier UI is optional: --plain drops the key, the tier map and both bars
    legend_html = "" if plain else legend()
    plain_note = ("" if not plain else
        f'<div style="border:1px solid {LINE};border-radius:8px;padding:10px 14px;'
        f'margin:0 0 18px;background:#fff;font-size:13px;color:{BODY}">'
        f'<strong style="color:{NAVY}">Motive tiering is off.</strong> Sources are shown '
        f'plain, with no incentive colouring. The denominator, claim-type, track-record and '
        f'reality-anchor flags are unchanged. Rebuild without <code>--plain</code> to restore '
        f'the motive view.</div>')
    sourcemix_html = ("" if plain else
        f'<div style="border:1px solid {LINE};border-radius:8px;padding:12px 14px;margin:0 0 18px;background:#fff">'
        f'<div style="font-weight:600;color:{NAVY};margin-bottom:6px">Source mix across all items</div>'
        f'{bar(all_tiers)}'
        f'<table style="border-collapse:collapse;font-size:13px;margin-top:12px;width:100%">'
        f'<thead><tr><th style="text-align:left;padding:4px 10px;color:{SLATE}">Most-covered entity</th>'
        f'<th style="text-align:right;padding:4px 10px;color:{SLATE}">Items</th></tr></thead>'
        f'<tbody>{movers}</tbody></table></div>')

    # the four explainer panels are collapsed into one closed panel so the reader
    # reaches the news cards immediately (they were stacked open and congested the top)
    about_html = ("" if plain else
        f'<details class="tierui" style="border:1px solid {LINE};border-radius:8px;'
        f'padding:10px 14px;margin:0 0 18px;background:#fff">'
        f'<summary style="font-weight:600;color:{NAVY};cursor:pointer">'
        f'How to read this board &middot; motive key, neutrality notes, tier map and source mix</summary>'
        f'<div style="margin-top:12px">{legend_html}{neutrality_html}{tiermap_html}{sourcemix_html}</div>'
        f'</details>')

    # disclosed-conflict panel: the US government's three hats on AI (gov_conflict.json).
    # Shown in both modes: it is a conflict-disclosure axis, independent of motive tiering.
    gc_path = os.path.join(HERE, "gov_conflict.json")
    govconflict_html = ""
    if os.path.isfile(gc_path):
        govconflict_html = gov_conflict_panel(json.load(open(gc_path, encoding="utf-8")))

    # AI Watch dashboard: dated resolution calendar + live gauges (registers.json)
    reg_path = os.path.join(HERE, "registers.json")
    ai_watch_html = ""
    if os.path.isfile(reg_path):
        ai_watch_html = ai_watch_panel(json.load(open(reg_path, encoding="utf-8")))

    # ---- sidebar controls: search + topic/tier filters + live tier toggle ----
    topic_counts, tiers_present = {}, set()
    for it in items:
        tp = it.get("topic", "")
        topic_counts[tp] = topic_counts.get(tp, 0) + 1
        for s in it["sources"]:
            tiers_present.add(int(s["motive_tier"]))
    topic_boxes = "".join(
        f'<label><input type="checkbox" class="f-topic" value="{esc(k)}" checked> '
        f'{esc(TOPIC_LABELS.get(k, k or "Untagged"))} '
        f'<span style="color:{SLATE}">({topic_counts[k]})</span></label>'
        for k in TOPIC_LABELS if k in topic_counts)
    tier_boxes = "".join(
        f'<label><input type="checkbox" class="f-tier" value="{t}" checked> '
        f'<span style="display:inline-block;width:10px;height:10px;border-radius:2px;'
        f'background:{TIER[t][0]};margin-right:4px"></span>Tier {t}</label>'
        for t in sorted(tiers_present))
    btn_label = "Show motive tiers" if plain else "Hide motive tiers"
    sidebar_html = (
        f'<aside class="side">'
        f'<input id="q" class="search" type="search" placeholder="Search feed and papers...">'
        f'<div class="fgroup"><h4>Topics</h4>{topic_boxes}</div>'
        f'<div class="fgroup tierui"><h4>Motive tier</h4>{tier_boxes}</div>'
        f'<div class="fgroup"><label><input type="checkbox" id="conflictonly"> '
        f'Disclosed conflict only</label></div>'
        f'<button id="tiertoggle" class="tierbtn">{btn_label}</button>'
        f'<div id="count" class="count"></div></aside>')

    style_block = f"""<style>
  body{{margin:0;background:{ALT};color:{BODY};font-family:Arial,Helvetica,sans-serif;line-height:1.5}}
  .wrap{{max-width:1040px;margin:0 auto;padding:28px 20px 60px}}
  .layout{{display:flex;gap:24px;align-items:flex-start}}
  .side{{flex:0 0 210px;position:sticky;top:16px}}
  .main{{flex:1;min-width:0}}
  .search{{width:100%;padding:8px 10px;border:1px solid {LINE};border-radius:6px;font-size:14px;margin-bottom:16px}}
  .fgroup{{margin-bottom:16px;font-size:13px}}
  .fgroup h4{{margin:0 0 6px;color:{NAVY};font-size:11px;text-transform:uppercase;letter-spacing:.05em}}
  .fgroup label{{display:block;margin:4px 0;cursor:pointer;color:{BODY}}}
  .tierbtn{{width:100%;padding:9px;border:1px solid {NAVY};background:#fff;color:{NAVY};border-radius:6px;cursor:pointer;font-size:13px}}
  .tierbtn:hover{{background:{ALT}}}
  .count{{font-size:12px;color:{SLATE};margin-top:12px}}
  body.plainmode .tierui{{display:none!important}}
  body.plainmode .motivebar{{display:none!important}}
  body.plainmode .tierchip{{background:#edf2f7!important;color:{BODY}!important;border:1px solid {LINE}!important}}
  @media(max-width:720px){{.layout{{flex-direction:column}}.side{{position:static;flex:1 1 auto;width:100%}}}}
</style>"""

    script_block = """<script>
(function(){
  var q=document.getElementById('q');
  var tb=[].slice.call(document.querySelectorAll('.f-topic'));
  var tr=[].slice.call(document.querySelectorAll('.f-tier'));
  var cards=[].slice.call(document.querySelectorAll('.card'));
  var sch=[].slice.call(document.querySelectorAll('.scholarrow'));
  var cnt=document.getElementById('count');
  var cf=document.getElementById('conflictonly');
  function vals(a){return a.filter(function(b){return b.checked}).map(function(b){return b.value})}
  function apply(){
    var term=(q.value||'').toLowerCase().trim();
    var tp=vals(tb), ti=vals(tr), shown=0;
    var conly=cf&&cf.checked;
    cards.forEach(function(c){
      var okS=!term||(c.getAttribute('data-search')||'').indexOf(term)>-1;
      var okT=tp.indexOf(c.getAttribute('data-topic')||'')>-1;
      var cts=(c.getAttribute('data-tiers')||'').split(' ').filter(Boolean);
      var okTi=cts.some(function(x){return ti.indexOf(x)>-1});
      var okC=!conly||c.getAttribute('data-conflict')==='1';
      var v=okS&&okT&&okTi&&okC;
      c.style.display=v?'':'none'; if(v)shown++;
    });
    sch.forEach(function(e){
      var okS=!term||(e.getAttribute('data-search')||'').indexOf(term)>-1;
      e.style.display=okS?'':'none';
    });
    if(cnt)cnt.textContent=shown+' of '+cards.length+' items';
  }
  q.addEventListener('input',apply);
  tb.concat(tr).forEach(function(b){b.addEventListener('change',apply)});
  if(cf)cf.addEventListener('change',apply);
  var tt=document.getElementById('tiertoggle');
  tt.addEventListener('click',function(){
    var off=document.body.classList.toggle('plainmode');
    tt.textContent=off?'Show motive tiers':'Hide motive tiers';
  });
  apply();
})();
</script>"""

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI News Reality Board</title>{style_block}</head>
<body class="{'plainmode' if plain else ''}">
<div class="wrap">
  <h1 style="color:{NAVY};margin:0 0 4px;font-size:26px">AI News Reality Board</h1>
  <div style="color:{SLATE};font-size:14px;margin-bottom:20px;max-width:760px">
    An experimental board that labels AI-news items by source type and the incentive behind a
    claim, notes whether a figure states a denominator, and links to a published base rate where
    one applies. It labels rather than narrates, so the reader draws the conclusion.
    Generated {esc(data.get("generated",""))}.
  </div>
  <div class="layout">
    {sidebar_html}
    <main class="main">
      {plain_note}
      {about_html}
      {cards}
      {ai_watch_html}
      {govconflict_html}
      {scholar_html}
      <div style="font-size:12px;color:{SLATE};margin-top:24px;border-top:1px solid {LINE};padding-top:14px">
        Method: source type and motive tier are assigned from a curated entity map; denominator
        and claim type are the announced-vs-delivered lens; the reality anchor links to a published
        base rate when the topic matches. Feed selection is editorial and disclosed. This surfaces
        the structural weakness of a claim; it does not adjudicate truth.<br><br>
        Conflict of interest: the maker of this board is an independent researcher assisted by an
        Anthropic model. Anthropic appears here as a subject and is tagged the same way as every
        other entity. Independent analysis, not investment advice.
      </div>
    </main>
  </div>
</div>
{script_block}
</body></html>"""
    open(OUT, "w", encoding="utf-8").write(doc)
    mode = "plain (motive tier OFF)" if plain else "motive-tiered"
    print(f"written: {OUT}  ({len(items)} items, {len(entity_counts)} entities, {mode})")


if __name__ == "__main__":
    main()
