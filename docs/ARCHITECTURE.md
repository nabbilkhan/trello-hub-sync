# Architecture

Trello Hub Sync is a **stateless, idempotent reconciler**. Every run fetches the
current truth from Trello, compares it to a small local state record, and applies
the minimum changes. It never trusts a webhook payload — a trigger just means
"something changed, reconcile now."

## The ownership model

The only signal is **card membership**: you (your `member_id`) are a member of a
card on a configured source board ⇒ that card is mirrored onto your hub board.
The source boards need no custom fields. Remove yourself from a card ⇒ its mirror
is archived on the next run.

## One run, step by step

1. **Read the hub board** — its lists (→ canonical statuses), its labels, and all
   existing mirrors (identified by a marker in the description).
2. **Read each source board** — lists, labels, members, and every open card you
   are a member of (with description, checklists, attachments).
3. **Exclude** cards carrying the configured "skip" label (e.g. `initiative`).
4. **Create** a mirror for each newly-owned card (skipping cards already `Done`).
5. **Status sync** — 3-way reconcile (below).
6. **Archive** mirrors whose source you no longer own.
7. **Labels** — two-way, by name, with a baseline.
8. **Content + attachments + collab title** — refresh only on change.
9. **Persist** the new state to SQLite.

A `flock` around the whole run serializes the poll timer and the webhook receiver
so they never double-act.

## Canonical status

Column names are messy and per-board. Each list name reduces to a canonical
status (see `trellohub/status.py`):

```
done | qa | discussion | hold | in_progress | sprint | dev | backlog
```

- Source boards use `source_status()` (`awaiting → hold`, `intake/other → backlog`).
- The hub board uses `hub_status()`, which additionally maps any **unmapped custom
  column** to `park` — a sticky state that's never pushed to a source board (great
  for a "Resources" or "Reference" column on your hub).

When pushing a status to a source board, if several of its lists share a canonical
status, the one whose name contains "executive" is preferred (handy for boards
that have both a personal and an executive lane); otherwise the first is used.

## Status reconciliation (3-way)

For each mirrored card the engine knows three values:

- `hs` — host (source) status, now
- `ms` — mirror (hub) status, now
- `L`  — last-synced status (from SQLite)

| condition | meaning | action |
|---|---|---|
| `hs == ms` | already in sync | record `L = ms` |
| `ms != L and hs == L` | you moved the mirror | **push** source → `ms` |
| `hs != L and ms == L` | source moved | **pull** mirror → `hs` |
| both `!= L` | both moved (conflict) | **hub wins**: push source → `ms` |

### Optional "Dev column home"

If `dev_list_id`/`dev_label_id` are set, a card that carries a `DEV` label (on
either side) is **pinned to the hub's Dev column** while its status is *upstream*
(backlog/sprint/in_progress) — so active dev work groups together no matter what
sprint column the source uses. The moment it reaches a **downstream** status
(`qa/discussion/hold/done`, configurable), the pin yields and normal two-way sync
resumes. This lets you advance a card to QA from your board without it snapping
back to Dev, and without removing the label.

## Labels (two-way, baseline-tracked)

Labels are matched **by name** (boards often have same-name labels in different
colours; matching by id would create ugly twins). A per-card **baseline** of
last-synced label names — stored in SQLite — distinguishes a deliberate removal
from a not-yet-synced label:

- on hub, not on source → add to source (and into baseline)
- on source, not on hub, **in baseline** → you removed it → remove from source
- on source, not on hub, **not in baseline** → new on source → add to hub
- on both → keep

"Mechanic" labels (the board-origin tag and the `DEV` label) are never synced, so
your team boards stay clean. The first run seeds the baseline with no removals.

## Content & attachments

The mirror description is `header + collab line + source description + rendered
checklists + marker`. Drift is detected with a **sha1 hash** of the composed
content; the description is rewritten only when that hash changes — so status and
label changes never churn the description.

Attachments are de-duplicated by `name+size` (files) or `url` (links). Files are
re-uploaded so they open on the hub card; set `attach_max_bytes = 0` to attach
links only.

## State & recovery

```
mirror(src_id PK, src_board, mirror_id, last_status, label_baseline, content_hash, updated_at)
```

The card description carries only a **stable, minimal marker**:
`trello-hub-sync:src=<card>;b=<board>`. That's enough to rebuild the entire state
DB from the boards alone — `trello-sync backfill` does exactly that. Because a
missing baseline means "additions only," a lost DB never deletes anything.
