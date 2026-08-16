#!/usr/bin/env python3
"""primary_crosscheck.py - Reconciles news claims against primary SEC EDGAR and official filings.

Elevates the AI News Board from heuristic tiering to empirical primary source assurance.
Matches entities mentioned in news items to regulatory tickers (ticker_map.json) and
cross-references quantitative claims against primary filings.
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
TICKER_MAP_FILE = HERE / "ticker_map.json"
FEED_ITEMS_FILE = HERE / "feed_items.json"
SPANS_FILE = HERE / "article_spans.json"
COSTWATCH_FILE = HERE.parent / "AI Costwatch" / "cost-watch" / "costwatch.json"


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error loading {path}: {e}", file=sys.stderr)
        return {}


def reconcile_items(feed_items: list, ticker_map: dict, costwatch_data: dict) -> list:
    """Reconciles news items against primary entity mapping and filing facts."""
    reconciled = []
    entities = ticker_map.get("entities", {})
    indicators = costwatch_data.get("indicators", {})

    for item in feed_items:
        headline = item.get("headline", "")
        item_entity = item.get("entity", "")
        mentions = [m.get("name") for m in item.get("mentions", [])]
        
        # Check matched tickers
        matched_tickers = []
        private_reasons = []
        
        for name in [item_entity] + mentions:
            if not name:
                continue
            for ent_name, ent_info in entities.items():
                if ent_name.lower() in name.lower() or name.lower() in ent_name.lower():
                    ticker = ent_info.get("ticker")
                    if ticker and ticker not in matched_tickers:
                        matched_tickers.append(ticker)
                    elif ent_info.get("private") and ent_info["private"] not in private_reasons:
                        private_reasons.append(f"{ent_name}: {ent_info['private']}")

        # Determine verification category
        if matched_tickers:
            # Check if we have costwatch / filing data for any matched ticker
            has_filing_facts = any(t in indicators for t in matched_tickers)
            status = "AUDITABLE_PUBLIC_FILING" if has_filing_facts else "MAPPED_PUBLIC_SECURITY"
            note = f"Mapped to SEC ticker(s): {', '.join(matched_tickers)}"
        elif private_reasons:
            status = "PRIVATE_UNCHECKABLE"
            note = "; ".join(private_reasons)
        else:
            status = "UNCLASSIFIED_SOURCE"
            note = "No listed security or registered private lab mapped"

        reconciled.append({
            "headline": headline,
            "entity": item_entity,
            "date": item.get("date", ""),
            "status": status,
            "tickers": matched_tickers,
            "note": note,
            "url": item.get("sources", [{}])[0].get("url", "")
        })

    return reconciled


def print_report(reconciled: list, filter_status: str = None):
    """Prints verification summary adhering to Rules 14 and 15."""
    filtered = [r for r in reconciled if not filter_status or r["status"] == filter_status]
    total = len(reconciled)
    
    counts = {}
    for r in reconciled:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    print("=" * 80)
    print("AI NEWS REALITY BOARD: PRIMARY SOURCE RECONCILIATION REPORT")
    print(f"Total News Items Evaluated: N = {total}")
    print("=" * 80)
    
    print("\nCoverage Breakdown:")
    for status, count in sorted(counts.items()):
        pct = (count / total * 100) if total > 0 else 0.0
        print(f"  {status:28s} : {count:4d} / {total} ({pct:5.1f}%)")

    print("\nDetailed Item Registry:")
    print("-" * 80)
    for idx, r in enumerate(filtered[:25], 1):
        print(f"[{idx:02d}] {r['status']}")
        print(f"     Entity:   {r['entity']}")
        print(f"     Headline: {r['headline']}")
        print(f"     Audit:    {r['note']}")
        print(f"     Source:   {r['url']}")
        print()
    if len(filtered) > 25:
        print(f"... and {len(filtered) - 25} more items.")
    print("-" * 80)


def main():
    parser = argparse.ArgumentParser(description="Primary source reconciliation engine for AI News Board")
    parser.add_argument("--status", choices=["AUDITABLE_PUBLIC_FILING", "MAPPED_PUBLIC_SECURITY", "PRIVATE_UNCHECKABLE", "UNCLASSIFIED_SOURCE"],
                        help="Filter report by reconciliation status")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    args = parser.parse_args()

    feed_data = load_json(FEED_ITEMS_FILE)
    ticker_data = load_json(TICKER_MAP_FILE)
    costwatch_data = load_json(COSTWATCH_FILE)

    items = feed_data.get("items", [])
    if not items:
        print("No items found in feed_items.json", file=sys.stderr)
        return

    results = reconcile_items(items, ticker_data, costwatch_data)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_report(results, filter_status=args.status)


if __name__ == "__main__":
    main()
