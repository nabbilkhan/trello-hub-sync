# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versioning is [SemVer](https://semver.org/).

## [1.0.0] — 2026-06-07

First public release. Production-hardened (originally developed syncing a personal
hub board against four shared executive boards).

### Added
- Membership-driven aggregation of owned cards onto a personal hub board.
- Two-way status sync across differing column schemes (canonical mapping, hub
  wins conflicts), with an optional "Dev column home".
- Two-way labels (name-matched, baseline-tracked removals).
- Description + checklist mirroring; attachment copy (file re-upload or link-only).
- Two-way comments with attribution and loop protection.
- Local SQLite state with content-hash drift detection (no description churn).
- Optional real-time webhook receiver with HMAC verification + debounce.
- `discover`, `backfill`, `webhooks`, `receiver`, `comments` subcommands.
- Zero runtime dependencies (Python standard library only).
