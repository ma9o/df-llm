# Harness design instructions

These instructions apply throughout this repository. For routine CLI play, load
`./dfctl guide`; exact action schemas come from `./dfctl actions NAME` and CLI
flags from `./dfctl COMMAND --help`. Routine play never requires this document.

## Product intent

This harness supports supervised LLM play of Dwarf Fortress adventure mode
through DFHack, using structured state, ASCII terrain and semantic actions.
Production control never depends on screenshots. The controller is an agent with
the game's affordances, not a keypress player: it chooses objectives, targets and
interruption conditions. The harness executes the mechanics through the
highest-level interface that exists, verifies the result from native state, and
reports the game's own refusals as facts.

## The test for every change

A change must alter what the controller can see or do, or raise a recipe's
completion rate on a live playtest. Bytes over loopback, RPC counts and internal
payload sizes are not goals. Do not build adapters for capabilities that cannot
execute; list them as unsupported in `capabilities`. Prefer removing an option to
maintaining an adapter for it.

## Controller owns policy, harness owns mechanics

- The controller chooses the action, item and unit targets, equipment
  replacements and their disposition, route constraints and interruption
  conditions. The harness never chooses an upgrade, infers hostility or invents
  a risk policy.
- The harness owns approaching a target, opening and scrolling menus, selecting
  native options by ID, handling delegated prompts, waiting for effects and
  verifying postconditions. Expose these as semantic dispatches.
- The controller decides whether a dispatch returns after one step or runs to
  completion, per dispatch or through saved settings. The harness never
  classifies an action as risky to override that choice. A modal is interface
  state: handle it when its response is delegated, otherwise return its
  structured choices.
- A sequence shares one policy, input budget, event history and checkpoint. A
  stage advances only after its postcondition is verified.
- Name actions for the gameplay result and resolve determined prerequisites
  inside them, such as removing worn equipment before dropping it. A missing
  native option is a factual blocker, not a list of guesses.
- Decode the scope of a native option before selecting it. A broader operation,
  such as a drop that empties the owning container, is its own objective and is
  never chosen for a narrower request.
- The controller interface is the Python client with the CLI front end. There is
  no MCP server. Action schemas live in the shared `actions` reference.

## Execution ladder

Take the highest rung that exists for the action:

1. A DFHack API function or shipped script.
2. The native action and choice structures the game's own handlers fill, such as
   movement commands, unit actions and conversation choices.
3. Native menu hotkeys, with the menu, target and scroll bounds validated from
   fresh state inside the request that sends input.
4. A guarded UI adapter: a semantic dispatch may click a control located uniquely
   in the current character layer after validating native context, target and
   pending selections. Never fixed coordinates or screenshots.

Arbitrary raw keys and clicks remain development operations. Postconditions are
verified from native state whichever rung executed the action.

## Only the game changes the game

Submission goes through the game's own processing. Never set an outcome, move a
unit, edit a wound, refresh a cache or skip a native refusal. What the game
rejects through its handlers is rejected here and reported as a fact. Do not
reimplement pathfinding, clocks, rest loops or combat resolution: supply the
target, bound the wait, watch the controller's predicates, verify the result.

## Support comes from DFHack

- The support gate is "DFHack exposes it". No disassembly listings, executable
  offsets, binary signatures or PE-timestamp gates. When a field or handler is
  missing, extend DFHack within the task using named df-structures fields, in a
  form suitable for an upstream contribution.
- Pinned read-only clones of dfhack, df-structures and scripts live under
  `.df-llm/upstream/`. Consult them before the executable.
- Reuse DFHack's calculations and tools: burden and speed helpers, walkable
  groups and reachability, item capacity and weight, save and load scripts,
  eventful report subscriptions, and the fastcombat overlay under completion
  policy. The values the game acts on, such as the HUD burden state and native
  cached loads, are authoritative. An estimate may accompany them, never replace
  them.
- Load repository modules by absolute package path. Never register the
  repository root for recursive script discovery.
- Fixture-only sandbox edits stay in a separate save. Restore the campaign
  checkpoint after testing.

## Guards, lifetime and honesty

- Guard known interfaces with native context, option identities and order,
  target IDs, filters, prompts and relevant character state. Keep text guards
  only for undecoded interfaces and raw UI inputs.
- Read only the fields owned by the active native mode. An inactive pointer can
  refer to freed state even when its field is readable.
- Dispatch progress lives in the DFHack session memory of the loaded world. It
  survives controller restarts while the same world and adventurer remain loaded.
  World reload or game restart revokes progress and every choice handle. A local
  map reload is not world replacement.
- Input delivery is not completion. Report whether a dispatch completed, needs a
  controller choice, hit a limit, was interrupted or failed. Never claim
  unverified success or silently substitute another execution mode.
- Never replay an input whose delivery is unknown. A failed verifier keeps its
  pending marker so an explicit resume re-verifies instead of re-sending. Bounded
  replanning is allowed only after a native stale-state rejection that proves no
  input was sent.
- Interruption predicates are the controller's facts: player health, named
  units, new visible units and report types. A missing requested reading is a
  blocker, never a healthy default.
- Attributions derived from text, such as report wording or English button
  labels, are labelled as such in results.

## Response contract

- Design receipts around the controller's next decision, with one outcome
  vocabulary across all actions.
- Return changed fields, not whole entities. Objective results go in `values`,
  replies once in `said`, one grouped choice list when a decision is needed, and
  concrete blockers with bounded `facts`.
- Preserve false, zero, unknown and truncation. Concise projections mark what
  they omit.
- Complete events, prompts and traces stay behind `dispatch-details`; compact
  receipts never repeat them.
- `status` is the comprehensive read-only character query. `brief` and `look`
  are projections that skip unread profiles at the native reader rather than
  discarding them afterward.
- Test representative completed, blocked and resumed receipts for content,
  duplication and size, not only for whether the input succeeded.

## Measurement, tests and reference material

- Measurement is passive and off by default: operation, outcome, timing, bytes
  and correlated RPC costs, never payload text. Tokenization runs offline.
  Logging failures never change execution.
- Run offline tests with `python -m tests.run`. It isolates controller settings
  and disables metrics.
- Use `.df-llm/wiki/articles/` as the first reference for game mechanics and
  cite the local file. Go online only for a gap the local copy cannot answer.

## Documentation

- `dfharness/guide.md` is the controller's entry point and stays short. `docs/`
  holds contracts: what a command does, its flags, receipt fields, limits and
  unsupported cases.
- Evidence does not live in `docs/`. Measurements, live-check narratives and
  pass counts go in commit messages, with artifacts under `.df-llm/`.
  `docs/history.md` records what shipped and where its evidence lives, one short
  entry per change.
- No dated review documents in the repository. No version bump without an
  external consumer.
- Prefer deleting a rule to explaining it. A constraint that guards one code
  path belongs in a comment or test beside that code, not here.

## Legacy code

Do not extend these. Remove each entry when its code is gone.

- `character_calculations.lua`: PE-timestamp-gated need and movement models,
  loaded on the observation path. Replacement requires working DFHack helpers;
  `computeMovementSpeed` is a stub in the pinned 53.16-r1.1 reference. Its
  provenance note is kept locally at `.df-llm/reviews/character-calculations.md`.
- `routing.py` and the observed-route branch of `next_walk`: retained only for
  the explicit `allow_occupied`, `max_liquid_depth`, `blocked_tiles` and
  `extend_route` options. Ordinary movement uses the native path command.
  Removing those options removes this adapter.
- The strike native observer and per-tile walking polls, once native action
  submission covers them.
- The `.df-llm/*.asm` listings and every offset cited anywhere: evidence of past
  verification, not a support basis.
