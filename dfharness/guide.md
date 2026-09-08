# dfctl agent guide

Run `./dfctl` from the repository root, or installed `dfctl` from any directory.
The CLI uses the Python client and DFHack; no MCP server or screenshots are needed.
`guide` prints this file offline, without reading settings or writing metrics.

## Read, choose, dispatch

Start with `./dfctl settings` to read your policy and `./dfctl look` for the scene.
The game must be running with DFHack; use `./dfctl doctor` if connection fails.
JSON is minified by default; `--pretty` indents it. Observations/actions also accept `--text`.

| Need | Command after `./dfctl` |
|---|---|
| Scene, visible units, choices, held items | `look` |
| Self: health, needs, equipment, skills | `brief` |
| Target condition and body-part IDs | `unit ID` |
| Item catalog; one item and its attack indices | `items --type ARMOR --limit 20`; `item ID` |
| Current menu/prompt only | `observe --view choices` |
| Readiness only; comprehensive character | `game-status`; `status` |
| Travel destinations; shop stock and armor materials | `navigation`; `shops --stock` |
| Merchant's specified Shop catalog | `open-trade UNIT --shop ZONE`; `barter --type ARMOR`; `close-trade` |
| Named checkpoint; load from title screen | `quicksave NAME`; `quickload NAME` |

Choose objectives, targets, replacements and interruption conditions yourself.
The harness handles approaches, prerequisites, menus and result verification.
Use one active dispatch at a time.

Load details only when needed:

```sh
./dfctl actions              # local action index
./dfctl actions walk_to      # exact JSON schema; names use underscores
./dfctl walk-to --help       # CLI syntax; commands use hyphens
./dfctl capabilities         # live support and limits
```

`actions sequence` references child schemas; `--expand` includes them all.
`trade` submits explicit item quantities and currency; read `actions trade` first.
Quicksave requires `--overwrite` for an existing name. Quickload is a development
operation from the title screen; it does not exit a running adventure.

## Set delegation explicitly

`step` returns after one mechanical step; `complete` runs the requested objective.
Built-ins: `step`, no automatic acknowledgements, 32 inputs, 30 seconds.
To delegate completion and routine acknowledgements, persist your choice:

```sh
./dfctl settings --mode complete --acknowledge --view concise
```

Settings live in `.df-llm/controller.json`, shared with Python. Global
`--settings PATH` selects another profile. Action flags override saved settings:
`--mode step|complete`, `--acknowledge` / `--no-acknowledge`, `--max-steps N`
(1..1024), `--seconds N` (up to 300), `--interrupt-on JSON`.
For example, `--interrupt-on '{"blood_loss":true,"new_wounds":true}'` delegates
those stops. This object replaces saved interruption rules; include every rule
you want. Complete mode includes Finish action; acknowledgements are separate.
Undelegated choices return control.

## Send an objective

Use current IDs/coordinates and the latest `state_id` as `--expect`.
Numbers below are illustrative; uppercase words are placeholders.

```sh
./dfctl walk-to 70 68 128 --expect STATE_ID --mode complete
./dfctl act '{"type":"pickup","item_id":123}' --expect STATE_ID
./dfctl sequence - --expect STATE_ID --mode complete < steps.json
```

`act` accepts one action object, or `act -` reads it from stdin. `sequence`
accepts an array of action objects; stages share policy, budget and a checkpoint.
`move` and short `wait` are valid stages. Completed stages survive resume. Coordinates refer to its
initial map. Global flags such as `--settings`, `--port`, `--log` and `--episode`
go before the command; action overrides go after it.

## Read the receipt, then decide

Read `values` (objective results), `said` (replies), `outcome`, `changes`,
`blocker` and any `choices`. Completion of a strike attempt does not imply a hit.

| `outcome` | Next step |
|---|---|
| `completed` | Assess results and choose the next objective. |
| `in_progress`, `limit_reached`, `interrupted` | Assess the reason; continue with returned `resume` if desired. |
| `needs_input` | Resolve the concrete blocker or select a supplied choice. |
| `rejected` | Refresh state and reconsider; no input was sent. |
| `no_effect`, `failed` | Inspect evidence; input may have executed. |

When supplied, send the returned `resume` object through `act`, or use
`./dfctl resume DISPATCH_ID`. Each continuation has a new ID; use the latest.
Resume uses current settings and call overrides, so reapply temporary policy.
Bare `resume` only settles current native activity; it does not recover a workflow.
Use fresh choice handles with `select-option ID`, `select-interaction ID` or
`talk UNIT_ID --choice-id ID` as appropriate. Missing options are factual blockers.

After a timeout/lost reply, read `look` before explicitly resuming; never blindly
repeat uncertain input. `session` finds recent in-memory dispatch IDs; `dispatch-details ID`
reads their evidence. `interrupt ID` stops further harness inputs without undoing
input already sent.
Game restart or world reload revokes progress; controller restarts do not.

## Keep follow-up reads small

Receipts include changes; query only missing facts. `look`, `unit ID`, `brief`,
`navigation` and `items` accept `--since READ_REF` for exact deltas.
`read_ref` identifies content; `state_id` guards input. An expired/incompatible
base returns a full reading. Omitted, unknown and truncated fields are explicit.
`navigation` skips the site grid; `items` skips detailed item profiles. Request
`--view full` when needed. Add `--after look --since READ_REF` to an action to
receive its final scene inside `after`, avoiding a separate look call.

For evidence: `dispatch-details ID --section events|prompts|steps|full` (choose
one). Retention is 128 dispatches; `--log PATH` preserves a JSONL trace.
Use `observe --view full` / `--result-format full` for diagnostics; raw keys and
clicks are development tools. More policy/recovery details:
[controller reference](../docs/controller.md#dispatch-policy). Mechanics reference:
`.df-llm/wiki/articles/` (search locally with `rg`).
