"""Offline interaction comparisons. RPC traffic is never counted as LLM tokens."""

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

from .metrics_episodes import episodes

FIELDS = (
    "duration_ms",
    "input_tokens",
    "output_tokens",
    "input_bytes",
    "output_bytes",
    "rpc_calls",
    "rpc_ms",
    "measurement_ms",
    "inputs",
    "ticks",
)


def distribution(rows, field):
    values = sorted(row[field] for row in rows if row.get(field) is not None)
    result = {"measured": len(values), "unmeasured": len(rows) - len(values)}
    if values:
        result.update(
            total=sum(values),
            mean=round(mean(values), 3),
            p50=median(values),
            p95=values[max(0, math.ceil(len(values) * 0.95) - 1)],
            max=max(values),
        )
    return result


def summarize(rows, fields):
    return {
        "count": len(rows),
        "outcomes": dict(Counter(row["outcome"] for row in rows)),
        **{field: distribution(rows, field) for field in fields},
    }


def read_logs(paths, run=None):
    rows, seen = [], {}
    incomplete = duplicates = 0
    for path in paths:
        path = Path(path)
        with path.open(encoding="utf-8") as stream:
            for number, line in enumerate(stream, 1):
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    if not line.endswith("\n"):
                        incomplete += 1
                        continue
                    raise ValueError(f"Invalid measurement JSONL at {path}:{number}") from exc
                if (
                    not isinstance(row, dict)
                    or row.get("schema_version") != 1
                    or row.get("kind") not in ("interaction", "rpc")
                    or not all(
                        isinstance(row.get(key), str) and row[key]
                        for key in ("id", "trace_id", "operation", "outcome", "run")
                    )
                ):
                    raise ValueError(
                        f"Invalid measurement record at {path}:{number}; use audit-log for episode logs"
                    )
                for field in FIELDS:
                    value = row.get(field)
                    if value is not None and (
                        type(value) not in (int, float) or not math.isfinite(value) or value < 0
                    ):
                        raise ValueError(f"Invalid {field} at {path}:{number}")
                if row.get("episode") is not None and (
                    not isinstance(row["episode"], str) or not row["episode"]
                ):
                    raise ValueError(f"Invalid episode label at {path}:{number}")
                if row["id"] in seen:
                    if seen[row["id"]] != row:
                        raise ValueError(f"Conflicting measurement ID at {path}:{number}")
                    duplicates += 1
                    continue
                seen[row["id"]] = row
                if run is None or row["run"] == run:
                    rows.append(row)
    return rows, {"incomplete_final_lines": incomplete, "duplicate_records": duplicates}


def group_key(row):
    action = ":" + row["action"] if row.get("action") else ""
    return (
        f"{row.get('surface', 'python')}/{row['operation']}{action}"
        f"/{row.get('output_format', 'canonical_json')}@{row.get('tokenizer', 'unknown')}"
    )


def analyze(paths, run=None, idle_gap=120):
    rows, reading = read_logs(paths, run)
    interactions = [row for row in rows if row["kind"] == "interaction"]
    rpcs = [row for row in rows if row["kind"] == "rpc"]
    groups, transport, token_groups = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in interactions:
        groups[group_key(row)].append(row)
        token_groups[row.get("tokenizer", "unknown")].append(row)
    for row in rpcs:
        key = row["operation"] + ("." + row["variant"] if row.get("variant") else "")
        transport[key].append(row)
    roots = {row["id"] for row in interactions}
    return {
        "files": [str(path) for path in paths],
        "selected_run": run,
        **reading,
        "runs": dict(Counter(row["run"] for row in interactions)),
        "versions": dict(Counter(row.get("harness_version", "unknown") for row in interactions)),
        "episodes": episodes(interactions, idle_gap),
        "interactions": summarize(
            interactions, ("duration_ms", "rpc_calls", "rpc_ms", "measurement_ms")
        ),
        "tokens": {
            name: summarize(group, ("input_tokens", "output_tokens"))
            for name, group in sorted(token_groups.items())
        },
        "operations": {key: summarize(group, FIELDS) for key, group in sorted(groups.items())},
        "rpc": {
            key: summarize(group, ("duration_ms", "input_bytes", "output_bytes"))
            for key, group in sorted(transport.items())
        },
        "rpc_traces_without_completed_interaction": len({row["trace_id"] for row in rpcs} - roots),
        "slowest": [
            {
                key: row[key]
                for key in (
                    "id",
                    "surface",
                    "operation",
                    "action",
                    "dispatch_id",
                    "duration_ms",
                    "outcome",
                    "input_tokens",
                    "output_tokens",
                    "rpc_calls",
                )
                if key in row
            }
            for row in sorted(
                interactions, key=lambda row: row.get("duration_ms", 0), reverse=True
            )[:5]
        ],
    }


def compare(current, baseline):
    result = {}
    for key in current["operations"].keys() & baseline["operations"].keys():
        after, before = current["operations"][key], baseline["operations"][key]
        values = {"samples": {"baseline": before["count"], "current": after["count"]}}
        for field in ("duration_ms", "input_tokens", "output_tokens", "rpc_calls", "rpc_ms"):
            old, new = before[field].get("mean"), after[field].get("mean")
            if old is None or new is None:
                values[field] = {"available": False}
            else:
                values[field] = {
                    "baseline_mean": old,
                    "current_mean": new,
                    "delta": round(new - old, 3),
                    "percent": round((new - old) / old * 100, 2) if old else None,
                }
        result[key] = values
    episode_changes = {}
    for field in ("calls", "dispatch_count", "wall_ms", "harness_ms", "gap_ms"):
        after = distribution(current["episodes"]["items"], field)
        before = distribution(baseline["episodes"]["items"], field)
        old, new = before.get("mean"), after.get("mean")
        episode_changes[field] = {
            "baseline_mean": old,
            "current_mean": new,
            "delta": round(new - old, 3) if old is not None and new is not None else None,
        }
    return {
        "operations": dict(sorted(result.items())),
        "episodes": {
            "samples": {
                "baseline": baseline["episodes"]["count"],
                "current": current["episodes"]["count"],
            },
            "means": episode_changes,
            "followup_reads_per_dispatch": {
                label: source["episodes"]["followup_reads"]["reads_per_dispatch"]
                for label, source in (("baseline", baseline), ("current", current))
            },
            "bounce_rate": {
                label: source["episodes"]["bounces"]["rate"]
                for label, source in (("baseline", baseline), ("current", current))
            },
            "basis": "Descriptive per-episode means; compare equivalent instructions and grouping thresholds. Episode identities/workloads are not automatically matched. Token totals remain separated by encoding in each episode.",
        },
        "only_current": sorted(current["operations"].keys() - baseline["operations"].keys()),
        "only_baseline": sorted(baseline["operations"].keys() - current["operations"].keys()),
        "basis": "Per-call means for matching surface, operation, action, output format and tokenizer; sample counts and outcome mix remain visible. Negative deltas are reductions.",
    }


def report(paths, baseline=None, run=None, idle_gap=120):
    current = analyze(paths, run, idle_gap)
    result = {
        "format": "interaction_metrics",
        "schema_version": 1,
        **current,
        "measurement": {
            "tokens": "Exact counts under the named local tokenizer, from the harness perspective: request=input, returned payload=output. Not provider usage; prompts, reasoning and controller thinking time are outside this boundary.",
            "payload": "Canonical Python arguments or CLI argv plus stdin; output is canonical Python JSON or actual CLI text. Historical records retain their original surface and format. No payload text is stored in this log.",
            "duration_ms": "Monotonic time through response production (including CLI output flush); tokenizer/log work follows. Python excludes client construction; CLI excludes interpreter/import startup.",
            "measurement_ms": "Serialization and token counting, including a cold tokenizer load; excludes JSONL append. Reported separately from response duration.",
            "rpc": "Lua source and returned command text bytes, excluding protobuf framing. Every Client.request RPC is recorded, including readiness polls and transport errors. No token counts for internal traffic.",
            "p95": "Nearest-rank percentile. Null counts are unmeasured, never zero. Process termination can leave RPC traces without a completed interaction.",
            "episodes": "All calls split per run after idle_gap_seconds or a label change. Explicit labels retain a segment number across splits; idle time between segments is excluded. One controller per run. Wall time covers first recorded start to last measured finish only; it excludes unseen instruction delivery, final deliberation and process startup.",
            "gap_ms": "Time outside all recorded harness intervals, including human pauses, deliberation, other tools and scheduling; not measured LLM thinking. Harness time unions overlapping calls, includes tokenizer measurement work and excludes the final JSONL append. RPC durations are children, never added again. Legacy finish times are inferred.",
            "followup_reads": "Observation calls starting after a dispatch response and before the next dispatch. Trailing reads are separate because the window is still open; overlapping dispatch windows are excluded. Receipt and read output tokens are shown together. A read can be intentional, not necessarily a deficient receipt.",
            "bounces": "Proxy: a non-completed targeted action is later reissued with the same action type and native target in its episode, including inside a sequence. Resumes and same-dispatch redeliveries are separate. Rate uses assessable non-completed calls with a later dispatch; missing targets, overlapping calls and open tails are counted separately. Targets/sequence blockers are unavailable in legacy records. Matching targets does not prove a prerequisite defect.",
            "references": "Calls to actions and capabilities are a discovery/relearning proxy, reported separately. Source-file reads and tools outside the harness are invisible.",
        },
    }
    if baseline:
        before = analyze(baseline, idle_gap=idle_gap)
        result["baseline"] = before
        result["comparison"] = compare(current, before)
    return result


def token_text(counts):
    value = str(counts.get("known_total", 0))
    if counts.get("unmeasured"):
        value += f" (+{counts['unmeasured']} unknown)"
    return value


def render(result):
    lines = [
        f"Interactions: {result['interactions']['count']}  Runs: {', '.join(result['runs']) or 'none'}",
    ]
    episode_data = result["episodes"]
    lines.append(
        f"Episodes: {episode_data['count']} (idle gap {episode_data['idle_gap_seconds']:g}s; untimed calls {episode_data['untimed_calls']})"
    )
    lines.append(
        "Episode | Calls/acts | wall/harness/gap s | output tokens | reads/act | references | bounces/assessed"
    )
    for episode in episode_data["items"]:
        output_counts = ",".join(
            f"{name}:{token_text(counts)}" for name, counts in episode["output_tokens"].items()
        )
        reads = episode["followup_reads"]["reads_per_dispatch"]
        bounce = episode["bounces"]
        label = (
            f"{episode['episode']}#{episode['segment']}"
            if episode["grouping"] == "explicit"
            else "auto:" + episode["episode"][:8]
        )
        lines.append(
            f"{episode['run']}/{label} | {episode['calls']}/{episode['dispatch_count']} | "
            f"{episode['wall_ms'] / 1000:.2f}/{episode['harness_ms'] / 1000:.2f}/{episode['gap_ms'] / 1000:.2f} | "
            f"{output_counts} | {reads if reads is not None else '?'} | "
            f"{sum(episode['reference_calls'].values())} | {bounce['reissued']}/{bounce['assessed']}"
        )
        omitted = {
            key: bounce[key]
            for key in ("unknown_target", "unknown_followup", "no_later_dispatch", "overlapping")
            if bounce[key]
        }
        if omitted:
            lines.append(f"  Bounce coverage exclusions: {omitted}")
        for window in episode["followup_reads"]["windows"]:
            receipts = window["receipt_output_tokens"]
            outputs = window["read_output_tokens"]
            token_pairs = ", ".join(
                f"{name} receipt={token_text(receipts.get(name, {}))}, reads={token_text(outputs.get(name, {}))}"
                for name in sorted(receipts.keys() | outputs.keys())
            )
            lines.append(
                f"  {window['action'] or 'act'} {window['dispatch'][:8]}: {window['read_calls']} reads"
                f"{' (open tail)' if window['next_dispatch'] is None else ''}; {token_pairs}"
            )
    lines.append("Operation | Calls | p50 ms | p95 ms | mean tokens in/out | mean RPCs")
    for operation, group in result["operations"].items():

        def number(field, key, group=group):
            value = group[field].get(key)
            return f"{value:.1f}" if value is not None else "?"

        lines.append(
            f"{operation} | {group['count']} | {number('duration_ms', 'p50')} | "
            f"{number('duration_ms', 'p95')} | {number('input_tokens', 'mean')}/"
            f"{number('output_tokens', 'mean')} | {number('rpc_calls', 'mean')}"
        )
    if "comparison" in result:
        change = result["comparison"]["episodes"]
        lines.append(
            f"Episode comparison: reads/act {change['followup_reads_per_dispatch']}; bounce rate {change['bounce_rate']}"
        )
        lines.append("Changes in per-call means (negative = reduction):")
        for operation, change in result["comparison"]["operations"].items():

            def delta(field, change=change):
                value = change[field].get("percent")
                return f"{value:+.1f}%" if value is not None else "?"

            lines.append(
                f"{operation}: duration {delta('duration_ms')}, tokens in/out "
                f"{delta('input_tokens')}/{delta('output_tokens')}, RPCs {delta('rpc_calls')}"
            )
    lines.append(
        "Gaps are time outside the harness, not proven thinking time. Tokens are local counts, not provider billing. Bounce and read rates are proxies; compare equivalent instructions."
    )
    unknown = result["incomplete_final_lines"] + result["rpc_traces_without_completed_interaction"]
    if unknown:
        lines.append(
            f"Incomplete final lines: {result['incomplete_final_lines']}; unfinished RPC traces: "
            f"{result['rpc_traces_without_completed_interaction']}"
        )
    return "\n".join(lines)
