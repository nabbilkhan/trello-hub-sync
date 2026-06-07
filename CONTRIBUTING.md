# Contributing

Thanks for your interest! This project values **simplicity and zero dependencies** —
please keep contributions in the Python standard library.

## Dev setup

```bash
git clone https://github.com/nabbilkhan/trello-hub-sync
cd trello-hub-sync
python3 -m pip install -e .
python3 -m py_compile trellohub/*.py     # quick sanity check
```

## Before opening a PR

- Keep it stdlib-only (no new runtime dependencies).
- Run `trello-sync sync --dry-run` against a throwaway pair of boards and confirm
  intended actions are correct.
- Match the existing style; keep functions small and the reconciliation logic in
  `engine.py` readable.
- Update `README.md` / `docs/` if behavior or config changes.

## Good first issues

- Windows/macOS scheduler examples (Task Scheduler, `launchd`).
- A `--once`/exit-code summary mode for CI-style health checks.
- Configurable custom status patterns (override `status.py` mappings via config).
- Tests with a recorded Trello API fixture.

## Reporting bugs

Open an issue with: your (redacted) config shape, the `trello-sync sync --dry-run`
output, and what you expected. Never paste your API token.
