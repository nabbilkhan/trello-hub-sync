"""Command-line entry point: ``trello-sync [sync|discover|backfill|receiver|comments]``."""
from __future__ import annotations

import argparse
import os
import sys

from . import config
from .api import Trello

__version__ = "1.0.0"


def _client_for_discover(args):
    """Discover needs only key+token (from --key/--token, env, or an existing config)."""
    key = args.key or os.environ.get("TRELLO_HUB_KEY")
    token = args.token or os.environ.get("TRELLO_HUB_TOKEN")
    if not (key and token):
        try:
            cfg = config.load(args.config)
            key, token = cfg.api_key, cfg.token
        except Exception:
            pass
    if not (key and token):
        sys.exit("discover needs credentials: set TRELLO_HUB_KEY and TRELLO_HUB_TOKEN, "
                 "pass --key/--token, or create a config first.")
    return Trello(key, token)


def main(argv=None):
    p = argparse.ArgumentParser(prog="trello-sync", description="Trello Hub Sync")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--config", help="path to config.toml")
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("sync", help="run one sync pass (default)")
    sp.add_argument("--dry-run", action="store_true", help="log intended actions, change nothing")

    dp = sub.add_parser("discover", help="print board/member/label ids for your config")
    dp.add_argument("--board", help="show this board's lists + labels")
    dp.add_argument("--key"); dp.add_argument("--token")

    sub.add_parser("backfill", help="rebuild the local state DB from card markers")
    sub.add_parser("receiver", help="run the real-time webhook receiver")
    wp = sub.add_parser("webhooks", help="list/repair the Trello webhooks")
    wp.add_argument("--repair", action="store_true", help="create missing / re-enable inactive")
    sub.add_parser("comments", help="route a commentCard webhook from stdin (internal)")

    args = p.parse_args(argv)
    cmd = args.cmd or "sync"

    if cmd == "discover":
        from . import discover
        discover.run(_client_for_discover(args), args.board)
        return

    if cmd == "comments":
        from . import comments
        comments.route(config.load(args.config), sys.stdin.buffer.read())
        return

    cfg = config.load(args.config)
    if cmd == "sync":
        from . import engine
        dry = args.dry_run or os.environ.get("DRY_RUN") == "1"
        engine.run(cfg, dry_run=dry)
    elif cmd == "backfill":
        from . import engine
        engine.backfill(cfg)
    elif cmd == "receiver":
        from . import webhook
        webhook.serve(cfg)
    elif cmd == "webhooks":
        from . import webhooks
        webhooks.run(cfg, args.repair)


if __name__ == "__main__":
    main()
