"""Local sync state (SQLite).

Machine state lives here, *not* inside card descriptions, so descriptions stay
clean and never churn. One row per mirrored card:

  * last_status    — last-synced canonical status (the 3-way reconcile baseline)
  * label_baseline — JSON list of last-synced label names (to tell a deliberate
                     removal from a not-yet-synced label)
  * content_hash   — sha1 of the composed description+checklists (drift detection)

If this file is ever lost, the next run rebuilds it from the stable card markers
(``--backfill``); unknown baselines are treated as empty, i.e. additions only —
never spurious removals.
"""
from __future__ import annotations

import datetime
import json
import os
import sqlite3


class State:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS mirror(
                 src_id TEXT PRIMARY KEY, src_board TEXT, mirror_id TEXT,
                 last_status TEXT, label_baseline TEXT, content_hash TEXT, updated_at TEXT)"""
        )
        self.data: dict[str, dict] = {}
        for r in self.conn.execute(
            "SELECT src_id, src_board, mirror_id, last_status, label_baseline, content_hash FROM mirror"
        ):
            self.data[r[0]] = {
                "src_board": r[1], "mirror_id": r[2], "last_status": r[3],
                "baseline": json.loads(r[4] or "[]"), "content_hash": r[5] or "",
            }

    def get(self, src):
        return self.data.get(src)

    def set(self, src, **fields):
        self.data.setdefault(src, {"baseline": [], "content_hash": "", "last_status": "backlog"})
        self.data[src].update(fields)

    def flush(self):
        now = datetime.datetime.now().isoformat()
        rows = [
            (src, s.get("src_board"), s.get("mirror_id"), s.get("last_status"),
             json.dumps(s.get("baseline", [])), s.get("content_hash", ""), now)
            for src, s in self.data.items() if s.get("mirror_id")
        ]
        self.conn.executemany(
            "INSERT OR REPLACE INTO mirror(src_id,src_board,mirror_id,last_status,"
            "label_baseline,content_hash,updated_at) VALUES(?,?,?,?,?,?,?)", rows)
        self.conn.commit()

    def close(self):
        self.conn.close()
