# What flows where, and what must not

Two stores exist and they refresh at different speeds. The board pulls feeds most days; the
private tracker is a hand-maintained spine that gets worked in sessions. Left alone, the fast
store fills with material the slow store never sees, and the slow store publishes judgements
the fast store cannot check.

The rule that keeps them coherent: **each store owns one thing, and neither writes to the
other.**

    a private tracker   owns JUDGEMENTS   which numbers were deflated, which questions
    (private)                             have a dated resolution, what the reading was

    the board           owns INTAKE       what was published, when, by whom, with which
    (public)                              figures, quoted verbatim with offsets

## Direction 1: tracker to board (built, 2026-07-25)

`a local generator script` reads §RC and §DR rows marked `🌐` and writes
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
