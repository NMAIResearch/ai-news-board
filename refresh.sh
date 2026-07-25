#!/usr/bin/env bash
# AI News Board - full local refresh, in the order the pipeline requires.
#
# WHY THE ORDER MATTERS, since getting it wrong silently loses work:
#   fetch_feeds    replaces the feed with a fresh pull; anything not persisted is gone
#   carry_reviews  re-applies prior human review labels by URL, so ONLY genuinely new
#                  items come back unreviewed. Must run immediately after the fetch.
#   apply_ratings  layers the topic-agnostic track-record ratings from sources.md
#   fetch_scholar  broad arXiv + HF pull for the scholarship panel
#   autolabel      OPTIONAL local-model pass. Sets claim_type and denominator on items a
#                  human has not reviewed. It never sets reviewed=true, so the board keeps
#                  flagging them as machine-tagged. Skipped automatically if ollama is down.
#   fetch_market   quotes; needs keys, skipped if absent
#   build          renders index.html
#
# ⛔ It does NOT commit or push. Review the page first: a feed pull brings in unreviewed
# items, and whether those go public is a judgement call, not a step in a script.
#
# Usage:  ./refresh.sh            full refresh
#         ./refresh.sh --no-label skip the local-model pass (fast)
set -uo pipefail
cd "$(dirname "$0")"

step() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
LABEL=1
[ "${1:-}" = "--no-label" ] && LABEL=0

step "1/7 fetch feeds";     python3 fetch_feeds.py    || echo "  ! feed fetch failed, continuing with the existing feed"
step "2/7 carry reviews";   python3 carry_reviews.py  || echo "  ! carry_reviews failed - CHECK BEFORE BUILDING, prior labels may be lost"
step "3/7 apply ratings";   python3 apply_ratings.py  || echo "  ! apply_ratings failed"
step "4/7 fetch scholar";   python3 fetch_scholar.py  || echo "  ! scholar fetch failed"

step "5/7 auto-label"
if [ "$LABEL" = "0" ]; then
  echo "  skipped (--no-label)"
elif ! curl -sf --max-time 3 http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo "  skipped: ollama is not responding on :11434"
else
  # Two models, deliberately. They tie at ceiling on the paper's extraction task
  # (60/66 each, zero misattribution), so picking one on accuracy grounds is not
  # supported. Running both and comparing turns the pass into a disagreement finder:
  # agreement is cheap confidence, disagreement marks the genuinely ambiguous items
  # for a human eye. Same pattern as the Sina/Tencent cross-check on the quote side.
  QWEN_MODEL=qwen3.6:27b python3 autolabel.py || echo "  ! qwen pass failed"
  if [ -f autolabel_crosscheck.py ]; then
    QWEN_MODEL=gemma3:27b python3 autolabel_crosscheck.py || echo "  ! gemma cross-check failed"
  fi
fi

step "6/7 fetch market"
if [ -f ~/.config/nmai/keys.env ]; then python3 fetch_market.py || echo "  ! market fetch failed"
else echo "  skipped: no ~/.config/nmai/keys.env"; fi

step "7/7 build";           python3 build.py

cat <<'EOF'

Done. Nothing has been committed.
  review:  python3 -m http.server 8123 --bind 127.0.0.1   then open http://127.0.0.1:8123
  publish: git add -A && git commit && git push
EOF
