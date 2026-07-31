#!/usr/bin/env python3
"""extract_spans.py - TIER 1 of the labelling ladder: verbatim figure-spans from articles.

Fetches each board item's article, extracts readable text, finds every quantitative figure,
and stores the VERBATIM sentence containing it plus a character offset into the stored text.

⛔ Never summarise or paraphrase here. A span is checkable by exact substring, a paraphrase
by nothing. `--verify` re-asserts every span against the stored text, so a label built on
spans is auditable without reading the article or trusting this script.

Spans, not article text: the denominator question only ever concerns a sentence containing a
number. Measured 2026-07-31 over 38 articles: 482 spans, 46.6k chars, all verified.

⛔ Do not go back to headlines or RSS descriptions for figures. Of 35 items with an RSS
description, exactly 1 carried a figure its headline lacked (measured 2026-07-30).

    python3 extract_spans.py              # fetch (cached) + extract
    python3 extract_spans.py --refetch    # ignore the cache
    python3 extract_spans.py --verify     # check stored spans are exact substrings
    python3 extract_spans.py --report     # per-item span counts, fetch nothing

Writes article_text.json (cache) and article_spans.json. Touches neither feed_items.json
nor index.html.
"""
import argparse
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
FEED = os.path.join(HERE, "feed_items.json")
CACHE = os.path.join(HERE, "article_text.json")
SPANS = os.path.join(HERE, "article_spans.json")

UA = "Mozilla/5.0 (NM AI Research board; +https://nmairesearch.github.io/ai-news-board)"
TIMEOUT = 25
# Per-host delay. One request per article, so this is the whole politeness budget.
DELAY = 1.5
MAX_CHARS = 400_000

DROP = re.compile(r"<(script|style|noscript|svg|form|nav|header|footer|aside)\b.*?</\1>",
                  re.S | re.I)
# <article> and <main> when present; the fallback is the whole body and is noisier.
MAIN = re.compile(r"<(?:article|main)\b[^>]*>(.*?)</(?:article|main)>", re.S | re.I)
BLOCK = re.compile(r"</(p|div|li|h[1-6]|br|tr)\s*>|<br\s*/?>", re.I)
TAG = re.compile(r"<[^>]+>")
WS = re.compile(r"[ \t ]+")
NL = re.compile(r"\n{2,}")

# ── figure detection ────────────────────────────────────────────────────────────────────
# Explicit money / percent / magnitude. These always count.
STRONG = re.compile(
    r"[\$£€]\s?\d[\d,]*(?:\.\d+)?\s*(?:bn|[mbk]\b|million|billion|trillion)?"
    r"|\d[\d,]*(?:\.\d+)?\s*(?:%|per cent|percent)"
    r"|\d[\d,]*(?:\.\d+)?\s*(?:million|billion|trillion)\b"
    r"|\d[\d,]*(?:\.\d+)?\s*(?:GW|MW|TWh|GWh|kWh)\b",
    re.I)
# Bare counts. Filtered, because most digits in an article are dates and version numbers.
BARE = re.compile(r"(?<![\w$£€/.\-])(\d[\d,]*(?:\.\d+)?)(?![\w/\-])")
YEAR = re.compile(r"^(?:19|20)\d\d$")          # 2026 is a year; 2,000 is a count
NOISE = re.compile(
    r"Q[1-4]\b|GPT-|Claude\s|Gemini\s|Llama\s|version\s|\bv\d|24/7|section\s\d"
    r"|item\?id|Points:|#\s*Comments|\bID\b|ISO\s|\bp\.\s?\d|\bNo\.\s?\d", re.I)
# Month anywhere in the preceding window, so "October 13 - 15" drops both numbers.
MONTH = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\b[\s\d\-–—,]*$", re.I)
# A stated base turns "a bare figure" into "a rate with its denominator".
BASE_CUE = re.compile(
    r"\bout of\b|\bof (?:the\s)?(?:some\s)?\d|\bfrom a total of\b|\bof all\b"
    r"|\bcompared (?:with|to)\b|\bversus\b|\bvs\.?\b|\bup from\b|\bdown from\b"
    r"|\bof (?:its|their|the) \w+ (?:total|base|fleet|workforce|revenue)\b", re.I)

# Page furniture that survives readable(): promo rails, contact blocks, ticket ads. These
# carry digits and would otherwise be scored as claims about the article's subject.
FURNITURE = re.compile(
    r"securely on Signal|\bSignal at\b|\bWhatsApp\b|Telegram @|\+\d[\d\s\-]{8,}"
    r"|Save up to|Register (?:now|today)|Buy (?:your )?tickets?|tickets? on sale"
    r"|Sign up (?:for|to) (?:our|the)|newsletter|Subscribe|All rights reserved|©"
    r"|Disrupt 20\d\d|Read more:|Related:|Image Credits", re.I)

SENT_END = re.compile(r"(?<=[.!?])[\s\n]+")
ABBREV = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|Prof|Inc|Ltd|Corp|Co|St|vs|approx|e\.g|i\.e|U\.S|U\.K)\.$",
                    re.I)


def readable(raw_html):
    """HTML to plain text. Paragraph structure kept as newlines; everything else dropped."""
    s = DROP.sub(" ", raw_html)
    m = MAIN.search(s)
    if m and len(m.group(1)) > 400:
        s = m.group(1)
    s = BLOCK.sub("\n", s)
    s = TAG.sub(" ", s)
    s = html.unescape(s)
    s = WS.sub(" ", s)
    s = NL.sub("\n", s)
    return "\n".join(ln.strip() for ln in s.split("\n")).strip()[:MAX_CHARS]


LINK = re.compile(r'<a\b[^>]*\bhref\s*=\s*["\']([^"\'#][^"\']*)["\']', re.I)
LD = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)
META = re.compile(
    r'<meta[^>]+(?:property|name)\s*=\s*["\']'
    r'(article:tag|keywords|og:site_name)["\'][^>]*\bcontent\s*=\s*["\']([^"\']*)["\']', re.I)


def publisher_tags(raw_html):
    """The publisher's own subject tagging: JSON-LD keywords/about plus tag meta.

    A candidate list, never an answer: TechCrunch tags 'Okta' alongside 'Exclusive' and
    'AI agents'. Resolution against a known-organisation registry happens in resolve_entity.
    An article the publisher tags with no organisation is evidence there is no subject
    entity, which is a valid outcome and must not be filled in.
    """
    tags, site = [], ""
    for m in LD.finditer(raw_html):
        try:
            doc = json.loads(m.group(1).strip())
        except Exception:
            continue
        stack = doc if isinstance(doc, list) else [doc]
        while stack:
            n = stack.pop()
            if isinstance(n, list):
                stack.extend(n)
                continue
            if not isinstance(n, dict):
                continue
            stack.extend(v for v in (n.get("@graph"),) if v)
            kw = n.get("keywords")
            if isinstance(kw, str):
                tags += [t.strip() for t in kw.split(",")]
            elif isinstance(kw, list):
                tags += [str(t).strip() for t in kw]
            for ab in (n.get("about") or []) if isinstance(n.get("about"), list) else []:
                if isinstance(ab, dict) and ab.get("name"):
                    tags.append(str(ab["name"]).strip())
    for key, val in META.findall(raw_html):
        val = html.unescape(val).strip()
        if key.lower() == "og:site_name":
            site = val
        elif val:
            tags += [t.strip() for t in val.split(",")]
    seen, out = set(), []
    for t in tags:
        if t and t.lower() not in seen and len(t) < 60:
            seen.add(t.lower())
            out.append(t)
    return out[:30], site


def outbound(raw_html, page_url):
    """Absolute off-site links from the main content region, deduped, in document order.

    Kept separate from readable(): the text pass strips tags, so a link check run on the
    stored text can only ever return zero.
    """
    s = DROP.sub(" ", raw_html)
    m = MAIN.search(s)
    if m and len(m.group(1)) > 400:
        s = m.group(1)
    here = urllib.parse.urlsplit(page_url).netloc.replace("www.", "")
    out, seen = [], set()
    for href in LINK.findall(s):
        u = urllib.parse.urljoin(page_url, html.unescape(href.strip()))
        if not u.startswith("http"):
            continue
        net = urllib.parse.urlsplit(u).netloc.replace("www.", "")
        if not net or net == here or u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out[:200]


def sentences(text):
    """[(sentence, offset)] with offsets exact into `text`."""
    out, pos = [], 0
    for line in text.split("\n"):
        if not line:
            pos += 1
            continue
        start, buf = 0, line
        parts, last = [], 0
        for m in SENT_END.finditer(buf):
            cand = buf[last:m.start() + 1]
            if ABBREV.search(cand.strip()):
                continue
            parts.append((cand, last))
            last = m.end()
        parts.append((buf[last:], last))
        for frag, off in parts:
            frag_stripped = frag.strip()
            if len(frag_stripped) < 15:
                continue
            lead = len(frag) - len(frag.lstrip())
            out.append((frag_stripped, pos + off + lead))
        pos += len(line) + 1
    return out


def figures(sent):
    """[(figure, offset_in_sentence)] for one sentence."""
    found, seen = [], set()
    for m in STRONG.finditer(sent):
        found.append((m.group(0).strip(), m.start()))
        seen.update(range(m.start(), m.end()))
    for m in BARE.finditer(sent):
        # Strip trailing punctuation before the year test: [\d,]* swallows it, and
        # "fiscal 2027," would otherwise pass as a count.
        val = m.group(1).rstrip(",.")
        if m.start() in seen or YEAR.match(val):
            continue
        ctx = sent[max(0, m.start() - 40):m.end() + 40]
        if NOISE.search(ctx) or MONTH.search(sent[max(0, m.start() - 24):m.start()]):
            continue
        found.append((val, m.start()))
    return sorted(found, key=lambda t: t[1])


def robots_ok(url, cache):
    """Respect robots.txt, fetched with the same User-Agent as the article request.

    ⛔ Do not use RobotFileParser.read(): it fetches with urllib's default agent, and on a
    401/403 for robots.txt itself it sets disallow_all and refuses every URL. nist.gov
    blocks that agent. An unreachable robots.txt is not a prohibition.
    """
    host = urllib.parse.urlsplit(url)
    root = f"{host.scheme}://{host.netloc}"
    if root not in cache:
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(root + "/robots.txt", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=15) as r:
                rp.parse(r.read().decode("utf-8", "replace").splitlines())
        except Exception:
            rp = None
        cache[root] = rp
    rp = cache[root]
    return True if rp is None else rp.can_fetch(UA, url)


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "text/html,application/xhtml+xml"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        ct = r.headers.get("Content-Type", "")
        if "html" not in ct.lower():
            raise ValueError(f"not html ({ct.split(';')[0]})")
        enc = r.headers.get_content_charset() or "utf-8"
        return r.read(4_000_000).decode(enc, "replace")


def board_urls():
    items = json.load(open(FEED))["items"]
    out = []
    for it in items:
        for s in it.get("sources", []):
            if s.get("url", "").startswith("http"):
                out.append((s["url"], it.get("headline", ""), s.get("name", "")))
                break
    return out


def load(path):
    return json.load(open(path)) if os.path.exists(path) else {}


def do_verify():
    text, spans = load(CACHE), load(SPANS)
    bad = miss = total = 0
    for url, rec in spans.items():
        body = (text.get(url) or {}).get("text", "")
        if not body:
            miss += 1
            continue
        for sp in rec["spans"]:
            total += 1
            if body[sp["offset"]:sp["offset"] + len(sp["sentence"])] != sp["sentence"]:
                bad += 1
                print(f"  MISMATCH {url} @{sp['offset']}: {sp['sentence'][:60]!r}")
    print(f"verify: {total} span(s), {bad} mismatched, {miss} article(s) with no cached text")
    return 1 if bad else 0


def do_report():
    spans = load(SPANS)
    if not spans:
        print("no article_spans.json yet")
        return
    ok = [r for r in spans.values() if r["fetch"] == "ok"]
    withfig = [r for r in ok if r["spans"]]
    nb = sum(1 for r in ok for s in r["spans"] if s["base_cue"])
    nf = sum(len(r["spans"]) for r in ok)
    print(f"articles: {len(spans)} attempted, {len(ok)} fetched")
    print(f"with at least one figure: {len(withfig)}/{len(ok)}")
    print(f"figure-spans: {nf}, of which {nb} carry a base cue "
          f"({nf - nb} bare figures for the labeller to judge)")
    fails = [(u, r["fetch"]) for u, r in spans.items() if r["fetch"] != "ok"]
    for u, why in fails:
        print(f"  not fetched: {why:22s} {u[:78]}")
    for u, r in spans.items():
        if r["spans"]:
            print(f"\n{r['headline'][:74]}")
            for s in r["spans"][:3]:
                print(f"   [{', '.join(s['figures'])}]"
                      f"{' +base' if s['base_cue'] else ''} "
                      f"@{s['offset']}: {s['sentence'][:110]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refetch", action="store_true", help="ignore the cache")
    ap.add_argument("--verify", action="store_true", help="check spans against cached text")
    ap.add_argument("--report", action="store_true", help="summarise, fetch nothing")
    ap.add_argument("--limit", type=int, default=0, help="stop after N articles")
    a = ap.parse_args()

    if a.verify:
        raise SystemExit(do_verify())
    if a.report:
        return do_report()

    cache, spans, robots, last = load(CACHE), {}, {}, {}
    urls = board_urls()
    if a.limit:
        urls = urls[:a.limit]
    print(f"{len(urls)} article(s); cache holds {len(cache)}")

    fetched = reused = skipped = 0
    for url, headline, src in urls:
        rec = cache.get(url)
        # Reuse successes only. A cached failure survives the fix that would clear it.
        if rec and rec.get("status") == "ok" and not a.refetch:
            reused += 1
        else:
            if not robots_ok(url, robots):
                cache[url] = {"text": "", "status": "robots-disallowed",
                              "fetched": datetime.now(timezone.utc).isoformat()}
                skipped += 1
            else:
                netloc = urllib.parse.urlsplit(url).netloc
                wait = DELAY - (time.time() - last.get(netloc, 0))
                if wait > 0:
                    time.sleep(wait)
                try:
                    raw_html = fetch(url)
                    tags, site = publisher_tags(raw_html)
                    cache[url] = {"text": readable(raw_html), "status": "ok",
                                  "links": outbound(raw_html, url),
                                  "publisher_tags": tags, "site_name": site,
                                  "fetched": datetime.now(timezone.utc).isoformat()}
                    fetched += 1
                except urllib.error.HTTPError as e:
                    cache[url] = {"text": "", "status": f"http-{e.code}",
                                  "fetched": datetime.now(timezone.utc).isoformat()}
                    skipped += 1
                except Exception as e:
                    cache[url] = {"text": "", "status": type(e).__name__.lower(),
                                  "fetched": datetime.now(timezone.utc).isoformat()}
                    skipped += 1
                last[netloc] = time.time()
            rec = cache[url]
            json.dump(cache, open(CACHE, "w"), indent=1)   # durable per article

        body, got, furniture = rec["text"], [], 0
        if rec["status"] == "ok":
            for sent, off in sentences(body):
                figs = figures(sent)
                if not figs:
                    continue
                if FURNITURE.search(sent):
                    furniture += 1
                    continue
                got.append({
                    "sentence": sent,
                    "offset": off,
                    "figures": [f for f, _ in figs],
                    "figure_offsets": [o for _, o in figs],
                    "base_cue": bool(BASE_CUE.search(sent)),
                })
        spans[url] = {"headline": headline, "source": src, "fetch": rec["status"],
                      "n_chars": len(body), "tier": 1, "furniture_dropped": furniture,
                      "spans": got}
        mark = "ok" if rec["status"] == "ok" else rec["status"]
        print(f"  {mark:18s} {len(got):3d} span(s)  {headline[:56]}")

    json.dump(spans, open(SPANS, "w"), indent=1)
    print(f"\nfetched {fetched}, cached {reused}, not fetched {skipped}")
    print(f"written: {SPANS}")
    print("run --verify to confirm every span is an exact substring of the stored article")


if __name__ == "__main__":
    main()
