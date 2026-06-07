# Configuration reference

Config is a single TOML file, found in this order: `--config PATH`, the
`TRELLO_HUB_CONFIG` env var, then `~/.config/trello-hub-sync/config.toml`. Start
from [`config.example.toml`](../config.example.toml).

Fill the IDs with `trello-sync discover` (see [README](../README.md#quick-start)).

## `[trello]`

| key | required | notes |
|---|---|---|
| `api_key` | ✅* | from <https://trello.com/power-ups/admin> |
| `token` | ✅* | a token you generate for your account |
| `api_key_file` / `token_file` | — | read the secret from a file instead (takes precedence) |
| `api_secret` / `api_secret_file` | — | only for the real-time receiver's HMAC verification |

\* either inline or via `_file`.

## `[hub]`

| key | required | notes |
|---|---|---|
| `board_id` | ✅ | your personal hub board |
| `member_id` | ✅ | the ownership signal — cards you're a member of get mirrored |
| `dev_list_id` | — | enable the "Dev column home" (needs `dev_label_id` too) |
| `dev_label_id` | — | a card with a label named `DEV` is treated as in-development |

## `[[sources]]` (one per team board)

| key | required | notes |
|---|---|---|
| `board_id` | ✅ | the shared/team board to aggregate from |
| `name` | ✅ | a friendly label used in logs and on the mirror |
| `origin_label_id` | — | a hub-board label id to tag every mirror from this board |

## `[behavior]`

| key | default | notes |
|---|---|---|
| `exclude_label_substring` | `"initiative"` | skip cards whose label name contains this; empty = mirror all |
| `attach_max_bytes` | `26214400` | re-upload files up to this size; `0` = links only |
| `downstream_statuses` | `["qa","discussion","hold","done"]` | statuses that release the Dev-column pin |
| `marker` | `"trello-hub-sync"` | description marker tag; change only on a fresh setup |

## `[paths]`

| key | default |
|---|---|
| `state_db` | `~/.local/state/trello-hub-sync/state.db` |
| `lock` | `~/.local/state/trello-hub-sync/sync.lock` |
| `log` | `~/.local/state/trello-hub-sync/sync.log` |

## `[comments]`

| key | default | notes |
|---|---|---|
| `direction` | `"both"` | `both` \| `source_to_daily` \| `daily_to_source` \| `off` |

## `[receiver]` (optional, real-time)

| key | default | notes |
|---|---|---|
| `port` | `18811` | localhost port the receiver binds |
| `path` | — | secret URL path; treat like a password (`openssl rand -hex 16`) |
| `public_url` | — | the HTTPS URL your proxy/tunnel forwards to `port`+`path` |
