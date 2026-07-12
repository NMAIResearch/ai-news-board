# AI News Reality Board

AI news, sorted by incentive rather than by political lean. Every AI-news claim is
tagged by who is telling you and what they gain if you believe it, flagged for whether
it states a denominator, and anchored to a published base rate. It flags; it does not
narrate. The reader draws the conclusion.

## Run

    python3 fetch_feeds.py     # pull BROAD AI news into feed_items.json (neutral intake)
    python3 apply_ratings.py   # layer the a local ratings file trust ratings
    python3 fetch_scholar.py   # pull latest arXiv papers + HF datasets
    python3 build.py           # reads items.json (+ feeds), writes index.html
    python3 build.py --plain   # same, but motive tiering OFF: plain sources only

All stdlib, no dependencies. Open `index.html` in any browser.

`--plain` turns the motive tier off entirely (no tier colours, per-item bar, motive
key or tier map): sources are shown plain, for a reader who would rather judge them
without the incentive layer. The other axes (denominator, claim type, track record
and reality anchors) are unaffected.

## Neutrality (why the intake is broad, not watchlist-filtered)
The public board takes BROAD AI news (RSS), it does NOT run through the personal
interest watchlist in `a local watchlist` (that watchlist is correct for
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
