#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Example watchdog for the optional real-time receiver. ADAPT THIS to your host.
#
# It keeps the pipeline healthy and self-heals the common failures:
#   1. receiver systemd service is active        -> restart it
#   2. local endpoint answers HTTP 200           -> restart receiver
#   3. public endpoint answers HTTP 200          -> run $TUNNEL_RESTART_CMD (optional)
#   4. poll timer is active                       -> start it
#   5. all Trello webhooks exist & are active     -> `trello-sync webhooks --repair`
#
# Everything host-specific is a variable/hook — no vendor is hard-coded. Run it
# every ~5 min from a timer/cron. Set ALERT_CMD to get notified (Telegram, ntfy,
# email, …); it is called as:  "$ALERT_CMD" "<message>".
# -----------------------------------------------------------------------------
set -uo pipefail

RECEIVER_SVC="${RECEIVER_SVC:-trello-sync-receiver.service}"
POLL_TIMER="${POLL_TIMER:-trello-sync.timer}"
LOCAL_URL="${LOCAL_URL:-http://127.0.0.1:18811/trello-hook/CHANGE_ME}"
PUBLIC_URL="${PUBLIC_URL:-}"                 # your [receiver].public_url, optional
TUNNEL_RESTART_CMD="${TUNNEL_RESTART_CMD:-}" # e.g. "systemctl --user restart cloudflared.service"
ALERT_CMD="${ALERT_CMD:-}"                   # e.g. "/path/to/notify.sh"

issues=()
code() { curl -s -o /dev/null -w '%{http_code}' -I "$1" --max-time "${2:-10}" 2>/dev/null; }
alert() { [[ -n "$ALERT_CMD" ]] && "$ALERT_CMD" "$1" >/dev/null 2>&1 || true; }

# 1 + 2. receiver service + local endpoint
if ! systemctl --user is-active --quiet "$RECEIVER_SVC"; then
  issues+=("receiver inactive"); systemctl --user restart "$RECEIVER_SVC" 2>/dev/null; sleep 2
fi
if [[ "$(code "$LOCAL_URL" 8)" != "200" ]]; then
  issues+=("local endpoint down"); systemctl --user restart "$RECEIVER_SVC" 2>/dev/null; sleep 2
fi

# 3. public endpoint (tunnel/reverse proxy)
if [[ -n "$PUBLIC_URL" && "$(code "$PUBLIC_URL" 12)" != "200" ]]; then
  issues+=("public endpoint down")
  [[ -n "$TUNNEL_RESTART_CMD" ]] && eval "$TUNNEL_RESTART_CMD" >/dev/null 2>&1
fi

# 4. poll timer
systemctl --user is-active --quiet "$POLL_TIMER" || { issues+=("poll timer inactive"); systemctl --user start "$POLL_TIMER" 2>/dev/null; }

# 5. webhooks (portable, API-only)
trello-sync webhooks --repair >/dev/null 2>&1 || issues+=("webhook repair failed")

if (( ${#issues[@]} )); then
  alert "🚨 trello-hub-sync watchdog: ${issues[*]}"
  printf 'watchdog: issues: %s\n' "${issues[*]}" >&2
fi
