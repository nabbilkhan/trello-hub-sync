"""Configuration loading for Trello Hub Sync.

Everything that is specific to *your* account and boards lives in a single TOML
file (see ``config.example.toml``). Nothing is hard-coded. The file is found via,
in order:

  1. ``--config PATH`` on the command line,
  2. the ``TRELLO_HUB_CONFIG`` environment variable,
  3. ``~/.config/trello-hub-sync/config.toml``.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field

DEFAULT_PATH = "~/.config/trello-hub-sync/config.toml"


def _expand(p: str) -> str:
    return os.path.expanduser(p) if p else p


def _resolve_secret(table: dict, inline_key: str, file_key: str) -> str:
    """Return a secret either inline (``api_key``) or from a file (``api_key_file``)."""
    path = table.get(file_key)
    if path:
        with open(_expand(path)) as fh:
            return fh.read().strip()
    return str(table.get(inline_key, "")).strip()


@dataclass
class Source:
    board_id: str
    name: str
    origin_label_id: str = ""


@dataclass
class Config:
    api_key: str
    token: str
    api_secret: str
    hub_board: str
    member_id: str
    dev_list_id: str
    dev_label_id: str
    sources: list[Source]
    exclude_label_substring: str
    attach_max_bytes: int
    downstream_statuses: set[str]
    state_db: str
    lock_path: str
    log_path: str
    receiver_port: int
    receiver_path: str
    receiver_public_url: str
    comment_direction: str
    marker: str = "trello-hub-sync"
    raw: dict = field(default_factory=dict)

    @property
    def board_name(self) -> dict[str, str]:
        return {s.board_id: s.name for s in self.sources}

    @property
    def origin_label(self) -> dict[str, str]:
        return {s.board_id: s.origin_label_id for s in self.sources if s.origin_label_id}


def find_config_path(explicit: str | None = None) -> str:
    for candidate in (explicit, os.environ.get("TRELLO_HUB_CONFIG"), DEFAULT_PATH):
        if candidate:
            path = _expand(candidate)
            if os.path.exists(path):
                return path
    raise FileNotFoundError(
        "No config found. Pass --config, set TRELLO_HUB_CONFIG, or create "
        f"{DEFAULT_PATH}. Copy config.example.toml to get started."
    )


def load(explicit: str | None = None) -> Config:
    path = find_config_path(explicit)
    with open(path, "rb") as fh:
        data = tomllib.load(fh)

    trello = data.get("trello", {})
    hub = data.get("hub", {})
    behavior = data.get("behavior", {})
    paths = data.get("paths", {})
    receiver = data.get("receiver", {})
    comments = data.get("comments", {})

    sources = [
        Source(board_id=s["board_id"], name=s.get("name", s["board_id"]),
               origin_label_id=s.get("origin_label_id", ""))
        for s in data.get("sources", [])
    ]
    if not sources:
        raise ValueError("config has no [[sources]] boards to aggregate from")

    cfg = Config(
        api_key=_resolve_secret(trello, "api_key", "api_key_file"),
        token=_resolve_secret(trello, "token", "token_file"),
        api_secret=_resolve_secret(trello, "api_secret", "api_secret_file"),
        hub_board=hub["board_id"],
        member_id=hub["member_id"],
        dev_list_id=hub.get("dev_list_id", ""),
        dev_label_id=hub.get("dev_label_id", ""),
        sources=sources,
        exclude_label_substring=behavior.get("exclude_label_substring", ""),
        attach_max_bytes=int(behavior.get("attach_max_bytes", 26214400)),
        downstream_statuses=set(behavior.get("downstream_statuses",
                                             ["qa", "discussion", "hold", "done"])),
        state_db=_expand(paths.get("state_db", "~/.local/state/trello-hub-sync/state.db")),
        lock_path=_expand(paths.get("lock", "~/.local/state/trello-hub-sync/sync.lock")),
        log_path=_expand(paths.get("log", "~/.local/state/trello-hub-sync/sync.log")),
        receiver_port=int(receiver.get("port", 18811)),
        receiver_path=receiver.get("path", ""),
        receiver_public_url=receiver.get("public_url", ""),
        comment_direction=comments.get("direction", "both"),
        marker=behavior.get("marker", "trello-hub-sync"),
        raw=data,
    )
    if not cfg.api_key or not cfg.token:
        raise ValueError("config is missing trello.api_key / trello.token")
    return cfg
