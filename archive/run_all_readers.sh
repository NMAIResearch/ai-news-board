#!/usr/bin/env bash
# ⛔ ALL READERS IN ONE INVOCATION. autolabel_crosscheck.py REPLACES the crosscheck field on
# every run, it does not accumulate, so separate invocations per model silently discard every
# earlier reader (caught 2026-07-30: three passes ran, only the last survived). Batching inside
# label_pass is what makes one combined invocation safe.
set -uo pipefail
cd "$(dirname "$0")"
printf '\n== all 4 readers, chunked == %s\n' "$(date +%H:%M:%S)"
python3 -u autolabel_crosscheck.py || echo "  ! pass failed"
printf '\n== persist == %s\n' "$(date +%H:%M:%S)"
python3 -u carry_reviews.py || echo "  ! carry_reviews FAILED"
printf '\n== build == %s\n' "$(date +%H:%M:%S)"
python3 -u build.py
printf '\n== report == %s\n' "$(date +%H:%M:%S)"
python3 -u autolabel_crosscheck.py --report || true
for m in gemma3:27b mistral-small:24b glm-4.7-flash:q4_K_M qwen3.6:35b; do
  curl -s --max-time 10 http://localhost:11434/api/generate -d "{\"model\":\"$m\",\"keep_alive\":0}" >/dev/null 2>&1
done
echo; echo "DONE. Nothing committed or pushed."
