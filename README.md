# AI News Board

A live board that applies a consistent method to AI news coverage. For each item it records
the publisher's incentive in the claim being true, whether a quoted figure states the base it
is measured against, and a link to a published base rate where one exists. Figures are quoted
verbatim from the article text with their position recorded, and every label carries the
method that produced it, so a reader can check any of it against the source.

## Who sets the labels, and on how much text

Stated here and on the page itself, not only in a hover tooltip.

**Set from the domain, no model involved:** source type and motive tier.

**Set by a local open-weight model:** `claim_type` and `denominator_stated`. `autolabel.py`
calls a model over Ollama (currently `qwen3.6:27b`), and `autolabel_crosscheck.py` runs three
more (`gemma3:27b`, `qwen3.6:35b`, `mistral-small:24b`, `glm-4.7-flash`) over the identical
prompt and records where they disagree. Disagreement lowers an item's review priority; it
settles nothing. A 2-1 split is recorded as a split, never resolved to the majority, because
readers from one model family share a lineage and a shared error looks exactly like agreement.

**No machine pass ever sets `reviewed = true`.** That is why items keep the "auto-tagged,
unreviewed" mark. A machine guess is never presented as a human check.

⚠️ **The model sees the headline and nothing else.** No article body is fetched; the prompt is
about 27 tokens per item. So "no denominator" means *the headline does not state one*, and the
article may well do. Read the flag as a prompt to check rather than as a finding about the
claim. Reader-facing wording on the page says the same.

⚠️ **Calibration is uneven.** On the extraction task in the companion Model Dependency work,
`gemma3:27b`, `qwen3.6:27b` and `qwen3.6:35b` are scored; `mistral-small:24b` and
`glm-4.7-flash` are not. Do not treat all four cross-check readers as equivalent.

## Run

    python3 fetch_feeds.py     # pull BROAD AI news into feed_items.json (neutral intake)
    python3 carry_reviews.py   # re-apply prior review labels by URL; only NEW items stay unreviewed
    python3 apply_ratings.py   # layer NM's ~/Desktop/Scripts/sources.md trust ratings
    python3 fetch_scholar.py   # pull latest arXiv papers + HF datasets
    python3 fetch_market.py    # pull quotes into data/market.json (needs API keys)
    python3 build.py           # reads items.json (+ feeds), writes index.html
    python3 build.py --plain   # same, but motive tiering OFF: plain sources only

All stdlib, no dependencies. Open `index.html` in any browser.

`--plain` turns the motive tier off entirely (no tier colours, per-item bar, motive
key or tier map): sources are shown plain, for a reader who would rather judge them
without the incentive layer. The other axes (denominator, claim type, track record
and reality anchors) are unaffected.

## Market context (added 2026-07-25)
A header strip and a per-item chip give the price context for an announced-vs-delivered
claim. The board **states the move and the window, and stops**: it never says an item caused
a move, never ranks a company and never implies a trade. A tier-5 source can be right while
the stock falls. An entity that is privately held (OpenAI, Anthropic, xAI) gets an explicit
**"no listed security"** rather than a blank, because the absence of a market check is itself
a finding under this board's method.

`ticker_map.json` is contestable in the same way as `tier_map.json`: a ticker is an
observable fact about a company, not a judgement about a claim.

Sources: **Finnhub** for equities (free tier, real-time quotes, no history) and **FRED** for
indices, because Finnhub's free tier refuses index data. **Twelve Data** is a fallback: if
Finnhub rate-limits or goes down, a symbol degrades to a second live quote rather than to
yesterday's number, and only a failure of *both* falls back to carrying the previous value
forward. It widens resilience, not coverage: its free tier is US and OTC only, and Hong Kong,
Shanghai and Seoul symbols return "available starting with the Pro or Venture plan". Indices therefore run one trading day
behind, which the strip says on its face. No euro-area index is shown: FRED's only euro-area
share-price series is monthly and about six months behind, so it would print stale beside
daily values.

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
The public board takes BROAD AI news (RSS), it does NOT run through the personal
interest watchlist in `~/Desktop/Scripts/watchlist.md` (that watchlist is correct for
private lead-hunting via `watch_routine.py`, but for a public page it would bias which
AI news appears). What it DOES reuse is `sources.md`, which rates *who a source is*,
not the topic, so it is neutral. That gives a two-axis board: motive tier (incentive)
and track record (trusted / caution from `sources.md`), kept separate so past accuracy is
not confused with incentive. `watch_routine.py` is left untouched; `apply_ratings.py` is a
separate read-only adapter over `sources.md`.

## Tier scale (canonical, from the Source Incentive Map)
This board is the live front-end of `~/Desktop/Project Source Incentive Map/`, and it
uses that map's distance-tier scale, NOT a bespoke one: **1 = least incentive to shade
the claim** (primary record, regulator, adversarial process), 2 = research institute
or academia, 3 = analyst house or trade press, 4 = tool or data vendor, 5 = the party
selling the thing the claim is about. It is claim-relative and it allocates
verification effort; it is not a trust or quality score. Green (low tier) to red (high
tier) is a coverage bar keyed on motive rather than on a left/right axis.

## What each item shows
- **Source chips + distribution bar** coloured by that tier scale.
- **claim_type** - announced / assertion / target / prediction / measurement (the
  announced-vs-delivered lens).
- **denominator_stated** - Y / partial / N. Almost always N, which is the point.
- **Reality anchor** - a link to a published base rate when the topic matches (a
  code-% claim anchors to the AI Research-Automation Scorecard; later, energy to
  the Forecast Scorecard, GW announcements to Contingent-Demand, water to the Water
  Tracker, cost to Cost Watch). Blank when no anchor exists, which is honest.

## v0 scope and roadmap
- **v0:** 9 items seeded from the AI Research-Automation Scorecard, plus a live RSS
  feed (`fetch_feeds.py`) with `source_type` from the domain.
- **Done since v0:** the anchor map is generalised beyond code to `water`, `power_demand`,
  `energy_forecast` and `cost` (each mapped to a portfolio DOI), and feed items are
  auto-matched to an anchor by headline keyword, flagged "auto-matched, unreviewed".
- **Scholarship source (decided 2026-07-12):** a broad direct-arXiv pull, NOT the
  interest-filtered `watch_routine.py`, so the public scholarship section stays neutral.
- **Next:** a review pass over the incoming feed; deploy.
- **Deploy:** static, so it drops onto `nmairesearch.github.io` beside the other tools.

## Automate the plumbing, not the call
Automatable: feed pull, `source_type` (from URL), `motive_tier` (entity lookup),
entity counting, the reality-anchor topic->DOI map, layout. Light human or
LLM-first-pass-then-spot-check: `claim_type` and `denominator_stated` on ambiguous
items. Flagging "no denominator stated" is a checkable, non-accusatory call, not a
claim that anyone lied.

## Honest ceilings
- The entity->motive map is curated and updatable; "who benefits" is a judgement
  made once per entity, transparently, not per item.
- The anchor map only covers topics the portfolio addresses; most items will have a
  blank anchor, which is honest, not a gap to paper over.
- Feed selection is editorial and disclosed. This is a curated digest, not a
  real-time firehose.
- It surfaces the structural weakness of a claim; it does not adjudicate truth.

## Conflict of interest
The maker is an independent researcher assisted by an Anthropic model. Anthropic
appears here as a subject and is tagged the same way as every other entity.
Independent analysis, not investment advice.
