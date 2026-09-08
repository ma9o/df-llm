"""Offline transport/receipt accounting from the harness's existing JSONL logs."""

import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median


def size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def distribution(values):
    return {"median": median(values), "max": max(values), "total": sum(values)} if values else None


def audit_logs(paths):
    operations = defaultdict(
        lambda: {
            "rpc_calls": [],
            "request_bytes": [],
            "result_bytes": [],
            "elapsed_ms": [],
        }
    )
    operation_counts = Counter()
    started, receipts, dispatch_calls = {}, {}, Counter()
    unmeasured_dispatches = set()
    errors, outcomes = Counter(), Counter()
    cache_misses = records = incomplete_lines = 0
    files = []
    for path in paths:
        path = Path(path)
        files.append(str(path))
        with path.open(encoding="utf-8") as stream:
            for number, line in enumerate(stream, 1):
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    # An active logger can leave its final write incomplete.
                    # Interior corruption must not become plausible statistics.
                    if not line.endswith("\n"):
                        incomplete_lines += 1
                        continue
                    raise ValueError(f"Invalid JSONL at {path}:{number}: {exc.msg}") from exc
                if isinstance(row, dict) and row.get("kind") == "controller_payload":
                    continue
                if (
                    not isinstance(row, dict)
                    or not isinstance(row.get("request"), dict)
                    or not isinstance(row.get("response"), dict)
                ):
                    raise ValueError(f"Missing request/response objects at {path}:{number}")
                records += 1
                request, response = row["request"], row["response"]
                transport = row.get("transport", {})
                op = request.get("op", "unknown")
                result = response.get("result", response)
                group = op
                if op == "poll" and isinstance(result, dict):
                    for field, label in (
                        ("pending_view", "pending"),
                        ("view_delta", "delta"),
                        ("view", "full"),
                    ):
                        if field in result:
                            group = "poll." + label
                            break
                stats = operations[group]
                operation_counts[group] += 1
                stats["result_bytes"].append(size(result))
                for field in ("rpc_calls", "request_bytes", "elapsed_ms"):
                    value = row.get(field) if field == "elapsed_ms" else transport.get(field)
                    if type(value) in (int, float) and value >= 0:
                        stats[field].append(value)
                cache_misses += transport.get("cache_miss") is True
                if response.get("ok") is False:
                    errors[response.get("code", "unknown")] += 1
                dispatch_id = None
                if op == "begin_dispatch":
                    dispatch_id = request.get("request_id")
                    started[dispatch_id] = request.get("action", {}).get("type", "unknown")
                elif op == "act":
                    dispatch_id = request.get("parent_dispatch")
                elif op == "poll":
                    dispatch_id = request.get("dispatch_id")
                elif op == "finish_dispatch":
                    dispatch_id = request.get("action_id")
                    receipt = request.get("compact")
                    if response.get("ok") is True and isinstance(receipt, dict):
                        receipts[dispatch_id] = receipt
                if dispatch_id is not None:
                    # Missing legacy transport counts are not guessed as one.
                    calls = transport.get("rpc_calls")
                    if type(calls) is int and calls >= 0:
                        dispatch_calls[dispatch_id] += calls
                    else:
                        unmeasured_dispatches.add(dispatch_id)
    largest = []
    for key, receipt in receipts.items():
        outcome = receipt.get("outcome", "unknown")
        outcomes[outcome] += 1
        parts = {}
        for field, value in receipt.items():
            if isinstance(value, dict):
                parts.update({field + "." + k: size(v) for k, v in value.items()})
            else:
                parts[field] = size(value)
        largest.append(
            {
                "dispatch_id": key,
                "action": started.get(key, "unknown"),
                "outcome": outcome,
                "bytes": size(receipt),
                "largest_values": dict(
                    sorted(parts.items(), key=lambda pair: pair[1], reverse=True)[:5]
                ),
            }
        )
    return {
        "format": "log_audit",
        "files": files,
        "records": records,
        "incomplete_final_lines": incomplete_lines,
        "cache_installs": cache_misses,
        "errors": dict(errors),
        "operations": {
            op: {
                "count": operation_counts[op],
                **{field: distribution(values) for field, values in stats.items()},
                "unmeasured": {
                    field: operation_counts[op] - len(values)
                    for field, values in stats.items()
                    if len(values) < operation_counts[op]
                },
            }
            for op, stats in sorted(operations.items())
        },
        "dispatches": {
            "begun": len(started),
            "receipts": len(receipts),
            "outcomes": dict(outcomes),
            "input_batches": sum(r.get("inputs", 0) for r in receipts.values()),
            "receipt_bytes": distribution([size(r) for r in receipts.values()]),
            "rpc_calls": distribution(
                [
                    dispatch_calls[key]
                    for key in receipts.keys() & started.keys() - unmeasured_dispatches
                ]
            ),
            "unmeasured_rpc_dispatches": len(
                receipts.keys() - (started.keys() - unmeasured_dispatches)
            ),
            "largest_receipts": sorted(largest, key=lambda entry: entry["bytes"], reverse=True)[:5],
        },
        "measurement": {
            "bytes": "Minified UTF-8 result/receipt JSON; request_bytes is measured Lua source across RPC attempts. These exclude protocol framing.",
            "elapsed_ms": "Logged call duration including any cache installation; not dispatch wall time.",
            "scope": "Only logged calls and successful finish records. Transport exceptions and unlogged wait-ready polls are not counted. Duplicate finish records count once per dispatch ID.",
        },
    }
