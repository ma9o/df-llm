# Measuring interactivity

Recording is passive and off by default. Ordinary CLI/Python calls record operation,
episode, outcome, timing, bytes, target IDs and correlated RPC costs. They never
import a tokenizer. Logging failures do not change results or retry game inputs.

## Record

```sh
./dfctl --metrics .df-llm/current.jsonl --metrics-run current --episode room-1 look
./dfctl settings --set '{"measurement":{"enabled":true,"path":"metrics.jsonl","run":"current"}}'
```

Settings accept `enabled`, `path`, `run` and `episode`. Relative saved paths resolve
beside the settings file. Overrides: `--metrics PATH` / `DFLLM_METRICS=PATH`,
`--no-metrics` / `DFLLM_METRICS=off`, `--metrics-run` / `DFLLM_METRICS_RUN`, and
`--episode` / `DFLLM_EPISODE`. Python uses `metrics_path`, `metrics_run` and
`metrics_episode` on `Client`. Explicit arguments override environment and settings.
Legacy saved tokenizer settings are ignored; tokenization is offline.

Use one run per controller and one episode label per instruction. Explicit labels
also split at idle gaps (120 seconds by default) and retain numbered segments.
Clear a saved episode with `{"measurement":{"episode":null}}` for idle grouping.

## Analyze and count tokens offline

```sh
./dfctl metrics .df-llm/current.jsonl --text
./dfctl metrics .df-llm/current.jsonl --baseline .df-llm/baseline.jsonl --text
```

Metrics logs contain no payload text, so new token counts remain unknown until
paired with an explicitly captured full log:

```sh
./dfctl --metrics .df-llm/current.jsonl --log .df-llm/payloads.jsonl look
# Explicit setup only; may download. tiktoken is in the optional analysis extra.
./dfctl metrics --prepare-tokenizer o200k_base
./dfctl metrics .df-llm/current.jsonl .df-llm/payloads.jsonl --tokenizer o200k_base --text
```

Install the `analysis` extra for an installed package (`pip install 'df-llm[analysis]'`).
Repository development dependencies already include it. Preparation stores verified
encoding data under `~/.cache/df-llm/tokenizers` (`DFLLM_TOKENIZER_DIR` overrides).
Offline analysis never downloads missing data. Historical counts keep their named
encoding; uncaptured or missing responses stay unknown, not zero or estimated.
`--log` includes full native traces plus controller input/output; `audit-log` ignores
the controller rows. Matching trace IDs deduplicate metrics and captured payloads.

## Boundaries and interpretation

| Field | Meaning |
|---|---|
| `input_bytes`, `output_bytes` | Canonical Python arguments/return JSON, or CLI argv plus stdin and actual output |
| `duration_ms` | Monotonic response time through CLI flush; excludes process/import startup |
| `measurement_ms` | Final serialization, excluding file append; older records also include tokenizer load |
| `rpc_calls`, `rpc_ms` | All nested native calls, including polls and failures |
| `at`, `finished_at` | Controller interaction interval; Python excludes client construction |

One outer call produces one interaction; internal helpers are not extra controller
calls. Exact token counts describe those payloads under a named encoding, not provider
billing, reasoning, prompts, tool wrappers or source-file reads. Native RPC bytes
are transport costs and are never counted as LLM tokens.

Episode reports separate harness time from gaps. Harness time unions overlapping
intervals; RPC time is already included. Gaps include human pauses, other tools,
scheduling and deliberation, so they are not proven LLM thinking time. Time before
the first call and after the last response is unobserved. `--idle-gap SECONDS`
controls grouping; long deliberation may split an instruction.

Pair output tokens with follow-up reads per dispatch. The report counts observations
between acts, trailing read windows, discovery calls and same-target reissues.
Resumes and duplicate dispatch IDs are separate from bounces. Missing targets,
overlapping calls and unfinished tails remain explicit. These are review signals:
an intentional observation or retry is not automatically a defect. Compare equivalent
objectives and outcome mixes, not bytes alone.

Tests: `uv run --locked python -m tests.run tests.test_metrics tests.test_metrics_report`.
