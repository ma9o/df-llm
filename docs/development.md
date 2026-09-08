# Development and setup

Read [AGENTS.md](../AGENTS.md) for the design rules and legacy adapters. Use
the [agent guide](../dfharness/guide.md) for routine play. Every command's
contract is printed by `./dfctl COMMAND --help`; the source of that text is
`dfharness/reference.py`.

## Connection and launch

DFHack must be loaded in the running game; the window need not be foregrounded.

```sh
./dfctl setup --port 5001   # once per installation
./dfctl launch              # ask Steam in CrossOver to start DFHack
./dfctl game-status
```

If Steam installs the hook but does not start the game, `./dfctl launch --direct`
starts the executable with the installed hook. Do not launch a second instance.

`setup` writes `dfhack-config/remote-server.json` with `allow_remote: false`,
preserves unrelated settings and backs up a pre-existing file. Restart the game
after changing the port. The client always connects to loopback. Port selection
is `--port`, then `DFHACK_PORT`, then the discovered game config, then 5000.
Discovery covers CrossOver Steam bottles and common native Steam paths; set
`DF_PATH` for a custom library. In the tested Windows build, saves live under
the bottle's `drive_c/users/crossover/AppData/Roaming/Bay 12 Games/Dwarf Fortress/save`.

## Environment and checks

The environment is pinned to Python 3.12 and managed by
[uv](https://docs.astral.sh/uv/):

```sh
uv sync --locked
make check
```

`make check` needs [Luacheck](https://github.com/lunarmodules/luacheck).
`make lint-fix` applies safe Ruff fixes and `make format` formats Python.
Vulture scans only the production package and the executable shims, so a
definition referenced only by a test is reported as dead. Lua is checked as 5.3
with DFHack's globals from `.luacheckrc`.

Pinned read-only clones of dfhack, df-structures and scripts for 53.16-r1.1
live under `.df-llm/upstream/`; see its README. Known gaps in that release:
`computeMovementSpeed` is a stub, the installed `quicksave` is fortress-only
and `load-save` uses obsolete title fields. The repository supplies its own
burden helper, an adventure quicksave extension and a repaired loader. Do not
work around gaps with binary-specific models.

### Tests

`uv run --locked python -m tests.run` runs the offline Python suite with
isolated controller settings and metrics disabled, so saved gameplay policy and
fixtures cannot contaminate each other. Append a module to run part of it, for
example `tests.test_dispatch -v`. `tests/test_reference.py` enforces that every
CLI command and argument documents itself.

`python3 -m tests.live_character_status --port 5001` checks the CLI and Python
character queries against the running adventurer, verifies that game time,
input serial, health and inventory are unchanged, and runs the isolated Lua
fixtures under `tests/*.lua` inside DFHack. `--fixtures-only` runs the fixtures
while someone is playing. The fixtures send no game input and do not insert or
injure units.

### Measurement

Passive measurement is off by default. It records operation, outcome, timing,
bytes and correlated RPC costs per controller call, never payload text, and
never changes execution. Enable it with
`./dfctl settings --set '{"measurement":{"enabled":true,"run":"NAME","episode":"LABEL"}}'`
or per process with `--metrics PATH`; `--no-metrics` disables it. Reports and
offline token counting are described by `./dfctl metrics --help`; tiktoken is
in the optional `analysis` extra and is prepared explicitly, never during play.

### Local game reference

A searchable source mirror of the Dwarf Fortress wiki lives at `.df-llm/wiki/`:
articles, templates, categories and module source, each file headed by its
revision URL and date, with coverage recorded in `manifest.json`.

```sh
rg -n -i 'stun|pain' .df-llm/wiki/articles/Ettin.wiki
uv run python tools/mirror_wiki.py            # create or resume the copy
uv run python tools/mirror_wiki.py --refresh  # explicit update only
```

The downloader uses the read-only MediaWiki API with `maxlag` and pauses, and
resumes from its last committed batch. Use the local copy first and cite the
file; wiki text is reference material, not execution policy.

## Architecture

```mermaid
flowchart LR
    L[LLM] -->|CLI or Python| P[Python client]
    P -->|localhost TCP, DFHack RPC| D[DFHack inside CrossOver]
    D -->|DFHack APIs, native actions, menu inputs| G[Running Dwarf Fortress]
    G -->|Character layer and structured state| D
    D -->|JSON observation| P
```

- **Observation.** The Premium UI character layer plus a bounded semantic ASCII
  map centered on the adventurer. Visibility and creature hiding use DFHack
  APIs. Health values are raw game counters.
- **Input.** Actions use DFHack APIs and native action structures where they
  exist, then menu adapters through `gui.simulateInput()` with named interface
  keys and mouse input. The harness never teleports units, spawns items or edits
  character state.
- **Synchronization.** Each request runs under DFHack's core suspension. An
  action schedules a callback after two frames, and the client polls until it
  has run and adventure mode is taking input again. Waits, sleep, long actions
  and site offloading affect readiness. The suspension is released between
  requests.
- **Dispatch.** One shared Python driver applies the controller's policy after
  every input. Recipes verify item IDs, roles, container membership and
  positions. One active-dispatch lease serializes inputs across clients.
  Workflow progress is checkpointed in the DFHack session before each input so
  a lost reply can be verified on resume.
- **Guards.** Movement requires the default local view, input readiness, no
  open panels and no blocking prompt. The `n2:` state token covers native
  context, option identities and order, targets, filters, prompts, scroll,
  character health and inventory, visible units, report cursor, position,
  coordinate frame, time and action serial. Full observations also expose
  `ui_state_id` (`u2:`) for raw UI inputs. Guards run inside the request that
  sends input.
- **Retries.** An explicit `request_id` deduplicates within the last 128 root
  dispatches; reusing it with different arguments fails. A duplicate returns the
  recorded result with a fresh observation and sends nothing. Uncertain delivery
  is never retried. Input errors can have partial effects, so errors direct the
  caller to observe.
- **Logging.** `--log PATH` or `Client(log_path=...)` records requests,
  responses, timestamps and latency as JSONL, including processing polls.
  `./dfctl audit-log PATH` summarizes such a log offline.

Two coordinate systems exist. `Uyy|` rows are UI character cells, with x as the
zero-based offset after the bar. `Myy|` rows are map crop cells; add the crop
origin for the local world tile. Map cells are not click coordinates. Local
coordinates change when a different area loads; observe again after travel.

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
`game.settings(update=...)`. Python controllers can reconstruct a `--since`
delta with `dfharness.readings.apply_read(previous, response)`.

## Burden helper for DFHack scripts

Capacity, load penalty and burden come from the repository's read-only DFHack
Lua helper `dfharness/burden`, which uses `getPhysicalAttrValue`,
`getEffectiveSkill`, `item:isArmor()` and mapped inventory fields in one bounded
pass over root inventory caches. Other DFHack scripts can call it directly:

```lua
local helper = dfhack.reqscript('Z:/Users/ma9o/Desktop/df-llm/dfharness/burden')
local load = helper.getBurden(dfhack.world.getAdventurer())
-- load.capacity, load.load_penalty, load.burden
```

Use your package's absolute path, or install the helper alone under
`hack/scripts/dfharness/`. Do not register the repository root as a script
search path.

## Raw UI operations

Raw operations are development tools, not controller actions:

```sh
./dfctl keys A_INV
./dfctl choose 'a unique visible label' --text
./dfctl click 98 15 --text
./dfctl text 'some text'
./dfctl key A_TALK --text
./dfctl select-unit 4232 --text   # only inside the conversation creature picker
./dfctl run COMMAND ARG...        # any DFHack console command
./dfhack-run COMMAND ARG...
```

Always use a fresh observation for coordinates and labels. A label must match
exactly one place in the character layer; if it repeats, click the intended
occurrence by coordinates.

## History and evidence

[history.md](history.md) lists what shipped and where each change's evidence
lives. Local traces, measurements and the longer review write-ups are kept
under `.df-llm/`, which is not tracked.
