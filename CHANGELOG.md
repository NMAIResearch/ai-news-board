# Changelog

Dated, descriptive, newest first. Method changes and defects found, not every commit.

## 2026-08-08

**Defect: modification and submission times were displayed as article dates.** The vendor
intake treated sitemap `<lastmod>` as a publication date. OpenAI marked three pages as
modified on 8 August even though the pages were published on 12 February, 5 March and
25 March. All three were consequently presented as current. The vendor intake now fetches
the publication date from each candidate page, caches it, and uses it for ranking, the
freshness cutoff and display. Sitemap modification times are used only to discover unseen
pages worth checking. The Hacker News intake now makes the same distinction: its `pubDate`
is the link's submission time, so the linked page's own publication date is used when the
page exposes one.

## 2026-08-07

**Defect: headlines printed their own HTML entities.** The board showed
`Jony Ive&#8217;s first OpenAI gadget` and `Announcing the &quot;AI Agent Standards
Initiative&quot;`. Publishers escape titles in the feed body, so an apostrophe arrives as
`&#8217;`; `build.py` then runs `html.escape` over every rendered field, turning that leading
`&` into `&amp;` and printing the entity verbatim. Escaping is right, escaping something
already escaped is the bug. Fixed at intake in `fetch_feeds.py` (`clean_title`, one
`html.unescape` on the RSS and Atom paths) rather than in `esc()`, because `esc()` touches
every string on the page and unescaping there would corrupt text meant to show an entity
literally. `fetch_vendor_news.py` had done this correctly since it was written, so only the
RSS path was wrong and the two intake paths now agree. 11 stored headlines were migrated
across `feed_items.json`, `archive.json` and `article_evidence.json`. ⛔ `article_spans.json`
and `article_text.json` were deliberately NOT touched: spans carry character offsets into the
cached article and must stay byte-exact. `extract_spans.py --verify` re-run after the
migration: 687 spans, 0 mismatched.

**Defect: the feed grid left dead space between tiles.** `.feedgrid` carried
`align-items:start`, and a CSS grid places items row by row, so whenever two cards in a row
differed in height the shorter one ended early and left a hole until the next row began. With
one column often carrying long "possible anchor" blocks and the other not, this was most of
the feed. Removed `align-items:start` (stretch is the default) and gave `.feedgrid .card`
`height:calc(100% - 16px)`. Row-major reading order is unchanged, newest first, left to
right; the whitespace moves inside the shorter card. Verified against before-and-after renders
at 1900px. ⛔ True masonry packing was considered and rejected: CSS columns pack with no gaps
at all but reorder the feed column-major, which changes what "first" means on a
recency-ordered board.

**`refresh.sh` was invisible in the README, so the pipeline looked like fourteen manual
commands.** It has existed and been maintained for weeks. The `## Run` section listed the raw
steps and never mentioned it, which is how a full run gets done by hand. `## Run` now leads
with `./refresh.sh` and keeps the step list for reading or re-running a single step. The list
was also missing `suggest_register_rows.py`, which the script has always run.

**`build.py --plain` sat as the last line of the run list, and both builds write the same
`index.html`.** Following the list literally publishes the motive-tier-OFF page. Moved into
its own block with a check command. The check is `grep -c motivebar index.html` == 1 for
plain, **not 0**: the `.motivebar` CSS rule is emitted either way and only the per-item divs
are dropped.

**`refresh.sh` gained a read-only pre-flight for origin divergence.** A CI job commits market
data to origin on its own schedule, so the local branch falls behind most days and the push
after a refresh is rejected. On 2026-08-06 a complete, correct run sat unpushed at `ahead 2,
behind 4` while the live board served the 4 August feed. The pre-flight fetches and prints the
ahead/behind counts, warning before the work rather than after. It does not merge: which side
wins for `data/market.json` is a judgement, not a step in a script.

## 2026-07-31

**Releases panel states what came out, not how well it is evidenced.** The headline was
"80 in the last 60 days: 53 open weights, an artefact you can download and hash, and 27
closed, known only because the party selling it says so." It is now the count and the
window. An API-only model is shipped: it serves traffic and people pay for it, and grading it
as a lesser release answered an auditability question the panel was not asking. Whether the
weights are published stays on each row as a plain attribute in a neutral colour, reading
"API only" rather than "closed".

**The open against API-only split was never comparable.** OpenRouter is taken in full;
Hugging Face is a hand-written list of labs capped at five repositories each, four of which
sat on the cap. OpenRouter rows dedupe to a base model, Hugging Face rows do not. The split
is no longer summarised as a ratio.

**Defect: two moving pointers were counted as releases.** `~x-ai/grok-latest` and
`~anthropic/claude-fable-latest` carry the date the alias was made, and each duplicated a
versioned row hours away (grok-latest 14:02 against grok-4.5 15:05 on 2026-07-08;
claude-fable-latest 18:32 against claude-fable-5 12:18 on 2026-06-09). Excluded by an alias
rule. Closed count 27 to 25.

**Trap recorded in the code, not just here:** `canonical_slug != id` looks like a second
alias test and empties the list. All 41 in-window OpenRouter rows have a dated canonical slug
behind an undated public id.

**Headline-only labelling closed.** `extract_spans.py` fetches each article and stores the
verbatim sentence around every figure with a character offset; `--verify` re-asserts each
span as an exact substring. `label_items.py` answers what the spans settle (tier 1) and asks
a local model only for the rest (tier 3). Every label carries `label_tier` and
`label_evidence`. First full run: 38 of 38 articles, 482 spans, all verified.

**RSS `<description>` falsified as a figure source.** Of 35 items carrying one, exactly 1
gained a figure its headline lacked. Kept only as a fallback when an article fetch fails.

**`claim_type` retired rather than fixed.** Two readers at full coverage over 38 items scored
kappa 0.52 on headlines and 0.56 given the article opening plus figure spans, and there is no
ground truth to score against. `article_evidence.py` replaces the judgement with countable
properties: attribution, primary links, figure sourcing, claim-relative motive tier.

**`resolve_entity.py`** replaces a model fill that fabricated "None", "Researchers", "AI
startups" and "x.com". Deterministic against `org_registry.json`, or blank.

**`robots.txt` was fetched with urllib's default agent**, which nist.gov blocks. On 401 or
403 the parser refuses every URL while holding zero rules, and it had silently excluded six
NIST articles, the tier-1 class the board was short of. Now fetched with the same agent as
the request. The fetch cache also reuses successes only, so a transient block cannot outlive
its fix.

**Docs realigned to the deployed board** (README and script docstrings): retired fields
marked as dead rather than described as live, the run order corrected to the full pipeline.

**Reader cross-check retired to `archive/`.** `autolabel.py`, `autolabel_crosscheck.py` and
the three runner scripts were built to read headlines, and two of the cross-check's three
fields no longer exist: `claim_type` is retired and the denominator now comes from quoted
spans, which is checkable rather than voted on. The chip is removed from `build.py` and the
stored disagreement is stripped from 19 items in `feed_items.json` and 38 in
`reviews_store.json`, so nothing renders a reading that nothing can regenerate. Provenance
travels on the label instead, as `label_tier` and `label_evidence`.

**`refresh.sh` was running the retired labeller and skipping the span ladder entirely.** It
listed 7 steps against a 12-step pipeline: no vendor newsrooms, no spans, no entity
resolution, no article evidence, no releases and no archive. Rewritten to the real order,
with the reason each step sits where it does.

**Registers extended.** Deflation register 14 rows to 16: OpenAI's "lost $38.5B in 2025"
(operating loss $20.9B; the headline carries a $41.55B non-cash charge from the nonprofit to
for-profit conversion) and Pangram's "1-in-10,000 false-positive rate". The second corrects a
skew in the register itself: 11 of the previous 14 rows deflated tier-4 press and creator
claims, while the board's thesis is that incentive concentrates at tier 5, the party selling
the thing. Resolution calendar 5 rows to 7: the ASML lithography controls expiring 10 November
and the PJM 2030/31 capacity auction in December.

**Reality anchors: 6 of 76 to 32 of 76, and two mistakes made getting there.**
`publisher_tags` was never broken. `extract_spans.py` harvested it into `article_text.json`,
which is gitignored, and never copied it to `article_spans.json`. Anything living only in a
gitignored file is invisible to a clean clone. Backfilled from the local cache, no refetch.
Three topics the portfolio already covered were then wired: models to The Model Is a
Dependency, chips to the Barbell.

⛔ WITHDRAWN: the commit for that work says "anchored 38 of 76". The measured figure is 32.
The number was written before the script printed it.

Two errors worth keeping in view. A failed build was committed because `build.py` was piped
into `tail`, and a pipeline reports the exit status of its last command, so a raised exception
looked like success; `refresh.sh` now aborts on a failed build. And the `agents` topic was
anchored to the shopping-agent paper, which mapped an MIT robotics award to a retail-commerce
finding, because the topic keywords catch embodied AI. Anchor removed. Narrow the topic before
anchoring it, not the other way round.

**The market strip stamped one date over four vintages.** Brent read 27 July, the US indices
30 July, the Nikkei and 29 of 34 equities 31 July, and the footer said "indices close
2026-07-30" because it took the S&P's date and applied it to everything. A four-day-old oil
price was displaying under a date that was not its own, which is the vintage error this board
flags in other people's work. The label-to-value pairing was never wrong; the date was.

Now the freshest value sets the reference, each cell carries its own date, and a cell behind
the reference is marked in visible text. Eight cells currently carry one. The footer also says
what each percentage is measured over, since a gap in a source series makes the window longer
than a day. Rule written up in PIPELINE.md.

**Hormuz gauge updated, and it now records a call that did not hold.** It read "Brent crossed
$100 on 23 July, the tell is whether it holds above $100". It did not: $105.32 on 23 July,
$100.31 on 24 July, $91.82 by 27 July, from a low of $68.53 on 2 July. Roughly $37 up and $13
back inside four weeks. All figures from FRED DCOILBRENTEU, the same series the market strip
reads, so the gauge and the strip can no longer disagree. Goldman's above-$120 case required
Hormuz disruption to persist, which on this path it has not.

**Hyperscaler capex row extended rather than closed**, from late July to late October. The Q2
read confirmed acceleration, so the crack the row watches for has not fired and the question
is still open. Extending changes the row id, so the hand-written public copy was rewritten
under the new id rather than silently lost.

**The deflation register implied an attribution it did not have.** Measured over the 16
published rows, 13 had a claim side that read like a citation and was not one: "YouTube
AI-finance video [4]", "grid-doom framing [4]", "press/aggregator [4]". A reader could not
check that anyone said it, on a board that flags exactly that failure in others, and whose
own ResearchGate row calls it institutional-name laundering.

Fixed by changing what the column claims rather than by naming creators. The claim line now
reads "circulating via" and the panel states the rule: the register grades the number, not
the person, so a figure taken from video or press is described by genre and motive tier, and
the checkable weight sits on the corrected line. Naming individual channels would turn a
register of numbers into a list of people being corrected.

`make_registers.py` gains a publication gate on the corrected side, since that is now where
all the weight sits. It blocks a row with no corrected reading or no stated error, which is
deterministic, and warns where no institution is named anywhere in the row, which is not: a
correction can rest on reasoning a reader can follow or on a fact anyone can look up. Six
rows warn, of which two want a source added.

**`PIPELINE.md`** states which store owns what. The tracker owns judgements, the board owns
intake, and neither writes to the other. Direction two, the board nominating candidate rows,
is designed there and not built.

## 2026-07-30

**Machine labels never survived a fetch.** `carry_reviews.py` harvested only items with
`reviewed=true`, which no machine pass sets, so every fetch wiped the labelling. A four-reader
cross-check over 35 items was lost this way and the board shipped with an unreviewed
denominator on every card. Fixed with `label_source` provenance; a human label is never
overwritten by a machine one.

**Labelling batched.** One all-items call timed out at 900s. The prompt was about 1,010
tokens, but reasoning models emit roughly 400 discarded thinking tokens per headline. Output
was the limit, never context, so a larger context window makes it worse.

**Tier-1 feeds added** (Federal Register, FTC, SEC, CMA, Ofgem, NIST); the board had none
before. Staleness is per source type: 30 days for news, 120 for independent, 180 for primary.
A flat 30-day cutoff deletes the regulator feeds on day one.

**`archive.py`** keeps every item ever fetched plus a ranked, capped revisit queue. Measured
over the git history of `feed_items.json`, 121 unique URLs were captured across 18 days and
each fetch replaced the last. Intake is about 6.7 items a day, so an uncapped queue was never
sustainable. The `outcome` is not automated.

**`fetch_releases.py`** replaced a hand-written closed-model list built and deleted the same
hour: it already lagged the sites that automate it.

**`claim_type` default changed from "announced" to "unclassified"** before it was retired. The
old default asserted a judgement nobody had made.

## 2026-07-25

Market strip and per-item chips (`fetch_market.py`, FRED for indices, Finnhub for equities).
Three chip states kept distinct: a ticker, "no listed security", and "listed, not covered
here". Collapsing them would misreport the gap. The free tier serves US and OTC ADR listings
only, so the reachable China names are platform and cloud companies rather than the domestic
chipmakers; presenting them as "China AI" would be a denominator error of the kind this board
flags in others.

Private-to-public boundary for the AI Watch registers: only rows marked for publication are
read, and the private columns are sliced away at read time rather than filtered later.

## 2026-07-13

Article-level human review pass over 30 of 36 items. Gov-conflict panel added.
`carry_reviews.py` persists reviews by URL so a refresh only leaves genuinely new items
unreviewed.

## 2026-07-12

First deploy. Live feed, contestable `tier_map.json`, reality anchors generalised beyond code,
`--plain` build flag, scholarship section. Tier scale reconciled to the canonical direction:
1 = least incentive to shade the claim, 5 = the party selling the thing.
