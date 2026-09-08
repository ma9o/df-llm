# Controller reference

Start with the [agent guide](../dfharness/guide.md). Read a section here when
you need the detailed contract; action schemas remain in `./dfctl actions NAME`.
All shell examples run from the repository root. Machine JSON is minified;
`--pretty` indents it without changing data or execution. `actions sequence`
lists child schemas by reference; `--expand` inlines them.

## Settings

`settings` saves controller preferences in `.df-llm/controller.json`, shared by
CLI and Python, and sends no game input. `--settings PATH` or `DFLLM_SETTINGS`
selects another profile. Settings are reread on every call. Precedence is
built-in, saved, client or CLI constructor overrides, then per-dispatch
overrides. Built-ins are step mode with acknowledgements disabled;
`settings --reset` restores them. Routine observations default to the concise
projection unless a saved `observation_view` says otherwise.

`settings --set '{"dispatch_timeout":45,"result_format":"compact"}'` saves
other preferences. `settings --interrupt-on '{"blood_loss":true}'` saves
interruption conditions; a per-dispatch `interrupt_on` replaces that whole
object. `Client.settings(update=...)` uses the same file.

## Observations

`look` is `observe --view concise`: ASCII terrain, visible units, current
choices, held items, inventory count, burden and the latest four relevant
reports, with explicit omission metadata. Terrain landmarks are inclusive
`[y, x_first, x_last]` spans grouped by z-level, shape and material. Decoded
menus return native choices; unclassified interface states retain UI text.
`observe --view choices` reads only the current menu or prompt.
`observe --view full` retains detailed items, the raw UI buffer and all 80
observed reports. `brief` is the character projection for health, attributes,
skills, equipment, load, movement and needs; `status` is the comprehensive
report described in [character status](character-status.md).

`navigation` omits the site grid unless `--view full` is requested. `items`
accepts `--type` and `--limit` before profiles are built; concise item profiles
omit descriptions, temperatures and attack definitions, which `item ID` and
`items --view full` retain.

Concise `look`, `unit`, `brief`, `navigation` and `items` return a `read_ref`.
Pass it back with `--since REF`, or `since=` in Python, to receive only the
fields that changed. The reference identifies the exact reading and its query
scope; `state_id` remains the input guard. A missing, expired or incompatible
base returns a fresh full reading with a resync reason. The cache holds 32
readings beside the settings file and adds no DFHack calls; a cache failure
returns the full reading rather than retrying the game query. Python can
reconstruct a delta with `dfharness.readings.apply_read(previous, response)`,
which checks both content hashes and preserves null, false, zero and empty
collections.

## Receipts

Actions return compact receipts (`format: compact`, `schema_version: 3`). Read
`values` and `said` first, then `outcome`, field-level `changes` and a concrete
`blocker` when execution is unfinished. `status` is a small readiness snapshot:
position, movement and input readiness, open panels. `dispatch_id` names the
saved diagnostic record, `state_id` guards the next action and `from_state`
identifies the baseline for `changes`. `inputs` counts game inputs. `ticks` is
elapsed local simulation frames when known; travel receipts add
`calendar_ticks`, or `calendar` when the year changes. `--text` renders the same
facts as lines.

`changes` reports inventory, health, visible units, world state and progress as
changed fields only. `changes.progress.xp` is a flat skill delta map using native
total experience; `levels` retains rank changes. Resumed intervals are compared
once. Ordinary need-timer increments are represented by `ticks`; severity
changes, drinking effects and unknown readings stay explicit.

`--after look`, or `after="look"` in Python, appends the final concise scene as
`after`, using the same crop, item radius and report window as `look`. Add
`--since REF` for an exact scene delta. It adds no game input and changes no
policy.

Dialogue replies occur once in `said: [{unit, topic, reply}]`. Choices appear
once when a decision is needed, grouped by native type. Verified
historical-figure subjects appear as `{hf, name}` for
`talk UNIT --topic AskAboutHf --subject-hf-id HF`. Other choices carry short
guarded IDs accepted by `--choice-id`, `select-option` and
`select-interaction`; a changed option set or expired handle is rejected.

`event_detail: task`, the default, counts routine item reports, ambient
conversation and simple animal actions in `omitted.events`. Replies, combat
reports, unknown report types and report types named in interruption
conditions stay visible. `--event-detail all` includes everything. Handled
prompts appear as counts by kind; an unresolved prompt retains its text and
choices.

Acknowledgements cover native adventure announcements and the separate world
popup queue, which blocks input even when the announcement flag is false. Popup
text and count remain visible until acknowledgement is delegated.

`dispatch-details ID --section events` (also `prompts`, `steps`, `summary`,
`compact`, `full`) reads a saved record without executing anything. The session
retains 128 dispatches. `--log PATH` keeps a JSONL trace of every request and
response. `--result-format full` returns the complete diagnostic response.
A duplicate `request_id` returns the original receipt with `replayed: true`.

## Dispatch policy

The controller chooses execution policy per dispatch or sets defaults once. The
same policy applies to item workflows, walking, waits, keys, clicks,
conversations and menus. The harness does not classify their risk.

| Setting | Behavior | Default |
|---|---|---|
| `mode: "step"` | One mechanical step plus delegated acknowledgements, then `in_progress` | `step` |
| `mode: "complete"` | The whole requested workflow, including Finish at a Continue/Stop/Finish prompt | |
| `acknowledge: true` | Handle help and announcement pages, including More and Okay | `false` |
| `max_steps` | Limit on game inputs, including menu navigation and automatic responses | `32`, range 1 to 1,024 |
| `interrupt_on` | Stop on controller-selected facts, checked before every input | `{}` |

Completion and acknowledgement are independent. An undelegated response returns
`needs_input`; unknown prompts return to the controller.

```sh
./dfctl key A_TALK --acknowledge --text
./dfctl resume DISPATCH_ID --mode complete --acknowledge --text
./dfctl interrupt DISPATCH_ID
./dfctl respond continue --text

# Defaults before the command; overrides after an action command.
./dfctl settings --acknowledge
./dfctl --acknowledge key A_TALK --no-acknowledge --text
```

### Resuming

Use the returned `resume` to continue after a step, interruption, limit or
controller decision. It creates a new dispatch ID and never repeats completed
inputs; always resume the latest continuation. A bare `resume` only settles the
current native action and prompts. Each resume uses current settings plus that
call's overrides, so persistent rules belong in settings.

`session` lists the last 128 dispatch IDs in the running DFHack session.
Progress survives controller restarts while the same world and adventurer
remain loaded. Game restart or world reload revokes progress and choice
handles. There is no cross-reload recovery.

### Interruption conditions

`interrupt_on` accepts the booleans `blood_loss`, `new_wounds` and
`new_visible_units`, the lists `visible_unit_ids` and `report_types` (exact
native report types), `new_visible_units_except: [IDS]`, and `unit_health`:

```json
{"unit_health":[{"unit_id":8526,"blood_loss":true,"new_wounds":true}]}
```

Health and visible units are compared with the dispatch's initial observation,
including during processing polls. Native wound IDs detect new injuries even
when the count is unchanged. Up to 32 loaded visible units can be watched.
Reports already returned by a prior dispatch do not interrupt again after
resume. These are factual predicates; a new creature is not classified as
hostile. A requested reading that is missing or unreadable, including during
map offloading, returns `needs_input` naming the unit and condition; it is
never treated as healthy. A match stops further harness inputs; it cannot undo
an injury or cancel an already submitted native action.

`interrupt ID` from another process stops future inputs and preserves progress.
Stopping a native long action still requires an explicit game response.

### Outcomes

| Outcome | Meaning |
|---|---|
| `completed` | Postconditions verified; primitive inputs settled at an input boundary |
| `in_progress` | Step mode returned with more mechanical work to do |
| `needs_input` | A choice, missing native action, blocked route or unsupported completion needs the controller |
| `interrupted` | The controller interrupted, or one of its predicates matched |
| `no_effect` | The input produced no observable change, or a delegated response left the same prompt |
| `limit_reached` | The step budget or dispatch timeout was reached |
| `failed` | The game input handler reported an error; partial effects are possible |
| `rejected` | The supplied state guard was stale before registration; nothing was sent |

A completed raw key or click proves only that input settled; read the resulting
menu and reports. Pre-input rejections carry a short reason, a code and
`input_sent: false`. A stale guard inside a dispatch returns `needs_input`,
keeps the last accepted checkpoint and releases the lease; its `resume`
continues from there. `resync_required` marks stale-state responses. In complete
mode, a stale-state rejection that proves no input was sent triggers a replan
from fresh state, at most three times per dispatch.

Transport failures are tool errors carrying a dispatch ID and a recovery action.
Delivery may have occurred, so observe before retrying anything.

### Diagnostics and processing

Full results include `dispatch.steps`, `dispatch.events`, `dispatch.prompts`
and stage verification records. Dispatches page reports forward from their
cursor, up to 4,096 per page; a cursor reset is reported explicitly. While an
input is processing, polls read only readiness, world identity, new reports and
the controller's requested watches, and never drive input. Visible-unit
enumeration is bounded at 500 units and 32,768 scanned entries; truncation
cannot satisfy a visibility watch.

Strike observers and report watches use scoped `eventful.onReport`
subscriptions with bounded native catch-up. Completed dispatches activate the
installed `advtools.fastcombat` overlay while input processes; the harness never
changes simulation timers. Missing or disabled overlays fall back to normal
execution.

Lua modules load through DFHack's `reqscript` by absolute package path. On
macOS the package parent is reached through CrossOver's `Z:` drive; set
`DFLLM_SCRIPT_PATH` for another layout.

### Timeouts

The dispatch timeout defaults to 30 seconds with a maximum of 300 (`--seconds`
on CLI actions, `timeout` in Python). It is checked between RPC calls and bounds
the RPC waits inside the dispatch. Returning does not cancel an ongoing game
action. An unchanged prompt stops automation instead of sending repeated
continues. The Continue/Stop/Finish mapping is implemented but not yet
verified live.

## Short movement, waits and prompts

`move` verifies arrival at the adjacent tile, preserving its target across map
rebasing. `wait` verifies that the short wait advanced the local frame counter,
or the calendar when no comparable counter exists. Both are valid `sequence`
stages. Missing clock evidence and unchanged position are explicit blockers
that retain the pending input for later verification. `wait-ready` waits for
the game to finish a turn without taking an action.

Read `status.modal` before acting. `{"type":"dismiss"}` acknowledges one help
or announcement page; with `acknowledge: true` a dispatch handles subsequent
pages. `{"type":"action_prompt","choice":"continue"}` answers a long-action
prompt; `stop` and `finish` are also accepted.

## Python client

The CLI delegates to `dfharness.client.Client`; both share actions, validation,
settings, readers and receipts. No API key or model provider is required.

```python
from dfharness.client import Client

game = Client()  # inherits the saved controller settings
view = game.observe(view="concise")
if view["status"]["can_move"]:
    result = game.act(
        {"type": "move", "direction": "w"},
        expect=view["state_id"],
        request_id="one-unique-id-per-intended-action",
    )
```

Pass a returned `resume` action to `game.act` with the latest state guard and
your execution overrides. Persist recurring policy with
`game.settings(update=...)`. DFHack connections are opened per call.
