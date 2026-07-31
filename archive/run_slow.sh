#!/usr/bin/env bash
# Chunked pass for the two reasoning readers. Batched via label_pass (BATCH=6), so a batch
# that overruns costs that batch only. Stops at build; nothing is committed or pushed.
set -uo pipefail
cd "$(dirname "$0")"
step() { printf '\n== %s == %s\n' "$1" "$(date +%H:%M:%S)"; }

step "1/4 glm-4.7-flash (chunked)"
python3 autolabel_crosscheck.py --models glm-4.7-flash:q4_K_M || echo "  ! glm pass failed"

step "2/4 qwen3.6:35b (chunked)"
python3 autolabel_crosscheck.py --models qwen3.6:35b || echo "  ! qwen3.6:35b pass failed"

step "3/4 persist"
python3 carry_reviews.py || echo "  ! carry_reviews FAILED"

step "4/4 build"
python3 build.py

step "report"
python3 autolabel_crosscheck.py --report || true

for m in glm-4.7-flash:q4_K_M qwen3.6:35b; do
  curl -s --max-time 10 http://localhost:11434/api/generate -d "{\"model\":\"$m\",\"keep_alive\":0}" >/dev/null 2>&1
done
echo; echo "DONE. Nothing committed or pushed."
