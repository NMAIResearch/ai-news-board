#!/usr/bin/env python3
"""
AI News Board - fetch_feeds.py (stdlib only).

Pulls AI-news RSS/Atom feeds and auto-tags ONLY the automatable fields: source_type
from the domain, a default motive_tier from that type, and the entity if a known
vendor is named in the headline. It deliberately does NOT set denominator_stated: that is
the call, left to label_items.py over the article spans, or to a human. Every fetched item
is written with reviewed=false and denominator "?" until then. That is "automate the
plumbing, not the call" in code.

⛔ claim_type is RETIRED (2026-07-31). Still written here as a dead field so old stores
carry across; nothing reads it and build.py does not render it. Do not revive it.

Run:  python3 fetch_feeds.py     # writes feed_items.json, then re-run build.py
Edit FEEDS below to change sources. Network required; a feed that fails is skipped.
"""
import html, json, os, re, sys, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

# ↻ [2026-07-30, his call] Drop feed items older than this at intake. Low-volume feeds
# return posts from months back, so the board was carrying items dated January and May 2026
# among the current ones; day grouping made them visible.
# ⚠️ An item with an UNPARSEABLE date is KEPT, not dropped. Dropping on a parse failure
# would silently discard current items from any feed whose date format is not handled.
# ↻ Resolved same day, archive.py now exists: the intake cutoff STAYS. Items are captured
# while fresh and the archive keeps them permanently after, so the revisit view is not
# starved. The only items lost are ones already older than the cutoff when first seen, which
# are the stale feed artefacts this was added to remove.
MAX_AGE_DAYS = int(os.environ.get("FEED_MAX_AGE_DAYS", "30"))
# ⚠️ The cutoff is PER SOURCE TYPE because news and regulation decay at different rates.
# A single 30-day rule deleted the tier-1 feeds the same day they were added: NIST had 10 AI
# items and every one was over 30 days old, Ofgem's was from 2024. A trade-press story is
# stale in a month; a Federal Register policy statement or a NIST framework is not.
MAX_AGE_BY_TYPE = {"primary-record": 180, "independent": 120,
                   "tool-vendor": 90, "press-office": 30}

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "feed_items.json")

# (url, needs_ai_filter). Trade-press feeds are already AI-scoped by the publisher's own
# category, so they pass through. Regulator and agency feeds are general-purpose and must be
# filtered, or the board fills with advisory-committee notices. The filter does for a primary
# feed what the publisher's category tag does for trade press; it is topic scope, not motive
# selection, and every source stays tiered by who it is.
FEEDS = [
    # trade press, AI sections (tier 3)
    ("https://techcrunch.com/category/artificial-intelligence/feed/", False),
    # ⛔ venturebeat.com REMOVED 2026-07-30: its AI feed serves nothing under 30 days old.
    # All 7 items it returned were dated May 2026 or January 2026, and it was the sole
    # source of the stale January items on the board. Re-add if the feed starts moving.
    ("https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", False),
    ("https://arstechnica.com/ai/feed/", False),
    # vendor-own (tier 5)
    ("https://deepmind.google/blog/rss.xml", False),
    # aggregator (tier 3)
    ("https://hnrss.org/newest?q=AI+OR+LLM+OR+OpenAI+OR+Anthropic&points=50", False),
    # ↻ [2026-07-30] primary record (tier 1). Added because the board scored ZERO tier-1 and
    # zero tier-2 sources on 2026-07-30 (30 items at tier 3, 6 at tier 5): a scale whose green
    # end is "regulator, primary record, adversarial process" had an empty green end.
    ("https://www.federalregister.gov/api/v1/documents.rss?conditions%5Bterm%5D=artificial+intelligence", True),
    ("https://www.ftc.gov/feeds/press-release.xml", True),
    ("https://www.sec.gov/news/pressreleases.rss", True),
    ("https://www.gov.uk/search/news-and-communications.atom?organisations%5B%5D=competition-and-markets-authority", True),
    ("https://www.gov.uk/search/news-and-communications.atom?organisations%5B%5D=ofgem", True),
    ("https://www.nist.gov/news-events/news/rss.xml", True),
    # ↻ [2026-07-31] tier 2 (research institute / academia). The tier read ZERO before this:
    # `independent` mapped only to arxiv.org, which fetch_scholar.py sends to its own panel.
    ("https://cset.georgetown.edu/feed/", True),
    ("https://ainowinstitute.org/feed", False),
    ("https://bair.berkeley.edu/blog/feed.xml", False),
    ("https://www.csail.mit.edu/rss.xml", True),
    # ↻ [2026-07-31] tier 5, MIT's press office, deliberately NOT the same source as CSAIL
    ("https://news.mit.edu/rss/topic/artificial-intelligence2", False),
    # ↻ [2026-07-31] tier 4 (tool or data vendor)
    ("https://semianalysis.com/feed/", True),
    ("https://www.finops.org/feed/", True),
    ("https://epochai.substack.com/feed", False),
]

# Checked 2026-07-30, do NOT re-add without re-testing: hai.stanford.edu (malformed XML),
# epoch.ai/rss.xml (404), ico.org.uk/rss/news-and-blogs (404),
# adalovelaceinstitute.org/feed (parses to 0 items).

AI_TERMS = re.compile(
    r"\b(a\.?i\.?|artificial intelligence|machine learning|algorithm\w*|"
    r"large language model|LLM|chatbot|generative|OpenAI|Anthropic|DeepMind|"
    r"Nvidia|data cent(?:re|er)|compute|semiconductor|chip\w*|automat\w*)\b",
    re.I)

# domain fragment -> source_type. A lab's own blog about AI is the party selling
# the topic (vendor-own); a regulator/court/agency is a primary record.
DOMAIN_TYPE = [
    ("sec.gov", "primary-record"), ("ftc.gov", "primary-record"),
    ("courtlistener.com", "primary-record"), ("regulations.gov", "primary-record"),
    ("europa.eu", "primary-record"), ("uspto.gov", "primary-record"),
    ("openai.com", "vendor-own"), ("anthropic.com", "vendor-own"),
    ("deepmind.google", "vendor-own"), ("blog.google", "vendor-own"),
    ("ai.googleblog", "vendor-own"), ("microsoft.com", "vendor-own"),
    ("about.fb.com", "vendor-own"), ("meta.com", "vendor-own"),
    ("techcrunch.com", "trade-press"), ("venturebeat.com", "trade-press"),
    ("theverge.com", "trade-press"), ("arstechnica.com", "trade-press"),
    ("wired.com", "trade-press"), ("reuters.com", "trade-press"),
    ("bloomberg.com", "trade-press"), ("ft.com", "trade-press"),
    ("news.ycombinator.com", "aggregator"), ("ycombinator.com", "aggregator"),
    ("reddit.com", "aggregator"), ("news.google.com", "aggregator"),
    ("federalregister.gov", "primary-record"), ("gov.uk", "primary-record"),
    ("nist.gov", "primary-record"), ("arxiv.org", "independent"),
    # tier 2, research institutes and academic labs (credibility-aligned)
    ("cset.georgetown.edu", "independent"), ("ainowinstitute.org", "independent"),
    ("bair.berkeley.edu", "independent"), ("csail.mit.edu", "independent"),
    # tier 5, an institution's PRESS OFFICE, kept separate from its research
    ("news.mit.edu", "press-office"),
    # tier 4, sells data, research access or tooling on the topics it reports
    ("semianalysis.com", "tool-vendor"), ("finops.org", "tool-vendor"),
    ("epoch.ai", "tool-vendor"), ("epochai.substack.com", "tool-vendor"),
    # a project publishing its own policy is a vendor-own claim, not trade press
    ("openjdk.org", "vendor-own"),
]
# canonical distance tier: 1 = least incentive ... 5 = sells the thing
# ⚠️ Every tier on the published scale must be reachable from this map. Until 2026-07-31
# no key mapped to 4, so "tool or data vendor" could never be assigned however the domain
# table grew, and the board showed a five-point scale with a permanently empty point.
# press-office sits at 5 deliberately: a university or lab press release about its own
# research is the party publicising the thing, whatever the research itself is worth.
TYPE_TIER = {"primary-record": 1, "independent": 2, "trade-press": 3,
             "aggregator": 3, "tool-vendor": 4, "vendor-own": 5,
             "press-office": 5, "other": 3}
VENDORS = ["OpenAI", "Anthropic", "Google DeepMind", "DeepMind", "Google",
           "Microsoft", "Meta", "Nvidia", "Amazon", "Salesforce", "Snap",
           "xAI", "Apple", "Mistral", "Cohere", "Perplexity"]

# A named principal IS the company for motive purposes: a Zuckerberg forecast about
# personal AI agents is a Meta claim, whatever masthead relays it. Headline-only text
# often names the person and never the firm, which is why 19 of 36 items in the
# 2026-07-30 feed resolved to no entity at all.
PRINCIPALS = [
    ("Zuckerberg", "Meta"), ("Altman", "OpenAI"), ("Amodei", "Anthropic"),
    ("Huang", "Nvidia"), ("Musk", "xAI"), ("Pichai", "Google"),
    ("Hassabis", "Google DeepMind"), ("Nadella", "Microsoft"),
    ("Jassy", "Amazon"), ("Cook", "Apple"), ("Benioff", "Salesforce"),
    ("LeCun", "Meta"), ("Sutskever", "OpenAI"),
]

MONTH_NAME = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|"
    r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
HUMAN_PUBLICATION_DATE = re.compile(
    rf"\b({MONTH_NAME}\s+\d{{1,2}},\s+\d{{4}})\b", re.I)
JSON_PUBLICATION_DATE = re.compile(
    r'["\']datePublished["\']\s*:\s*["\']([^"\']+)["\']', re.I)
META_TAG = re.compile(r"<meta\b[^>]*>", re.I)
META_ATTR = re.compile(r"([:\w-]+)\s*=\s*[\"']([^\"']*)[\"']", re.I)
URL_PUBLICATION_DATE = (
    re.compile(r"/(\d{4})/(\d{1,2})/(\d{1,2})(?:/|$)"),
    re.compile(rf"/(\d{{4}})/({MONTH_NAME})/(\d{{1,2}})(?:/|$)", re.I),
)


def normalise_publication_date(value):
    """Return a page publication date as YYYY-MM-DD, or blank if it is not a date."""
    value = html.unescape((value or "").strip())
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def publication_date_from_html(raw):
    """Extract the article's publication date, never its modified timestamp.

    Structured metadata is preferred. OpenAI and Anthropic currently omit it from these
    newsroom pages, so the fallback takes the human-readable date nearest the first h1.
    Restricting that fallback to the heading region avoids dates mentioned in the article.
    """
    m = JSON_PUBLICATION_DATE.search(raw or "")
    if m:
        date = normalise_publication_date(m.group(1))
        if date:
            return date

    for tag in META_TAG.findall(raw or ""):
        attrs = {k.lower(): v for k, v in META_ATTR.findall(tag)}
        key = (attrs.get("property") or attrs.get("name") or
               attrs.get("itemprop") or "").lower()
        if key in {"article:published_time", "datepublished", "publishdate"}:
            date = normalise_publication_date(attrs.get("content", ""))
            if date:
                return date

    heading = re.search(r"<h1\b", raw or "", re.I)
    if not heading:
        return ""
    start = max(0, heading.start() - 1800)
    end = min(len(raw), heading.start() + 1800)
    matches = list(HUMAN_PUBLICATION_DATE.finditer(raw[start:end]))
    if not matches:
        return ""
    nearest = min(matches, key=lambda hit: abs(start + hit.start() - heading.start()))
    return normalise_publication_date(nearest.group(1))


def publication_date_from_url(url):
    """Extract a date from an explicit YYYY/MM/DD or YYYY/Mon/DD URL path."""
    for index, pattern in enumerate(URL_PUBLICATION_DATE):
        match = pattern.search(url or "")
        if not match:
            continue
        try:
            if index == 0:
                value = datetime(int(match.group(1)), int(match.group(2)),
                                 int(match.group(3)))
            else:
                month = datetime.strptime(match.group(2)[:3], "%b").month
                value = datetime(int(match.group(1)), month, int(match.group(3)))
            return value.date().isoformat()
        except ValueError:
            continue
    return ""


def publication_date_of_url(url):
    """Fetch one article page and return its publication date, if exposed."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (NM AI Research board)"})
    with urllib.request.urlopen(req, timeout=20) as response:
        raw = response.read().decode(
            response.headers.get_content_charset() or "utf-8", "replace")
    return publication_date_from_html(raw)


def source_type(url):
    for dom, t in DOMAIN_TYPE:
        if dom in url:
            return t
    return "other"   # unknown domain: do not assert 'trade press'; the unreviewed flag covers it


def entity_of(title):
    """The entity the claim is ABOUT, best-effort from the headline.

    Picks the name appearing EARLIEST IN THE TEXT, not first in VENDORS. Headlines lead with
    their subject, so position beats list order: "Salesforce rolls out X as it battles
    Microsoft and Google" returned Google under list order, because Google sits above
    Salesforce in VENDORS.

    ⚠️ Still a heuristic, and it will be wrong on headlines that open with the object
    ("Nvidia chips power Meta's new cluster"). Items stay flagged unreviewed; a human pass
    is what settles the entity.
    """
    hits = []
    for v in VENDORS:
        m = re.search(r"\b" + re.escape(v) + r"\b", title, re.I)
        if m:
            hits.append((m.start(), -len(v), v))
    for person, firm in PRINCIPALS:
        m = re.search(r"\b" + re.escape(person) + r"\b", title, re.I)
        if m:
            hits.append((m.start(), -len(person), firm))
    if not hits:
        return ""
    # Tie on position: prefer the longer match, so "Google DeepMind" beats "Google".
    return min(hits)[2]


def item_date(s):
    """Feed date -> aware datetime, or None if it does not parse."""
    s = (s or "").strip()
    if not s:
        return None
    try:                                    # RFC 822: "Wed, 29 Jul 2026 18:25:00 +0000"
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        d = None
    if d is None:
        try:                                # ISO 8601: "2026-07-29T18:25:00Z"
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            d = None
    if d is None:
        # Date-only variants. parsedate_to_datetime rejects "Tue, 19 May 2026" (no time),
        # which let a 2-month-old item through the cutoff on the first test.
        for fmt in ("%a, %d %b %Y", "%d %b %Y", "%Y-%m-%d"):
            try:
                d = datetime.strptime(s[:len("Tue, 19 May 2026")].strip(), fmt)
                break
            except ValueError:
                continue
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def too_old(s, now, stype="other"):
    d = item_date(s)
    if d is None:                     # unparseable date: keep, never drop on a parse failure
        return False
    return (now - d) > timedelta(days=MAX_AGE_BY_TYPE.get(stype, MAX_AGE_DAYS))


def domain(url):
    m = re.match(r"https?://([^/]+)/?", url or "")
    return m.group(1).replace("www.", "") if m else (url or "")


def clean_title(s):
    """Decode entities ONCE at intake, so the store holds real characters.

    Publishers escape titles in the feed body, so an apostrophe arrives as &#8217; and a
    quote as &quot;. build.py runs html.escape over every field it renders, which turns
    that leading & into &amp; and prints the entity to the reader verbatim. Escaping is
    right; escaping something already escaped is the bug.

    Fixed at intake rather than in build.py's esc(), because esc() is applied to every
    string on the page and unescaping there would corrupt any text meant to show an
    entity literally. fetch_vendor_news.py already did this, so the two intake paths now
    agree. Seen 2026-08-07 on "Jony Ive&#8217;s first OpenAI gadget".
    """
    return html.unescape((s or "").strip())


def parse(xmlbytes):
    out, root = [], ET.fromstring(xmlbytes)
    items = list(root.iter("item"))
    if items:                                   # RSS
        for it in items:
            out.append((clean_title(it.findtext("title")),
                        (it.findtext("link") or "").strip(),
                        (it.findtext("pubDate") or "").strip()))
    else:                                       # Atom
        ns = "{http://www.w3.org/2005/Atom}"
        for e in root.iter(ns + "entry"):
            le = e.find(ns + "link")
            out.append((clean_title(e.findtext(ns + "title")),
                        (le.get("href") if le is not None else "").strip(),
                        (e.findtext(ns + "updated") or "").strip()))
    return out


def main():
    per_feed, collected, dropped_old = 6, [], 0
    now = datetime.now(timezone.utc)
    for f, needs_filter in FEEDS:
        try:
            req = urllib.request.Request(
                f, headers={"User-Agent": "Mozilla/5.0 (NM AI Research board)"})
            raw = urllib.request.urlopen(req, timeout=20).read()
            rows = parse(raw)
            if needs_filter:
                # Filter BEFORE truncating, or a general feed's first 6 items crowd out the
                # AI ones further down.
                rows = [r for r in rows if AI_TERMS.search(r[0] or "")]
            fresh = [r for r in rows
                     if not too_old(r[2], now, source_type(r[1] or f))]
            dropped_old += len(rows) - len(fresh)

            # HN's RSS pubDate is when somebody submitted the link, not when the linked
            # article was published. Prefer the article's own date before applying the
            # cutoff and displaying it. If a page exposes no date, keep the feed date rather
            # than silently dropping the item.
            if "hnrss.org" in f:
                dated = []
                for title, link, feed_date in fresh:
                    page_date = ""
                    if link:
                        page_date = publication_date_from_url(link)
                        try:
                            page_date = publication_date_of_url(link) or page_date
                        except Exception as e:
                            print(f"  no page date for {domain(link)}: {e}", file=sys.stderr)
                    effective_date = page_date or feed_date
                    if too_old(effective_date, now, source_type(link or f)):
                        dropped_old += 1
                        continue
                    dated.append((title, link, effective_date))
                    if len(dated) == per_feed:
                        break
                rows = dated
            else:
                rows = fresh[:per_feed]
        except Exception as e:
            print(f"skip {domain(f)}: {e}", file=sys.stderr)
            continue
        for title, link, date in rows:
            if not title:
                continue
            st = source_type(link or f)
            collected.append({
                # ⛔ Do NOT fall back to the domain. The entity answers "who is the claim
                # about", the source chip already answers "who published it". Conflating
                # them put outlet names into the most-covered-entity table and silently
                # told the reader that TechCrunch was the claimant.
                "entity": entity_of(title),
                "headline": title,
                "date": date[:16] if date else "",
                "topic": "",
                # ⛔ Not "announced". That is a judgement about the rhetorical form of the
                # claim and nobody has made it yet. A board that flags unearned assertion
                # must not open by asserting a claim_type it has not checked.
                "claim_type": "unclassified",
                "denominator_stated": "?",
                "reviewed": False,
                "sources": [{"name": domain(link or f), "url": link,
                             "source_type": st, "motive_tier": TYPE_TIER.get(st, 4)}],
            })
    json.dump({"fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
               "items": collected}, open(OUT, "w", encoding="utf-8"), indent=1)
    print(f"written: {OUT}  ({len(collected)} items"
          + (f", {dropped_old} dropped older than {MAX_AGE_DAYS}d" if dropped_old else "")
          + "). Now run: python3 build.py")


if __name__ == "__main__":
    main()
