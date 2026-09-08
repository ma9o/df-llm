"""World site search on one native snapshot, with optional bounded CPU workers."""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from heapq import nsmallest
from typing import Any, TypedDict

from .rpc import DFHackError

# Original native names from df-structures; exposed enum names remain canonical.
ALIASES = {
    "lair": "lairshrine",
    "city": "town",
    "cavedetailed": "mountainhalls",
    "treecity": "forestretreat",
}


class Bucket(TypedDict):
    matches: list[dict[str, Any]]
    total: int
    unknown: int


def normalized(value):
    return "".join(c for c in value.casefold() if c.isalnum())


def validate(tokens, match, limit, workers):
    if not isinstance(tokens, (list, tuple)) or not 1 <= len(tokens) <= 32:
        raise ValueError("world_scan requires 1..32 search tokens")
    if any(not isinstance(t, str) or not t.strip() or len(t) > 200 for t in tokens):
        raise ValueError("Search tokens must be nonempty strings of at most 200 characters")
    if match not in ("any", "type", "name", "flag"):
        raise ValueError("match must be any, type, name or flag")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer in [1, 100] per token")
    if type(workers) is not int or not 1 <= workers <= 8:
        raise ValueError("workers must be an integer in [1, 8]")
    return [token.strip() for token in tokens]


def rank(site):
    return site.get("distance", float("inf")), site["id"]


def scan_chunk(sites, tokens, match, limit, origin):
    buckets: list[Bucket] = [{"matches": [], "total": 0, "unknown": 0} for _ in tokens]
    needles = [
        (ALIASES.get(normalized(t), normalized(t)), normalized(t), t.casefold()) for t in tokens
    ]
    for row in sites:
        types = {normalized(row["type"]), normalized(row.get("subtype", ""))} - {""}
        flags = {normalized(flag) for flag in row.get("flags", [])}
        names = [row.get("name", "").casefold(), row.get("native_name", "").casefold()]
        site = dict(row)
        if origin is not None:
            site["distance"] = max(abs(site["position"][k] - origin[k]) for k in ("x", "y"))
        for (type_needle, flag_needle, name_needle), bucket in zip(needles, buckets, strict=True):
            type_match = type_needle in types
            name_match = any(name_needle in name for name in names)
            found = (
                (match in ("any", "type") and type_match)
                or (match in ("any", "name") and name_match)
                or (match in ("any", "flag") and flag_needle in flags)
            )
            if found:
                bucket["total"] += 1
                bucket["matches"].append(site)
                if len(bucket["matches"]) >= limit * 2:
                    bucket["matches"] = nsmallest(limit, bucket["matches"], key=rank)
            elif (match in ("any", "type") and row.get("subtype_unavailable")) or (
                match in ("any", "flag") and ("flags" not in row or row.get("flags_unavailable"))
            ):
                bucket["unknown"] += 1
    for bucket in buckets:
        bucket["matches"] = nsmallest(limit, bucket["matches"], key=rank)
    return buckets


def run_worker(payload):
    # A separate module process also works when Client is called from a REPL or
    # stdin script. Workers have no game connection and cannot issue native reads.
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "dfharness.world_scan", "--worker"],
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=30,
            check=True,
        )
        return json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise DFHackError("World scan worker failed; the native snapshot was not reread") from exc


def search(snapshot, tokens, match="any", limit=20, workers=1):
    tokens = validate(tokens, match, limit, workers)
    out = {k: v for k, v in snapshot.items() if k not in ("sites", "tokens", "format")}
    out["format"] = "world_scan"
    if not snapshot.get("available"):
        return out
    sites = snapshot["sites"]
    actual_workers = min(workers, max(1, len(sites)))
    if actual_workers == 1:
        batches = [scan_chunk(sites, tokens, match, limit, snapshot.get("origin"))]
    else:
        size = (len(sites) + actual_workers - 1) // actual_workers
        payloads = [
            [sites[start : start + size], tokens, match, limit, snapshot.get("origin")]
            for start in range(0, len(sites), size)
        ]
        with ThreadPoolExecutor(max_workers=actual_workers) as pool:
            batches = list(pool.map(run_worker, payloads))
        actual_workers = len(payloads)
    out["workers"] = actual_workers
    out["order"] = (
        "Chebyshev distance to site center, then site ID"
        if snapshot.get("origin") is not None
        else "site ID"
    )
    out["results"] = []
    for i, token in enumerate(tokens):
        total = sum(batch[i]["total"] for batch in batches)
        unknown = snapshot.get("error_count", 0) + sum(batch[i]["unknown"] for batch in batches)
        matches = nsmallest(
            limit, (row for batch in batches for row in batch[i]["matches"]), key=rank
        )
        out["results"].append(
            {
                "token": token,
                "matches": matches,
                "total": total,
                "truncated": len(matches) < total,
                "complete": snapshot.get("complete", False) and unknown == 0,
                **({"unknown": unknown} if unknown else {}),
            }
        )
    out["complete"] = all(result["complete"] for result in out["results"])
    return out


if __name__ == "__main__":
    if sys.argv[1:] != ["--worker"]:
        raise SystemExit("Use dfctl world-scan TOKEN [--workers N]")
    print(json.dumps(scan_chunk(*json.load(sys.stdin)), ensure_ascii=False, separators=(",", ":")))
