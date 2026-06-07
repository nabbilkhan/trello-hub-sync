"""Canonical status mapping.

Different boards use different column names ("Requires QA ☑️", "QA / Test", "Done
🎉" …). Both the hub board and every source board reduce to one shared, canonical
status so a move on one side maps cleanly to a column on the other.

Canonical statuses: backlog, sprint, in_progress, qa, discussion, hold, done, dev.
Hub-only columns with no shared meaning (e.g. "Resources") reduce to ``park`` and
are left untouched (never pushed to a source board).
"""
from __future__ import annotations

SHARED = {"backlog", "sprint", "in_progress", "qa", "discussion", "hold", "done"}


def canon(name: str) -> str:
    s = (name or "").lower()
    if "done" in s: return "done"
    if "qa" in s: return "qa"
    if "discussion" in s: return "discussion"
    if "awaiting" in s: return "awaiting"
    if "hold" in s: return "hold"
    if "in progress" in s: return "in_progress"
    if "to do today" in s: return "sprint"
    if "sprint" in s: return "sprint"
    if "intake" in s: return "intake"
    if s == "dev": return "dev"
    if "backlog" in s: return "backlog"
    return "other"


def norm(c: str) -> str:
    if c == "awaiting": return "hold"
    if c in ("intake", "other"): return "backlog"
    return c


def source_status(name: str) -> str:
    """Status of a column on a *source* board."""
    return norm(canon(name))


def hub_status(name: str) -> str:
    """Status of a column on the *hub* board (unmapped custom columns -> park)."""
    c = canon(name)
    if c == "awaiting":
        return "hold"
    if c in SHARED:
        return c
    if c == "dev":
        return "dev"
    return "park"
