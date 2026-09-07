"""Optional exact deltas for controller reads, independent of execution state.

The bounded local cache survives CLI processes and costs no additional RPC.
Only complete projected values enter it. A miss or incompatible query returns
a fresh full value; these references are never accepted as input guards.
"""

import hashlib
import json
import sqlite3
from contextlib import closing
from copy import deepcopy
from pathlib import Path

from .rpc import DFHackError
from .wire import apply_delta, delta

__all__ = ["ReadCache", "apply_read"]

MAX_READS = 32
MAX_BYTES = 2_000_000
META = {"read_ref", "read_cache"}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def reference(value):
    return "r1:" + hashlib.sha256(encoded(value).encode()).hexdigest()[:24]


def read_value(response):
    return {k: deepcopy(v) for k, v in response.items() if k not in META}


def apply_read(previous, response):
    """Reconstruct an exact read; reject wrong/edited bases and corrupt deltas."""
    if response.get("format") != "reading_delta":
        return deepcopy(response)
    before = read_value(previous)
    if response.get("base") != previous.get("read_ref") or reference(before) != response["base"]:
        raise DFHackError("Reading delta base mismatch; request a fresh read without since")
    value = apply_delta(before, response["change"])
    if reference(value) != response.get("read_ref"):
        raise DFHackError("Reading delta content mismatch; request a fresh read without since")
    return dict(value, read_ref=response["read_ref"])


class ReadCache:
    def __init__(self, path):
        self.path = Path(path)

    def project(self, value, scope, since=None):
        body = encoded(value)
        if len(body.encode()) > MAX_BYTES:
            return dict(
                value, read_cache={"available": False, "reason": "Read exceeds cache byte limit"}
            )
        ref = reference(value)
        reason = None
        base = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path, timeout=0.2)) as db, db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS readings (seq INTEGER PRIMARY KEY, ref TEXT, scope TEXT, body TEXT, UNIQUE(ref, scope))"
                )
                if since:
                    row = db.execute(
                        "SELECT body FROM readings WHERE ref=? AND scope=?", (since, encoded(scope))
                    ).fetchone()
                    if row:
                        base = json.loads(row[0])
                        if reference(base) != since:
                            base = None
                            reason = "Cached base failed its content check"
                    else:
                        reason = "Base expired or query/world scope changed"
                db.execute(
                    "INSERT OR REPLACE INTO readings(ref, scope, body) VALUES (?,?,?)",
                    (ref, encoded(scope), body),
                )
                db.execute(
                    "DELETE FROM readings WHERE seq NOT IN (SELECT seq FROM readings ORDER BY seq DESC LIMIT ?)",
                    (MAX_READS,),
                )
        except (OSError, sqlite3.Error, ValueError) as exc:
            # Caching must not turn a successful observation into a failed call
            # or a retry. Never let a missing base masquerade as 'no changes'.
            return dict(value, read_cache={"available": False, "reason": type(exc).__name__})
        if base is not None:
            result = {
                "format": "reading_delta",
                "base": since,
                "read_ref": ref,
                "state_id": value.get("state_id"),
                "change": delta(base, value),
            }
            if len(encoded(result)) < len(body):
                return result
            reason = "Full read is smaller than its delta"
        result = dict(value, read_ref=ref)
        if reason:
            result["read_cache"] = {"resync": reason}
        return result
