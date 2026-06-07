"""Bidirectional comment sync (optional).

Routes a single Trello ``commentCard`` webhook event between a source card and its
hub mirror. New comments only (no backfill/edits). Loop-safe: every mirrored
comment carries a trailing ``⟦synced:ocs=<id>⟧`` marker; comments containing it
are ignored, and we also check the counterpart's recent comments for the id.

Comments are posted via your token (Trello can't post as another user), so each is
prefixed ``💬 <author> · <origin>`` to preserve attribution.
"""
from __future__ import annotations

import json
import re

from .api import Trello, TrelloError

SYNCED = "⟦synced:"


def route(cfg, body: bytes):
    if cfg.comment_direction == "off":
        return
    try:
        action = (json.loads(body or b"{}").get("action", {}) or {})
    except ValueError:
        return
    if action.get("type") != "commentCard":
        return
    data = action.get("data", {}) or {}
    text = data.get("text", "") or ""
    if SYNCED in text:
        return  # one of ours

    card_id = (data.get("card", {}) or {}).get("id")
    board_id = (data.get("board", {}) or {}).get("id")
    orig_id = action.get("id")
    mc = action.get("memberCreator", {}) or {}
    author = mc.get("fullName") or mc.get("username") or "someone"
    if not (card_id and board_id and orig_id):
        return

    t = Trello(cfg.api_key, cfg.token)
    marker_re = re.compile(re.escape(cfg.marker) + r":src=([a-zA-Z0-9]{24});b=([a-zA-Z0-9]{24})")
    names = cfg.board_name

    if board_id == cfg.hub_board:
        if cfg.comment_direction not in ("both", "daily_to_source"):
            return
        c = t.get(f"/cards/{card_id}", fields="desc")
        m = marker_re.search(c.get("desc") or "")
        if not m:
            return
        counterpart, origin = m.group(1), "Hub board"
    elif board_id in names:
        if cfg.comment_direction not in ("both", "source_to_daily"):
            return
        counterpart = None
        for card in t.get(f"/boards/{cfg.hub_board}/cards", fields="id,desc", filter="open"):
            mm = marker_re.search(card.get("desc") or "")
            if mm and mm.group(1) == card_id:
                counterpart = card["id"]; break
        if not counterpart:
            return
        origin = names[board_id]
    else:
        return

    acts = t.get(f"/cards/{counterpart}/actions", filter="commentCard", limit="50")
    if any(f"ocs={orig_id}" in (a.get("data", {}).get("text", "")) for a in acts):
        return  # already mirrored (Trello retry / dedup)

    body_text = f"💬 {author} · {origin}\n{text}\n\n{SYNCED}ocs={orig_id}⟧"
    try:
        t.post(f"/cards/{counterpart}/actions/comments", text=body_text)
    except TrelloError:
        pass
