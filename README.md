# AI News Board

A live board that applies a consistent method to AI news coverage. For each item it records
the publisher's incentive in the claim being true, whether a quoted figure states the base it
is measured against, and a link to a published base rate where one exists. Figures are quoted
verbatim from the article text with their position recorded, and every label carries the
method that produced it, so a reader can check any of it against the source.

Live: https://nmairesearch.github.io/ai-news-board/
Method changes and defects found, dated: [CHANGELOG.md](CHANGELOG.md)

## Run

    python3 fetch_feeds.py        # pull BROAD AI news into feed_items.json (neutral intake)
    python3 fetch_vendor_news.py  # append vendor newsroom posts that publish no RSS
    python3 carry_reviews.py      # re-apply prior labels by URL; only NEW items stay unreviewed
    python3 apply_ratings.py      # layer NM's ~/Desktop/Scripts/sources.md trust ratings
    python3 extract_spans.py      # fetch each article, store verbatim figure-spans + offsets
    python3 label_items.py        # denominator from spans where they settle it, model for the rest
    python3 resolve_entity.py     # decide who each claim is about, deterministically or blank
    python3 article_evidence.py   # per-article attribution, primary links, figure sourcing
    python3 fetch_scholar.py      # pull latest arXiv papers + HF datasets
    python3 fetch_releases.py     # models released in the last 60 days
    python3 archive.py            # permanent record + revisit queue
    python3 fetch_market.py       # pull quotes into data/market.json (needs API keys)
    python3 build.py              # writes index.html
    python3 build.py --plain      # same, but motive tiering OFF: plain sources only

All stdlib, no dependencies. Open `index.html` in any browser. A feed refresh costs nothing
but time; the only optional cost in the pipeline is the local model in `label_items.py`.

`--plain` turns the motive tier off entirely (no tier colours, per-item bar, motive key or
tier map): sources are shown plain, for a reader who would rather judge them without the
incentive layer. The other axes (denominator, track record, reality anchors) are unaffected.

## Who sets the labels, and on how much text

Stated here and on the page itself, not only in a hover tooltip.

**Set from the domain, no model involved:** source type and a default motive tier.

**Set deterministically:** the entity, by `resolve_entity.py` against `org_registry.json`,
resolved from the headline, a product name, the publisher's own JSON-LD tags, or the
publisher's site, in that order. Every result records which route reached it. Blank is a
valid and common outcome: a piece about a labour market or a lawsuit trend has no subject
organisation, and the motive tier correctly falls back to source type. Nothing is guessed.

**Set from article text:** `denominator_stated`. `extract_spans.py` fetches each article and
stores the verbatim sentence around every figure with a character offset into the stored text.
`--verify` re-asserts every span as an exact substring, so a label built on spans is auditable
without reading the article or trusting the script. `label_items.py` then answers what the
spans settle deterministically (tier 1) and asks a local model over Ollama only for the rest
(tier 3).

**Every field carries `label_tier` and `label_evidence`, and the page renders them.** A
denominator from a regex over quoted spans and one from a model are different evidence and
must not look identical.

**No machine pass ever sets `reviewed = true`.** That is why items keep the "auto-tagged,
unreviewed" mark, and why a machine label is never overwritten onto a human one.

### `claim_type` was retired, not fixed (2026-07-31)

It is no longer set or rendered. Two readers at full coverage over 38 items scored kappa 0.52
on headlines and 0.56 given the article opening plus the figure spans, so article context did
not rescue it, and there is no ground truth to score it against. A field that will not
stabilise is better deleted than caveated. `article_evidence.py` replaces the judgement with
four countable properties: who the article's claims are attributed to and how many of those
attributions are to a party to the claim, whether a piece describing a filing or a paper links
to one, how many extracted figures name a source in the same sentence, and a claim-relative
motive tier from `stake_map.json`.

### The headline-only limit, and how it was closed

Until 2026-07-31 the labeller saw the headline and nothing else, about 27 tokens per item, so
"no denominator" meant only that the headline did not state one. Two rungs were measured
before the fix was built:

- **RSS `<description>` is not enough.** Of 35 items carrying one, exactly 1 gained a figure
  its headline lacked. It stays useful as a fallback when an article fetch fails.
- **Verbatim spans work.** Over 38 articles: 482 figure-spans, 46.6k characters, all 482
  verified as exact substrings.

Spans are quoted, never summarised. A span is checkable by exact substring; a paraphrase is
checkable by nothing.

### The reader cross-check was retired with the headline era

Several local models used to read the same headline and their disagreement was rendered as a
chip. Two of its three fields are now gone: `claim_type` is retired, and the denominator comes
from quoted spans, which is checkable rather than voted on. Provenance travels on the label
itself instead. The tooling is in [`archive/`](archive/), which explains what it did and what
is worth keeping if it is ever rebuilt on spans.

## What each item shows

- **Source chips and distribution bar** coloured by the tier scale below.
- **denominator_stated**, Y / partial / N / n-a, with the tier and the evidence that produced
  it, and the quoted span where one settles it.
- **Entity**, with the route that resolved it, or blank.
- **Citation chain**, whether the article links to the primary document it describes. The
  label is "cites", never "restates": absence of a link is not evidence that reporting is
  second-hand.
- **Reality anchor**, a link to a published base rate when the topic matches (a code-share
  claim anchors to the AI Research-Automation Scorecard, energy to the Forecast Scorecard, GW
  announcements to Contingent-Demand, water to the Water Tracker, cost to Cost Watch). Blank
  when no anchor exists, which is honest.

## Model releases

Models that reached OpenRouter or the Hugging Face API in the last 60 days. That is the whole
job of the panel: what came out recently.

Each row says whether the weights are published. This is an attribute of the release, not a
grade. An API-only model is shipped, it is serving traffic and people are paying for it, it is
simply not downloadable. Whether it can be hashed and re-run later is an auditability question
and belongs in the companion Model Dependency work, not in a list of what came out.

⛔ **The open and API-only totals are not a ratio and are not presented as one.** OpenRouter is
taken in full; Hugging Face is a hand-written list of labs capped at five repositories each,
four of which sat on that cap on 2026-07-31. OpenRouter rows are deduped to a base model,
Hugging Face rows are not. Such a ratio would move with the org list rather than with the
world.

⚠️ **The two dates differ in kind.** An OpenRouter date is a listing observed by a third party.
A Hugging Face `createdAt` is repo creation, which can sit either side of a public release.

Moving pointers such as `~x-ai/grok-latest` are excluded: their date is when the alias was
made, and each duplicates a versioned row already in the list. No benchmark scores, by choice;
that is a leaderboard, and a percentage with no stated denominator is the defect this board
flags elsewhere. A model announced but never shipped cannot appear in any release list,
including this one.

## Archive and revisit queue

The board's lens is announced against delivered, but a feed can only ever show the
announcement. Measured over the git history of `feed_items.json`, 121 unique URLs were
captured across 18 days and each fetch replaced the last, so nothing could be asked again
later. `archive.py` keeps every item ever fetched and builds a ranked, capped revisit queue
that asks the second question at a due date. Intake runs at roughly 6.7 items a day, so an
uncapped queue was never sustainable.

Capture, the due date, the ranking and the cap are automated. The `outcome` is not. Whether a
thing was delivered is the call, and a model must not make it.

## AI Watch registers

A dated resolution calendar and a set of live gauges, from `registers.json`. These are
extracted from a private working tracker by an external script that reads only rows marked for
publication and slices away the columns holding private material at read time. The generated
rows carry the date and the question; the reader-facing wording is written by hand and carried
forward by row id across regenerations, so a machine refresh cannot blow away human judgement.

## Market context

A header strip and a per-item chip give the price context for an announced-against-delivered
claim. The board **states the move and the window, and stops**: it never says an item caused a
move, never ranks a company and never implies a trade. A tier-5 source can be right while the
stock falls. An entity that is privately held (OpenAI, Anthropic, xAI) gets an explicit **"no
listed security"** rather than a blank, because the absence of a market check is itself a
finding under this board's method.

`ticker_map.json` is contestable in the same way as `tier_map.json`: a ticker is an observable
fact about a company, not a judgement about a claim.

Sources: **Finnhub** for equities (free tier, real-time quotes, no history) and **FRED** for
indices, because Finnhub's free tier refuses index data. **Twelve Data** is a fallback: if
Finnhub rate-limits or goes down, a symbol degrades to a second live quote rather than to
yesterday's number, and only a failure of *both* falls back to carrying the previous value
forward. It widens resilience, not coverage: its free tier is US and OTC only, and Hong Kong,
Shanghai and Seoul symbols return "available starting with the Pro or Venture plan". Indices
therefore run one trading day behind, which the strip says on its face. No euro-area index is
shown: FRED's only euro-area share-price series is monthly and about six months behind, so it
would print stale beside daily values.

**Coverage limit, disclosed rather than papered over.** The quote source serves US-listed and
OTC ADR securities only; native Hong Kong, Shanghai, Seoul and European symbols are refused.
So the reachable China names (Alibaba, Baidu, Tencent, Xiaomi, Kingsoft Cloud) are platform
and cloud companies, **not** the domestic chipmakers: SMIC, Hua Hong and Cambricon cannot be
shown, and neither can Samsung or SK Hynix. Reading the visible China names as coverage of
Chinese AI hardware would be a denominator error of the kind this board flags elsewhere.
Those entities therefore render **"listed, not covered here"**, a third state kept distinct
from "no listed security", because one is a fact about the company and the other is a limit
of this data tier. OTC ADRs (Infineon, Schneider, Siemens, Tencent, Xiaomi) are thinly traded
and can lag their home listing, which is noted on each. Yahoo Finance and Stooq were both
tested on 2026-07-25 and are unusable: Yahoo returns 429 and blocks browser CORS, Stooq now
runs a JavaScript proof-of-work wall.

Refreshed by `.github/workflows/market.yml` (weekdays, twice) which writes **only**
`data/market.json`. It deliberately does not run the feed pipeline or rebuild `index.html`,
because the review pass is a human call and a timer-driven rebuild would publish unreviewed
items. The page renders real numbers at build time and works with JavaScript off; the
client-side refresh only keeps an open tab current, via a same-origin fetch of a static file,
so no API key reaches the browser.

## Neutrality (why the intake is broad, not watchlist-filtered)

The public board takes BROAD AI news (RSS), it does NOT run through the personal interest
watchlist in `~/Desktop/Scripts/watchlist.md` (that watchlist is correct for private
lead-hunting via `watch_routine.py`, but for a public page it would bias which AI news
appears). What it DOES reuse is `sources.md`, which rates *who a source is*, not the topic, so
it is neutral. That gives a two-axis board: motive tier (incentive) and track record (trusted
or caution from `sources.md`), kept separate so past accuracy is not confused with incentive.
`watch_routine.py` is left untouched; `apply_ratings.py` is a separate read-only adapter over
`sources.md`.

Feeds are mixed by source type on purpose. Primary and regulatory sources (Federal Register,
FTC, SEC, CMA, Ofgem, NIST) sit alongside trade press and vendor newsrooms, because a board
that tiers claims by incentive and then carries only tier-3 sources is grading a scale it does
not span. Staleness cutoffs are per source type: 30 days for news, 120 for independent
sources, 180 for primary ones. A flat 30-day cutoff deletes the regulator feeds on day one.

## Tier scale (canonical)

**1 = least incentive to shade the claim** (primary record, regulator, adversarial process),
2 = research institute or academia, 3 = analyst house or trade press, 4 = tool or data vendor,
5 = the party selling the thing the claim is about. It is claim-relative and it allocates
verification effort; it is not a trust or quality score. Green (low tier) to red (high tier) is
a coverage bar keyed on motive rather than on a left or right axis.

`tier_map.json` records every tier with its basis, and every cell is contestable.

## Automate the plumbing, not the call

Automatable: the feed pull, source type from the URL, motive tier by entity lookup, entity
resolution against a registry, the denominator where quoted spans settle it, entity counting,
the anchor topic to DOI map, archive capture and layout.

Not automatable, and not automated: whether an announcement was delivered, whether an item has
been reviewed, and which private register rows may be published.

## Honest ceilings

- The entity to motive map is curated and updatable. "Who benefits" is a judgement made once
  per entity, transparently, not per item.
- `stake_map.json` needs curating. An unlisted publisher keeps its source-type tier and is
  marked as such, never guessed.
- The anchor map only covers topics the portfolio addresses, so most items have a blank
  anchor. That is honest, not a gap to paper over.
- Feed selection is editorial and disclosed. This is a curated digest, not a real-time
  firehose.
- Span precision is unmeasured. Long documents dominate the span counts, and in those the
  numbers are often legal citations or benchmark rows rather than claims.
- It surfaces the structural weakness of a claim; it does not adjudicate truth.

## Conflict of interest

The maker is an independent researcher assisted by an Anthropic model. Anthropic appears here
as a subject and is tagged the same way as every other entity. Independent analysis, not
investment advice.
