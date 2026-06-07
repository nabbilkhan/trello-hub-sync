"""Manage the Trello webhooks that drive the real-time receiver.

``trello-sync webhooks``           list webhooks for your hub + source boards
``trello-sync webhooks --repair``  create missing ones, re-enable inactive ones

Trello disables a webhook after repeated callback failures (e.g. while your public
endpoint is briefly down). Run ``--repair`` on a timer (or from your own watchdog)
to keep them healthy. Needs ``[receiver].public_url`` set in config.
"""
from __future__ import annotations

from .api import Trello, TrelloError


def run(cfg, repair: bool):
    if not cfg.receiver_public_url:
        print("Set [receiver].public_url in your config first."); return
    t = Trello(cfg.api_key, cfg.token)
    boards = {cfg.hub_board: "hub board"} | {s.board_id: s.name for s in cfg.sources}
    existing = {}
    for w in t.get(f"/tokens/{cfg.token}/webhooks"):
        if w.get("callbackURL") == cfg.receiver_public_url:
            existing[w.get("idModel")] = w
    for bid, name in boards.items():
        w = existing.get(bid)
        if w and w.get("active"):
            print(f"  ok        {name} ({bid})")
        elif w and not w.get("active"):
            print(f"  inactive  {name} ({bid})")
            if repair:
                try: t.put(f"/webhooks/{w['id']}", active="true"); print("    -> re-enabled")
                except TrelloError as e: print(f"    -> FAILED: {e}")
        else:
            print(f"  MISSING   {name} ({bid})")
            if repair:
                try:
                    t.post("/webhooks", callbackURL=cfg.receiver_public_url, idModel=bid,
                           description=f"{cfg.marker} {name}")
                    print("    -> created")
                except TrelloError as e:
                    print(f"    -> FAILED: {e}")
    if not repair:
        print("\nRun with --repair to create/re-enable.")
