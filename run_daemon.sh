#!/usr/bin/env bash
# run_daemon.sh - Detached background runner for L8 Autonomous AI Surveillance Daemon
# Survives terminal closes and system sleep via systemd-inhibit or tmux.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION="ai_surveillance"

usage() {
  echo "Usage: $0 {start|stop|status|attach|sweep|alerts}"
  echo "  start   - Launch surveillance daemon in a detached tmux session (interval: 1800s)"
  echo "  stop    - Terminate background surveillance daemon"
  echo "  status  - Print current surveillance health and latest banked alerts"
  echo "  attach  - Attach terminal directly to live daemon logs"
  echo "  sweep   - Execute single immediate pass across all gazettes and 29 jurisdiction packs"
  echo "  alerts  - Display recent high-priority alerts"
  exit 1
}

case "${1:-}" in
  start)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "Surveillance daemon is already running in tmux session: $SESSION"
      exit 0
    fi
    echo "Starting detached L8 AI Surveillance Daemon..."
    tmux new-session -d -s "$SESSION" "cd '$DIR' && python3 ai_surveillance_daemon.py --daemon --interval 1800"
    echo "Daemon active in tmux session: $SESSION. Use '$0 attach' to monitor live logs."
    ;;
  stop)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      tmux kill-session -t "$SESSION"
      echo "Surveillance daemon session '$SESSION' terminated."
    else
      echo "No active surveillance daemon session found."
    fi
    ;;
  status)
    cd "$DIR" && python3 ai_surveillance_daemon.py --status
    ;;
  attach)
    tmux attach-session -t "$SESSION"
    ;;
  sweep)
    cd "$DIR" && python3 ai_surveillance_daemon.py --once
    ;;
  alerts)
    cd "$DIR" && python3 ai_surveillance_daemon.py --alerts
    ;;
  *)
    usage
    ;;
esac
