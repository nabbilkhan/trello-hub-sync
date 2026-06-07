# Real-time sync (optional)

Out of the box, the poll timer syncs every 30 minutes. For near-instant sync, run
the webhook receiver and point Trello webhooks at it. The poll timer stays on as a
safety net for anything missed while the endpoint is briefly down.

## How it works

1. The receiver listens on `127.0.0.1:<port><path>` and answers Trello's
   verification probe.
2. Trello POSTs on every board action; the receiver **debounces** a burst into a
   single sync run and verifies the HMAC signature.
3. It never trusts the payload — it just triggers `engine.run()`, which reconciles
   from the API. A forged/spurious call is at worst a no-op.

## Setup

**1. Pick a secret path and set the public URL** in your config:

```toml
[trello]
api_secret = "YOUR_API_SECRET"     # from the Power-Up admin page

[receiver]
port = 18811
path = "/trello-hook/PUT_A_RANDOM_SECRET_HERE"   # openssl rand -hex 16
public_url = "https://hooks.example.com/trello-hook/PUT_A_RANDOM_SECRET_HERE"
```

**2. Expose the local port over HTTPS.** Any of these works — the receiver only
needs `public_url` to forward to `127.0.0.1:port` + the secret path:

- a Cloudflare Tunnel (`cloudflared`),
- a `tailscale funnel`,
- an `nginx`/`caddy` reverse proxy with TLS,
- an SSH reverse tunnel to a VPS.

**3. Run the receiver:**

```bash
cp systemd/trello-sync-receiver.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now trello-sync-receiver.service
```

**4. Register the webhooks** (one per hub + source board, all pointing at
`public_url`):

```bash
trello-sync webhooks            # show current state
trello-sync webhooks --repair   # create missing / re-enable inactive
```

## Keeping it healthy

Trello disables a webhook after repeated callback failures. Re-run
`trello-sync webhooks --repair` on a timer, or use the adaptable
[`examples/watchdog.sh`](../examples/watchdog.sh) (checks the service, the local
and public endpoints, the timer, and repairs webhooks; pluggable alert + tunnel
commands, no vendor hard-coded):

```bash
# every 5 minutes via cron, with your own notifier:
ALERT_CMD=/path/to/notify.sh PUBLIC_URL="$YOUR_PUBLIC_URL" \
  LOCAL_URL="http://127.0.0.1:18811/trello-hook/YOUR_SECRET" \
  examples/watchdog.sh
```
