"""``trello-sync discover`` — print the IDs you need to fill in config.toml.

Onboarding is the usual pain with the Trello API: you need board ids, your member
id and (optionally) list/label ids. This command prints them all so you can copy
them straight into your config.

    export TRELLO_HUB_KEY=...      # from https://trello.com/power-ups/admin
    export TRELLO_HUB_TOKEN=...    # token you generate for your account
    trello-sync discover                 # member id + all your boards
    trello-sync discover --board <id>    # that board's lists + labels
"""
from __future__ import annotations

from .api import Trello


def run(t: Trello, board: str | None):
    me = t.get("/members/me", fields="id,username,fullName")
    print(f"\nYou: {me.get('fullName')} (@{me.get('username')})")
    print(f"  hub.member_id = \"{me['id']}\"\n")

    if not board:
        print("Your boards (use one as [hub], the rest as [[sources]]):\n")
        rows = t.get("/members/me/boards", fields="id,name,closed")
        for b in sorted(rows, key=lambda x: x.get("name", "")):
            if b.get("closed"):
                continue
            print(f"  {b['id']}  {b['name']}")
        print("\nRun `trello-sync discover --board <id>` for a board's lists + labels.")
        return

    name = t.get(f"/boards/{board}", fields="name").get("name", board)
    print(f"Board: {name} ({board})\n")
    print("  Lists (columns):")
    for l in t.get(f"/boards/{board}/lists", fields="name"):
        print(f"    {l['id']}  {l['name']}")
    print("\n  Labels:")
    for l in t.get(f"/boards/{board}/labels", fields="name,color", limit=1000):
        print(f"    {l['id']}  {(l.get('name') or '(no name)'):24} {l.get('color') or ''}")
    print("\n  -> dev_list_id / dev_label_id (hub) or origin_label_id (source) come from above.")
