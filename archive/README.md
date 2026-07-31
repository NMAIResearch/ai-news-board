# Archive

⛔ Nothing in this folder runs. It is not part of the pipeline and it is not wired into
`build.py`. Kept for the record, because the changelog refers to it.

Retired 2026-07-31, when the labelling ladder replaced headline-only reading.

| File | Replaced by | Why |
|---|---|---|
| `autolabel.py` | `label_items.py` | Sent `[entity] headline`, about 27 tokens per item, and never fetched an article. A denominator flag built on a headline reports what the headline omits, not what the claim omits. |
| `autolabel_crosscheck.py` | `label_tier` and `label_evidence` on every field | Ran several local readers over the same headline and recorded disagreement. Two of its three output fields are gone: `claim_type` is retired, and the denominator now comes from verbatim spans, which is checkable rather than voted on. |
| `run_all_readers.sh` | | Ran every cross-check reader in one invocation. |
| `run_crosscheck.sh` | | Ran two readers with a known limit: it sent all items in one call per model, which is what uncapped output overran. |
| `run_slow.sh` | | Ran the two readers that spill past 16 GB VRAM. |

**What the cross-check got right, and worth keeping if it is ever rebuilt:** a 2-1 split was
recorded as a split, never resolved to the majority, because readers from one model family
share a lineage and a shared error looks exactly like agreement.

**Measured before retirement:** two readers at full coverage over 38 items scored kappa 0.52
on headlines and 0.56 given the article opening plus the figure spans. Article context did not
rescue the field.
