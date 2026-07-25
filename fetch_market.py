#!/usr/bin/env python3
"""AI News Board - fetch_market.py (stdlib only). Writes data/market.json.

WHY THIS EXISTS, AND WHAT IT IS NOT
-----------------------------------
The board's lens is announced-vs-delivered. A market price is the cheapest public read on
what got delivered after something was announced, so it belongs here. But a price strip is
also the easiest way to turn a flagging tool into a markets product, which this is not.

So the rule this file encodes: the board states the move and the window, and stops. It never
says a move was CAUSED by an item, never ranks a company, never implies a trade. An entity
that is privately held gets "no listed security" rather than a blank, because "there is no
market check available on this claim" is a real finding under this board's own method.

Prices are a claim's CONTEXT, not its verdict. A tier-5 source can be right and the stock can
still fall, and vice versa.

SOURCES
-------
Finnhub for US-listed equities (free tier: real-time quotes, no history).
FRED for indices, because Finnhub's free tier refuses index data ("subscription required for
CFD indices"). FRED redistributes the exchange and CBOE prints and runs one trading day
behind, which is labelled on the strip.

Yahoo Finance and Stooq were both tested on 2026-07-25 and are unusable: Yahoo 429s and blocks
browser CORS, Stooq now runs a JavaScript proof-of-work wall.

⛔ Because Finnhub's free tier has no /stock/candle, a "move since this item was published"
cannot be backfilled. data/market_history.json accumulates one point per run so that window
becomes available going forward. Until history covers an item's date, the chip shows the
current quote only and says so. It does not guess.

KEYS
----
Read from FINNHUB_API_KEY / FRED_API_KEY in the environment, falling back to
~/.config/nmai/keys.env for local runs. In CI they come from repo secrets. No key is ever
written into data/market.json, which is a public file.

Run:  python3 fetch_market.py
"""
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = DATA / "market.json"
HISTORY = DATA / "market_history.json"
TICKER_MAP = HERE / "ticker_map.json"

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
FINNHUB_BASE = "https://finnhub.io/api/v1/quote"


def keys():
    out = {k: os.environ.get(k, "") for k in ("FINNHUB_API_KEY", "FRED_API_KEY")}
    local = pathlib.Path.home() / ".config" / "nmai" / "keys.env"
    if local.exists():
        for line in local.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out.setdefault(k.strip(), "")
                out[k.strip()] = out[k.strip()] or v.strip()
    missing = [k for k, v in out.items() if not v]
    if missing:
        sys.exit(f"missing key(s): {', '.join(missing)}")
    return out


def get_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def fred_last(series_id, key):
    """Latest two non-missing observations, so a day-change can be shown."""
    q = urllib.parse.urlencode({"series_id": series_id, "file_type": "json",
                                "sort_order": "desc", "limit": 8, "api_key": key})
    obs = [(o["date"], float(o["value"]))
           for o in get_json(f"{FRED_BASE}?{q}")["observations"] if o["value"] != "."]
    if not obs:
        raise RuntimeError("no observations")
    d, v = obs[0]
    prev = obs[1][1] if len(obs) > 1 else None
    return {"value": v, "asof": d,
            "change_pct": (v / prev - 1) * 100 if prev else None}


def finnhub_quote(symbol, key, attempts=3):
    """One quote, with backoff. The free tier allows 60 calls/minute and returns 429 past it."""
    for n in range(attempts):
        try:
            d = get_json(f"{FINNHUB_BASE}?symbol={urllib.parse.quote(symbol)}",
                         headers={"X-Finnhub-Token": key})
            if "error" in d or not d.get("c"):
                raise RuntimeError(d.get("error", "empty quote"))
            return {"value": d["c"], "change_pct": d.get("dp"),
                    "asof": datetime.fromtimestamp(d["t"], timezone.utc).date().isoformat()}
        except urllib.error.HTTPError as e:
            if e.code != 429 or n == attempts - 1:
                raise
            time.sleep(5 * (n + 1))
    raise RuntimeError("unreachable")


def main():
    k = keys()
    tm = json.loads(TICKER_MAP.read_text())
    strip = tm["strip"]
    DATA.mkdir(exist_ok=True)

    indices, equities, errors = {}, {}, {}

    for spec in strip["indices"]:
        try:
            q = fred_last(spec["fred"], k["FRED_API_KEY"])
            q.update(label=spec["label"], dp=spec["dp"], prefix=spec.get("prefix", ""),
                     source=f"FRED {spec['fred']}")
            indices[spec["key"]] = q
        except Exception as e:
            errors[spec["key"]] = f"{type(e).__name__}: {e}"

    # Every ticker named in the map, not just the strip: the per-item chips need any
    # entity that appears in the feed, and the free tier is 60 calls/minute.
    wanted = sorted({e["ticker"] for e in tm["entities"].values() if e.get("ticker")}
                    | set(strip["equities"]))
    for sym in wanted:
        try:
            equities[sym] = finnhub_quote(sym, k["FINNHUB_API_KEY"])
        except Exception as e:
            errors[sym] = f"{type(e).__name__}: {e}"
        time.sleep(1.1)  # stay inside 60 calls/minute rather than relying on the retry

    # A partial pull must NEVER overwrite a complete one. A transient 429 in CI would
    # otherwise publish a strip with holes in it. Carry the last known value forward and
    # mark it stale, so the page can say the quote is old rather than show nothing.
    if errors and OUT.exists():
        try:
            prev = json.loads(OUT.read_text()).get("equities", {})
            for sym in list(errors):
                if sym in prev:
                    equities[sym] = dict(prev[sym], stale=True)
                    errors[sym] += " (carried forward from the previous run)"
        except (json.JSONDecodeError, OSError):
            pass

    # One point per run, so "since published" becomes computable going forward. Finnhub's
    # free tier has no history endpoint, so this cannot be backfilled.
    hist = json.loads(HISTORY.read_text()) if HISTORY.exists() else {}
    today = datetime.now(timezone.utc).date().isoformat()
    # Carried-forward quotes are not a fresh observation and must not enter the history.
    hist[today] = {s: q["value"] for s, q in equities.items() if not q.get("stale")}
    hist = {d: hist[d] for d in sorted(hist)[-400:]}
    HISTORY.write_text(json.dumps(hist, separators=(",", ":"), sort_keys=True) + "\n")

    payload = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "indices": indices,
        "equities": equities,
        "errors": errors,
        "disclosure": ("Indices are one trading day behind (FRED, which redistributes the "
                       "exchange and CBOE prints). Equity quotes are from Finnhub. Prices are "
                       "shown as context for an announced-vs-delivered claim. No causal link "
                       "to any item is asserted, and nothing here is investment advice."),
    }
    # Write only when the DATA changed. 'generated' moves on every run, so writing
    # unconditionally would put a commit in the repo twice a weekday forever, most of them
    # a one-line timestamp. That means 'generated' reads as "when this data was captured",
    # which is the more useful of the two meanings anyway.
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text())
            if {k: v for k, v in old.items() if k != "generated"} == \
               {k: v for k, v in payload.items() if k != "generated"}:
                print(f"unchanged, not rewriting {OUT}")
                return
        except (json.JSONDecodeError, OSError):
            pass

    OUT.write_text(json.dumps(payload, indent=1) + "\n")
    print(f"{len(indices)} indices, {len(equities)} equities, {len(errors)} errors -> {OUT}")
    for s, e in errors.items():
        print(f"  ERROR {s}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
