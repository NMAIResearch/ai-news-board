#!/usr/bin/env bash
# sovereign_watch_schedule.sh - Automated Daily 06:00 AM Scheduler for Sovereign Watch
#
# Schedule:
#   05:55 AM -> Sends 5-minute GPU pre-warning desktop notification (prevents VRAM contention)
#   06:00 AM -> Executes Sovereign Watch pass with Qwen 3.8 (27B) via Ollama
#
# Usage:
#   ./sovereign_watch_schedule.sh pre_warn     # Trigger 5m warning notification
#   ./sovereign_watch_schedule.sh run_sweep    # Trigger 06:00 AM Qwen sweep
#   ./sovereign_watch_schedule.sh install_cron # Register in user crontab
#   ./sovereign_watch_schedule.sh remove_cron  # Unregister from user crontab
#   ./sovereign_watch_schedule.sh status       # Check current crontab and status

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$DIR/logs"
mkdir -p "$LOG_DIR"

export DISPLAY="${DISPLAY:-:0}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}"

case "${1:-status}" in
  pre_warn)
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚡ Triggering 05:55 AM GPU Pre-Warning..." >> "$LOG_DIR/schedule.log"
    python3 "$DIR/sovereign_watch.py" --pre-warn >> "$LOG_DIR/schedule.log" 2>&1 || true
    ;;

  run_sweep)
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🚀 Starting scheduled 06:00 AM Sovereign Watch pass (Qwen 3.8)..." >> "$LOG_DIR/schedule.log"
    python3 "$DIR/sovereign_watch.py" --sweep --model "qwen3.8:latest" >> "$LOG_DIR/schedule.log" 2>&1
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✓ Scheduled pass completed." >> "$LOG_DIR/schedule.log"
    ;;

  install_cron)
    CURRENT_CRON=$(crontab -l 2>/dev/null || true)
    FILTERED_CRON=$(echo "$CURRENT_CRON" | grep -v "sovereign_watch_schedule.sh" || true)

    NEW_CRON=$(cat <<EOF
$FILTERED_CRON
# Sovereign Watch Daily 06:00 AM Sweep (with 05:55 AM GPU VRAM Pre-Warning)
55 5 * * * /bin/bash "$DIR/sovereign_watch_schedule.sh" pre_warn
0 6 * * * /bin/bash "$DIR/sovereign_watch_schedule.sh" run_sweep
EOF
)
    echo "$NEW_CRON" | crontab -
    echo "✓ Crontab successfully installed:"
    echo "  - 05:55 AM: Desktop Warning (5 min GPU notice)"
    echo "  - 06:00 AM: Sovereign Watch Qwen 3.8 Sweep"
    ;;

  remove_cron)
    CURRENT_CRON=$(crontab -l 2>/dev/null || true)
    echo "$CURRENT_CRON" | grep -v "sovereign_watch_schedule.sh" | crontab - || true
    echo "✓ Sovereign Watch schedule removed from crontab."
    ;;

  status)
    echo "=== Sovereign Watch Daily Schedule Status ==="
    python3 "$DIR/sovereign_watch.py" --status
    echo ""
    echo "Crontab Entries:"
    crontab -l 2>/dev/null | grep "sovereign_watch" || echo "  (No active crontab entry found. Run './sovereign_watch_schedule.sh install_cron' to activate)"
    ;;

  *)
    echo "Usage: $0 {pre_warn|run_sweep|install_cron|remove_cron|status}"
    exit 1
    ;;
esac
