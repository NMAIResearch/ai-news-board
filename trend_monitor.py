#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""trend_monitor.py - Search & Market Trend Monitor (stdlib only).

Monitors:
1. Real-time search query spikes from Google Trends (US, UK, and Global feeds).
2. Symmetrical market anomalies: breakout rallies (>= +10%), surges (>= +5%),
   warning drops (-3% to -5%), and critical drops (<= -5%) from data/market.json.
3. Structured keyword matching across 7 project-aligned research domains:
   - AI Labour Market & Employment
   - Forward-Looking Architectures & Research Automation
   - AI IPOs, Private Marks & Public Listings
   - Consumer Sentiment & Dark Patterns
   - Physical Buildout, Grid & Hardware Chokepoints
   - Sovereign Regulation & Antitrust
   - Macro & Market Volatility

Usage:
    python3 trend_monitor.py --show       # Print formatted report to terminal
    python3 trend_monitor.py --notify     # Send desktop notification on high-severity matches
    python3 trend_monitor.py --write      # Write results to data/trend_alerts.json
"""

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

HERE = pathlib.Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
MARKET_FILE = DATA_DIR / "market.json"
TREND_OUT = DATA_DIR / "trend_alerts.json"

USER_AGENT = "Mozilla/5.0 (NM AI Research Trend Monitor; +https://nmairesearch.github.io)"

# 7-Domain taxonomy aligned with project research spine
WATCH_TOPICS: Dict[str, Dict[str, Any]] = {
    "AI Labour Market & Employment": {
        "color": "#0284c7",
        "description": "Hiring freezes, entry-level contraction, ATS screening, and workforce displacement.",
        "keywords": [
            "junior developer", "entry level tech", "hiring freeze", "ai layoffs",
            "replaced by ai", "ai resume filter", "applicant tracking system",
            "hirevue", "upwork ai", "freelance writing ai", "workforce reduction",
            "ai restructuring", "headcount cut"
        ]
    },
    "Forward-Looking Architectures & Research Automation": {
        "color": "#7c3aed",
        "description": "Reasoning scaling, test-time compute, agentic RAG, autonomous science, and synthetic data.",
        "keywords": [
            "test-time compute", "process reward model", "mcts reasoning", "self-correction",
            "speculative decoding", "graphrag", "agentic rag", "kv cache", "context caching",
            "ai scientist", "automated paper", "theorem proving", "lab robotics",
            "synthetic data collapse", "model collapse", "fineweb-edu"
        ]
    },
    "AI IPOs, Private Marks & Public Listings": {
        "color": "#059669",
        "description": "S-1 registrations, private secondary marks, lock-up unlocks, and public float dilution.",
        "keywords": [
            "openai s-1", "openai ipo", "anthropic ipo", "cerebras ipo", "coreweave ipo",
            "databricks ipo", "forge global", "hiive", "secondary mark", "down round",
            "spacex unlock", "lockup expiration", "short interest ai", "float squeeze"
        ]
    },
    "Consumer Sentiment & Dark Patterns": {
        "color": "#dc2626",
        "description": "Public backlash against AI slop, subscription cancellation traps, and deceptive patterns.",
        "keywords": [
            "ai slop", "ai garbage", "turn off ai", "disable ai overview", "remove ai search",
            "ai ruined", "opt out ai", "cancel chatgpt", "cancel claude", "cancel copilot",
            "subscription refund", "ai pricing increase", "ai deepfake scam", "ai hallucination lawsuit"
        ]
    },
    "Physical Buildout, Grid & Hardware Chokepoints": {
        "color": "#d97706",
        "description": "Data-centre power demand, grid queues, nuclear SMRs, water permits, and memory pass-through.",
        "keywords": [
            "datacenter blackout", "ai grid queue", "pjm power", "ercot datacenter",
            "nuclear datacenter", "smr datacenter", "ai electricity bill", "ai water usage",
            "cooling permit", "datacenter wastewater", "blackwell delay", "hbm shortage",
            "cowos packaging", "tsmc price", "asml export", "dram price"
        ]
    },
    "Sovereign Regulation & Antitrust": {
        "color": "#475569",
        "description": "EU AI Act enforcement, Article 50 transparency, FTC/DOJ probes, and surveillance restrictions.",
        "keywords": [
            "eu ai act", "article 50 transparency", "ai watermarking", "ai office guidelines",
            "ftc ai probe", "doj nvidia", "cma ai investigation", "cloud antitrust",
            "flock safety ban", "alpr warrant", "facial recognition lawsuit", "automated decision discrimination"
        ]
    },
    "Macro & Market Volatility": {
        "color": "#991b1b",
        "description": "Market sell-offs, rate policy, liquidity shifts, and volatility index spikes.",
        "keywords": [
            "stock crash", "market selloff", "vix spike", "rate cut", "recession",
            "liquidity crunch", "margin call", "circuit breaker", "tech rotation"
        ]
    }
}

# Symmetrical market anomaly thresholds
RALLY_THRESHOLD_BREAKOUT = 10.0  # Percentage gain
RALLY_THRESHOLD_SURGE = 5.0      # Percentage gain
DROP_THRESHOLD_WARN = -3.0       # Percentage drop
DROP_THRESHOLD_ALERT = -5.0      # Percentage drop
MACRO_MOVE_THRESHOLD = 3.0       # Index percentage move


def fetch_google_trends(geo: str = "US") -> List[Dict[str, Any]]:
    """Fetch and parse Google Trends RSS feed for a specific region."""
    url = f"https://trends.google.com/trending/rss?geo={geo}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    items = []

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml_content = resp.read()
        root = ET.fromstring(xml_content)
        for it in root.findall(".//item"):
            title = it.find("title").text if it.find("title") is not None else ""
            approx_el = it.find("{https://trends.google.com/trending/rss}approx_traffic")
            traffic = approx_el.text if approx_el is not None else "N/A"
            pub_el = it.find("pubDate")
            pub_date = pub_el.text if pub_el is not None else ""
            news_items = []
            for n in it.findall("{https://trends.google.com/trending/rss}news_item"):
                ntitle = n.find("{https://trends.google.com/trending/rss}news_item_title")
                nurl = n.find("{https://trends.google.com/trending/rss}news_item_url")
                if ntitle is not None and ntitle.text:
                    news_items.append({
                        "title": ntitle.text,
                        "url": nurl.text if nurl is not None else ""
                    })

            items.append({
                "query": title,
                "traffic": traffic,
                "pub_date": pub_date,
                "geo": geo,
                "news_items": news_items
            })
    except Exception as e:
        items.append({"error": f"Failed fetching {geo} trends: {str(e)[:60]}"})

    return items


def scan_search_trends(geos: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Scan trending searches against the 7-domain watch taxonomy."""
    if geos is None:
        geos = ["US", "GB"]

    matches = []
    for geo in geos:
        trends = fetch_google_trends(geo)
        for t in trends:
            if "error" in t:
                continue
            query = t.get("query", "").lower()
            news_titles = " ".join([n["title"].lower() for n in t.get("news_items", [])])
            search_corpus = f"{query} {news_titles}"

            matched_categories = []
            matched_keywords = []

            for cat_name, cat_data in WATCH_TOPICS.items():
                for kw in cat_data["keywords"]:
                    if re.search(r"\b" + re.escape(kw) + r"\b", search_corpus):
                        if cat_name not in matched_categories:
                            matched_categories.append(cat_name)
                        if kw not in matched_keywords:
                            matched_keywords.append(kw)

            if matched_categories:
                matches.append({
                    "query": t.get("query"),
                    "geo": geo,
                    "traffic": t.get("traffic"),
                    "pub_date": t.get("pub_date"),
                    "categories": matched_categories,
                    "matched_keywords": matched_keywords,
                    "news_items": t.get("news_items", [])[:2]
                })

    return matches


def scan_market_anomalies() -> Dict[str, Any]:
    """Scan data/market.json for symmetrical stock anomalies (drops, surges, and macro moves)."""
    if not MARKET_FILE.is_file():
        return {"error": "data/market.json not found"}

    try:
        with open(MARKET_FILE, "r", encoding="utf-8") as f:
            mdata = json.load(f)
    except Exception as e:
        return {"error": f"Failed reading market file: {e}"}

    breakouts = []
    surges = []
    drops_alert = []
    drops_warn = []
    indices_alerts = []

    # Check equities
    equities = mdata.get("equities", {})
    for ticker, info in equities.items():
        chg = info.get("change_pct", 0.0)
        val = info.get("value", 0.0)
        asof = info.get("asof", "")

        entry = {
            "ticker": ticker,
            "change_pct": round(chg, 2),
            "price": val,
            "asof": asof
        }

        if chg >= RALLY_THRESHOLD_BREAKOUT:
            breakouts.append(entry)
        elif chg >= RALLY_THRESHOLD_SURGE:
            surges.append(entry)
        elif chg <= DROP_THRESHOLD_ALERT:
            drops_alert.append(entry)
        elif chg <= DROP_THRESHOLD_WARN:
            drops_warn.append(entry)

    # Check macro indices and commodities
    indices = mdata.get("indices", {})
    for sym, info in indices.items():
        chg = info.get("change_pct", 0.0)
        lbl = info.get("label", sym)
        if abs(chg) >= MACRO_MOVE_THRESHOLD:
            indices_alerts.append({
                "symbol": sym,
                "label": lbl,
                "change_pct": round(chg, 2),
                "value": info.get("value"),
                "asof": info.get("asof", "")
            })

    breakouts.sort(key=lambda x: x["change_pct"], reverse=True)
    surges.sort(key=lambda x: x["change_pct"], reverse=True)
    drops_alert.sort(key=lambda x: x["change_pct"])
    drops_warn.sort(key=lambda x: x["change_pct"])
    indices_alerts.sort(key=lambda x: abs(x["change_pct"]), reverse=True)

    return {
        "asof": mdata.get("generated", ""),
        "breakouts": breakouts,
        "surges": surges,
        "critical_drops": drops_alert,
        "warning_drops": drops_warn,
        "macro_moves": indices_alerts
    }


def send_desktop_notification(title: str, message: str, urgency: str = "normal") -> None:
    """Send a Linux desktop notification using notify-send."""
    try:
        subprocess.run(["notify-send", "-u", urgency, title, message], check=False)
    except Exception:
        pass


def run_monitor(notify: bool = False, write: bool = False) -> Dict[str, Any]:
    """Execute complete search and market trend monitor run."""
    search_matches = scan_search_trends()
    market_signals = scan_market_anomalies()

    result = {
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "search_trend_matches": search_matches,
        "market_signals": market_signals,
        "watch_taxonomy_count": len(WATCH_TOPICS)
    }

    if write:
        DATA_DIR.mkdir(exist_ok=True)
        with open(TREND_OUT, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

    if notify:
        # Check critical drops
        crit_drops = market_signals.get("critical_drops", [])
        if crit_drops:
            tickers = ", ".join([f"{d['ticker']} ({d['change_pct']}%)" for d in crit_drops[:4]])
            send_desktop_notification("Market Alert: Heavy Stock Drops", f"Equities down <= -5%: {tickers}", urgency="critical")

        # Check breakout surges
        breakouts = market_signals.get("breakouts", []) + market_signals.get("surges", [])
        if breakouts:
            tickers = ", ".join([f"{b['ticker']} ({b['change_pct']}%)" for b in breakouts[:4]])
            send_desktop_notification("Market Alert: Heavy Stock Rallies", f"Equities up >= +5%: {tickers}", urgency="normal")

        # Check search trends
        if search_matches:
            top_trend = search_matches[0]
            send_desktop_notification("Search Trend Alert", f"Trending: {top_trend['query']} (Matched: {', '.join(top_trend['matched_keywords'])})")

    return result


def print_report(res: Dict[str, Any]) -> None:
    """Print clean terminal report."""
    print("=" * 75)
    print(f"SEARCH & MARKET TREND MONITOR  [{res['timestamp'][:19]} UTC]")
    print(f"Tracking 7 project research domains and symmetrical market movements.")
    print("=" * 75)

    # 1. Market Anomalies Section
    m = res.get("market_signals", {})
    print("\n[1] MARKET ANOMALIES (EQUITIES & MACRO INDICES)")
    print("-" * 75)

    breakouts = m.get("breakouts", [])
    surges = m.get("surges", [])
    crit = m.get("critical_drops", [])
    warn = m.get("warning_drops", [])
    macro = m.get("macro_moves", [])

    if breakouts:
        print("  BREAKOUT RALLIES (>= +10.0%):")
        for b in breakouts:
            print(f"    + {b['ticker']:<6}  {b['change_pct']:+6.2f}%  (Price: ${b['price']})")

    if surges:
        print("\n  SHARP SURGES (+5.0% to +10.0%):")
        for s in surges:
            print(f"    + {s['ticker']:<6}  {s['change_pct']:+6.2f}%  (Price: ${s['price']})")

    if crit:
        print("\n  CRITICAL DROPS (<= -5.0%):")
        for d in crit:
            print(f"    - {d['ticker']:<6}  {d['change_pct']:+6.2f}%  (Price: ${d['price']})")

    if warn:
        print("\n  WARNING DROPS (-3.0% to -5.0%):")
        for d in warn:
            print(f"    - {d['ticker']:<6}  {d['change_pct']:+6.2f}%  (Price: ${d['price']})")

    if not (breakouts or surges or crit or warn):
        print("  No equity movements outside the +/- 3.0% threshold.")

    if macro:
        print("\n  MACRO & VOLATILITY SHIFTS (>= 3.0%):")
        for mc in macro:
            print(f"    * {mc['label']:<15}  {mc['change_pct']:+6.2f}%  (Value: {mc['value']})")

    # 2. Search Trends Section
    s_matches = res.get("search_trend_matches", [])
    print("\n[2] PROJECT-ALIGNED SEARCH TREND SPIKES (Google Trends US/UK)")
    print("-" * 75)
    if s_matches:
        for it in s_matches:
            cats = ", ".join(it["categories"])
            kws = ", ".join(it["matched_keywords"])
            print(f"  * {it['query'].upper()} [{it['geo']}] (Traffic: {it['traffic']})")
            print(f"    Category: {cats} | Keywords: {kws}")
            for n in it.get("news_items", []):
                print(f"    - {n['title']}")
            print()
    else:
        print("  No direct keyword matches in current Google Trends top 20 RSS window.")
        print("  (7 research domains active: Labour, Architectures, IPOs, Sentiment, Hardware, Regulation, Macro)")

    print("=" * 75)


def main():
    parser = argparse.ArgumentParser(description="Search & Market Trend Monitor")
    parser.add_argument("--show", action="store_true", help="Print formatted report to terminal")
    parser.add_argument("--notify", action="store_true", help="Send desktop notification on alerts")
    parser.add_argument("--write", action="store_true", help="Write to data/trend_alerts.json")
    args = parser.parse_args()

    if not args.show and not args.notify and not args.write:
        args.show = True
        args.write = True

    result = run_monitor(notify=args.notify, write=args.write)

    if args.show:
        print_report(result)


if __name__ == "__main__":
    main()
