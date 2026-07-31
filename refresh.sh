#!/usr/bin/env bash
# AI News Board - full local refresh, in the order the pipeline requires.
#
# WHY THE ORDER MATTERS, since getting it wrong silently loses work:
#   fetch_feeds       replaces the feed with a fresh pull; anything not persisted is gone
#   fetch_vendor_news appends vendor newsroom posts that publish no RSS; must follow the
#                     fetch, since the fetch overwrites the file it appends to
#   carry_reviews     re-applies prior labels by URL, so ONLY genuinely new items come back
#                     unreviewed. Must run immediately after the intake steps.
#   apply_ratings     layers the topic-agnostic track-record ratings from sources.md
#   extract_spans     fetches each article, stores the verbatim sentence around every figure
#                     with a character offset. Must precede label_items: it is the evidence
#                     label_items reads.
#   label_items       denominator from spans where they settle it, a local model for the
#                     rest. OPTIONAL. Skipped automatically if ollama is down; the
#                     deterministic tier-1 labels still land.
#   resolve_entity    who the claim is about, from the registry, or blank
#   article_evidence  attribution, primary links, figure sourcing, claim-relative tier
#   fetch_scholar     broad arXiv + HF pull for the scholarship panel
#   fetch_releases    models that reached OpenRouter or Hugging Face in the window
#   archive           permanent record + revisit queue; run before the build
#   suggest_register_rows  nominates candidate tracker rows into a dated, gitignored file.
#                     Writes nothing anyone publishes from, so it is safe to run every time.
#   fetch_market      quotes; needs keys, skipped if absent
#   build             renders index.html
#
# ⛔ It does NOT commit or push. Review the page first: a feed pull brings in unreviewed
# items, and whether those go public is a judgement call, not a step in a script.
#
# ⛔ The cross-check readers are retired (archive/). Do not add them back here.
#
# Usage:  ./refresh.sh            full refresh
#         ./refresh.sh --no-label skip the local-model pass (fast)
set -uo pipefail
cd "$(dirname "$0")"

step() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
LABEL=1
[ "${1:-}" = "--no-label" ] && LABEL=0

step "1/12 fetch feeds";      python3 fetch_feeds.py       || echo "  ! feed fetch failed, continuing with the existing feed"
step "2/12 vendor newsrooms"; python3 fetch_vendor_news.py || echo "  ! vendor news failed"
step "3/12 carry reviews";    python3 carry_reviews.py     || echo "  ! carry_reviews failed - CHECK BEFORE BUILDING, prior labels may be lost"
step "4/12 apply ratings";    python3 apply_ratings.py     || echo "  ! apply_ratings failed"
step "5/12 extract spans";    python3 extract_spans.py     || echo "  ! span extraction failed - labels will fall back to tier 3"

step "6/12 label items"
if [ "$LABEL" = "0" ]; then
  echo "  skipped (--no-label)"
elif ! curl -sf --max-time 3 http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo "  skipped: ollama is not responding on :11434"
else
  python3 label_items.py || echo "  ! label pass failed"
fi

step "7/12 resolve entity";   python3 resolve_entity.py    || echo "  ! entity resolution failed"
step "8/12 article evidence"; python3 article_evidence.py  || echo "  ! article evidence failed"
step "9/12 fetch scholar";    python3 fetch_scholar.py     || echo "  ! scholar fetch failed"
step "10/12 fetch releases";  python3 fetch_releases.py    || echo "  ! release fetch failed"
step "11/12 archive";         python3 archive.py           || echo "  ! archive failed"
step "  + candidates";        python3 suggest_register_rows.py --write >/dev/null \
                              || echo "  ! candidate scan failed"

step "12/12 fetch market"
if [ -f ~/.config/nmai/keys.env ]; then python3 fetch_market.py || echo "  ! market fetch failed"
else echo "  skipped: no ~/.config/nmai/keys.env"; fi

step "build"
# ⛔ Never pipe build.py into tail/head when chaining with &&. The pipeline's exit status is
# the LAST command's, so a build that raises still reports success and a stale index.html
# gets committed. Cost that mistake once, 2026-07-31.
python3 build.py || { echo "  ! BUILD FAILED - do not commit, index.html is stale"; exit 1; }

cat <<'EOF'

Done. Nothing has been committed.
  review:  python3 -m http.server 8123 --bind 127.0.0.1   then open http://127.0.0.1:8123
  publish: git add -A && git commit && git push
EOF
