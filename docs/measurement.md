# Measuring interactivity

The measurement layer records the cost of controller interactions without
changing their payloads, execution policies or game inputs. It is off by default.
Failures to count tokens or append a log do not retry an action or turn a
successful query into an error. Diagnostics go to stderr, never MCP stdout.

## Recording and episode identity

```sh
./dfctl metrics --prepare-tokenizer o200k_base
./dfctl settings --set '{"measurement":{"enabled":true,"path":"metrics.jsonl","run":"baseline","episode":"drop-backpack-and-strike-1"}}'
./dfctl mcp
```

Saved measurement settings refresh across CLI processes and existing Python/MCP
clients. `path` defaults to `metrics.jsonl` beside the controller settings file;
relative saved paths resolve there. `run` names a controller session/comparison
cohort. `episode` identifies one instruction within that run. Use a unique label
per instruction, within one game/world, and a separate run for each controller.
Explicit labels group across idle gaps. Clear the label using
`{"measurement":{"episode":null}}` for inferred episodes.

| Setting | Process override | Python constructor |
|---|---|---|
| `enabled`, `path` | `--metrics PATH`, `DFLLM_METRICS=PATH` | `metrics_path=Path(...)` |
| Disable | `--no-metrics`, `DFLLM_METRICS=off` | `metrics_path=False` |
| `run` | `--metrics-run LABEL`, `DFLLM_METRICS_RUN` | `metrics_run="baseline"` |
| `episode` | `--episode LABEL`, `DFLLM_EPISODE` | `metrics_episode="fight-1"` |
| `tokenizer` | `--tokenizer NAME` | `tokenizer="o200k_base"` |

Explicit process/constructor values override environment, then saved settings.
An explicit path enables recording without changing saved settings. Disable
saved recording with `{"measurement":{"enabled":false}}`.

MCP controllers can set the episode through the existing `df_settings` tool:

```json
{"update":{"measurement":{"enabled":true,"run":"baseline","episode":"room-1"}}}
```

That settings call itself starts under the previous configuration; subsequent
calls use the new label. The measurement report is an offline CLI operation;
it adds no controller tools or gameplay round trips.

## Local tokenizer preparation

Preparation uses the installed tiktoken encoding definitions and their verified
asset downloads. It saves constructor data locally, without copying a model's
token patterns into the harness. Runtime counting constructs `tiktoken.Encoding`
from that file and never calls the library's downloading registry. Files live
under `~/.cache/df-llm/tokenizers`, overridable with `DFLLM_TOKENIZER_DIR`.
After changing tiktoken versions, explicitly prepare the encoding again.

Missing/corrupt data leaves token counts null, with a counted failure; byte and
duration measurements still work. No approximate character-to-token ratio is
substituted. CLI processes still pay local tokenizer loading cost, recorded as
`measurement_ms`. A persistent MCP/Python client caches the encoding in memory.
Encoding and package versions are retained for comparisons.

## What is measured

Each outer controller call has one `interaction` record; its nested native calls
have `rpc` records with the same `trace_id`. Python aliases and the methods used
inside a dispatch do not become additional controller calls. An optional full
`--log` trace includes that trace ID for diagnosis; measurement logs store no
payload text. Bounded action types, numeric target IDs/coordinates, sequence
intents, dispatch/resume IDs, outcomes and error codes support episode analysis.

| Field | Boundary |
|---|---|
| Input bytes/tokens | Canonical Python arguments, MCP params, or CLI argv plus stdin |
| Output bytes/tokens | Canonical Python return JSON, actual CLI output, or MCP tool text |
| `duration_ms` | Monotonic time to response production, including CLI/MCP output flush and MCP worker queueing |
| `measurement_ms` | Final serialization/token counting, including a cold local encoding load; excludes the JSONL append |
| `at`, `finished_at` | Start and end of the measured interval, including token counting |
| `rpc_calls`, `rpc_ms` | Native calls beneath the interaction, including readiness polls and failures |
| RPC bytes | Lua request source and command output, excluding protobuf framing |

No internal RPC token counts are added to controller tokens. Errors with a CLI
or MCP response measure that response; a Python exception without a returned
payload has unknown output tokens. Trace records can remain without a finished
interaction if a process is terminated. Reports count these unfinished traces.

These are payload counts under the selected encoding, not provider input/output
usage. Model prompts, reasoning, source-file reads, tool wrappers, and other
applications are outside this boundary. Python excludes client construction;
CLI excludes interpreter/import startup. Setup, raw development commands,
offline reports and CLI parse errors do not create interaction records.

## Episode reports

```sh
./dfctl metrics .df-llm/current.jsonl --text
./dfctl metrics .df-llm/current.jsonl --run current --idle-gap 120
./dfctl metrics .df-llm/current.jsonl --baseline .df-llm/baseline.jsonl --text
```

Without an explicit episode label, a gap of more than `--idle-gap` seconds
between measured intervals starts an episode within that run. Default: 120
seconds. Explicit labels override that heuristic; a long deliberation can split
an unlabeled instruction, and several short instructions can merge. Historical
timestamps cannot reconstruct the user's original instruction identity.

The wall interval spans the first recorded start through the last measured
finish. Harness time is the union of measured intervals, so overlapping calls
are not added twice. Child RPC times are already inside those intervals. Gap
time is the remainder: time outside the measured harness, including controller
deliberation, other tools, scheduling and human pauses. It is not a measurement
of LLM thinking. Unseen time before the first call and after the last call is
not included. Old records infer finish from duration plus tokenizer overhead;
missing or inconsistent timestamps are counted as ungroupable calls. Summed
episode wall times are per-objective costs, not a deduplicated session wall clock.

Follow-up reads are observation calls after a dispatch's response and before
the next dispatch. Reports pair their count and tokens with the preceding
receipt's output tokens. Reads while a dispatch is running are excluded;
trailing reads are separate open windows. Intentional observation also counts,
so this is a signal to inspect receipt adequacy rather than proof of a defect.
`actions` and `capabilities` counts provide a separate discovery/relearning proxy.

A bounce is a non-completed targeted dispatch followed by the same action type
and native target in that episode, including a reissue inside a sequence.
Sequence blockers identify the active objective, not completed stages. Weapon
and strike style changes do not change the attacked creature's identity.
Explicit resumes and same-dispatch redeliveries are counted separately. A
same-target retry is a diagnostic proxy, not proof of a prerequisite bug or an
unnecessary action. No new actions or reads are issued to establish a match.

The bounce-rate denominator contains assessable non-completed calls with a
later dispatch. Unknown target metadata, ambiguous legacy follow-ups,
overlapping calls and open tails are counted separately. Old records contain
action types but no targets, so their same-target bounce rate is unavailable.
Targetless actions do not establish a targeted bounce. Token totals remain
separate by encoding, with known sums and unmeasured counts.

Baseline comparisons show per-call means for matching surfaces, operations,
action types, output formats and encodings, plus per-episode costs, read rates
and bounce rates. These are descriptive comparisons: use equivalent
instructions, settings and grouping thresholds. Lower token counts alone do
not prove an improvement. Sample counts, outcome mix and coverage remain visible.

## Verification

`uv run python -m tests.run tests.test_metrics tests.test_metrics_report -v`
covers boundaries on all three surfaces, correlated native calls and errors,
passive failure isolation, concurrent appends, offline tokenization, timing
overlaps, legacy records, follow-up reads, bounces/resumes and comparisons.
