# Security

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Email the maintainer
(see the GitHub profile) with details and steps to reproduce. You'll get an
acknowledgement, and a fix or mitigation will be coordinated before disclosure.

## Security model

- **Credentials.** Your Trello API key, token, and (optional) webhook secret are
  the only secrets. Keep them in files (`*_file` config keys) with `chmod 600`,
  not in shared config. The token grants full access to your Trello account —
  treat it accordingly and rotate it from <https://trello.com/power-ups/admin> if
  exposed.
- **Webhook receiver.** Binds to `127.0.0.1` only. The URL path is a shared
  secret, and Trello's HMAC signature is verified when `api_secret` + `public_url`
  are set. You control how (and whether) it's exposed to the internet.
- **No third parties.** The only outbound network calls are to `api.trello.com`.
  No telemetry, no analytics, no card data leaves your machine.
- **Least surprise.** The engine only moves card lists, adds/removes labels, edits
  mirror descriptions, copies attachments, and posts comments — all reversible.
  Use `--dry-run` to preview.

## Hardening tips

- Run under a dedicated user / systemd user session.
- Prefer `*_file` secrets over inline values in `config.toml`.
- If you don't need real-time, skip the receiver entirely and rely on the poll
  timer — there's then no inbound surface at all.
