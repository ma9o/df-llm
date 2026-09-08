# DF-LLM: adventure-mode harness

Supervised LLM play of Dwarf Fortress through DFHack, using structured state,
ASCII terrain and semantic actions. The controller chooses objectives and
interruption conditions; the harness executes the intermediate steps and verifies
the result. CLI and Python share one client. No MCP server or screenshots are required.

Tested on macOS/CrossOver with **DF 53.16 / DFHack 53.16-r1.1** (2026-09-08),
in the `Steam` bottle, using **127.0.0.1:5001**.

## Start here

From the repository root, install the locked Python 3.12+ environment:

```sh
uv sync --locked
./dfctl guide
```

`guide` is the compact, offline [agent guide](dfharness/guide.md). It covers
observations, dispatch policy, receipts, choices and resume. Load details on demand:

```sh
./dfctl actions             # local action index
./dfctl actions walk_to     # exact JSON schema; underscore name
./dfctl walk-to --help      # CLI flags; hyphenated command
```

With DFHack running:

```sh
./dfctl doctor              # installation and connection checks
./dfctl settings            # read current controller preferences
./dfctl look                # compact scene
./dfctl brief               # character essentials
```

Choose targets from current readings and pass the latest `state_id` as `--expect`.
The guide explains how to delegate completion, handle blockers and resume safely.

## Connect or launch

For a new local installation, configure the loopback port, then start DFHack:

```sh
./dfctl setup --port 5001
./dfctl launch
./dfctl game-status
```

Restart after changing the port; launch only when the game is not already running.
If Steam installs the DFHack hook but does not start DF, use `launch --direct`.
`DF_PATH` selects a custom game installation. The client port follows `--port`,
`DFHACK_PORT`, the discovered game config, then 5000. This Mac uses 5001 because
Control Center occupies 5000. See [connection details](docs/development.md#connection-and-launch)
for discovery, configuration backups and save locations.

## Reference

| Need | Read |
|---|---|
| Routine CLI play | [Agent guide](dfharness/guide.md) or `./dfctl guide` |
| Settings, reads, receipts, policy, resume, Python | [Controller reference](docs/controller.md) |
| Trading, sequences, equipment, movement, combat, travel, save and load | [Gameplay reference](docs/gameplay.md) |
| Comprehensive character state | [Character status](docs/character-status.md) |
| World site search | [World scan](docs/world-scan.md) |
| Local game mechanics lookup | [Offline wiki](docs/local-wiki.md) |
| Passive measurement | [Measurement](docs/measurement.md) |
| Setup, architecture, development tools | [Development](docs/development.md) |
| Tests and known limits | [Tests and known limits](docs/validation.md) |
| What shipped and where its evidence lives | [History](docs/history.md) |

Use `./dfctl capabilities` for runtime support and concrete limitations.

## Development

Follow [AGENTS.md](AGENTS.md). Run offline tests with isolated controller settings:

```sh
uv run --locked python -m tests.run
```

`make check` runs the full checks and package build; it also requires Luacheck and
ShellCheck. See [development setup](docs/development.md#environment-and-checks).
