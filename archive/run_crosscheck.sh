#!/usr/bin/env bash
# Unattended cross-check run. Safe to start and walk away.
#
# ORDER, and why:
#   1. FAST readers first (gemma3:27b, mistral-small:24b). Neither is a reasoning model, both
#      return in minutes, and either one on its own already gives a real agreement signal
#      against the qwen3.6:27b base labels.
#   2. SLOW readers second (glm-4.7-flash, qwen3.6:35b), each in its OWN invocation. Both emit
#      discarded thinking tokens and qwen3.6:35b spills hardest on 16 GB. Separate runs mean a
#      timeout on one costs that reader only, not the whole pass.
#   3. carry_reviews to persist, then build.
#
# ⛔ IT STOPS AT BUILD. No commit, no push. Publishing is a judgement call and nobody is here
# to make it. Review index.html before anything goes public.
#
# ⚠️ KNOWN LIMIT, not fixed here: autolabel_crosscheck.py sends ALL items in ONE call per
# reader (label_pass, no batching), so a reader that overruns its 2400s timeout returns
# NOTHING for its whole pass. Splitting the invocations below limits the blast radius; it does
# not remove the flaw. The real fix is to port autolabel.py's batching into it.
#
# Run:  nohup systemd-inhibit --what=idle:sleep --why="AnchorAI cross-check" \
#         ./run_crosscheck.sh > crosscheck_$(date +%Y%m%d_%H%M).log 2>&1 &
set -uo pipefail
cd "$(dirname "$0")"

step() { printf '\n== %s == %s\n' "$1" "$(date +%H:%M:%S)"; }

if ! curl -sf --max-time 5 http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo "ABORT: ollama is not responding on :11434"; exit 1
fi

step "1/3 fast readers (gemma3:27b, mistral-small:24b)"
python3 autolabel_crosscheck.py --models gemma3:27b,mistral-small:24b \
  || echo "  ! fast pass failed; continuing"

# ⛔ [2026-07-30] glm-4.7-flash and qwen3.6:35b are DELIBERATELY NOT RUN HERE. Both are
# reasoning models, both would be sent all 38 items in one unbatched call, and the measured
# rates say that overruns or comes close to it. Running them unbatched first and then chunking
# them afterwards would burn an hour to produce nothing. They run separately, chunked, once
# autolabel_crosscheck.py has the batching that autolabel.py already has.

step "2/3 persist labels"
python3 carry_reviews.py || echo "  ! carry_reviews FAILED - check before building"

step "3/3 build"
python3 build.py

step "report"
python3 autolabel_crosscheck.py --report || true

# Free the VRAM so the machine is idle when he comes back.
for m in gemma3:27b mistral-small:24b glm-4.7-flash:q4_K_M qwen3.6:35b; do
  curl -s --max-time 10 http://localhost:11434/api/generate \
    -d "{\"model\":\"$m\",\"keep_alive\":0}" >/dev/null 2>&1
done

cat <<'EOF'

DONE. Nothing was committed or pushed.
  review:  python3 -m http.server 8123 --bind 127.0.0.1
  publish: git add -A && git commit && git push
EOF
