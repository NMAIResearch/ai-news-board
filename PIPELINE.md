# What flows where, and what must not

Two stores exist and they refresh at different speeds. The board pulls feeds most days; the
private tracker is a hand-maintained spine that gets worked in sessions. Left alone, the fast
store fills with material the slow store never sees, and the slow store publishes judgements
the fast store cannot check.

The rule that keeps them coherent: **each store owns one thing, and neither writes to the
other.**

    a private tracker   owns JUDGEMENTS   which numbers were deflated, which questions
    (local, not here)                     have a dated resolution, what the reading was

    the board           owns INTAKE       what was published, when, by whom, with which
    (public)                              figures, quoted verbatim with offsets

Source class can cross into a Research Protocol intake record only as `source_class_tier` metadata.
It cannot accept, reject or prioritise a claim. The executable source is `tier_map.json` under
`source_types`; claim relationship, reliability rating, evidence coverage, primary-link status
and review status remain separate.

## Public harness landscape

`harnesses.json` is a versioned directory of source types, not a copied league table and not a
read from a private working tree. OpenLabor carries a channel-specific usage ranking. HarnessMatch
keeps eight usage channels, documented capabilities and evidence separate. Best of Agent
Harnesses is a curated discovery catalogue. HarnessRank supplies a controlled-comparison method
but had no full result rows on the checked date.

The board does not add usage, popularity, capability and benchmark results into one score.
Qihoo360 Harness-Bench and Harbor remain method references rather than ranking authorities. The
earlier PLAG IN client order is a compact project note pinned to its public evidence commit.
`board_checks.py` rejects missing source coverage, duplicate source types, missing boundaries,
board-authored ranks and an unpinned project note.

## Direction 1: tracker to board (built, 2026-07-25)

A local generator script reads the tracker rows marked `🌐` and writes
`registers.json`. Fail-closed: unmarked rows never publish. The §RC parser slices each row to
its first two columns at read time, so the private columns are never bound to a variable.

⛔ It generates. You review, you commit. It never touches git and never edits the tracker.

⚠️ The public `settles` and `matters` fields are hand-written and carried forward by row id.
When you write them, you are moving material across the boundary by hand. Check that what you
write is a public fact rather than a private read of one.

## Direction 2: board to tracker (BUILT 2026-07-31, `suggest_register_rows.py`)

The board must never write a tracker row, because a tracker row is a judgement. What it can
do is **nominate candidates** into a dated file that you read and act on, or ignore.

Screening rules, all of which reuse labels the board already carries:

    §DR candidate    a figure span + source tier 4 or 5 + denominator_stated = N
                     (a quantitative claim from a party with an incentive, with no
                     stated base). Emit the verbatim span, the URL, the tier.

    §RC candidate    a span containing a future date, or an item whose text names a
                     scheduled event (expiry, deadline, auction, hearing, effective date).
                     Emit the date, the span, the URL.

Output is a markdown list written to `register_candidates_<date>.md` in this folder. It is
not `registers.json` and it is not the tracker. Nothing published, nothing decided.

⛔ **The §RC screen reads `article_text.json`, not the spans, and that is structural.** Spans
are sentences containing a figure, and `extract_spans.py` filters dates out of its figure set
because most digits in an article are dates and version numbers. A sentence like "the
consultation closes on 16 September" carries no other number, so it never becomes a span.
Measured over the whole span store on 2026-07-31: 46 spans matched a date pattern, 2 held a
scheduled-event word, and 0 held both. The text cache is gitignored, so this half only runs
on a machine that has fetched articles; when the cache is absent the screen says it skipped.

⚠️ First run: 19 deflation candidates, 1 calendar candidate. The calendar hit arrived wrapped
in page furniture, because the sentence splitter runs over raw cached text. Read it as a
pointer to the article, not as copy.

⛔ Do not have the board suggest the CORRECTED figure for a §DR row. The deflation is the
call, and a model proposing both the error and its correction is the cascade trap: it would
launder a guess through a format that looks audited.

## The refresh rule: no cell displays under a date it does not have

Four things refresh on different clocks: the market Action twice a weekday, the feed when it
is run, the registers when they are regenerated, the page when it is built. Anything that
prints one timestamp over several of them will be wrong.

The rule, applied to the market strip on 2026-07-31 and the pattern for anything similar:

1. The **freshest** value in the payload sets the reference date, not the first one, and not a
   nominated series.
2. Every cell carries **its own** date, and a cell behind the reference is marked in visible
   text, not only in a tooltip.
3. A percentage states the window it covers. A gap in a source series makes the move longer
   than a day, and calling it a daily change would be wrong.

⛔ Do not flatten the spread by showing only the oldest date or hiding the stale cells. The
spread is real and per-source: FRED runs a trading day behind by design, Finnhub is live, and
a market closed on a day has no later price. Reporting the spread is correct.

## What must not flow, in either direction

- The interest watchlist. Public intake stays broad, or the board is a personal feed with a
  method attached.
- Unmarked register rows, by construction rather than by care.
- Outcomes into the calendar. §RC's own note holds: the observable is the point, not the
  result. A row past its date retires; it does not acquire a verdict from a script.

## Known gaps

- A published row whose date has passed still renders. Retiring is manual: remove the `🌐`.
- Month-precision dates default to the 1st. `late-` and `end-` map to the last day, `mid-` to
  the 15th. A bare "Dec 2026" therefore reads as 1 December, which is early for anything that
  happens later in the month.

## Unattended public refresh boundary

`daily_publish.py` may automate intake, extraction, deterministic labels, local-model labels,
entity resolution, source relationships, article-linked primary-source extraction, market data,
model releases, the archive and the static build. It does not run a general paper or dataset
search. Each machine output remains visibly unreviewed.

It may also publish Sovereign Watch classifications as unverified machine candidates. Source
queue priority controls processing order only. Evaluated substantive priority, evaluation method,
model identity, human review state and legacy raw priority are separate schema-versioned fields.
A failed or malformed evaluation is explicit unassessed data and cannot inherit P1 or P2 from the
source queue. Notifications require an evaluated local-model P1 or P2, a named model and the
duty-shift predicate. Legacy rows with missing provenance remain unassessed while preserving their
raw historical priority.

The retired N = 20 model comparison recorded Qwen agreement on 19 of 20 records, equal to the
always-no baseline of 19 of 20, N = 20. Positive recall was 0 accepted positives out of 1
comparator-positive record, N = 1 positive. The files remain recoverable from Git history and
contain model outputs but no independently reviewed gold labels. These figures do not support a
precision claim or autonomous legal review.

The unattended route must stop on a dirty non-generated path, stale inherited output,
upstream divergence, a failed refresh stage, malformed data, a failed unit test, a diff-check
failure, a rejected commit or a rejected push. It never writes a tracker row, changes a
review status, resolves a legal call, merges, rebases or force-pushes.

Sovereign bulletins, the JSONL event stream and the schedule log are local runtime evidence. They
are ignored by Git and cannot enter the unattended publication allowlist. Local jurisdiction-pack
changes are hashed and notified locally, but their paths and contents do not enter the public
regulatory alert bank.
