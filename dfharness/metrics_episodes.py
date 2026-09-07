"""Objective-level analysis of passive records; gaps and retries are proxies."""

import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

READS = {
    "observe",
    "look",
    "brief",
    "status",
    "character_status",
    "game_status",
    "unit",
    "item",
    "items",
    "navigation",
    "locate",
    "session",
    "inspect",
    "dispatch_details",
    "wait_ready",
}


def role(row):
    operation = row["operation"].removeprefix("df_").replace("-", "_")
    if row.get("action") or operation in {"act", "sequence"}:
        return "dispatch"
    if operation in READS:
        return "read"
    if operation in {"actions", "capabilities"}:
        return "reference"
    return "other"


def milliseconds(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.timestamp() * 1000 if parsed.tzinfo is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def interval(row):
    start = milliseconds(row.get("at"))
    duration = row.get("duration_ms")
    if start is None or duration is None:
        return None
    if row.get("finished_at") is not None:
        end = milliseconds(row["finished_at"])
    else:
        # Legacy rows predate finished_at. Counting tokenizer work as controller
        # deliberation would recreate the measurement error we are trying to fix.
        end = start + duration + (row.get("measurement_ms") or 0)
    return (start, end) if end is not None and end >= start + duration - 0.01 else None


def occupied(intervals):
    total, until = 0.0, -math.inf
    for start, end in sorted(intervals):
        total += max(0, end - max(start, until))
        until = max(until, end)
    return total


def tokens(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row.get("tokenizer", "unknown")].append(row.get("output_tokens"))
    return {
        name: {
            "known_total": sum(value for value in values if value is not None),
            "measured": sum(value is not None for value in values),
            "unmeasured": sum(value is None for value in values),
        }
        for name, values in sorted(groups.items())
    }


def followups(calls, dispatches):
    windows: list[dict[str, Any]] = []
    overlaps = 0
    latest_response = -math.inf
    for index, call in enumerate(dispatches):
        next_call = dispatches[index + 1] if index + 1 < len(dispatches) else None
        start = interval(call)[0]
        latest_response = max(latest_response, start + call["duration_ms"])
        end = latest_response
        bound = interval(next_call)[0] if next_call else math.inf
        # Concurrent reads while an act is running are polling, not evidence
        # that its receipt was insufficient. Keep them out of this signal.
        if bound < end:
            overlaps += 1
            continue
        reads = [row for row in calls if role(row) == "read" and end <= interval(row)[0] < bound]
        windows.append(
            {
                "dispatch": call["id"],
                "action": call.get("action"),
                "next_dispatch": next_call["id"] if next_call else None,
                "read_calls": len(reads),
                "read_operations": dict(Counter(row["operation"] for row in reads)),
                "receipt_output_tokens": tokens([call]),
                "read_output_tokens": tokens(reads),
            }
        )
    closed = [window for window in windows if window["next_dispatch"] is not None]
    trailing = [window for window in windows if window["next_dispatch"] is None]
    return {
        "between_dispatches": len(closed),
        "reads": sum(window["read_calls"] for window in closed),
        "reads_per_dispatch": round(sum(window["read_calls"] for window in closed) / len(closed), 3)
        if closed
        else None,
        "trailing_reads": sum(window["read_calls"] for window in trailing),
        "overlapping_dispatch_windows": overlaps,
        "windows": windows,
    }


def identity(value):
    if not isinstance(value, dict) or not value.get("action") or not value.get("target"):
        return None
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def bounces(dispatches):
    counts = Counter(
        noncompleted=0,
        assessed=0,
        reissued=0,
        resumed=0,
        redelivered=0,
        unknown_target=0,
        unknown_followup=0,
        no_later_dispatch=0,
        overlapping=0,
    )
    links = []
    for index, call in enumerate(dispatches):
        if call["outcome"] == "completed" or call.get("action") == "resume":
            continue
        counts["noncompleted"] += 1
        intents = call.get("intents") or []
        key = identity(
            call.get("blocked_intent")
            if call.get("action") == "sequence"
            else intents[0]
            if len(intents) == 1
            else None
        )
        if key is None:
            counts["unknown_target"] += 1
            continue
        following = dispatches[index + 1 :]
        if not following:
            counts["no_later_dispatch"] += 1
            continue
        # Overlapping calls cannot be responses to a receipt still in flight.
        following = [
            row for row in following if interval(row)[0] >= interval(call)[0] + call["duration_ms"]
        ]
        if not following:
            counts["overlapping"] += 1
            continue
        counts["assessed"] += 1
        unknown = False
        for later in following:
            dispatch_id = call.get("dispatch_id")
            if (
                dispatch_id
                and later.get("action") == "resume"
                and (later.get("resume_id") or later.get("dispatch_id")) == dispatch_id
            ):
                counts["resumed"] += 1
                break
            if dispatch_id and later.get("dispatch_id") == dispatch_id:
                counts["redelivered"] += 1
                break
            if key in {identity(value) for value in later.get("intents", [])}:
                counts["reissued"] += 1
                links.append({"from": call["id"], "to": later["id"], "outcome": call["outcome"]})
                break
            if later.get("action") in (call.get("action"), "sequence") and "intents" not in later:
                unknown = True
        else:
            if unknown:
                counts["assessed"] -= 1
                counts["unknown_followup"] += 1
    return {
        **counts,
        "rate": round(counts["reissued"] / counts["assessed"], 4) if counts["assessed"] else None,
        "links": links,
    }


def summarize_episode(key, calls):
    ranges = [interval(row) for row in calls]
    start, end = min(r[0] for r in ranges), max(r[1] for r in ranges)
    harness = occupied(ranges)
    dispatches = [row for row in calls if role(row) == "dispatch"]
    return {
        "run": key[0],
        "grouping": key[1],
        "episode": key[2],
        "segment": key[3],
        "started_at": calls[0]["at"],
        "calls": len(calls),
        "dispatch_count": len(dispatches),
        "resume_calls": sum(row.get("action") == "resume" for row in dispatches),
        "wall_ms": round(end - start, 3),
        "harness_ms": round(harness, 3),
        "gap_ms": round(max(0, end - start - harness), 3),
        "response_ms": round(
            occupied(
                [(r[0], r[0] + row["duration_ms"]) for r, row in zip(ranges, calls, strict=True)]
            ),
            3,
        ),
        "output_tokens": tokens(calls),
        "dispatch_output_tokens": tokens(dispatches),
        "reference_calls": dict(
            Counter(row["operation"] for row in calls if role(row) == "reference")
        ),
        "followup_reads": followups(calls, dispatches),
        "bounces": bounces(dispatches),
        "timing_inferred_calls": sum("finished_at" not in row for row in calls),
    }


def episodes(rows, idle_gap=120):
    if not math.isfinite(idle_gap) or idle_gap <= 0:
        raise ValueError("idle_gap must be a positive finite number of seconds")
    timed = sorted(
        [row for row in rows if interval(row) is not None],
        key=lambda row: (interval(row)[0], row["id"]),
    )
    groups, pending, segments = {}, {}, Counter()
    for row in timed:
        run, label = row["run"], row.get("episode")
        start, end = interval(row)
        grouping = "explicit" if label else "idle_gap"
        previous = pending.get(run)
        same_label = (
            previous is not None
            and previous[0][1] == grouping
            and (not label or previous[0][2] == label)
        )
        if same_label and start - previous[1] <= idle_gap * 1000:
            key = previous[0]
            end = max(end, previous[1])
        else:
            identity = (run, grouping, label or row["id"])
            segments[identity] += 1
            key = (*identity, segments[identity])
        pending[run] = (key, end)
        groups.setdefault(key, []).append(row)
    items = [summarize_episode(key, calls) for key, calls in groups.items()]
    windows = sum(item["followup_reads"]["between_dispatches"] for item in items)
    reads = sum(item["followup_reads"]["reads"] for item in items)
    bounce_counts = Counter()
    for item in items:
        bounce_counts.update(
            {key: value for key, value in item["bounces"].items() if type(value) is int}
        )
    return {
        "count": len(items),
        "idle_gap_seconds": idle_gap,
        "untimed_calls": len(rows) - len(timed),
        "totals": {
            key: round(sum(item[key] for item in items), 3)
            for key in ("calls", "dispatch_count", "wall_ms", "harness_ms", "gap_ms")
        },
        "followup_reads": {
            "between_dispatches": windows,
            "reads": reads,
            "reads_per_dispatch": round(reads / windows, 3) if windows else None,
            "trailing_reads": sum(item["followup_reads"]["trailing_reads"] for item in items),
        },
        "bounces": {
            **bounce_counts,
            "rate": round(bounce_counts["reissued"] / bounce_counts["assessed"], 4)
            if bounce_counts["assessed"]
            else None,
        },
        "items": items,
    }
