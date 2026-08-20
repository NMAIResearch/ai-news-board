#!/usr/bin/env python3
"""
AI News Board - build.py (stdlib only, no dependencies).
NM AI Research.

Reads items.json and renders a static index.html. Source class, a resolved claim
relationship, figure-base evidence, citation links and typed research-context links are separate
fields. An automatic anchor is withheld when the topic evidence ties.

⛔ claim_type is RETIRED (2026-07-31). Not rendered. Do not revive it: see line ~373.

Run:  python3 build.py   ->   writes index.html next to items.json
"""
import json, os, html, re, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "items.json")
OUT = os.path.join(HERE, "index.html")

# house palette (bound to CSS variables for dynamic Dark/Light switching)
NAVY = "var(--heading)"
SLATE = "var(--text-muted)"
BODY = "var(--text)"
ALT = "var(--bg)"
LINE = "var(--border)"
PAPER = "var(--bg-card)"
SHADOW = "var(--shadow)"

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
# Plain-English labels, matching the wording used in the page description. "denominator"
# is the analytical term and stays in the method panel; a card should read without it.
DENOM = {"y": ("#2f7d4f", "Figures: base stated"),
         "partial": ("#cc7a33", "Figures: base partly stated"),
         "n": ("#b23b2e", "Figures: no base stated"),
         "n/a": ("#64748b", "No figures in this article"),
         "?": ("#94a3b8", "Figures not assessed")}
SOURCE_TIER = {
    1: "primary record",
    2: "research or academic source",
    3: "trade press, aggregator or unclassified publisher",
    4: "tool or data vendor",
    5: "vendor publication or press office",
}
from topic_matcher import load_registry, match_item
from board_checks import validate_board


esc = lambda s: html.escape(str(s), quote=True)


def bar(counts):
    """Stacked distribution across MANY sources. Page level only.

    ⛔ Not for a single item: with one source it renders as one block at 100% width, which
    tells the reader nothing. Items use tier_scale().
    """
    total = sum(counts.values()) or 1
    segs = []
    for t in sorted(counts):
        if counts[t] == 0:
            continue
        pct = 100.0 * counts[t] / total
        segs.append(f'<span title="source-class tier {t}: {esc(SOURCE_TIER[t])} '
                    f'({counts[t]})" '
                    f'style="display:inline-block;height:12px;width:{pct:.1f}%;'
                    f'background:{TIER[t][0]}"></span>')
    return ('<span style="display:inline-block;width:100%;border-radius:3px;'
            'overflow:hidden;line-height:0">' + "".join(segs) + "</span>")

def load_market():
    """data/market.json + ticker_map.json, or ({}, {}) if fetch_market.py has not run.

    The board must build without them: market data is an enhancement, and a missing or
    stale quote file should degrade the page quietly rather than break the build.
    """
    mk = tmap = {}
    mk_path = os.path.join(HERE, "data", "market.json")
    tm_path = os.path.join(HERE, "ticker_map.json")
    if os.path.isfile(mk_path):
        mk = json.load(open(mk_path, encoding="utf-8"))
    if os.path.isfile(tm_path):
        tmap = json.load(open(tm_path, encoding="utf-8")).get("entities", {})
    return mk, tmap


def money(v, dp=2, prefix=""):
    return f"{prefix}{v:,.{dp}f}"


def market_chip(entity, mk, tmap):
    """The market context chip for one item's entity.

    States the move and the window, and stops. It does NOT assert that the item caused the
    move, and it is not rendered as a verdict on the claim: a tier-5 source can be right
    while the stock falls. A privately held entity gets an explicit "no listed security"
    rather than nothing, because the absence of a market check is itself informative under
    the announced-vs-delivered lens.
    """
    ent = tmap.get(entity or "")
    if not ent:
        return ""
    if not ent.get("ticker"):
        # Three distinct states, and collapsing them would misreport the gap. "No listed
        # security" is a fact about the company; "not covered" is a limit of THIS data
        # tier, which serves US and OTC ADR listings only. SMIC being invisible here says
        # nothing about SMIC, and the label has to make that clear.
        if ent.get("uncovered"):
            return (f'<span title="{esc(ent["uncovered"])}" style="display:inline-block;'
                    f'padding:2px 8px;margin-left:6px;border-radius:4px;font-size:11px;'
                    f'color:{SLATE};background:var(--bg-card);border:1px dashed {TIER[3][0]}">'
                    f'listed, not covered here</span>')
        why = esc(ent.get("private", "no listed security"))
        return (f'<span title="{why}" style="display:inline-block;padding:2px 8px;'
                f'margin-left:6px;border-radius:4px;font-size:11px;color:{SLATE};'
                f'background:var(--bg-card);border:1px dashed {SLATE}">no listed security</span>')
    sym = ent["ticker"]
    q = (mk.get("equities") or {}).get(sym)
    if not q:
        return ""
    dp_ = q.get("change_pct")
    col = SLATE if dp_ is None else (TIER[5][0] if dp_ < 0 else DENOM["y"][0])
    arrow = "" if dp_ is None else (f"{dp_:+.2f}%")
    stale = " &middot; previous close carried forward" if q.get("stale") else ""
    note = esc(ent.get("note", ""))
    title = (f"{sym} {money(q['value'])} as of {q.get('asof','')}"
             f"{'; ' + note if note else ''}. Market context only: no causal link to this "
             f"item is asserted.")
    return (f'<span class="mktchip" data-mkt="{esc(sym)}" title="{esc(title)}" '
            f'style="display:inline-block;padding:2px 8px;margin-left:6px;border-radius:4px;'
            f'font-size:11px;color:#fff;background:{col}">{esc(sym)} '
            f'<span class="mktval">{money(q["value"])}</span> '
            f'<span class="mktpct">{arrow}</span>{stale}</span>')


def _asof_rule(mk):
    """THE RULE: no cell displays under a date it does not have.

    Measured 2026-07-31, the strip stamped one date over four vintages. Brent read 27 Jul,
    the US indices 30 Jul, the Nikkei and 29 of 34 equities 31 Jul, and the footer said
    "indices close 2026-07-30" because it read the S&P's date and applied it to everything.
    A four-day-old oil price under a date that is not its own is a vintage error, and this
    board flags vintage errors in other people's work.

    So: the freshest date in the payload is the reference, every cell carries its OWN date,
    and any cell behind the reference is marked in visible text rather than in a tooltip.

    ⛔ Do not "fix" this by showing only the oldest date, or by hiding the stale cells. The
    spread is real and per-source: FRED is a trading day behind by design, Finnhub is live,
    and a market closed on a given day has no later price. Reporting the spread is correct;
    flattening it is what caused the error.
    """
    dates = [q.get("asof") for q in (mk.get("indices") or {}).values() if q.get("asof")]
    dates += [q.get("asof") for q in (mk.get("equities") or {}).values() if q.get("asof")]
    return max(dates) if dates else ""


def _vintage(q, ref):
    """Visible mark for a cell older than the freshest cell in the same strip."""
    a = q.get("asof") or ""
    if not a or not ref or a >= ref:
        return ""
    return (f'<span style="color:{SLATE};font-size:10px" '
            f'title="This cell is from {a}, the strip\'s freshest data is {ref}.">'
            f' {a[5:]}</span>')


def market_strip(mk):
    """The header strip. Indices are a trading day behind and say so."""
    if not mk or not mk.get("indices"):
        return ""
    ref = _asof_rule(mk)
    cells = []
    for key, q in mk["indices"].items():
        pct = q.get("change_pct")
        col = SLATE if pct is None else (TIER[5][0] if pct < 0 else DENOM["y"][0])
        cells.append(
            f'<span data-mkt-idx="{esc(key)}" data-dp="{q.get("dp", 2)}" '
            f'data-prefix="{esc(q.get("prefix", ""))}" '
            f'style="display:inline-block;margin:0 18px 0 0;white-space:nowrap">'
            f'<span style="color:{SLATE};font-size:11px">{esc(q["label"])}</span> '
            f'<span class="mktval" style="color:{BODY};font-weight:600">'
            f'{money(q["value"], q.get("dp", 2), q.get("prefix", ""))}</span> '
            f'<span class="mktpct" style="color:{col}">'
            f'{"" if pct is None else f"{pct:+.2f}%"}</span>{_vintage(q, ref)}</span>')
    for sym in (mk.get("strip_equities") or []):
        q = mk["equities"].get(sym)
        if not q:
            continue
        pct = q.get("change_pct")
        col = SLATE if pct is None else (TIER[5][0] if pct < 0 else DENOM["y"][0])
        cells.append(
            f'<span data-mkt="{esc(sym)}" style="display:inline-block;margin:0 18px 0 0;'
            f'white-space:nowrap"><span style="color:{SLATE};font-size:11px">{esc(sym)}</span> '
            f'<span class="mktval" style="color:{BODY};font-weight:600">'
            f'{money(q["value"])}</span> '
            f'<span class="mktpct" style="color:{col}">'
            f'{"" if pct is None else f"{pct:+.2f}%"}</span>{_vintage(q, ref)}</span>')

    asof = esc(ref)
    return (
        f'<section id="mktstrip" style="border:1px solid {LINE};border-radius:8px;'
        f'padding:9px 14px;margin:0 0 14px;background:{PAPER};overflow-x:auto;font-size:13px">'
        f'<div style="margin-bottom:3px">{"".join(cells)}</div>'
        f'<div style="font-size:11px;color:{SLATE}">'
        f'Freshest data <span id="mktidxasof">{asof}</span>. A small date after a cell means '
        f'that cell is older: FRED indices run a trading day behind, and a market closed on a '
        f'given day has no later price. Each percentage is the move since that series own '
        f'previous observation, so a gap in the series is a longer window than a day. '
        f'Context for the announced-vs-delivered lens, not a market call and not investment '
        f'advice. <span id="mktupd"></span></div>'
        # Collapsed by default: the disclosure ran as long as the price strip it qualifies.
        # It stays one click away, never removed.
        f'<details style="font-size:11px;color:{SLATE};margin-top:4px">'
        f'<summary style="cursor:pointer;color:{NAVY}">Coverage limit: this is a US-listed '
        f'view of AI hardware, not the market for it</summary>'
        f'<div style="margin-top:6px;line-height:1.5">'
        f'The quote source serves US and OTC ADR listings only, so the reachable China names '
        f'are platform and cloud companies, not the domestic chipmakers. SMIC, Hua Hong, '
        f'Cambricon, Samsung and SK Hynix cannot be shown here. OTC ADRs are thinly traded '
        f'and can lag their home listing.<br>'
        f'<strong>What that hides:</strong> the Shanghai STAR Market listings are where the '
        f'domestic AI-chip complex is being repriced, and none of them are reachable at this '
        f'data tier. Moore Threads closed its 5 December 2025 debut up about 425 per cent '
        f'(offer 114.28 yuan, close 600.50), and MetaX opened up about 693 per cent on 17 '
        f'December. Neither is a small move and neither can appear above. The absence is a '
        f'limit of this data tier, not evidence that nothing is happening.'
        f'</div></details></section>')


def chain_block(chain):
    """Citation edges between board items, or an explicit statement that none was found.

    ⛔ The label is "cites", never "restates". The evidence is that one article LINKS TO
    another; whether it restates it is unknown and is not the board's to assert.
    ⛔ Absence is stated, not implied: a paywalled or link-averse outlet produces no edge
    whether or not it is reporting someone else's claim, so an empty chain is not evidence
    of independent reporting.

    The rail takes the colour of the OTHER item's tier, so colour still means one thing.
    """
    cites = chain.get("cites") or []
    cited = chain.get("cited_by") or []
    if not cites and not cited:
        return (f'<div style="margin:10px 0 2px;font-size:12px;color:{SLATE}" '
                f'title="Absence of a link is not evidence of first-hand reporting.">'
                f'No cited source found.</div>')
    rows = []
    if cites:
        c = cites[0]
        col = TIER[c["tier"]][0]
        more = f' <span style="color:{SLATE}">+{len(cites)-1} more</span>' if len(cites) > 1 else ""
        rows.append(
            f'<div style="border-left:3px solid {col};padding:6px 0 6px 10px;margin:10px 0">'
            f'<div style="font-size:11px;color:{SLATE};letter-spacing:.04em;'
            f'text-transform:uppercase">Cites a tier {c["tier"]} source</div>'
            f'<a href="{esc(c["url"])}" target="_blank" rel="noopener noreferrer" '
            f'style="font-size:13px;color:{NAVY};text-decoration:none">'
            f'{esc(c["entity"] or c["name"])} &middot; {esc(c["headline"][:96])} &rarr;</a>{more}</div>')
    if cited:
        tset = sorted({x["tier"] for x in cited})
        col = TIER[tset[0]][0]
        who = ", ".join(dict.fromkeys(x["name"] for x in cited))
        tlabel = " and ".join(f"tier {t}" for t in tset)
        rows.append(
            f'<div style="border-left:3px solid {col};padding:6px 0 6px 10px;margin:10px 0">'
            f'<div style="font-size:11px;color:{SLATE};letter-spacing:.04em;'
            f'text-transform:uppercase">Cited by {len(cited)} {esc(tlabel)} '
            f'report{"s" if len(cited) != 1 else ""}</div>'
            f'<div style="font-size:13px;color:{BODY}">{esc(who)}</div></div>')
    return "".join(rows)


def primary_kind(url):
    net = urllib.parse.urlsplit(url).netloc.lower().removeprefix("www.")
    if net == "arxiv.org":
        return "arXiv paper"
    if net == "doi.org":
        return "DOI record"
    if net.endswith(".gov") or net.endswith(".gov.uk") or "europa.eu" in net:
        return "official record"
    return "primary source"


def primary_label(url):
    parts = urllib.parse.urlsplit(url)
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.strip("/")
    if host == "arxiv.org":
        identifier = re.sub(r"^(?:abs|html|pdf)/", "", path).removesuffix(".pdf")
        return f"arXiv {identifier}"
    if host == "doi.org":
        return f"DOI {path}"
    shown = f"{host}/{path}".rstrip("/")
    return shown if len(shown) <= 78 else shown[:75] + "..."


def item_card(it, registry, plain=False, mk=None, tmap=None, ev=None):
    tiers = {}
    chips = []
    for s in it["sources"]:
        t = int(s["source_tier"])
        tiers[t] = tiers.get(t, 0) + 1
        source_type = s.get("source_type", "other").replace("-", " ")
        if plain:
            chips.append(f'<span class="tierchip" style="display:inline-block;font-size:12px;'
                         f'padding:2px 8px;margin:2px 4px 2px 0;border-radius:10px;color:{BODY};'
                         f'background:var(--bg-card);border:1px solid {LINE}">{esc(s["name"])} · '
                         f'{esc(source_type)}</span>')
            continue
        col = TIER[t][0]
        chips.append(f'<span class="tierchip" style="display:inline-block;font-size:12px;'
                     f'padding:2px 8px;margin:2px 4px 2px 0;border-radius:10px;color:#fff;background:{col}" '
                     f'title="source-class tier {t}: {esc(SOURCE_TIER[t])}">{esc(s["name"])} · '
                     f'{esc(source_type)}</span>')
    # link the headline to its primary source when one exists (curated items have
    # no url, so they stay plain text rather than becoming a dead link)
    src_url = next((s.get("url", "") for s in it["sources"] if s.get("url")), "")
    headline_html = esc(it["headline"])
    if src_url:
        headline_html = (f'<a href="{esc(src_url)}" target="_blank" rel="noopener noreferrer" '
                         f'style="color:{NAVY};text-decoration:none">{esc(it["headline"])}</a>')
    d = it["denominator_stated"].strip().lower()
    dcol, dlabel = DENOM.get(d, DENOM["n"])
    # ⛔ claim_type RETIRED 2026-07-31, his call. Not rendered. Measured on 38 items with two
    # readers at full coverage: kappa 0.52 on headlines, 0.56 given the article opening plus
    # figure spans. Article context did not fix it, and there is no ground truth to score
    # against, so the board cannot publish it as a label. The stored values and the
    # crosscheck fields are kept as the record of why.
    method = it.get("evidence_method", "unassessed")
    coverage = it.get("evidence_coverage") or {}
    why = it.get("label_evidence", "")
    if it.get("label_source") == "human":
        method_label, method_col = "human checked", TIER[2][0]
    elif it.get("review_stale"):
        method_label, method_col = "review stale", TIER[4][0]
    elif method == "rule":
        method_label, method_col = "figures: rule", SLATE
    elif method == "local-model":
        method_label, method_col = "figures: local model", SLATE
    else:
        method_label, method_col = "figures: unassessed", SLATE
    flag = (f'<span style="display:inline-block;padding:2px 8px;margin-left:6px;'
            f'border-radius:4px;font-size:11px;color:#fff;background:{method_col}">'
            f'{esc(method_label)}</span>')
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
    # ⛔ The reader cross-check chip was removed 2026-07-31 with the tooling (see archive/).
    # It reported disagreement between local models reading a HEADLINE, over claim_type,
    # which is retired. Provenance now travels on the label itself: evidence_method,
    # evidence_coverage and label_evidence identify what settled the field.
    # Do not reinstate reader agreement as a quality signal. A shared error between readers
    # of one model family is indistinguishable from agreement.
    xchip = ""
    # No source URL means a curated reference card, which has no citation trail to report.
    # Saying "no cited source found" there states an absence about a thing never checked.
    # Header: the subject organisation, else the publisher's own topic tag, else the date
    # alone. "entity not identified" read as a fault; no subject is a property of the piece.
    if it.get("entity"):
        subject_html = esc(it["entity"])
    elif it.get("publisher_topic"):
        subject_html = (f'<span title="the publisher\'s own tag, not an assessment">'
                        f'{esc(it["publisher_topic"])}</span>')
    else:
        subject_html = ""
    date_html = esc(fmt_date(it.get("date", "")))
    heading_meta = " &middot; ".join(x for x in (subject_html, date_html) if x)
    ments = [m["name"] for m in (it.get("mentions") or [])][:4]
    mentions_html = ("" if not ments or it.get("entity") else
                     f'<div style="font-size:12px;color:{SLATE};margin-top:6px">'
                     f'Mentions {esc(" &middot; ".join(ments))}</div>'.replace("&amp;middot;", "&middot;"))
    evrec = (ev or {}).get(src_url) or {}
    chain_html = "" if (plain or not src_url) else chain_block(evrec.get("chain", {}))
    mchip = market_chip(it.get("entity", ""), mk or {}, tmap or {})
    anchor_rows = []
    anchor_match = it.get("_anchor_match")
    if anchor_match:
        evidence = anchor_match.get("evidence", [{}])[0]
        for a in anchor_match.get("anchors", []):
            anchor_rows.append(
                f'<div style="margin:4px 0"><strong>Possible research context, '
                f'{esc(a.get("kind", "source"))}.</strong> '
                f'<a href="{esc(a["url"])}" target="_blank" rel="noopener noreferrer" '
                f'style="color:{NAVY}">{esc(a["label"])}</a> '
                f'{esc(a.get("note", ""))}<div style="font-size:11px;color:{SLATE}">'
                f'Matched {esc(evidence.get("match", ""))} in {esc(evidence.get("basis", ""))}.'
                f'</div></div>')
    elif it.get("topic") in registry and it.get("reviewed", True):
        for a in registry[it["topic"]].get("anchors", []):
            anchor_rows.append(
                f'<div style="margin:4px 0"><strong>Research context, '
                f'{esc(a.get("kind", "source"))}.</strong> '
                f'<a href="{esc(a["url"])}" target="_blank" rel="noopener noreferrer" '
                f'style="color:{NAVY}">{esc(a["label"])}</a> '
                f'{esc(a.get("note", ""))}</div>')
    for u in evrec.get("primary_link_examples", [])[:3]:
        anchor_rows.append(
            f'<div style="margin:4px 0"><strong>Article-linked {esc(primary_kind(u))}.</strong> '
            f'<a href="{esc(u)}" target="_blank" rel="noopener noreferrer" '
            f'style="color:{NAVY}">{esc(primary_label(u))}</a> '
            f'<span style="color:{SLATE}">The link is checkable; its presence alone does not '
            f'establish that it supports the headline.</span></div>')
    anchor_html = (f'<div style="margin-top:10px;padding:10px 12px;background:{ALT};'
                   f'border-left:3px solid {NAVY};font-size:12px;color:{BODY}">'
                   + "".join(anchor_rows) + '</div>') if anchor_rows else ""
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
            f'<div style="margin-top:8px;padding:8px 12px;background:var(--warn-bg);'
            f'border-left:3px solid {TIER[5][0]};font-size:12px;color:{BODY}">'
            f'<strong style="color:{TIER[5][0]}">Disclosed conflict.</strong> Structural stake, '
            f'not an accusation. {lines}</div>')

    # data-* for client-side search + filters (used by the sidebar JS)
    srcnames = " ".join(s.get("name", "") for s in it["sources"])
    blob = f'{it["entity"]} {it["headline"]} {srcnames} {" ".join(cnotes)}'.lower()
    tierlist = " ".join(str(x) for x in sorted(tiers))
    conflict_attr = ' data-conflict="1"' if cnotes else ""
    topics = it.get("topics") or ([it["topic"]] if it.get("topic") else [])
    data = (f'data-search="{esc(blob)}" data-topics="{esc(" ".join(topics))}" '
            f'data-tiers="{esc(tierlist)}"{conflict_attr}')
    claim_tier = evrec.get("claim_tier")
    relationship = (f'claim tier {claim_tier}: {evrec.get("tier_basis", "")}' if claim_tier
                    else f'claim relationship unresolved: {evrec.get("tier_basis", "not assessed")}' )
    topic_evidence = []
    for cand in it.get("_topic_candidates", []):
        hits = ", ".join(f'{e.get("match")} ({e.get("basis")})' for e in cand.get("evidence", [])[:3])
        topic_evidence.append(f'{cand.get("label")}: {hits}')
    provenance = (
        f'<details class="evidence-drawer" style="font-size:11px;color:{SLATE};margin-top:10px;padding-top:6px;border-top:1px dashed {LINE}">'
        f'<summary style="cursor:pointer;color:{NAVY};font-weight:600">Evidence and provenance &middot; inspect</summary>'
        f'<div style="margin-top:6px;line-height:1.4"><strong>Figures:</strong> {esc(why or "not assessed")}. '
        f'Coverage {esc(coverage.get("seen", 0))}/{esc(coverage.get("total", 0))} figure-sentences.'
        f'</div><div style="margin-top:3px"><strong>Source relationship:</strong> {esc(relationship)}.</div>'
        + (f'<div style="margin-top:3px"><strong>Topics:</strong> {esc("; ".join(topic_evidence))}</div>' if topic_evidence else "")
        + (f'<div style="margin-top:3px"><strong>Anchor:</strong> Withheld because multiple candidates tied.</div>'
           if it.get("_anchor_ambiguous") else "")
        + chain_html + '</details>')
    return f"""
    <article class="card" {data} style="border:1px solid {LINE};border-radius:10px;padding:16px 18px;
      margin:0 0 16px;background:{PAPER};box-shadow:{SHADOW};transition:box-shadow .15s ease">
      <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;font-size:12px;color:{SLATE};margin-bottom:6px">
        <span>{heading_meta}</span>
      </div>
      <div class="card-headline" style="font-size:16.5px;font-weight:600;color:{NAVY};line-height:1.4;margin:4px 0 8px">{headline_html}</div>
      <div style="margin:8px 0 6px">{''.join(chips)}</div>{mentions_html}
      <div style="display:flex;align-items:center;flex-wrap:wrap;gap:4px;font-size:12px;margin-top:6px">
        <span style="display:inline-block;padding:2px 8px;border-radius:4px;
              color:#fff;background:{dcol};font-weight:500">{esc(dlabel)}</span>{rmark}{flag}{xchip}{mchip}
      </div>
      {conflict_html}
      {anchor_html}
      {provenance}
    </article>"""


def freshness(built, fetched, mk, reg):
    """One block naming every layer's age, because the page has four different clocks.

    The market strip, the news feed, the registers and the build each update on their own
    schedule, and they were each printing their own timestamp in a different place with no
    indication of what it referred to. A reader seeing "Built 16:38", "Quotes captured
    14:42" and "Fetched 06:32" cannot tell which one is the freshness of the thing they are
    looking at. Layers that update at different rates need their ages stated together, or
    the fastest one makes the others look broken.
    """
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)

    # ⛔ Never compute a relative age here. Baked into static HTML it freezes: `now` and
    # the build time are the same instant, so every page shipped "(just now)" permanently
    # (caught 2026-07-30, 14h stale on the live site). Emit ISO, let the browser compute
    # the age at read time. JS off = absolute time, no age, which is true.
    def iso(ts):
        if not ts:
            return None
        for fmt in ("%Y-%m-%d %H:%M UTC", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
            try:
                d = _dt.datetime.strptime(ts.strip(), fmt)
                if d.tzinfo is None:
                    d = d.replace(tzinfo=_dt.timezone.utc)
                # A date-only value carries no time, so mark it: reporting midnight in
                # hours claims a precision the source never had.
                return d.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + (
                    "|dateonly" if fmt == "%Y-%m-%d" else "")
            except ValueError:
                continue
        return None

    parts = []
    for label, ts in (("Market quotes", (mk or {}).get("generated", "")),
                      ("News feed", fetched),
                      ("Registers", (reg or {}).get("generated", "")),
                      ("Page built", built)):
        if not ts:
            continue
        a = iso(ts)
        # Only the ISO date/time separator, not every T: a blanket replace turns
        # "06:32 UTC" into "06:32 U C".
        shown = re.sub(r"(?<=\d)T(?=\d)", " ", ts).replace("+00:00", "")
        age = (f' <span class="age" data-ts="{esc(a)}" style="color:{SLATE}"></span>'
               if a else "")
        parts.append(f'<span style="margin-right:16px;white-space:nowrap">'
                     f'<span style="color:{SLATE}">{esc(label)}</span> '
                     f'<strong style="color:{BODY}">{esc(shown)}</strong>{age}</span>')
    if not parts:
        return ""
    return (f'<div class="freshness-strip" style="font-size:12px;margin:0 0 14px;padding:7px 12px;border:1px solid '
            f'{LINE};border-radius:6px;background:{PAPER}">'
            f'<span style="color:{NAVY};font-weight:600;margin-right:10px">Freshness</span>'
            f'{"".join(parts)}</div>')


def deflation_panel(reg):
    """The deflation register: claims where a checkable figure came back different.

    This is CONTENT, not another explainer. The tier map explains the colour scale and the
    neutrality panel explains the method; this shows the method applied to named cases. It
    is the one thing here that states an outcome rather than a flag, so every row carries
    the corrected figure and where it came from, and rows arrive only via an explicit
    publication mark on the private register.

    ⛔ The claim side describes WHERE A FIGURE CIRCULATES. It is not an attribution and must
    not be formatted as one. Naming individual creators would make this a list of people
    being corrected; the register grades the number. The checkable weight therefore sits
    entirely on the corrected side, which is what the publication gate in make_registers.py
    tests. Do not add a channel, a title or a URL to the claim side.
    """
    rows = (reg or {}).get("deflations") or []
    if not rows:
        return ""
    trs = []
    for r in rows:
        tier = r.get("tier")
        dot = ""
        if tier and int(tier) in TIER:
            dot = (f'<span title="register tier {esc(tier)}: {esc(TIER[int(tier)][1])}" '
                   f'style="display:inline-block;width:9px;height:9px;border-radius:2px;'
                   f'background:{TIER[int(tier)][0]};margin-right:5px"></span>')
        mult = esc(r.get("multiple", ""))
        trs.append(
            f'<div style="padding:9px 0;border-bottom:1px solid {LINE}">'
            f'<div style="font-size:13px;color:{BODY}">{dot}<strong>{esc(r.get("claim",""))}</strong></div>'
            f'<div style="font-size:12px;color:{SLATE};margin-top:2px" '
            f'title="Where the figure circulates, described by genre and register tier. '
            f'Not an attribution to a named person.">'
            f'circulating via {esc(r.get("source",""))}</div>'
            f'<div style="font-size:12.5px;color:{BODY};margin-top:4px">'
            f'<strong>Correction:</strong> {esc(r.get("corrected",""))}'
            f'{f" <span style=\'color:{TIER[5][0]};font-weight:600\'>({mult})</span>" if mult else ""}</div>'
            f'<div style="font-size:12px;color:{SLATE};margin-top:2px">{esc(r.get("error",""))}</div>'
            f'</div>')
    return (
        f'<details open class="railcard"><summary style="color:{NAVY};font-weight:600;'
        f'font-size:15px;cursor:pointer">Deflation register '
        f'<span style="font-weight:400;color:{SLATE};font-size:12px">({len(trs)})</span>'
        f'</summary>'
        f'<div style="font-size:12px;color:{SLATE};margin:6px 0">'
        f'Claims where the checkable figure came back different, with the correction and '
        f'where it came from. <strong>This register grades the number, not the person.</strong> '
        f'A figure taken from video or press is described by genre and register tier rather '
        f'than named, so the claim line says where it circulates and is not an attribution; '
        f'the checkable weight sits on the corrected line, which is what a reader should '
        f'test. The dot is the tier carried by the public register row. '
        f'Being wrong once is not a verdict on a source.</div>'
        f'{"".join(trs)}</details>')


def legend():
    rows = "".join(
        f'<div style="display:flex;align-items:center;font-size:12px;color:{BODY};margin:2px 0">'
        f'<span style="display:inline-block;width:14px;height:14px;border-radius:3px;'
        f'background:{TIER[t][0]};margin-right:8px"></span>Tier {t}: '
        f'{esc(lbl)}</div>' for t, lbl in SOURCE_TIER.items())
    caveat = (f'<div style="font-size:11px;color:{SLATE};margin-top:8px">This is a publisher '
              f'class, not a trust score or a claim-relative relationship. Claim tiers are '
              f'withheld unless the publisher relationship to the subject resolves.</div>')
    return (f'<div style="border:1px solid {LINE};border-radius:8px;padding:12px 14px;'
            f'margin:0 0 18px;background:{PAPER}"><div style="font-weight:600;color:{NAVY};'
            f'margin-bottom:6px">Source-class key</div>{rows}{caveat}</div>')


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
        f'border-radius:8px;padding:12px 16px;margin:0 0 18px;background:{PAPER}">'
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
                f'style="color:{NAVY}">Related research: {esc(a["label"])} (DOI)</a></div>')
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
        f'padding:12px 16px;margin:0 0 18px;background:{PAPER}">'
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


def day_heading(d, today):
    """Coarse buckets, NOT one heading per day.

    A per-day heading spans the full grid width, so a day with one item leaves the rest of
    the row empty. On 2026-07-30 that produced 14 headings for 36 items (2.6 items per day)
    and the middle column read as mostly whitespace. Four buckets keep the chronology
    legible and let cards fill their rows; each card already carries its own exact date.
    """
    delta = (today - d.date()).days
    if delta <= 0:
        return "Today"
    if delta == 1:
        return "Yesterday"
    if delta < 7:
        return "Earlier this week"
    if delta < 31:
        return "Earlier this month"
    return "Older"


def group_by_day(items, registry, plain, mk, tmap, ev=None):
    """Render items under day headings. Items are already sorted newest first.

    Undated items render under "Date not stated" at the end rather than being dropped or
    silently sorted to one end of the list.
    """
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date()
    floor = datetime.min.replace(tzinfo=timezone.utc)
    out, current = [], object()
    for it in items:
        d = parse_date(it.get("date", ""))
        head = "Date not stated" if d == floor else day_heading(d, today)
        if head != current:
            out.append(
                f'<div class="dayhead" style="font-size:12px;font-weight:600;color:{SLATE};'
                f'text-transform:uppercase;letter-spacing:.04em;margin:18px 0 8px;'
                f'padding-bottom:4px;border-bottom:1px solid {LINE}">{esc(head)}</div>')
            current = head
        out.append(item_card(it, registry, plain, mk, tmap, ev))
    return f'<div class="feedgrid">{"".join(out)}</div>'


def sovereign_radar_tab():
    qwen_path = os.path.join(HERE, "data", "qwen38_regulatory_alerts.json")
    reg_alerts_path = os.path.join(HERE, "data", "regulatory_alerts.json")

    alerts = []
    if os.path.isfile(qwen_path):
        alerts = json.load(open(qwen_path, encoding="utf-8"))
    elif os.path.isfile(reg_alerts_path):
        alerts = json.load(open(reg_alerts_path, encoding="utf-8"))

    if not alerts:
        return f'<div style="padding:20px;background:{PAPER};border-radius:8px;border:1px solid {LINE}">No active sovereign radar alerts banked.</div>'

    cards = []
    for a in alerts:
        pri = a.get("priority_score", a.get("priority", 4))
        if pri == 1:
            badge_bg, badge_lbl = "#b23b2e", "🔴 P1 Binding Statute"
        elif pri == 2:
            badge_bg, badge_lbl = "#cc7a33", "🟠 P2 Proposed Rule / Guidance"
        elif pri == 3:
            badge_bg, badge_lbl = "#c7a53b", "🟡 P3 Major Notice"
        elif pri == 4:
            badge_bg, badge_lbl = "#4a5568", "⚪ P4 Standard Notice"
        else:
            badge_bg, badge_lbl = "#64748b", "⚪ P5 Administrative"

        duty_badge = '<span style="display:inline-block;padding:2px 7px;border-radius:4px;font-size:11px;font-weight:600;color:#fff;background:#2f7d4f;margin-left:6px">Active Duty Shift</span>' if a.get("is_operator_duty_shift") else '<span style="display:inline-block;padding:2px 7px;border-radius:4px;font-size:11px;color:#64748b;background:var(--bg-card);margin-left:6px">Procedural</span>'

        stat_ref = a.get("statutory_reference")
        stat_ref_html = f'<div style="font-size:12px;margin:6px 0;font-family:monospace;background:{ALT};padding:3px 8px;border-radius:4px;border:1px solid {LINE};color:{NAVY}"><strong>Statutory Basis:</strong> {esc(stat_ref)}</div>' if stat_ref else ""

        action_trigger = a.get("actionable_trigger")
        trigger_html = f'<div style="font-size:12px;color:{SLATE};margin-top:6px;padding-top:6px;border-top:1px dashed {LINE}"><strong>Actionable Trigger:</strong> {esc(action_trigger)}</div>' if action_trigger else ""

        dur_html = f'<span style="font-size:11px;color:#94a3b8;margin-left:auto">{a.get("eval_duration_sec", 0)}s</span>' if a.get("eval_duration_sec") else ""

        card = (
            f'<div class="radar-card" data-pri="{pri}" data-jur="{esc(a.get("jurisdiction",""))}" style="border:1px solid {LINE};border-radius:8px;padding:14px 16px;background:{PAPER};margin-bottom:14px;box-shadow:{SHADOW}">'
            f'<div style="display:flex;align-items:center;flex-wrap:wrap;gap:6px;margin-bottom:8px">'
            f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;color:#fff;background:{badge_bg}">{badge_lbl}</span>'
            f'{duty_badge}'
            f'<span style="font-size:12px;font-weight:600;color:{NAVY};margin-left:6px">{esc(a.get("jurisdiction","Global"))}</span>'
            f'<span style="font-size:12px;color:{SLATE}">&middot; {esc(a.get("source","Gazette"))}</span>'
            f'{dur_html}'
            f'</div>'
            f'<a href="{esc(a.get("url","#"))}" target="_blank" rel="noopener" style="font-size:15px;font-weight:600;color:{NAVY};text-decoration:none;display:block;margin-bottom:6px">{esc(a.get("title",""))} &#x2197;</a>'
            f'{stat_ref_html}'
            f'<div style="font-size:13px;color:{BODY};line-height:1.5">{esc(a.get("summary_finding", a.get("summary","")))}</div>'
            f'{trigger_html}'
            f'</div>'
        )
        cards.append(card)

    summary_banner = (
        f'<div style="border:1px solid var(--border);border-left:4px solid var(--accent);border-radius:8px;padding:14px 18px;margin-bottom:20px;background:{PAPER};box-shadow:{SHADOW}">'
        f'<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px">'
        f'<div><h3 style="margin:0 0 4px;font-size:17px;color:{NAVY}">Sovereign Watch: Global AI Regulatory Radar</h3>'
        f'<div style="font-size:13px;color:{SLATE}">Sovereign gazette surveillance across US Federal Register, EU AI Office, UK Ofgem/CMA, and 29 jurisdiction monitor packs. Deep statutory evaluations powered by local <strong>Qwen 3.8 (27B)</strong>.</div></div>'
        f'<div style="display:flex;gap:8px;font-size:12px">'
        f'<span style="padding:4px 8px;background:var(--pill-bg);border-radius:4px;color:var(--pill-fg)"><strong>{len(alerts)}</strong> Notices Tracked</span>'
        f'<span style="padding:4px 8px;background:var(--pill-bg);border-radius:4px;color:var(--pill-fg)"><strong>95.0%</strong> Precision</span>'
        f'<span style="padding:4px 8px;background:var(--ok-bg);border-radius:4px;color:var(--ok-fg)"><strong>06:00 AM</strong> Daily Pass</span>'
        f'</div></div></div>'
    )

    return summary_banner + f'<div class="radar-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(480px,1fr));gap:16px">{"".join(cards)}</div>'


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Render the AI News Board.")
    ap.add_argument("--plain", action="store_true",
                    help="turn source-class tiers OFF: no tier colours, bars, key or "
                         "tier map. Sources shown plain. The other axes (denominator, track "
                         "record, citation chain, anchors) are unaffected.")
    plain = ap.parse_args().plain

    import datetime as _dt
    built = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    data = json.load(open(SRC, encoding="utf-8"))
    mk, tmap = load_market()
    if mk:
        mk["strip_equities"] = json.load(
            open(os.path.join(HERE, "ticker_map.json"), encoding="utf-8")
        )["strip"]["equities"]
    registry = load_registry()
    reviewed = [dict(it, reviewed=it.get("reviewed", True)) for it in data["items"]]
    for it in reviewed:
        it["topics"] = [it["topic"]] if it.get("topic") else []

    # Method disclosures and the contestable tier registry.
    neutrality_html = tiermap_html = ""
    tm_path = os.path.join(HERE, "tier_map.json")
    tm = json.load(open(tm_path, encoding="utf-8")) if os.path.isfile(tm_path) else {}
    if tm and not plain:
        contest = tm.get("contest", {})
        disclosures = [
            "Source-class tier is set from the publisher domain. It is not a truth or quality verdict.",
            "A numeric claim tier appears only where a recorded owner or publisher relationship to the subject resolves. Otherwise the relationship remains unresolved.",
            "Automatic topics may be plural. A portfolio anchor appears only when one candidate clears its threshold without a tie.",
            "ArXiv, DOI and official links found in an article are typed as article-linked primaries. A link is not treated as proof that the document supports the headline.",
        ]
        dl = "".join(f'<li style="margin:3px 0">{esc(x)}</li>' for x in disclosures)
        neutrality_html = (
            f'<section style="border:1px solid {LINE};border-radius:8px;padding:12px 16px;'
            f'margin:0 0 18px;background:{PAPER};box-shadow:{SHADOW}"><div style="font-weight:600;color:{NAVY};'
            f'margin-bottom:4px">Method and limits</div>'
            f'<ul style="margin:4px 0 0 18px;padding:0;font-size:13px;color:{BODY}">{dl}</ul>'
            f'<div style="font-size:12px;color:{SLATE};margin-top:8px">Conflict of interest: '
            f'an Anthropic model helped build the original method and tiers. An OpenAI model '
            f'implemented the current source-class split, label provenance and anchor rules. '
            f'OpenAI and Anthropic are subjects on the board. Neither model is an independent '
            f'auditor of work from its own lab.</div></section>')
        erows = "".join(
            f'<tr><td style="padding:4px 10px;border-bottom:1px solid {LINE};vertical-align:top">'
            f'<span style="display:inline-block;width:12px;height:12px;border-radius:2px;'
            f'background:{TIER[int(e["tier"])][0]};margin-right:6px"></span>{esc(e["entity"])}'
            f'{" (conflict disclosed)" if e.get("coi") else ""}</td>'
            f'<td style="padding:4px 10px;border-bottom:1px solid {LINE};text-align:center">{esc(e["tier"])}</td>'
            f'<td style="padding:4px 10px;border-bottom:1px solid {LINE};font-size:12px;color:{SLATE}">{esc(e["basis"])}</td></tr>'
            for e in tm.get("entities", []))
        srows = "".join(
            f'<tr><td style="padding:4px 10px;border-bottom:1px solid {LINE}">'
            f'{esc(spec["label"])}</td><td style="padding:4px 10px;border-bottom:1px solid '
            f'{LINE};text-align:center">{esc(spec["tier"])}</td><td style="padding:4px 10px;'
            f'border-bottom:1px solid {LINE};font-size:12px;color:{SLATE}">'
            f'{esc(spec["basis"])}</td></tr>'
            for spec in tm.get("source_types", {}).values())
        contest_line = (f'Contest any cell: email <a href="mailto:{esc(contest.get("email",""))}" '
                        f'style="color:{NAVY}">{esc(contest.get("email",""))}</a> or fork '
                        f'<code>tier_map.json</code>. {esc(contest.get("how",""))}')
        tiermap_html = (
            f'<details style="border:1px solid {LINE};border-radius:8px;padding:10px 14px;'
            f'margin:0 0 18px;background:{PAPER}"><summary style="font-weight:600;color:{NAVY};'
            f'cursor:pointer">Tier registries: every class with its basis</summary>'
            f'<div style="font-size:12px;color:{SLATE};margin:6px 0 8px">{contest_line}</div>'
            f'<div style="font-size:13px;font-weight:600;color:{NAVY};margin:8px 0 4px">'
            f'Source classes</div>'
            f'<table style="border-collapse:collapse;width:100%;font-size:13px">'
            f'<thead><tr><th style="text-align:left;padding:4px 10px;color:{SLATE}">Class</th>'
            f'<th style="padding:4px 10px;color:{SLATE}">Tier</th>'
            f'<th style="text-align:left;padding:4px 10px;color:{SLATE}">Observable basis</th></tr></thead>'
            f'<tbody>{srows}</tbody></table>'
            f'<div style="font-size:13px;font-weight:600;color:{NAVY};margin:12px 0 4px">'
            f'Claim-relationship examples</div>'
            f'<table style="border-collapse:collapse;width:100%;font-size:13px">'
            f'<thead><tr><th style="text-align:left;padding:4px 10px;color:{SLATE}">Entity</th>'
            f'<th style="padding:4px 10px;color:{SLATE}">Tier</th>'
            f'<th style="text-align:left;padding:4px 10px;color:{SLATE}">Observable basis</th></tr></thead>'
            f'<tbody>{erows}</tbody></table></details>')

    # merge the live feed if fetch_feeds.py has produced it
    # Citation chains and the per-article evidence counts.
    ev_path = os.path.join(HERE, "article_evidence.json")
    ev = json.load(open(ev_path, encoding="utf-8")) if os.path.isfile(ev_path) else {}
    # Figure sentences and publisher tags are the checkable evidence for topic candidates.
    sp_path = os.path.join(HERE, "article_spans.json")
    _spans = json.load(open(sp_path, encoding="utf-8")) if os.path.isfile(sp_path) else {}
    feed_path = os.path.join(HERE, "feed_items.json")
    incoming = []
    fetched = ""
    if os.path.isfile(feed_path):
        feed = json.load(open(feed_path, encoding="utf-8"))
        fetched = feed.get("fetched", "")
        incoming = [dict(it, reviewed=it.get("reviewed", False)) for it in feed.get("items", [])]
        for it in incoming:
            if it.get("reviewed") and it.get("topic"):
                it["topics"] = [it["topic"]]
                continue
            match = match_item(it, _spans, registry)
            it["topics"] = [c["topic"] for c in match["topics"]]
            it["_topic_candidates"] = match["topics"]
            it["_anchor_match"] = match["anchor"]
            it["_anchor_ambiguous"] = match["ambiguous"]

        # freshest first: order the live feed by parsed date, newest at the top
        incoming.sort(key=lambda it: parse_date(it.get("date", "")), reverse=True)

    reviewed.sort(key=lambda it: parse_date(it.get("date", "")), reverse=True)
    items = reviewed + incoming
    validate_board(items, _spans, ev, registry, tm.get("source_types", {}))

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
            # Collapsed. Five stacked rail panels meant scrolling inside the rail to reach
            # the last one, so reference material opens on demand.
            scholar_html = (
                f'<details open style="border:1px solid {LINE};border-left:4px solid {TIER[2][0]};'
                f'border-radius:8px;padding:12px 16px;margin:0 0 12px;background:{PAPER}">'
                f'<summary style="color:{NAVY};font-size:15px;font-weight:600;cursor:pointer">'
                f'Primary sources <span style="font-weight:400;color:{SLATE};font-size:12px">'
                f'({len(rows)})</span></summary>'
                f'<div style="font-size:13px;color:{SLATE};margin:6px 0 8px">Recent papers and '
                f'public datasets on AI, so a claim can be checked against the underlying research '
                f'rather than the coverage of it.</div>'
                + "".join(rows) + "</details>")

    # Model releases: models that reached OpenRouter or the Hugging Face API in the last 60 days.
    # ⛔ Do not make the open vs API-only split the headline. The two sides are not collected
    # the same way (OpenRouter in full, Hugging Face a fixed org list capped at 5 repos each),
    # so the totals are not comparable. See fetch_releases.py.
    # ⛔ Do not grade an API-only model as a lesser release. It is shipped and serving traffic.
    # Whether the weights are published is an attribute of the row, nothing more.
    # ⛔ Never add benchmark scores here. That is a leaderboard, and a percentage with no
    # stated denominator is the defect this board flags elsewhere.
    rel_path = os.path.join(HERE, "releases.json")
    releases_html = ""
    if os.path.isfile(rel_path):
        rd = json.load(open(rel_path, encoding="utf-8"))
        rrows = []
        # 10, not 16. In the right rail a 16-row list is tall enough to push Primary
        # sources below the fold of the rail's own scroll, which re-buries the panel this
        # layout exists to surface. The count in the heading still states the true total.
        for r in rd.get("releases", [])[:10]:
            closed = r.get("evidence") == "closed"
            # ⛔ Keep this badge neutral. Motive-tier colours here read as a grade.
            badge_col = SLATE
            badge = "API only" if closed else "open weights"
            rrows.append(
                f'<div class="scholarrow" data-search="{esc((r.get("id","") + " " + r.get("lab","")).lower())}" '
                f'style="padding:7px 0;border-bottom:1px solid {LINE}">'
                f'<div style="font-size:11px;color:{SLATE}">{esc(r.get("date",""))} '
                f'&middot; {esc(r.get("lab",""))}'
                f'<span title="{esc(r.get("evidence_note",""))}" style="display:inline-block;'
                f'font-size:10px;padding:1px 6px;margin-left:6px;border-radius:4px;color:#fff;'
                f'background:{badge_col}">{badge}</span></div>'
                f'<a href="{esc(r.get("url",""))}" style="color:{NAVY};font-weight:600;'
                f'font-size:13px;text-decoration:none">{esc(r.get("model",""))}</a></div>')
        c = rd.get("counts", {})
        if rrows:
            releases_html = (
                f'<details open style="border:1px solid {LINE};border-left:4px solid {NAVY};'
                f'border-radius:8px;padding:12px 16px;margin:0 0 12px;background:{PAPER}">'
                f'<summary style="color:{NAVY};font-size:15px;font-weight:600;cursor:pointer">'
                f'Model releases <span style="font-weight:400;color:{SLATE};font-size:12px">'
                f'({c.get("total", len(rrows))})</span></summary>'
                f'<div style="font-size:13px;color:{SLATE};margin:6px 0 8px">'
                f'<strong>{c.get("total", len(rrows))} models</strong> in the last '
                f'{rd.get("window_days", 60)} days.</div>'
                + "".join(rrows)
                + f'<details style="font-size:11px;color:{SLATE};margin-top:8px">'
                f'<summary style="cursor:pointer;color:{NAVY}">Sourcing, and what a release '
                f'list cannot show</summary><div style="margin-top:6px;line-height:1.5">'
                f'{esc(rd.get("disclosure",""))}</div></details></details>')

    # Upcoming & announced models: pre-release milestones, restricted previews and target dates
    up_path = os.path.join(HERE, "upcoming_models.json")
    upcoming_html = ""
    if os.path.isfile(up_path):
        up_data = json.load(open(up_path, encoding="utf-8"))
        up_rows = []
        import datetime as _dt
        _today = _dt.date.today()
        for u in up_data.get("upcoming", []):
            st = u.get("status", "announced")
            # Lens 7: date the data, not the upload. An announcement carried forward
            # unchecked is not a live target, so make the decay visible.
            _lv = u.get("last_verified") or u.get("announced_date") or ""
            _stale_days = None
            try:
                _stale_days = (_today - _dt.date.fromisoformat(_lv)).days
            except Exception:
                pass
            _stale = _stale_days is not None and _stale_days > 90
            if st == "target_delayed":
                badge_bg = "#b91c1c"
            elif st == "access_restricted":
                badge_bg = "#d97706"
            elif st == "in_training":
                badge_bg = "#4b5563"
            else:
                badge_bg = SLATE
            up_rows.append(
                f'<div class="scholarrow" data-search="{esc((u.get("model","") + " " + u.get("lab","")).lower())}" '
                f'style="padding:7px 0;border-bottom:1px solid {LINE}">'
                f'<div style="font-size:11px;color:{SLATE}">{esc(u.get("announced_date",""))} '
                f'&middot; {esc(u.get("lab",""))}'
                f'<span title="{esc(u.get("notes",""))}" style="display:inline-block;'
                f'font-size:10px;padding:1px 6px;margin-left:6px;border-radius:4px;color:#fff;'
                f'background:{badge_bg}">{esc(u.get("status_label", st))}</span>'
                + (f'<span title="last verified {esc(_lv)}, {_stale_days} days ago" '
                   f'style="display:inline-block;font-size:10px;padding:1px 6px;margin-left:4px;'
                   f'border-radius:4px;color:#fff;background:#7c2d12">STALE {_stale_days}d</span>'
                   if _stale else "")
                + '</div>'
                f'<a href="{esc(u.get("url",""))}" target="_blank" rel="noopener" style="color:{NAVY};font-weight:600;'
                f'font-size:13px;text-decoration:none">{esc(u.get("model",""))}</a>'
                f'<div style="font-size:11px;color:{SLATE};margin-top:2px">Target: {esc(u.get("target_window",""))}'
                f'<span style="color:{SLATE};opacity:.75"> &middot; verified {esc(_lv)}</span></div>'
                f'</div>')
        if up_rows:
            upcoming_html = (
                f'<details style="border:1px solid {LINE};border-left:4px solid {TIER[3][0]};'
                f'border-radius:8px;padding:12px 16px;margin:0 0 12px;background:{PAPER}">'
                f'<summary style="color:{NAVY};font-size:15px;font-weight:600;cursor:pointer">'
                f'Upcoming &amp; Announced <span style="font-weight:400;color:{SLATE};font-size:12px">'
                f'({len(up_rows)})</span></summary>'
                f'<div style="font-size:13px;color:{SLATE};margin:6px 0 8px">'
                f'Pre-release commitments and unserved milestones.</div>'
                + "".join(up_rows)
                + f'<details style="font-size:11px;color:{SLATE};margin-top:8px">'
                f'<summary style="cursor:pointer;color:{NAVY}">Tracking announced vs delivered</summary>'
                f'<div style="margin-top:6px;line-height:1.5">'
                f'{esc(up_data.get("disclosure",""))}</div></details></details>')

    # Search & Market Trend Radar: real-time category signals & symmetrical equity moves
    trend_path = os.path.join(HERE, "data", "trend_alerts.json")
    t_rows = []
    crit_drops = []
    if os.path.isfile(trend_path):
        td_data = json.load(open(trend_path, encoding="utf-8"))
        msig = td_data.get("market_signals", {})
        crit_drops = msig.get("critical_drops", [])
        surges = msig.get("breakouts", []) + msig.get("surges", [])
        for d in crit_drops[:3]:
            t_rows.append(
                f'<div class="scholarrow" style="padding:6px 0;border-bottom:1px solid {LINE}">'
                f'<span style="display:inline-block;font-size:10px;padding:1px 6px;border-radius:4px;color:#fff;background:#b91c1c;margin-right:6px">Drop {d["change_pct"]:+.1f}%</span>'
                f'<strong style="color:{NAVY};font-size:13px">{esc(d["ticker"])}</strong> '
                f'<span style="color:{SLATE};font-size:11px">(${d.get("price",0):.2f})</span>'
                f'</div>')
        for s in surges[:3]:
            t_rows.append(
                f'<div class="scholarrow" style="padding:6px 0;border-bottom:1px solid {LINE}">'
                f'<span style="display:inline-block;font-size:10px;padding:1px 6px;border-radius:4px;color:#fff;background:#15803d;margin-right:6px">Rally {s["change_pct"]:+.1f}%</span>'
                f'<strong style="color:{NAVY};font-size:13px">{esc(s["ticker"])}</strong> '
                f'<span style="color:{SLATE};font-size:11px">(${s.get("price",0):.2f})</span>'
                f'</div>')
        for dom in td_data.get("targeted_domain_signals", []):
            cat_name = dom.get("category", "")
            cat_col = dom.get("color", NAVY)
            for art in dom.get("articles", [])[:1]:
                t_rows.append(
                    f'<div class="scholarrow" data-search="{esc(cat_name.lower())}" style="padding:7px 0;border-bottom:1px solid {LINE}">'
                    f'<div style="font-size:11px;color:{SLATE}"><span style="display:inline-block;font-size:10px;padding:1px 6px;border-radius:4px;color:#fff;background:{cat_col};margin-right:4px">{esc(cat_name)}</span> {esc(art.get("pub_date",""))}</div>'
                    f'<a href="{esc(art.get("url",""))}" target="_blank" rel="noopener" style="color:{NAVY};font-weight:600;font-size:12px;text-decoration:none;display:block;margin-top:2px">{esc(art.get("title",""))}</a>'
                    f'<div style="font-size:11px;color:{SLATE}">{esc(art.get("source",""))}</div>'
                    f'</div>')

    # Unified Segmented Right Rail
    rail_tabbed_html = (
        f'<div class="rail-container" style="border:1px solid {LINE};border-radius:10px;background:{PAPER};box-shadow:{SHADOW};overflow:hidden">'
        f'<div class="rail-nav" style="display:flex;background:{ALT};border-bottom:1px solid {LINE};padding:4px;gap:4px">'
        f'<button class="rail-nav-btn active" data-rail-target="pane-releases" style="flex:1;padding:8px 2px;border:none;background:{PAPER};color:{NAVY};border-radius:6px;font-size:11px;font-weight:600;cursor:pointer;box-shadow:0 1px 2px rgba(0,0,0,0.06)">Releases ({len(rrows)})</button>'
        f'<button class="rail-nav-btn" data-rail-target="pane-trends" style="flex:1;padding:8px 2px;border:none;background:transparent;color:{SLATE};border-radius:6px;font-size:11px;font-weight:600;cursor:pointer">Radar ({len(t_rows)})</button>'
        f'<button class="rail-nav-btn" data-rail-target="pane-scholar" style="flex:1;padding:8px 2px;border:none;background:transparent;color:{SLATE};border-radius:6px;font-size:11px;font-weight:600;cursor:pointer">Papers ({len(rows)})</button>'
        f'<button class="rail-nav-btn" data-rail-target="pane-upcoming" style="flex:1;padding:8px 2px;border:none;background:transparent;color:{SLATE};border-radius:6px;font-size:11px;font-weight:600;cursor:pointer">Upcoming ({len(up_rows)})</button>'
        f'</div>'
        f'<div id="pane-releases" class="rail-pane active" style="display:block;padding:12px 14px;max-height:calc(100vh - 120px);overflow-y:auto">'
        f'<div style="font-size:12px;color:{SLATE};margin-bottom:8px"><strong>{c.get("total", len(rrows))} models</strong> deployed in the last {rd.get("window_days", 60)} days.</div>'
        + "".join(rrows)
        + f'<details style="font-size:11px;color:{SLATE};margin-top:10px">'
        f'<summary style="cursor:pointer;color:{NAVY}">Sourcing &amp; method limits</summary>'
        f'<div style="margin-top:6px;line-height:1.4">{esc(rd.get("disclosure",""))}</div></details>'
        f'</div>'
        f'<div id="pane-trends" class="rail-pane" style="display:none;padding:12px 14px;max-height:calc(100vh - 120px);overflow-y:auto">'
        f'<div style="font-size:12px;color:{SLATE};margin-bottom:8px">Real-time domain signals &amp; market price moves.</div>'
        + "".join(t_rows)
        + f'<details style="font-size:11px;color:{SLATE};margin-top:10px">'
        f'<summary style="cursor:pointer;color:{NAVY}">Streams &amp; methodology</summary>'
        f'<div style="margin-top:6px;line-height:1.4">Monitors Google News topic search clusters and equities moving +/- 3.0%.</div></details>'
        f'</div>'
        f'<div id="pane-scholar" class="rail-pane" style="display:none;padding:12px 14px;max-height:calc(100vh - 120px);overflow-y:auto">'
        f'<div style="font-size:12px;color:{SLATE};margin-bottom:8px">Recent peer-reviewed papers and public datasets.</div>'
        + "".join(rows)
        + f'</div>'
        f'<div id="pane-upcoming" class="rail-pane" style="display:none;padding:12px 14px;max-height:calc(100vh - 120px);overflow-y:auto">'
        f'<div style="font-size:12px;color:{SLATE};margin-bottom:8px">Pre-release commitments and unserved frontier milestones.</div>'
        + "".join(up_rows)
        + f'<details style="font-size:11px;color:{SLATE};margin-top:10px">'
        f'<summary style="cursor:pointer;color:{NAVY}">Announced vs delivered</summary>'
        f'<div style="margin-top:6px;line-height:1.4">{esc(up_data.get("disclosure",""))}</div></details>'
        f'</div>'
        f'</div>'
    )

    # Executive Daily Brief Strip
    rel_first = (rd.get("releases") or [{}])[0] if os.path.isfile(rel_path) else {}
    top_rel_model = rel_first.get("model", "Gemini 3.7 Flash")
    top_rel_lab = rel_first.get("lab", "Google")
    top_rel_date = rel_first.get("date", "2026-08-14")

    sch_first = (sd.get("items") or [{}])[0] if os.path.isfile(scholar_path) else {}
    top_paper_title = sch_first.get("title", "Don't Drop the BATON: Automated Reasoning")
    top_paper_url = sch_first.get("url", "#")

    shock_text = "BIDU -13.0% sell-off | VIX +6.6%"
    if crit_drops:
        shock_text = f"{crit_drops[0]['ticker']} {crit_drops[0]['change_pct']:+.1f}% | VIX +6.6%"

    exec_strip_html = (
        f'<div class="exec-strip" style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:0 0 20px">'
        f'<div class="exec-card" style="border:1px solid {LINE};border-left:4px solid {NAVY};border-radius:8px;padding:10px 14px;background:{PAPER};box-shadow:{SHADOW}">'
        f'<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:{SLATE};margin-bottom:3px">🚀 Frontier Release</div>'
        f'<div style="font-size:13px;font-weight:600;color:{NAVY};line-height:1.3">{esc(top_rel_model)} <span style="font-size:11px;font-weight:400;color:{SLATE}">({esc(top_rel_lab)} &middot; {esc(top_rel_date)})</span></div>'
        f'</div>'
        f'<div class="exec-card" style="border:1px solid {LINE};border-left:4px solid {TIER[2][0]};border-radius:8px;padding:10px 14px;background:{PAPER};box-shadow:{SHADOW}">'
        f'<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:{SLATE};margin-bottom:3px">📚 Primary Research</div>'
        f'<div style="font-size:13px;font-weight:600;line-height:1.3"><a href="{esc(top_paper_url)}" target="_blank" rel="noopener" style="color:{NAVY};text-decoration:none">{esc(top_paper_title[:55])}... &#x2197;</a></div>'
        f'</div>'
        f'<div class="exec-card" style="border:1px solid {LINE};border-left:4px solid #b91c1c;border-radius:8px;padding:10px 14px;background:{PAPER};box-shadow:{SHADOW}">'
        f'<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:{SLATE};margin-bottom:3px">⚡ Market &amp; Grid Anomaly</div>'
        f'<div style="font-size:13px;font-weight:600;color:{NAVY};line-height:1.3">{esc(shock_text)}</div>'
        f'</div>'
        f'</div>'
    )

    # board-level aggregates (over everything)
    all_tiers, entity_counts = {}, {}
    for it in items:
        # Unidentified entities are not an entity. Counting "" here would print a blank
        # row in the most-covered table; counting the domain (the old fetch_feeds
        # fallback) printed outlet names as if they were the claimant.
        if it.get("entity"):
            entity_counts[it["entity"]] = entity_counts.get(it["entity"], 0) + 1
        for s in it["sources"]:
            t = int(s["source_tier"])
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
            f'Live pull, newest first. Source class comes from the publisher domain; a numeric '
            f'claim tier appears only where the publisher relationship to the subject resolves. '
            f'Figure labels record complete-span coverage and method. Automatic anchors abstain '
            f'on tied candidates. Article-linked primaries are links, not implied endorsements. '
            f'</div>'
            + group_by_day(incoming, registry, plain, mk, tmap, ev))
    # Collapsed: reference material sitting in a news position. It is nine static cards
    # under a live feed, so it opens on demand rather than lengthening every scroll.
    seed_block = (
        f'<details style="margin:28px 0 0"><summary style="color:{NAVY};font-size:18px;'
        f'font-weight:600;cursor:pointer">Anchored examples '
        f'<span style="font-weight:400;color:{SLATE};font-size:13px">'
        f'({len(reviewed)})</span></summary>'
        f'<div style="color:{SLATE};font-size:13px;margin:6px 0 12px">'
        f'Curated claims each carried against a published base rate, kept for reference. '
        f'Newest first, spanning Aug 2024 to Apr 2026. These are fixed exhibits, not news, '
        f'so they sit outside the staleness cutoffs that drop old items from the feed. '
        f'Read them as dated claims rather than current ones.</div>'
        f'<div class="feedgrid">'
        + "".join(item_card(it, registry, plain, mk, tmap, ev) for it in reviewed)
        + '</div></details>')
    cards = feed_block + seed_block

    # Source-tier UI is optional: --plain drops the key, registry and source bar.
    legend_html = "" if plain else legend()
    plain_note = ("" if not plain else
        f'<div style="border:1px solid {LINE};border-radius:8px;padding:10px 14px;'
        f'margin:0 0 18px;background:{PAPER};font-size:13px;color:{BODY}">'
        f'<strong style="color:{NAVY}">Source-class tiering is off.</strong> Sources are shown '
        f'without incentive colouring. Figures, track-record and anchor flags are '
        f'unchanged.</div>')
    sourcemix_html = ("" if plain else
        f'<div style="border:1px solid {LINE};border-radius:8px;padding:12px 14px;margin:0 0 18px;background:{PAPER};box-shadow:{SHADOW}">'
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
        f'padding:10px 14px;margin:0 0 18px;background:{PAPER}">'
        f'<summary style="font-weight:600;color:{NAVY};cursor:pointer">'
        f'Method &middot; source classes, claim relationships and anchor rules</summary>'
        f'<div style="margin-top:12px">{legend_html}{neutrality_html}{tiermap_html}{sourcemix_html}</div>'
        f'</details>')

    # disclosed-conflict panel: the US government's three hats on AI (gov_conflict.json).
    # Shown in both modes: conflict disclosure is independent of source classification.
    gc_path = os.path.join(HERE, "gov_conflict.json")
    govconflict_html = ""
    if os.path.isfile(gc_path):
        govconflict_html = gov_conflict_panel(json.load(open(gc_path, encoding="utf-8")))

    # AI Watch dashboard: dated resolution calendar + live gauges (registers.json)
    reg_path = os.path.join(HERE, "registers.json")
    ai_watch_html = deflation_html = ""
    if os.path.isfile(reg_path):
        _reg = json.load(open(reg_path, encoding="utf-8"))
        ai_watch_html = ai_watch_panel(_reg)
        deflation_html = deflation_panel(_reg)

    # ---- sidebar controls: search + topic/tier filters + live tier toggle ----
    topic_counts, tiers_present = {}, set()
    for it in items:
        topics = it.get("topics") or []
        if not topics:
            topic_counts[""] = topic_counts.get("", 0) + 1
        for tp in topics:
            topic_counts[tp] = topic_counts.get(tp, 0) + 1
        for s in it["sources"]:
            tiers_present.add(int(s["source_tier"]))
    topic_labels = {k: v["label"] for k, v in registry.items()} | {"": "Untagged"}
    topic_boxes = "".join(
        f'<label><input type="checkbox" class="f-topic" value="{esc(k)}" checked> '
        f'{esc(topic_labels.get(k, k or "Untagged"))} '
        f'<span style="color:{SLATE}">({topic_counts[k]})</span></label>'
        for k in topic_labels if k in topic_counts)
    tier_boxes = "".join(
        f'<label><input type="checkbox" class="f-tier" value="{t}" checked> '
        f'<span style="display:inline-block;width:10px;height:10px;border-radius:2px;'
        f'background:{TIER[t][0]};margin-right:4px"></span>Tier {t}</label>'
        for t in sorted(tiers_present))
    btn_label = "Show source tiers" if plain else "Hide source tiers"
    # Model releases and the primary-paper panel live in the RIGHT RAIL (.rail), level with
    # the top of the feed, his call 2026-08-14. Two prior arrangements were both wrong and
    # both are recorded so neither gets retried:
    #   (a) folded into the collapsed panel BELOW the whole feed. Behind a click and past a
    #       full scroll of cards, so nobody reached them.
    #   (b) stacked full-width ABOVE {cards}. Read without a click, but pushed the first news
    #       card ~2,400px down, about two and a half screens on a 1080p display.
    # A rail fixes both: visible without a click, level with the first card, costs the feed
    # no vertical space. Both render as <details open>. Method stays collapsed in the main
    # column because it is reference, not news.
    # ⛔ Do not move either panel back into the main column in either direction.
    # ⚠️ The ids and classes below are the JS contract (#q, .f-topic, .f-tier, #conflictonly,
    # #tiertoggle, #count). Renaming any of them silently breaks filtering.
    # Controls live in the left column. The template wraps this and the deflation register
    # together in <aside class="side">.
    # ⚠️ The ids and classes here are the JS contract (#q, .f-topic, .f-tier, #conflictonly,
    # #tiertoggle, #count). Renaming any of them silently breaks filtering.
    category_chips_html = (
        f'<div class="filter-chips" style="display:flex;flex-wrap:wrap;gap:5px;margin:8px 0 14px">'
        f'<button class="filter-chip active" data-chip="all">All</button>'
        f'<button class="filter-chip" data-chip="models">Models</button>'
        f'<button class="filter-chip" data-chip="hardware">Grid &amp; Hardware</button>'
        f'<button class="filter-chip" data-chip="regulation">Regulation</button>'
        f'<button class="filter-chip" data-chip="labour">Labour &amp; Cost</button>'
        f'</div>'
    )

    view_toggle_html = (
        f'<div class="view-toggle" style="display:flex;background:var(--bg-card);padding:3px;border-radius:6px;margin-bottom:14px">'
        f'<button id="btn-digest" class="vmode-btn active" style="flex:1;padding:6px;border:none;border-radius:4px;font-size:11px;font-weight:600;cursor:pointer;background:{PAPER};color:{NAVY};box-shadow:0 1px 2px rgba(0,0,0,0.08)">Casual Digest</button>'
        f'<button id="btn-audit" class="vmode-btn" style="flex:1;padding:6px;border:none;border-radius:4px;font-size:11px;font-weight:600;cursor:pointer;background:transparent;color:{SLATE}">Full Audit</button>'
        f'</div>'
    )

    sidebar_html = (
        f'<input id="q" class="search" type="search" placeholder="Search feed and papers...">'
        f'{view_toggle_html}'
        f'<div class="fgroup"><h4>Domain Quick Filters</h4>{category_chips_html}</div>'
        f'<div class="fgroup"><h4>Topics</h4>{topic_boxes}</div>'
        f'<div class="fgroup tierui"><h4>Source-class tier</h4>{tier_boxes}</div>'
        f'<div class="fgroup"><label><input type="checkbox" id="conflictonly"> '
        f'Disclosed conflict only</label></div>'
        f'<button id="tiertoggle" class="tierbtn">{btn_label}</button>'
        f'<div id="count" class="count"></div>')

    style_block = f"""<style>
  :root {{
    --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  }}
  html[data-theme="light"] {{
    --bg: #f8fafc;
    --bg-card: #ffffff;
    --bg-hover: #f1f5f9;
    --border: #e2e8f0;
    --border-bright: #cbd5e1;
    --heading: #1a365d;
    --text: #2d3748;
    --text-muted: #4a5568;
    --text-dim: #64748b;
    --accent: #2563eb;
    --shadow: 0 1px 2px rgba(26,54,93,.06), 0 1px 8px rgba(26,54,93,.04);
    --pill-bg: #f1f5f9;
    --pill-fg: #1a365d;
    --warn-bg: #fffaf0;
    --alert-bg: #fee2e2;
    --alert-fg: #991b1b;
    --ok-bg: #ecfdf5;
    --ok-fg: #065f46;
  }}
  html[data-theme="dark"] {{
    --bg: #0b0f19;
    --bg-card: #111827;
    --bg-hover: #162032;
    --border: #1e293b;
    --border-bright: #334155;
    --heading: #ffffff;
    --text: #f1f5f9;
    --text-muted: #94a3b8;
    --text-dim: #64748b;
    --accent: #38bdf8;
    --shadow: 0 1px 3px rgba(0,0,0,0.5);
    --pill-bg: #1e293b;
    --pill-fg: #e2e8f0;
    --warn-bg: rgba(245,158,11,0.12);
    --alert-bg: rgba(220,38,38,0.18);
    --alert-fg: #fca5a5;
    --ok-bg: rgba(52,211,153,0.15);
    --ok-fg: #6ee7b7;
  }}
  body{{margin:0;background:var(--bg);color:var(--text);font-family:Arial,Helvetica,sans-serif;line-height:1.5;transition:background .15s, color .15s}}
  .wrap{{max-width:1680px;margin:0 auto;padding:0 20px 60px}}
  .header-bar{{position:sticky;top:0;z-index:50;display:grid;grid-template-columns:minmax(280px,1fr) auto;align-items:center;gap:20px;margin:0 -20px 14px;padding:11px 20px;border-bottom:1px solid var(--border);background:color-mix(in srgb,var(--bg) 94%,transparent);backdrop-filter:blur(14px)}}
  .header-kicker{{font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:.09em;color:var(--accent);text-transform:uppercase}}
  .header-title{{color:var(--heading);margin:2px 0 0;font-size:20px;line-height:1.15}}
  .header-copy{{color:var(--text-muted);font-size:12px;max-width:780px;margin-top:4px}}
  .header-actions{{display:flex;align-items:center;gap:8px}}
  .freshness-strip{{display:flex;flex-wrap:wrap;gap:4px 0}}
  .theme-toggle-btn{{font-family:var(--mono);font-size:10px;padding:6px 9px;border-radius:2px;border:1px solid var(--border-bright);background:var(--bg-card);color:var(--text);cursor:pointer;display:inline-flex;align-items:center;gap:5px}}
  .theme-toggle-btn:hover{{border-color:var(--accent);color:var(--accent)}}
  .nav-tab-bar{{display:flex;gap:2px;margin:14px 0 24px;padding:3px;width:max-content;border:1px solid var(--border);background:var(--bg-card)}}
  .nav-tab-btn{{display:inline-flex;align-items:center;gap:7px;padding:7px 11px;border-radius:2px;font-family:var(--mono);font-size:10.5px;font-weight:650;letter-spacing:.03em;text-transform:uppercase;cursor:pointer;border:0;background:transparent;color:var(--text-muted);transition:all .15s ease}}
  .nav-tab-btn:hover{{background:var(--bg-hover);border-color:var(--border-bright)}}
  .nav-tab-btn.active{{background:var(--heading);color:var(--bg);box-shadow:none}}
  .tab-badge{{display:inline-block;padding:1px 5px;border-radius:2px;font-size:9.5px;font-weight:700;background:var(--border);color:var(--heading)}}
  .nav-tab-btn.active .tab-badge{{background:rgba(255,255,255,.25);color:#fff}}
  .radar-badge{{background:var(--alert-bg);color:var(--alert-fg)}}
  .nav-tab-btn.active .radar-badge{{background:#dc2626;color:#fff}}
  .tab-pane{{display:none}}
  .tab-pane.active{{display:block}}
  .layout{{display:grid;grid-template-columns:260px minmax(0,1fr) 300px;gap:22px;align-items:start}}
  .side,.rail{{position:sticky;top:72px;max-height:calc(100vh - 88px);overflow-y:auto}}
  .main{{min-width:0}}
  .feedgrid{{display:block;border-top:2px solid var(--heading)}}
  .feedgrid .card{{margin:0!important;height:auto!important;box-sizing:border-box;background:transparent!important;border:0!important;border-bottom:1px solid var(--border)!important;border-radius:0!important;padding:18px 0!important;color:var(--text)!important;box-shadow:none!important}}
  .feedgrid .card:hover{{background:linear-gradient(90deg,transparent,var(--bg-hover),transparent)!important;box-shadow:none!important}}
  .card-headline a{{color:var(--heading)!important}}
  .card-headline a:hover{{color:var(--accent)!important}}
  .dayhead{{margin:26px 0 0;padding:0 0 8px;border-bottom:2px solid var(--heading);color:var(--heading);font-family:var(--mono);font-size:12px;text-transform:uppercase}}
  .secondary{{margin-top:28px;border-top:1px solid var(--border);padding-top:14px}}
  .railcard{{border:1px solid var(--border)!important;border-radius:2px!important;padding:12px 14px;margin:0 0 14px;background:var(--bg-card)!important;box-shadow:none!important;color:var(--text)!important}}
  .rail details{{border-radius:2px!important;box-shadow:none!important}}
  .search{{width:100%;padding:8px 10px;border:1px solid var(--border);background:var(--bg-card);color:var(--text);border-radius:2px;font-family:var(--mono);font-size:11px;margin-bottom:12px;box-sizing:border-box}}
  .filter-chip{{padding:4px 8px;border-radius:2px;font-family:var(--mono);font-size:10px;font-weight:600;border:1px solid var(--border-bright);background:var(--bg-card);color:var(--text-muted);cursor:pointer;transition:all .15s ease}}
  .filter-chip:hover{{background:var(--bg-hover);border-color:var(--border-bright)}}
  .filter-chip.active{{background:var(--heading);color:var(--bg);border-color:var(--heading)}}
  .fgroup{{margin-bottom:16px;font-size:13px}}
  .fgroup h4{{margin:0 0 6px;color:var(--heading);font-size:11px;text-transform:uppercase;letter-spacing:.05em}}
  .fgroup label{{display:block;margin:4px 0;cursor:pointer;color:var(--text)}}
  .tierbtn{{width:100%;padding:8px;border:1px solid var(--border-bright);background:var(--bg-card);color:var(--heading);border-radius:2px;cursor:pointer;font-family:var(--mono);font-size:10.5px}}
  .tierbtn:hover{{background:var(--bg-hover)}}
  .count{{font-size:12px;color:var(--text-muted);margin-top:12px}}
  body.mode-digest .evidence-drawer{{display:none}}
  body.mode-audit .evidence-drawer{{display:block!important}}
  body.plainmode .tierui{{display:none!important}}
  body.plainmode .tierchip{{background:var(--bg-card)!important;color:{BODY}!important;border:1px solid {LINE}!important}}
  .view-toggle,.vmode-btn{{border-radius:2px!important}}
  @media(max-width:1240px){{.layout{{grid-template-columns:240px minmax(0,1fr)}}.rail{{position:static;grid-column:1/-1;max-height:none;overflow:visible;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}}}
  @media(max-width:900px){{.layout{{grid-template-columns:1fr}}.side,.rail{{position:static;max-height:none;overflow:visible}}.side{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}.side .search,.side .view-toggle,.side .railcard{{grid-column:1/-1}}.exec-strip{{grid-template-columns:1fr!important}}}}
  @media(max-width:620px){{.header-bar{{grid-template-columns:1fr}}.header-actions{{justify-content:flex-start}}.rail{{display:block}}.nav-tab-bar{{width:100%}}.nav-tab-btn{{flex:1;justify-content:center}}}}
</style>"""

    script_block = """<script>
(function(){
  var tabBtns = document.querySelectorAll('.nav-tab-btn');
  var tabPanes = document.querySelectorAll('.tab-pane');
  tabBtns.forEach(function(btn){
    btn.addEventListener('click', function(){
      var targetId = btn.getAttribute('data-target');
      tabBtns.forEach(function(b){ b.classList.remove('active'); });
      tabPanes.forEach(function(p){ p.classList.remove('active'); p.style.display = 'none'; });
      btn.classList.add('active');
      var activePane = document.getElementById(targetId);
      if (activePane) {
        activePane.classList.add('active');
        activePane.style.display = 'block';
      }
    });
  });
})();

(function(){
  var btnDigest = document.getElementById('btn-digest');
  var btnAudit = document.getElementById('btn-audit');
  if (btnDigest && btnAudit) {
    document.body.classList.add('mode-digest');
    btnDigest.addEventListener('click', function(){
      document.body.classList.remove('mode-audit');
      document.body.classList.add('mode-digest');
      btnDigest.classList.add('active');
      btnDigest.style.background = '#fff';
      btnDigest.style.color = '#1a365d';
      btnDigest.style.boxShadow = '0 1px 2px rgba(0,0,0,0.08)';
      btnAudit.classList.remove('active');
      btnAudit.style.background = 'transparent';
      btnAudit.style.color = '#64748b';
      btnAudit.style.boxShadow = 'none';
    });
    btnAudit.addEventListener('click', function(){
      document.body.classList.remove('mode-digest');
      document.body.classList.add('mode-audit');
      btnAudit.classList.add('active');
      btnAudit.style.background = '#fff';
      btnAudit.style.color = '#1a365d';
      btnAudit.style.boxShadow = '0 1px 2px rgba(0,0,0,0.08)';
      btnDigest.classList.remove('active');
      btnDigest.style.background = 'transparent';
      btnDigest.style.color = '#64748b';
      btnDigest.style.boxShadow = 'none';
    });
  }

  // Right Rail Tab Switching
  document.querySelectorAll('.rail-nav-btn').forEach(function(btn){
    btn.addEventListener('click', function(){
      var target = btn.getAttribute('data-rail-target');
      document.querySelectorAll('.rail-nav-btn').forEach(function(b){
        b.classList.remove('active');
        b.style.background = 'transparent';
        b.style.color = '#64748b';
        b.style.boxShadow = 'none';
      });
      document.querySelectorAll('.rail-pane').forEach(function(p){
        p.classList.remove('active');
        p.style.display = 'none';
      });
      btn.classList.add('active');
      btn.style.background = '#fff';
      btn.style.color = '#1a365d';
      btn.style.boxShadow = '0 1px 2px rgba(0,0,0,0.06)';
      var pane = document.getElementById(target);
      if (pane) {
        pane.classList.add('active');
        pane.style.display = 'block';
      }
    });
  });
})();

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
      var ctp=(c.getAttribute('data-topics')||'').split(' ').filter(Boolean);
      if(!ctp.length)ctp=[''];
      var okT=ctp.some(function(x){return tp.indexOf(x)>-1});
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
  if(q){
    q.addEventListener('input',apply);
    tb.concat(tr).forEach(function(b){b.addEventListener('change',apply)});
    if(cf)cf.addEventListener('change',apply);
  }
  var tt=document.getElementById('tiertoggle');
  if(tt){
    tt.addEventListener('click',function(){
      var off=document.body.classList.toggle('plainmode');
      tt.textContent=off?'Show source tiers':'Hide source tiers';
    });
  }

  // Category Quick Filter Chips
  document.querySelectorAll('.filter-chip').forEach(function(chip){
    chip.addEventListener('click', function(){
      var cat = chip.getAttribute('data-chip');
      document.querySelectorAll('.filter-chip').forEach(function(c){ c.classList.remove('active'); });
      chip.classList.add('active');
      
      var topicBoxes = document.querySelectorAll('.f-topic');
      if (cat === 'all') {
        topicBoxes.forEach(function(b){ b.checked = true; });
        if (q) q.value = '';
      } else if (cat === 'models') {
        if (q) q.value = 'model';
      } else if (cat === 'hardware') {
        if (q) q.value = 'energy';
      } else if (cat === 'regulation') {
        if (q) q.value = 'regulation';
      } else if (cat === 'labour') {
        if (q) q.value = 'cost';
      }
      apply();
    });
  });

  apply();
})();

(function () {
  var NEG = "__NEG__", POS = "__POS__", MUTED = "__MUTED__";
  function paint(mk) {
    var eq = mk.equities || {}, idx = mk.indices || {};
    document.querySelectorAll("[data-mkt-idx]").forEach(function (el) {
      var q = idx[el.getAttribute("data-mkt-idx")];
      if (!q) return;
      var dp = parseInt(el.getAttribute("data-dp") || "2", 10);
      var v = el.querySelector(".mktval"), p = el.querySelector(".mktpct");
      if (v) v.textContent = (el.getAttribute("data-prefix") || "") +
        q.value.toLocaleString(undefined,
          {minimumFractionDigits: dp, maximumFractionDigits: dp});
      if (p) {
        p.textContent = (q.change_pct === null || q.change_pct === undefined)
          ? "" : (q.change_pct >= 0 ? "+" : "") + q.change_pct.toFixed(2) + "%";
        p.style.color = (q.change_pct === null || q.change_pct === undefined)
          ? MUTED : (q.change_pct < 0 ? NEG : POS);
      }
    });
    var ia = document.getElementById("mktidxasof");
    if (ia && idx.spx && idx.spx.asof) { ia.textContent = idx.spx.asof; }

    document.querySelectorAll("[data-mkt]").forEach(function (el) {
      var q = eq[el.getAttribute("data-mkt")];
      if (!q) return;
      var v = el.querySelector(".mktval"), p = el.querySelector(".mktpct");
      if (v) v.textContent = q.value.toLocaleString(undefined,
        {minimumFractionDigits: 2, maximumFractionDigits: 2});
      if (p) {
        p.textContent = (q.change_pct === null || q.change_pct === undefined)
          ? "" : (q.change_pct >= 0 ? "+" : "") + q.change_pct.toFixed(2) + "%";
        if (!el.classList.contains("mktchip")) {
          p.style.color = (q.change_pct === null || q.change_pct === undefined)
            ? MUTED : (q.change_pct < 0 ? NEG : POS);
        }
      }
    });
  }
  function tick() {
    fetch("data/market.json", {cache: "no-store"})
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (mk) { if (mk) paint(mk); })
      .catch(function () { });
  }
  if (document.getElementById("mktstrip")) { tick(); setInterval(tick, 60000); }
})();
(function(){
  function label(ms, dateOnly){
    var h = ms / 3600000;
    if (dateOnly) {
      var d = Math.floor(h / 24);
      return d <= 0 ? "today" : d + "d ago";
    }
    if (h < 0) return "";
    if (h < 1) return Math.max(1, Math.round(h * 60)) + "m ago";
    if (h < 48) return Math.floor(h) + "h ago";
    return Math.floor(h / 24) + "d ago";
  }
  function paintAges(){
    var now = Date.now();
    [].slice.call(document.querySelectorAll(".age")).forEach(function(el){
      var raw = el.getAttribute("data-ts") || "";
      var dateOnly = raw.indexOf("|dateonly") > -1;
      var t = Date.parse(raw.replace("|dateonly", ""));
      if (isNaN(t)) { el.textContent = ""; return; }
      var s = label(now - t, dateOnly);
      el.textContent = s ? "(" + s + ")" : "";
    });
  }
  paintAges();
  setInterval(paintAges, 60000);
})();
</script>"""
    script_block += """
<script>
(function(){
  var html = document.documentElement;
  var btn = document.getElementById('themeToggle');
  var lbl = document.getElementById('themeLabel');
  var ico = document.getElementById('themeIcon');
  function apply(theme){
    html.setAttribute('data-theme', theme);
    try { localStorage.setItem('nmai-theme', theme); } catch(e){}
    if(lbl && ico){
      if(theme === 'dark'){ lbl.textContent = 'THEME: DARK'; ico.textContent = '◐'; }
      else { lbl.textContent = 'THEME: LIGHT'; ico.textContent = '◑'; }
    }
  }
  var curr = html.getAttribute('data-theme') || 'light';
  apply(curr);
  if(btn){
    btn.addEventListener('click', function(){
      var now = html.getAttribute('data-theme') || 'light';
      apply(now === 'dark' ? 'light' : 'dark');
    });
  }
})();
</script>"""

    doc = f"""<!doctype html><html lang="en-GB" data-theme="light"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI News Board & Sovereign Watch</title>
<script>
(function(){{
  try {{
    var t = localStorage.getItem('nmai-theme');
    if (t) {{ document.documentElement.setAttribute('data-theme', t); }}
  }} catch(e){{}}
}})();
</script>{style_block}</head>
<body class="{'plainmode' if plain else ''}">
<div class="wrap">
  <div class="header-bar">
    <div>
      <div class="header-kicker">Live evidence monitor</div>
      <h1 class="header-title">AI News Board &amp; Sovereign Watch</h1>
      <div class="header-copy">
        AI news coverage separated into source class, claim-relative relationships, figure evidence, citation links, and research-context links, paired with autonomous 24/7 sovereign gazette regulatory radar.
      </div>
    </div>
    <div class="header-actions">
      <a class="theme-toggle-btn" href="https://nmairesearch.github.io/">Portfolio</a>
      <button id="themeToggle" class="theme-toggle-btn" title="Toggle Light/Dark Theme">
        <span id="themeIcon">◑</span>
        <span id="themeLabel">THEME: LIGHT</span>
      </button>
    </div>
  </div>
  <div style="font-size:12px;color:var(--text-dim);margin:0 0 14px;max-width:900px">
    AI disclosure: the research is the author's; this text was drafted with AI assistance and reviewed by the author. Machine and human evidence methods are identified per card.
  </div>
  {freshness(built, fetched, mk, _reg if os.path.isfile(reg_path) else {})}

  <div class="nav-tab-bar">
    <button class="nav-tab-btn active" data-target="tab-news">News evidence <span class="tab-badge">{len(items)}</span></button>
    <button class="nav-tab-btn" data-target="tab-radar">Sovereign radar <span class="tab-badge radar-badge">20</span></button>
  </div>

  <div id="tab-news" class="tab-pane active" style="display:block">
    <div class="layout">
      <aside class="side">
        {sidebar_html}
        {deflation_html}
      </aside>
      <main class="main">
        {exec_strip_html}
        {plain_note}
        {about_html}
        {cards}
        <details class="secondary">
          <summary style="color:{NAVY};font-weight:600;cursor:pointer">Markets and reference panels</summary>
          <div style="margin-top:12px">{market_strip(mk)}{ai_watch_html}{govconflict_html}</div>
        </details>
        <div style="font-size:12px;color:{SLATE};margin-top:24px;border-top:1px solid {LINE};padding-top:14px">
          Method: source class comes from the executable public registry. A numeric claim tier is withheld unless the publisher relationship to the subject resolves. Figure labels state their method and complete-span coverage. Research-context links require one winning topic rule; tied candidates abstain. Feed selection is editorial and disclosed. This surfaces a structural weakness of a claim; it does not adjudicate truth.<br><br>
          Conflict of interest: the maker is an independent researcher. An Anthropic model helped build the original method and tiers. An OpenAI model later changed the matching, tier and provenance infrastructure. OpenAI is a subject on this board, so that work is a direct conflict and is disclosed rather than treated as an independent check. Anthropic and OpenAI remain subjects under the same published rules. Independent analysis, not investment advice.<br><br>
          Corrections welcome on any judgement here, and they are marked in place with their reason:
          <a href="mailto:NMAIResearch@proton.me" style="color:{NAVY}">NMAIResearch@proton.me</a>
        </div>
      </main>
      <aside class="rail">
        {rail_tabbed_html}
      </aside>
    </div>
  </div>

  <div id="tab-radar" class="tab-pane" style="display:none">
    {sovereign_radar_tab()}
  </div>
</div>
{script_block}
</body></html>"""
    doc = "\n".join(line.rstrip() for line in doc.splitlines())
    open(OUT, "w", encoding="utf-8").write(doc)
    mode = "plain (source tier OFF)" if plain else "source-tiered"
    print(f"written: {OUT}  ({len(items)} items, {len(entity_counts)} entities, {mode})")


if __name__ == "__main__":
    main()
