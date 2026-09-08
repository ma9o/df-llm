# Tests and known limits

Runtime support for the running game comes from `./dfctl capabilities`. This
page covers the test suites and the limits that shape what the controller can
expect. Development setup is in [development](development.md).

## Offline suite

`uv run --locked python -m tests.run` runs the offline Python suite with
isolated controller settings and metrics disabled, so saved gameplay policy and
fixtures cannot contaminate each other. Append a module to run part of it, for
example `tests.test_dispatch -v`. It covers the RPC protocol, argument
validation, policy precedence, delegated prompt chains, execution limits, event
retention, resumption and duplicate requests, item and equipment recipes,
composition, interruption predicates, receipts and read deltas. `make check`
adds lint, formatting, types, dead code, Lua and shell checks and the package
build.

## Native suite

`python3 -m tests.live_character_status --port 5001` checks the CLI and Python
character queries against the running adventurer and verifies that game time,
input serial, health and inventory are unchanged. It also runs the isolated Lua
fixtures under `tests/*.lua` inside DFHack: anatomy and wound mapping, effective
stats, truncation, container accounting, cache validity, menu bindings,
conversation and combat readers, report events, pathing, saving and loading,
barter and exchange, and session lifetime. `--fixtures-only` runs the fixtures
while someone is playing. The fixtures send no game input and do not insert or
injure units.

## Known limits

- Single aimed melee attempts are semantic; defense, wrestling, charge,
  multiattack and ranged combat are not. Character creation needs raw controls.
- Trade supports held items and currency; containers and contained rows are
  unsupported. The Trade button lookup needs English UI text.
- Wells and ground-container drinking are unsupported. Live until-dawn
  completion has not been observed. The Continue/Stop/Finish response mapping is
  unverified live.
- The character layer can contain duplicate or residual text and omit icon-only
  controls; DFHack focus strings do not describe every prompt. Check resulting
  game state rather than trusting text alone.
- The semantic map is a single z-level summary with creatures and building
  occupancy. Visibility checks are useful for play, not a strict information
  boundary.
- Nearby item queries default to radius 20 (maximum 50), four nested container
  levels and a 500-item budget; inventory reads have a 300-item budget.
  Truncation is reported.
- Native walkability comes from DF's cached groups and can be stale; movement
  still verifies arrival.
- Fit and capacity conflicts, quantity pickers and unrecognised choices return
  `needs_input`. Equipment replacement is resumable but does not roll back a
  partial change.
- Interruption predicates stop future harness inputs; they cannot undo an
  already submitted native action or recover discarded reports.
- Crafting, performances, abilities and companion orders are not implemented.

References: [DFHack remote interface](https://docs.dfhack.org/en/stable/docs/dev/Remote.html),
[DFHack Lua API](https://docs.dfhack.org/en/stable/docs/dev/Lua%20API.html).
