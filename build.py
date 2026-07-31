#!/usr/bin/env python3
"""
AI News Board - build.py (stdlib only, no dependencies).
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
# Surfaces. The page sits on ALT and every panel and card sits on PAPER above it.
# Cards previously set no background, so they inherited ALT and separated from the
# page by a 1px border alone, while the side panels were already white.
PAPER = "#ffffff"
SHADOW = "0 1px 2px rgba(26,54,93,.06), 0 1px 8px rgba(26,54,93,.04)"

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
# Short names for the motive scale. The long strings in TIER stay as the hover text.
TIER_SHORT = {1: "primary record", 2: "research institute", 3: "trade press",
              4: "tool or data vendor", 5: "party selling the thing"}
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
    ("work_automation", ["layoff", "layoffs", "laying off", "lay off", "headcount",
                         "workforce", "job cuts", "job losses", "redundanc",
                         "replace workers", "automate the work"]),
    ("power_demand", ["gigawatt", "megawatt", "gw", "mw", "data center", "data centre",
                      "datacenter", "grid", "nuclear", "power plant", "capacity buildout",
                      "electricity", "substation", "turbine"]),
    ("energy_forecast", ["energy demand", "electricity demand", "power consumption",
                         "terawatt", "twh", "energy forecast", "power forecast"]),
    ("cost", ["capex", "billion", "spend", "spending", "investment", "funding round",
              "valuation", "revenue"]),
    # ↻ [2026-07-30] Descriptive topics added below. The seven above are ANCHOR topics: the
    # portfolio holds a published base rate for each, so an item tagged with one gets a
    # reality anchor. These do not anchor, they only make the filter usable.
    # ⚠️ Keep them BELOW the anchor topics. tag_topic returns the FIRST match, so putting a
    # descriptive topic above an anchor topic would strip the anchor off an anchorable item.
    ("chips", ["chip", "semiconductor", "gpu", "tpu", "wafer", "foundry", "nvidia",
               "tsmc", "asml", "lithograph", "hbm", "accelerator", "silicon"]),
    ("regulation", ["regulat", "lawsuit", "sued", "sues", "antitrust", "court",
                    "settlement", "copyright", "ftc", "sec", "eu ai act", "compliance",
                    "subpoena", "investigation", "ruling", "legislat", "policy statement"]),
    ("safety", ["safety", "alignment", "jailbreak", "guardrail", "red team", "misuse",
                "hallucinat", "breach", "vulnerab", "exploit", "deepfake", "csam",
                "privacy", "surveillance"]),
    ("models", ["model release", "launches", "unveil", "releases", "benchmark",
                "open-weight", "open weights", "fine-tun", "context window",
                "multimodal", "reasoning model"]),
    ("agents", ["agent", "agentic", "tool use", "autonomous", "assistant", "chatbot",
                "copilot mode", "orchestrat"]),
]


TOPIC_LABELS = {
    "code_automation": "Code automation", "work_automation": "Work automation",
    "self_improvement": "Self-improvement", "water": "Water",
    "power_demand": "Power demand", "energy_forecast": "Energy forecast",
    "cost": "Cost / spend", "governance": "Politics / governance",
    # Descriptive only, no reality anchor behind them.
    "chips": "Chips / hardware", "regulation": "Regulation / legal",
    "safety": "Safety / security", "models": "Model releases", "agents": "Agents",
    "": "Untagged",
}


# Suffix tolerance. "code" failed to match "coders" and "layoff" failed to match
# "laying off", so real matches were missed on a morphology technicality. Deliberately
# narrow: common English inflections only, never a prefix match, because loosening this
# further starts anchoring items the portfolio has no base rate for, and a wrong anchor
# is worse than a blank one.
_SUFFIX = r"(?:s|es|ed|ing|er|ers)?"


def tag_topic(headline):
    """Return the first topic whose keyword matches the headline, else '' (no anchor).

    A blank is a legitimate outcome and the common one. The portfolio holds base rates for
    energy, water, cost and code automation; most AI news is product launches and funding
    rounds, which those base rates do not speak to. Raising the hit rate by loosening this
    would mean anchoring claims to numbers that do not measure them.
    """
    hay = " " + (headline or "").lower() + " "
    for topic, kws in TOPIC_KEYWORDS:
        for kw in kws:
            if re.search(r"(?<![a-z0-9])" + re.escape(kw) + _SUFFIX + r"(?![a-z0-9])", hay):
                return topic
    return ""


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
        segs.append(f'<span title="tier {t}: {esc(TIER[t][1])} ({counts[t]})" '
                    f'style="display:inline-block;height:12px;width:{pct:.1f}%;'
                    f'background:{TIER[t][0]}"></span>')
    return ('<span style="display:inline-block;width:100%;border-radius:3px;'
            'overflow:hidden;line-height:0">' + "".join(segs) + "</span>")


def tier_scale(tiers):
    """The five-point scale with this item's tier(s) filled.

    ⛔ Replaces a stacked distribution bar. Almost every item has exactly one source, so the
    distribution rendered as a single block at 100% width: it showed the reader nothing and
    read as a rendering fault. The scale shows WHERE the source sits and what the other
    points are, which is information on every item including single-source ones.
    """
    active = sorted(int(t) for t in tiers)
    steps = []
    for t in (1, 2, 3, 4, 5):
        on = t in active
        col = TIER[t][0] if on else "#e2e8f0"
        steps.append(
            f'<span title="tier {t}: {esc(TIER[t][1])}" style="display:inline-block;'
            f'width:26px;height:8px;border-radius:2px;background:{col};margin-right:3px"></span>')
    if len(active) == 1:
        t = active[0]
        label = f'tier {t} &middot; {esc(TIER_SHORT[t])}'
    else:
        label = " &middot; ".join(f"tier {t}" for t in active)
    return (f'<div style="display:flex;align-items:center;gap:10px;margin:12px 0 8px">'
            f'<span style="font-size:11px;color:{SLATE};letter-spacing:.04em;'
            f'text-transform:uppercase">Motive</span>'
            f'<span style="line-height:0">{"".join(steps)}</span>'
            f'<span style="font-size:12px;color:{BODY}">{label}</span></div>')


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
                    f'color:{SLATE};background:#edf2f7;border:1px dashed {TIER[3][0]}">'
                    f'listed, not covered here</span>')
        why = esc(ent.get("private", "no listed security"))
        return (f'<span title="{why}" style="display:inline-block;padding:2px 8px;'
                f'margin-left:6px;border-radius:4px;font-size:11px;color:{SLATE};'
                f'background:#edf2f7;border:1px dashed {SLATE}">no listed security</span>')
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


def market_strip(mk):
    """The header strip. Indices are a trading day behind and say so."""
    if not mk or not mk.get("indices"):
        return ""
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
            f'{"" if pct is None else f"{pct:+.2f}%"}</span></span>')
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
            f'{"" if pct is None else f"{pct:+.2f}%"}</span></span>')

    asof = esc((mk.get("indices", {}).get("spx") or {}).get("asof", ""))
    return (
        f'<section id="mktstrip" style="border:1px solid {LINE};border-radius:8px;'
        f'padding:9px 14px;margin:0 0 14px;background:#fff;overflow-x:auto;font-size:13px">'
        f'<div style="margin-bottom:3px">{"".join(cells)}</div>'
        f'<div style="font-size:11px;color:{SLATE}">'
        f'Indices close <span id="mktidxasof">{asof}</span> (FRED, one trading day behind); '
        f'equities live (Finnhub). '
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


def item_card(it, anchors, plain=False, mk=None, tmap=None, ev=None):
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
    # ⛔ claim_type RETIRED 2026-07-31, his call. Not rendered. Measured on 38 items with two
    # readers at full coverage: kappa 0.52 on headlines, 0.56 given the article opening plus
    # figure spans. Article context did not fix it, and there is no ground truth to score
    # against, so the board cannot publish it as a label. The stored values and the
    # crosscheck fields are kept as the record of why.
    unreviewed = it.get("reviewed", True) is False
    # Hover carries the provenance: which model set this label, and on how much text. Named
    # from the item's own auto_labelled_by so it cannot drift from what actually ran.
    by = it.get("auto_labelled_by")
    tier, why = it.get("label_tier"), it.get("label_evidence", "")
    if tier == 1:
        ftip = (f'Denominator derived from the article itself, no model involved: {why}. '
                f'Every figure sentence behind this is stored verbatim with its position in '
                f'the article and can be checked against the source.')
    elif tier == 3:
        ftip = (f'Denominator set by {by or "a local model"} reading the figure sentences '
                f'quoted from the article ({why}). Not a human check.')
    else:
        ftip = 'no denominator has been derived for this item'
    flag = (f'<span title="{esc(ftip)}" style="display:inline-block;padding:2px 8px;'
            f'margin-left:6px;border-radius:4px;font-size:11px;color:{SLATE};background:#edf2f7;'
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
    # Two labellers read the same headline and differed: the item is genuinely ambiguous,
    # so it is surfaced for review rather than presented as settled.
    cc = it.get("crosscheck") or {}
    xchip = ""
    if cc.get("verdict") in ("split", "tied", "majority") or cc.get("agrees") is False:
        readers = cc.get("readers") or []
        detail = "; ".join(f'{r.get("model","?")}: {r.get("claim_type","")} / '
                           f'{r.get("denominator","")}' for r in readers)
        v = cc.get("verdict")
        label = {"split": "labellers split", "tied": "labellers tied",
                 "majority": "labellers differ"}.get(v, "labellers disagree")
        # A majority is not shown as a resolution: readers from one family share a
        # lineage, so a shared error is indistinguishable from agreement.
        tip = (f'{detail}. Shown for review; no reading is treated as correct and a '
               f'majority does not settle it.') if detail else 'readers differ'
        xchip = (f'<span title="{esc(tip)}" style="display:inline-block;padding:2px 8px;'
                 f'margin-left:6px;border-radius:4px;font-size:11px;color:{TIER[4][0]};'
                 f'background:#fff7ed;border:1px dashed {TIER[4][0]}">{esc(label)}</span>')
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
        subject_html = "&mdash;"
    ments = [m["name"] for m in (it.get("mentions") or [])][:4]
    mentions_html = ("" if not ments or it.get("entity") else
                     f'<div style="font-size:12px;color:{SLATE};margin-top:6px">'
                     f'Mentions {esc(" &middot; ".join(ments))}</div>'.replace("&amp;middot;", "&middot;"))
    chain_html = "" if (plain or not src_url) else chain_block(
        ((ev or {}).get(src_url) or {}).get("chain", {}))
    mchip = market_chip(it.get("entity", ""), mk or {}, tmap or {})
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
    <article {data} style="border:1px solid {LINE};border-radius:8px;padding:14px 16px;
      margin:0 0 14px;background:{PAPER};box-shadow:{SHADOW}">
      <div style="font-size:12px;color:{SLATE};margin-bottom:4px">
        {subject_html} &middot; {esc(fmt_date(it.get("date", "")))}
      </div>
      <div style="font-size:16px;font-weight:600;color:{NAVY};line-height:1.35">{headline_html}</div>
      {chain_html}
      {'' if plain else f'<div class="motivebar">{tier_scale(tiers)}</div>'}
      <div style="margin:10px 0 6px">{''.join(chips)}</div>{mentions_html}
      <div style="font-size:12px">
        <span style="display:inline-block;padding:2px 8px;border-radius:4px;
              color:#fff;background:{dcol}">{esc(dlabel)}</span>{rmark}{flag}{xchip}{mchip}
      </div>
      {conflict_html}
      {anchor_html}
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
    return (f'<div style="font-size:12px;margin:0 0 14px;padding:7px 12px;border:1px solid '
            f'{LINE};border-radius:6px;background:#fff">'
            f'<span style="color:{NAVY};font-weight:600;margin-right:10px">Freshness</span>'
            f'{"".join(parts)}</div>')


def deflation_panel(reg):
    """The deflation register: claims where a checkable figure came back different.

    This is CONTENT, not another explainer. The tier map explains the colour scale and the
    neutrality panel explains the method; this shows the method applied to named cases. It
    is the one thing here that states an outcome rather than a flag, so every row carries
    the corrected figure and where it came from, and rows arrive only via an explicit
    publication mark on the private register.
    """
    rows = (reg or {}).get("deflations") or []
    if not rows:
        return ""
    trs = []
    for r in rows:
        tier = r.get("tier")
        dot = ""
        if tier and int(tier) in TIER:
            dot = (f'<span title="motive tier {esc(tier)}: {esc(TIER[int(tier)][1])}" '
                   f'style="display:inline-block;width:9px;height:9px;border-radius:2px;'
                   f'background:{TIER[int(tier)][0]};margin-right:5px"></span>')
        mult = esc(r.get("multiple", ""))
        trs.append(
            f'<div style="padding:9px 0;border-bottom:1px solid {LINE}">'
            f'<div style="font-size:13px;color:{BODY}">{dot}<strong>{esc(r.get("claim",""))}</strong></div>'
            f'<div style="font-size:12px;color:{SLATE};margin-top:2px">'
            f'{esc(r.get("source",""))}</div>'
            f'<div style="font-size:12.5px;color:{BODY};margin-top:4px">'
            f'&rarr; {esc(r.get("corrected",""))}'
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
        f'where it came from. The dot is the motive tier of the source that carried the '
        f'original claim. Being wrong once is not a verdict on a source; the register '
        f'records the specific figure, not the outlet.</div>'
        f'{"".join(trs)}</details>')


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


def group_by_day(items, anchors, plain, mk, tmap, ev=None):
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
        out.append(item_card(it, anchors, plain, mk, tmap, ev))
    return f'<div class="feedgrid">{"".join(out)}</div>'


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Render the AI News Board.")
    ap.add_argument("--plain", action="store_true",
                    help="turn the motive tier OFF entirely: no tier colours, bars, key or "
                         "tier map. Sources shown plain. The other axes (denominator, claim "
                         "type, track record, anchors) are unaffected.")
    plain = ap.parse_args().plain

    import datetime as _dt
    built = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    data = json.load(open(SRC, encoding="utf-8"))
    mk, tmap = load_market()
    if mk:
        mk["strip_equities"] = json.load(
            open(os.path.join(HERE, "ticker_map.json"), encoding="utf-8")
        )["strip"]["equities"]
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
            f'margin:0 0 18px;background:{PAPER};box-shadow:{SHADOW}"><div style="font-weight:600;color:{NAVY};'
            f'margin-bottom:4px">Method and limits</div>'
            f'<ul style="margin:4px 0 0 18px;padding:0;font-size:13px;color:{BODY}">{dl}</ul>'
            f'<div style="font-size:12px;color:{SLATE};margin-top:8px">Conflict of interest: an '
            f'Anthropic model assisted in building this board, including the tiers applied to '
            f'Anthropic and its competitors. Anthropic is tiered in the map on the same basis '
            f'as any other source.</div></section>')
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
    # Citation chains and the per-article evidence counts.
    ev_path = os.path.join(HERE, "article_evidence.json")
    ev = json.load(open(ev_path, encoding="utf-8")) if os.path.isfile(ev_path) else {}
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
            # Collapsed. Five stacked rail panels meant scrolling inside the rail to reach
            # the last one, so reference material opens on demand.
            scholar_html = (
                f'<details open style="border:1px solid {LINE};border-left:4px solid {TIER[2][0]};'
                f'border-radius:8px;padding:12px 16px;margin:0 0 12px;background:#fff">'
                f'<summary style="color:{NAVY};font-size:15px;font-weight:600;cursor:pointer">'
                f'Primary sources <span style="font-weight:400;color:{SLATE};font-size:12px">'
                f'({len(rows)})</span></summary>'
                f'<div style="font-size:13px;color:{SLATE};margin:6px 0 8px">Recent papers and '
                f'public datasets on AI, so a claim can be checked against the underlying research '
                f'rather than the coverage of it.</div>'
                + "".join(rows) + "</details>")

    # Model releases. Open weights only, and the panel says why: an artefact you can
    # download is a different KIND of evidence from a model described in a press release.
    # ⛔ Never add benchmark scores here. That is a leaderboard, and a percentage with no
    # stated denominator is the defect this board flags elsewhere.
    rel_path = os.path.join(HERE, "releases.json")
    releases_html = ""
    if os.path.isfile(rel_path):
        rd = json.load(open(rel_path, encoding="utf-8"))
        rrows = []
        for r in rd.get("releases", [])[:16]:
            closed = r.get("evidence") == "closed"
            # Tier 5 = the party selling it is the only source. Tier 1 = inspectable artefact.
            badge_col = TIER[5][0] if closed else TIER[1][0]
            badge = "closed" if closed else "open weights"
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
                f'border-radius:8px;padding:12px 16px;margin:0 0 12px;background:#fff">'
                f'<summary style="color:{NAVY};font-size:15px;font-weight:600;cursor:pointer">'
                f'Model releases <span style="font-weight:400;color:{SLATE};font-size:12px">'
                f'({c.get("total", len(rrows))})</span></summary>'
                f'<div style="font-size:13px;color:{SLATE};margin:6px 0 8px">'
                f'{c.get("total", len(rrows))} in the last {rd.get("window_days", 60)} days: '
                f'<strong>{c.get("open_weights", 0)} open weights</strong>, an artefact you '
                f'can download and hash, and <strong>{c.get("closed", 0)} closed</strong>, '
                f'known only because the party selling it says so. Same list, two different '
                f'kinds of evidence.</div>'
                + "".join(rrows)
                + f'<details style="font-size:11px;color:{SLATE};margin-top:8px">'
                f'<summary style="cursor:pointer;color:{NAVY}">Sourcing, and what a release '
                f'list cannot show</summary><div style="margin-top:6px;line-height:1.5">'
                f'{esc(rd.get("disclosure",""))}</div></details></details>')

    # board-level aggregates (over everything)
    all_tiers, entity_counts = {}, {}
    for it in items:
        # Unidentified entities are not an entity. Counting "" here would print a blank
        # row in the most-covered table; counting the domain (the old fetch_feeds
        # fallback) printed outlet names as if they were the claimant.
        if it.get("entity"):
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
            f'Live pull, newest first. Motive tier is set from the source domain. The figures '
            f'flag is derived from quoted sentences in the article; where a rule settles it, '
            f'no model is involved. Citation links are between items on this board. '
            f'Claim type was retired on 31 Jul 2026 at inter-reader agreement of &kappa;&nbsp;0.56. '
            f'</div>'
            + group_by_day(incoming, anchors, plain, mk, tmap, ev))
    # Collapsed: reference material sitting in a news position. It is nine static cards
    # under a live feed, so it opens on demand rather than lengthening every scroll.
    seed_block = (
        f'<details style="margin:28px 0 0"><summary style="color:{NAVY};font-size:18px;'
        f'font-weight:600;cursor:pointer">Anchored examples '
        f'<span style="font-weight:400;color:{SLATE};font-size:13px">'
        f'({len(reviewed)})</span></summary>'
        f'<div style="color:{SLATE};font-size:13px;margin:6px 0 12px">'
        f'Curated claims each carried against a published base rate, kept for reference. '
        f'Newest first; some predate 2026.</div>'
        f'<div class="feedgrid">'
        + "".join(item_card(it, anchors, plain, mk, tmap, ev) for it in reviewed)
        + '</div></details>')
    cards = feed_block + seed_block

    # motive-tier UI is optional: --plain drops the key, the tier map and both bars
    legend_html = "" if plain else legend()
    plain_note = ("" if not plain else
        f'<div style="border:1px solid {LINE};border-radius:8px;padding:10px 14px;'
        f'margin:0 0 18px;background:#fff;font-size:13px;color:{BODY}">'
        f'<strong style="color:{NAVY}">Motive tiering is off.</strong> Sources are shown '
        f'without incentive colouring. Figures, track-record and anchor flags are '
        f'unchanged.</div>')
    sourcemix_html = ("" if plain else
        f'<div style="border:1px solid {LINE};border-radius:8px;padding:12px 14px;margin:0 0 18px;background:#fff;box-shadow:{SHADOW}">'
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
        f'Method &middot; motive key, limits, tier map and source mix</summary>'
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
    ai_watch_html = deflation_html = ""
    if os.path.isfile(reg_path):
        _reg = json.load(open(reg_path, encoding="utf-8"))
        ai_watch_html = ai_watch_panel(_reg)
        deflation_html = deflation_panel(_reg)

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
    # Controls run horizontally above the feed. They were a 210px left column, which spent
    # a whole column of a wide screen on six checkboxes and pushed the reference panels into
    # one over-long rail. The freed column now carries Model releases and Primary sources.
    # ⚠️ The ids and classes below are the JS contract (#q, .f-topic, .f-tier, #conflictonly,
    # #tiertoggle, #count). Renaming any of them silently breaks filtering.
    # Controls live in the left column. The template wraps this and the deflation register
    # together in <aside class="side">.
    # ⚠️ The ids and classes here are the JS contract (#q, .f-topic, .f-tier, #conflictonly,
    # #tiertoggle, #count). Renaming any of them silently breaks filtering.
    sidebar_html = (
        f'<input id="q" class="search" type="search" placeholder="Search feed and papers...">'
        f'<div class="fgroup"><h4>Topics</h4>{topic_boxes}</div>'
        f'<div class="fgroup tierui"><h4>Motive tier</h4>{tier_boxes}</div>'
        f'<div class="fgroup"><label><input type="checkbox" id="conflictonly"> '
        f'Disclosed conflict only</label></div>'
        f'<button id="tiertoggle" class="tierbtn">{btn_label}</button>'
        f'<div id="count" class="count"></div>')

    style_block = f"""<style>
  body{{margin:0;background:{ALT};color:{BODY};font-family:Arial,Helvetica,sans-serif;line-height:1.5}}
  .wrap{{max-width:2200px;margin:0 auto;padding:28px 20px 60px}}
  .layout{{display:flex;gap:24px;align-items:flex-start}}
  /* Left column: controls, then the deflation register under them. Own scroll so a long
     register never lengthens the page. */
  .side{{flex:0 0 290px;position:sticky;top:16px;max-height:calc(100vh - 32px);overflow-y:auto}}
  /* The rail takes the space a wide screen would otherwise waste, and gets the
     reference panels out from under a 45-item feed where nobody scrolls to them. */
  .main{{flex:1 1 auto;min-width:0}}
  /* Two columns, fixed. Auto-fill gave three or four on a wide screen and the cards read
     as a wall; two keeps a headline and its chips on one or two lines. */
  .feedgrid{{display:grid;grid-template-columns:repeat(2,1fr);gap:0 16px;align-items:start}}
  .feedgrid .card{{margin:0 0 16px}}
  .dayhead{{margin-top:26px}}
  /* A day heading labels every card under it, so it must span the whole grid. */
  .dayhead{{grid-column:1/-1}}
  /* Four columns: controls+register | feed | releases | reference.
     The feed is narrowed so the releases column sits beside it rather than the feed
     running the full width and the rail carrying everything. */
  .relcol{{flex:0 0 320px;position:sticky;top:16px;max-height:calc(100vh - 32px);overflow-y:auto}}
  .rail{{flex:0 0 340px;position:sticky;top:16px;max-height:calc(100vh - 32px);overflow-y:auto}}
  .relcol h2,.rail h2{{font-size:15px;margin:0 0 8px}}
  .rail h2{{font-size:15px;margin:0 0 8px}}
  .railcard{{border:1px solid #e2e8f0;border-radius:8px;padding:12px 14px;margin:0 0 14px;background:{PAPER};box-shadow:{SHADOW}}}
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
  /* Rail folds below the feed before the sidebar does: it is reference material,
     so it is the first thing that should stop competing for width. */
  /* Reference columns fold below the feed before the controls do: they are reference
     material, so they are the first thing that should stop competing for width. */
  @media(max-width:1600px){{.relcol{{position:static;flex:1 1 320px;max-height:none;overflow:visible}}
    .layout{{flex-wrap:wrap}}}}
  @media(max-width:1200px){{.rail,.relcol{{position:static;flex:1 1 auto;width:100%;max-height:none;overflow:visible}}
    .layout{{flex-wrap:wrap}}.main{{max-width:none}}}}
  /* One column below 1100px: two cards plus a rail no longer fit. */
  @media(max-width:1100px){{.feedgrid{{grid-template-columns:1fr}}}}
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

/* Market refresh. The page is rendered with real numbers at build time and works with
   JavaScript off; this only keeps an open tab current. Same-origin fetch of a static
   file, so there is no API key in the client and no CORS involved. */
(function () {
  var NEG = "__NEG__", POS = "__POS__", MUTED = "__MUTED__";
  function paint(mk) {
    var eq = mk.equities || {}, idx = mk.indices || {};
    /* Indices refresh too. Without this the strip's index values and their close date
       would freeze at whatever build.py last rendered, while the equities beside them
       moved, which is a worse failure than showing nothing. */
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
        /* Only the strip recolours: a chip sits on a solid tier-coloured background. */
        if (!el.classList.contains("mktchip")) {
          p.style.color = (q.change_pct === null || q.change_pct === undefined)
            ? MUTED : (q.change_pct < 0 ? NEG : POS);
        }
      }
    });
    var u = document.getElementById("mktupd");
    if (u && mk.generated) {
      /* The header freshness block owns the timestamps; this only flags a refresh
         that happened after the page was built. */
      u.textContent = "";
    }
  }
  function tick() {
    fetch("data/market.json", {cache: "no-store"})
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (mk) { if (mk) paint(mk); })
      .catch(function () { /* offline or file absent: leave the built-in numbers alone */ });
  }
  if (document.getElementById("mktstrip")) { tick(); setInterval(tick, 60000); }
})();
(function(){
  // Ages are computed HERE, at read time, never at build time. A static "(just now)"
  // is true for one instant and wrong for every instant after it.
  function label(ms, dateOnly){
    var h = ms / 3600000;
    if (dateOnly) {
      var d = Math.floor(h / 24);
      return d <= 0 ? "today" : d + "d ago";
    }
    if (h < 0) return "";                    // clock skew: say nothing rather than "in 3h"
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
    # Plain string, not an f-string: the JS is full of braces. Substituting the
    # palette by placeholder avoids both brace-doubling and %-format collisions
    # with the literal percent signs in the existing filter script.
    script_block = (script_block.replace("__NEG__", TIER[5][0])
                                .replace("__POS__", DENOM["y"][0])
                                .replace("__MUTED__", SLATE))

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI News Board</title>{style_block}</head>
<body class="{'plainmode' if plain else ''}">
<div class="wrap">
  <h1 style="color:{NAVY};margin:0 0 4px;font-size:26px">AI News Board</h1>
  <div style="color:{SLATE};font-size:14px;margin-bottom:20px;max-width:760px">
    AI news coverage assessed on four axes: the publisher's incentive in the claim, whether
    quoted figures state the base they are measured against, which items cite which, and a
    link to a published base rate where one exists. Figures and citations are taken verbatim
    from the article text and stored with their position. Each label records the method that
    produced it.
  </div>
  {freshness(built, fetched, mk, _reg if os.path.isfile(reg_path) else {})}
  {market_strip(mk)}
  <div class="layout">
    <aside class="side">
      {sidebar_html}
      {deflation_html}
    </aside>
    <main class="main narrow">
      {plain_note}
      {about_html}
      {cards}
      <div style="font-size:12px;color:{SLATE};margin-top:24px;border-top:1px solid {LINE};padding-top:14px">
        Method: source type and motive tier are assigned from a curated entity map; denominator
        and claim type are the announced-vs-delivered lens; the reality anchor links to a published
        base rate when the topic matches. Feed selection is editorial and disclosed. This surfaces
        the structural weakness of a claim; it does not adjudicate truth.<br><br>
        Conflict of interest: the maker of this board is an independent researcher assisted by an
        Anthropic model. Anthropic appears here as a subject and is tagged the same way as every
        other entity. Independent analysis, not investment advice.<br><br>
        Corrections welcome on any judgement here, and they are marked in place with their reason:
        <a href="mailto:NMAIResearch@proton.me" style="color:{NAVY}">NMAIResearch@proton.me</a>
      </div>
    </main>
    <aside class="relcol">
      {ai_watch_html}
      {scholar_html}
    </aside>
    <aside class="rail">
      {releases_html}
      {govconflict_html}
    </aside>
  </div>
</div>
{script_block}
</body></html>"""
    open(OUT, "w", encoding="utf-8").write(doc)
    mode = "plain (motive tier OFF)" if plain else "motive-tiered"
    print(f"written: {OUT}  ({len(items)} items, {len(entity_counts)} entities, {mode})")


if __name__ == "__main__":
    main()
