# History

What shipped, in order, and where the evidence lives. Detailed review write-ups
and the original long-form docs are kept outside the repository under
`.df-llm/reviews/`. They are local artifacts, not required reading.

## 2026-09-06

- **Initial harness.** Direct DFHack RPC from macOS to the Windows Steam build,
  observations from the Premium character layer plus a semantic ASCII map, raw
  keys and clicks, conversation target selection, comprehensive character status.
  Evidence: `.df-llm/reviews/CONVERSATIONS.md` (eleven conversations, 33 matched
  replies), `.df-llm/conversations.jsonl`.
- **Quality tooling.** Ruff, ty, vulture, luacheck, shellcheck and `make check`.

## 2026-09-07

- **0.23, adventure control.** Semantic item and equipment recipes, sequences,
  controller interruption predicates, receipts with XP deltas, passive metrics.
  A 521-input training sequence stopped at input 182 on a new visible unit and
  completed through explicit resume. Evidence:
  `.df-llm/reviews/playtest-2026-09-07.md`, `.df-llm/play-metrics.jsonl`,
  `.df-llm/leveling-trace.jsonl`.
- **0.24, native paths.** Local walking submits `adventure_movement_pathst`;
  the constrained observed-route adapter remains only for explicit route options.
  An eight-tile walk took one input and nine RPCs instead of eight inputs and 36.
  The `travel_goal_*` names are `long_action_duration` and `travel_start_*`, not
  a waypoint API. Evidence: `.df-llm/reviews/pathing-review-2026-09-07.md`,
  `.df-llm/pathing-trace.jsonl`.
- **0.25, DFHack reuse.** Eventful `onReport` subscriptions at frequency one for
  strike observers and report watches; the fastcombat overlay activated under
  completion policy; `onUnitAttack` found to miss adventure hits; modules loaded
  by absolute path so reference clones no longer register as duplicate overlays.
  Evidence: `.df-llm/reviews/dfhack-reuse-review-2026-09-07.md`,
  `.df-llm/integration-trace.jsonl`.
- **0.26, read efficiency.** Concise `unit`, `--since` read deltas, the MCP
  server removed, save-scoped checkpoints added and later removed. Evidence:
  `.df-llm/reviews/read-efficiency-review-2026-09-07.md`,
  `.df-llm/read-comparison.json`.

## 2026-09-08

- **0.27, world and site reads (started 2026-09-07).** `world-scan`, `shops`, market-flag search and
  enlarged travel map tracking.
- **Token efficiency.** Minified JSON by default, navigation grid omitted at the
  native reader, item catalog filters, `--after look`, `move` and `wait` as
  sequence stages, travel blocker facts, the DFHack quicksave adventure extension
  and a repaired `load-save`. Evidence:
  `.df-llm/reviews/token-efficiency-review-2026-09-08.md`,
  `.df-llm/reviews/token-efficiency-implementation-2026-09-08.md`,
  `.df-llm/token-efficiency-*.json`.
- **Cleanup.** Save-scoped checkpoint persistence removed in favour of in-memory
  progress; the classic-render capture, the `record_dispatch` op and world-scan
  worker processes removed; tokenization moved offline with tiktoken as the
  optional `analysis` extra, taking a CLI call from 231 ms to 68 ms; trade
  submission through a guarded character-layer Trade button with native
  transfer verification, exercised live with one refusal, one purchase and one
  sale. A transport-delta A/B with three samples per mode overlapped in timing
  and deltas were retained. Evidence: `.df-llm/cleanup-merchant-20260908.jsonl`,
  `.df-llm/transport-ab*.json`, `.df-llm/cleanup-measurement-*.json`.
- **Documentation consolidated.** Dated reviews and the calculation provenance
  note moved to `.df-llm/reviews/`, AGENTS.md reduced to principles, reference
  docs trimmed to contracts. The pre-trim docs are under
  `.df-llm/reviews/docs-before-trim-2026-09-08/`.
- **Shop armor lookup.** `shops --stock` resolves armor materials from native
  production allotments for shops and markets, without visiting each seller.
  Exact item quality, fit and current availability remain separate reads.
  Evidence: `.df-llm/shop-armor-lookup.json`, `.df-llm/shop-stock-fixtures.json`.
- **World material stock search.** `world-scan --material` reads persistent
  resources at unloaded sites and identifies matching available shop sale records.
  Imported materials follow their source production catalog. Evidence:
  `.df-llm/steel-search/`.
- **Contracts moved into the CLI.** Every command's summary, contract and
  argument help live in `dfharness/reference.py`, printed by `COMMAND --help`
  and `actions NAME`, with a test enforcing coverage. The controller, gameplay,
  character-status, validation, world-scan, measurement and local-wiki docs were
  folded into that text, `capabilities` and `development.md`.
