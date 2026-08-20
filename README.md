# AI News Board

A live board that separates publisher class, resolved claim relationships, figure-base
evidence, citation links and typed research-context links. Figures are quoted verbatim from article
text with their position recorded. Every machine label states its method, complete-span
coverage, content hash and schema version.

AI disclosure: AI models assisted with parts of this project. Machine and human evidence
methods are identified separately. The models and their conflicts are named below.

Live: https://nmairesearch.github.io/ai-news-board/
Method changes and defects found, dated: [CHANGELOG.md](CHANGELOG.md)

## Deploy, start to finish

Four commands, in this order.

    git pull --rebase origin main    # 1. take CI's market commits FIRST
    ./refresh.sh                     # 2. fetch, label, build
    git add -A && git commit         # 3. hook blocks a stale or failing build
    git push origin main             # 4. live in about a minute

⚠️ **Step 1 comes first, always.** A CI job pushes market data to origin twice a day. Refreshing
before pulling is what strands a good run: the data is right locally and never reaches the board.

**If step 2 fails**, nothing is committed and `index.html` is untouched. Fix and re-run step 2.

**If step 1 conflicts on `data/market.json`**, you pulled after refreshing. Take your side and let
step 2 rewrite it, rather than reasoning about which side is which:

    git checkout --theirs data/market.json data/market_history.json
    git add data/market.json data/market_history.json
    git rebase --continue

⚠️ During a rebase `--theirs` means **your** commit and `--ours` means the upstream. The labels
read backwards. That is why the line above is written out rather than left to judgement.

⛔ **Never `git push --force`.** It deletes CI's market commits.

**Check it went live:**

    curl -s https://nmairesearch.github.io/ai-news-board/ | grep -o 'Page built[^<]*<[^>]*>[^<]*'

### The pre-commit hook

`.git/hooks/pre-commit` refuses a commit whose board data fails the integrity check, whose
`index.html` is older than `feed_items.json`, or which stages an editor lock file.

⚠️ **Git does not track hooks.** It protects this working copy only; a fresh clone has no gate.
Bypass with `git commit --no-verify` if you ever need to.

## Run

**One command does the whole thing.** Use this, not the list below:

    ./refresh.sh                  # every step in order, then builds index.html
    ./refresh.sh --no-label       # same, deterministic labels only (fast)

It runs the thirteen steps in the required order. If Ollama is unavailable, it runs the
deterministic label rules and leaves unresolved items unassessed. It skips the market pull if
`~/.config/nmai/keys.env` is absent, and
**aborts rather than leaving a stale `index.html`** if the build raises. It never runs
`--plain`, never commits and never pushes.

The step list below is what `refresh.sh` runs. Keep it for reading a single step in isolation
or for re-running one after a failure. ⚠️ Running these by hand is how you end up publishing a
`--plain` page or skipping `suggest_register_rows.py`, which is in the script but was missing
from this list until 2026-08-07.

    python3 fetch_feeds.py        # pull BROAD AI news into feed_items.json (neutral intake)
    python3 fetch_vendor_news.py  # append vendor newsroom posts that publish no RSS
    python3 carry_reviews.py      # re-apply prior labels by URL; only NEW items stay unreviewed
    python3 apply_ratings.py      # layer local source trust ratings (optional, see RATINGS_PATH)
    python3 extract_spans.py      # fetch each article, store verbatim figure-spans + offsets
    python3 label_items.py        # denominator from spans where they settle it, model for the rest
    python3 carry_reviews.py      # persist current-schema labels by URL and content hash
    python3 resolve_entity.py     # decide who each claim is about, deterministically or blank
    python3 article_evidence.py   # per-article attribution, primary links, figure sourcing
    python3 fetch_scholar.py      # pull latest arXiv papers + HF datasets
    python3 fetch_releases.py     # models released in the last 60 days
    python3 archive.py            # permanent record + revisit queue
    python3 suggest_register_rows.py --write   # nominate candidate tracker rows, gitignored
    python3 fetch_market.py       # pull quotes into data/market.json (needs API keys)
    python3 build.py              # writes index.html. LAST STEP: see the --plain warning below

Optional check, after `extract_spans.py`:

    python3 extract_spans.py --verify   # every span is an exact substring of the stored article

All stdlib, no dependencies. Open `index.html` in any browser. A feed refresh costs nothing
but time; the only optional cost in the pipeline is the local model in `label_items.py`.

### `--plain` is a toggle, not a pipeline step

    python3 build.py --plain      # same page, source-class tiering off

**`build.py` and `build.py --plain` write the same `index.html`.** There is one `OUT` path and
no separate plain file. This block used to sit as the last line of the run list above, which
reads as a step to run after `build.py`; doing that leaves the tier-OFF page published as the
board. Caught 2026-08-07 by falling into it.

Run one or the other. If you build `--plain` to look at it, **re-run plain `build.py` before
committing.** To check whether the current file is plain:

    grep -c 'body class="plainmode"' index.html    # 1 = plain, 0 = source-tiered

`--plain` removes source-tier colours, the source-class key and the tier registry. The other
axes, including figure provenance, track record and research-context links, are unaffected.

### Publishing, and the step that is not a script

The board deploys from `origin/main`, and a CI job commits market-data refreshes to origin on
its own schedule. A local pipeline run therefore **diverges from origin most days**: local is
ahead on feed data, origin is ahead on market data. `git push` fails until the two are
reconciled, and the reconcile is a judgement (which side wins for `data/market.json`), not a
mechanical step.

The pattern that works, and the reason `bd4ef19` and `aadda8b` exist:

    git fetch origin && git status -sb     # read the ahead/behind counts first
    git merge origin/main                  # CI touches only data/, so this merges clean
    # then run the pipeline, so fetch_market.py rewrites data/market.json over the merge

⚠️ Running the pipeline **before** merging is what strands a good refresh: the data is correct
locally and never reaches the board. On 2026-08-06 a full run sat unpushed at `ahead 2, behind
4` while the live board served the 4 August feed.

## Who sets the labels, and on how much text

Stated here and on the page itself, not only in a hover tooltip.

**Set from the domain, no model involved:** source type and source-class tier, using the
executable `source_types` registry in `tier_map.json`.

**Set deterministically:** the entity, by `resolve_entity.py` against `org_registry.json`,
resolved from the headline, a product name, the publisher's own JSON-LD tags, or the
publisher's site, in that order. Every result records which route reached it. Blank is a
valid and common outcome: a piece about a labour market or a lawsuit trend has no subject
organisation. An unresolved publisher relationship has no numeric claim tier.

**Set from article text:** `denominator_stated`. `extract_spans.py` fetches each article and
stores the verbatim sentence around every figure with a character offset into the stored text.
`--verify` re-asserts every span as an exact substring, so a label built on spans is auditable
without reading the article or trusting the script. `label_items.py` then answers what the
spans settle deterministically and asks a local model over Ollama only for the rest. The local
model receives every extracted figure sentence. Batches are packed by prompt size, not by a
fixed span count. An item above the prompt budget fails closed as unassessed rather than being
sampled.

The extractor prefers an `<article>` element over an outer `<main>`, trims known recommendation
and comment tails from legacy cache records, removes repeated renders of the same sentence, and
removes an exact figure sentence that appears under more than one article URL. Primary links are
eligible only when they were extracted from an article element. Main-page and document-level
link lists are withheld because they can contain recommendation or navigation links.

**Every machine denominator carries `evidence_method`, `evidence_coverage`, `label_evidence`,
`content_hash`, `evidence_hash` and `label_schema_version`.** The evidence hash covers the
article version and complete extracted span set, so an extraction-rule change invalidates a
label even when the cached article bytes are unchanged. A deterministic label and a local-model
label do not look identical.

The default local reader is `gemma4:12b` at a 32,768-token context. Override it with
`LABEL_MODEL` and `LABEL_CTX`. The older `QWEN_MODEL` and `QWEN_CTX` names remain accepted for
existing scripts. On 11 August 2026, Gemma 4 12B returned valid structured output for 6/6
single-item requests, N=6, in 9-60 seconds each. This measures output compliance and speed,
not label accuracy.

**No machine pass ever sets `reviewed = true`.** Machine provenance is visible per card, and a
machine label is never overwritten onto a human one.

### `claim_type` was retired, not fixed (2026-07-31)

It is no longer set or rendered. Two readers at full coverage over 38 items scored kappa 0.52
on headlines and 0.56 given the article opening plus the figure spans, so article context did
not rescue it, and there is no ground truth to score it against. A field that will not
stabilise is better deleted than caveated. `article_evidence.py` replaces the judgement with
four countable properties: who the article's claims are attributed to and how many of those
attributions are to a party to the claim, whether a piece describing a filing or a paper links
to one, how many extracted figures name a source in the same sentence, and a claim-relative
tier only where `stake_map.json` resolves the publisher relationship to the subject.

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

- **Source chips** labelled with publisher class and source tier. The aggregate source mix is
  shown once under Method and limits.
- **denominator_stated**, Y / partial / N / n-a / unassessed, with method and complete-span
  coverage.
- **Entity**, with the route that resolved it, or blank.
- **Citation chain**, whether the article links to the primary document it describes. The
  label is "cites", never "restates": absence of a link is not evidence that reporting is
  second-hand.
- **Research-context links**, typed as portfolio syntheses or article-linked primaries. Topics may be
  plural and require headline or publisher-tag evidence. Article spans can strengthen a topic
  but cannot create one alone. An automatic portfolio anchor also requires headline evidence
  and appears only when one topic clears its threshold without a tie. ArXiv, DOI and official
  links found in a verified article element are shown as links to inspect, not as automatic
  support for the headline.

## Model releases

Models that reached OpenRouter or the Hugging Face API in the last 60 days.

Each row says whether the weights are published. This is an attribute of the release, not a
grade. An API-only model is shipped, it is serving traffic and people are paying for it, it is
simply not downloadable. Whether it can be hashed and re-run later is an auditability question
and belongs in the companion Model Dependency work, not in a list of what came out.

**The open and API-only totals are not a ratio and are not presented as one.** OpenRouter is
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

The public board takes BROAD AI news (RSS). It does not run through any personal interest
watchlist: a topic watchlist is the right tool for private lead-hunting, but on a public page
it would bias which AI news appears. What it does reuse is a local source-ratings file, which
rates *who a source is* rather than the topic, so it is neutral. Source class and track record (trusted or caution from `sources.md`) remain
separate, so past accuracy is not confused with publisher type.
`watch_routine.py` is left untouched; `apply_ratings.py` is a separate read-only adapter over
`sources.md`.

Feeds are mixed by source type on purpose. Primary and regulatory sources (Federal Register,
FTC, SEC, CMA, Ofgem, NIST) sit alongside trade press and vendor newsrooms, because a board
that classifies sources and then carries only trade press does not span its own registry.
Staleness cutoffs are per source type: 30 days for news, 120 for independent
sources, 180 for primary ones. A flat 30-day cutoff deletes the regulator feeds on day one.

## Tier registries

Source tier classifies the publisher domain: 1 primary record, 2 research or academic source,
3 trade press, aggregator or unclassified publisher, 4 tool or data vendor, and 5 vendor
publication or press office. It is not a trust score. A separate claim tier is emitted only
when a recorded publisher or owner relationship to the subject resolves.

`tier_map.json` records every tier with its basis, and every cell is contestable.

## What is decided by hand, and what is not

Automatable: the feed pull, source type and source tier from the URL, entity resolution against
a registry, the denominator where quoted spans settle it, topic candidates, unique automatic
anchor selection, archive capture and layout.

Not automatable, and not automated: whether an announcement was delivered, whether an item has
been reviewed, and which private register rows may be published.

## Honest ceilings

- `stake_map.json` needs curating. An unlisted publisher relationship has no numeric claim
  tier. Source class remains available as a separate field.
- Portfolio anchors cover only registered topics. Article-linked primaries widen the checkable
  source set, but the presence of a link does not establish support for the headline.
- Feed selection is editorial and disclosed. This is a curated digest, not a real-time
  firehose.
- Span precision is unmeasured. Long documents dominate the span counts, and in those the
  numbers are often legal citations or benchmark rows rather than claims.
- It surfaces the structural weakness of a claim; it does not adjudicate truth.

## Conflict of interest

The maker is an independent researcher. An Anthropic model helped build the original method and
tiers. An OpenAI model implemented the current source-class split, label provenance and anchor
rules. OpenAI is a subject on the board, so this work is a direct conflict and is not an
independent check of OpenAI-related output. Anthropic and OpenAI remain subjects under the same
published registries. Independent analysis, not investment advice.
