# Harness design instructions

These instructions apply throughout this repository.

## Product intent

This harness supports supervised LLM play of Dwarf Fortress through DFHack,
using ASCII and structured observations and actions. Production control must
not depend on screenshots. Supervised play should still automate routine
interaction so the controller does not spend a decision on every UI step or
game timestep.

The controller is an agent with the game's affordances, not a keypress player.
The harness drives the game through the highest-level interface that exists
for an action, verifies the result from native state, and treats the game's
own rules and refusals as facts to report rather than rules to reimplement.

## The controller owns dispatch policy

- The **controller chooses the action and assesses threats**. It selects item
  and unit targets, equipment replacements, the disposition of replaced items,
  route constraints, and any interruption conditions. The harness must not
  choose an upgrade, infer hostility, or invent a risk policy on its behalf.
- The **harness owns execution mechanics**: approaching a specified target,
  opening and scrolling menus, selecting the correct native option by ID,
  handling delegated prompts, waiting for effects, and verifying the requested
  postconditions. Expose these as semantic dispatches instead of requiring the
  controller to script each UI interaction.
- The **controller decides how far each dispatch should execute**: return after
  an incremental step, or run the requested action through to completion.
  This choice can be supplied per dispatch or through controller configuration.
- The **harness implements that choice**. It must not independently classify
  actions as low risk or high risk and use that classification to decide whether
  to finish them, require incremental continues, or return control.
- When the controller requests completion, the harness should execute the
  necessary intermediate steps without repeated controller decisions. This
  includes multi-timestep actions and prompt responses covered by the supplied
  policy, such as routine acknowledgements or choosing Finish action.
- A modal is an interface state, not inherently a reason to require supervision.
  Handle it automatically when the controller's policy delegates its response.
  If it requires a choice that has not been delegated, return its structured
  state and available choices to the controller.
- Apply this separation consistently across the harness: movement, waiting,
  conversations, menu navigation, long actions, and future capabilities. Avoid
  feature-specific rules that silently override the controller's dispatch policy.
- Make gameplay objectives composable. A sequence shares one dispatch policy,
  input budget, event history and resume checkpoint; each stage advances only
  after its declared postcondition is verified. A new screen alone does not
  create a new controller decision when the requested objective determines it.
- Name actions for the requested gameplay result. Resolve determined
  prerequisites inside the dispatch: dropping or stowing worn equipment includes
  removing it first. Keep meaningful choices about targets and tactics with the
  controller. A missing native option is a factual blocker, never a list of
  speculative causes or an empty controller choice list.
- Keep the controller interface in the Python client with a CLI front end.
  Do not maintain a separate MCP server. Expose shared action schemas through
  the local `actions` reference. Routine play must not require reading implementation code
  or independently reconstructing menu sequences.
- Keep native menu bindings as execution adapters. Prefer objective receipts,
  factual blockers and collected results at the controller boundary. Expose
  menus when a choice is missing and retain full traces for diagnosis. Do not
  treat input batches, opening a combat menu, or speaking a line as proof that
  an attack resolved or a requested listener replied.
- Decode the scope of a native option's effects, including operations that act
  on an owning container. A known broader effect must not be selected for a
  narrower item objective and discovered only by a failed postcondition. Expose
  the broader operation explicitly so the controller can request it.
- Choose the execution path by this ladder and take the highest rung that
  exists for the action: (1) a DFHack API function or shipped script;
  (2) the native action and choice structures the game's own input handlers
  fill, such as unit actions for Move, Attack and Talk or conversation choice
  entries; (3) native menu hotkeys; (4) raw keys and clicks, development only.
  Postconditions are verified the same way whichever rung executed the action.
- Submitting native actions and choices is permitted where DFHack's own
  adventure tools already do it. The submission must go through the game's own
  processing: never set an outcome directly, never move a unit, edit a wound,
  refresh a cache or skip a native refusal. What the game rejects through its
  handlers it must also reject here, and the refusal is reported as a fact.
- Menu hotkeys and allowlisted native scroll writes remain the adapter for
  interfaces that have no action equivalent. Validate the native menu and
  target first, obtain effective scroll bounds from DF, resolve the hotkey from
  fresh state, and never perform such writes during observation.
- The support gate is "DFHack exposes it", not "we verified the handler in
  the executable". Do not add disassembly listings, executable offsets or
  PE-timestamp-gated models to the harness. When a field or handler is
  missing, implement the required DFHack extension within the authorized task,
  integrate it, and verify it. A migration list is not delivery of requested
  work. Mark any still-unverifiable behavior unsupported. A repository-shipped
  DFHack helper must use DFHack APIs and named df-structures fields, be suitable
  for an upstream contribution, and identify its calculation provenance. It must
  never depend on executable offsets, binary signatures, per-executable models
  or version gates; provenance notes do not make those supportable. Read-only clones
  of dfhack, df-structures and scripts pinned to the installed release live under `.df-llm/upstream/`;
  consult those before reading the executable or an unpinned copy.
- Reuse DFHack's calculations and tools instead of reconstructing the game's:
  movement speed and slowdown, walkable groups and reachability, item capacity
  and weight helpers, save and load scripts, and DFHack's native script loader.
  Load repository modules by explicit absolute package paths; do not register
  the repository root for recursive script discovery, which would execute
  reference clones as duplicate overlays. The values the game actually uses, such as the HUD burden state
  and native cached loads, are authoritative for what the game will do; an
  independent estimate may be reported alongside them, never instead of them.
- Do not reimplement pathfinding, clocks, rest loops or combat resolution. Let
  the game path, sleep, rest and fight; the harness supplies the target,
  bounds the wait, watches the controller's interruption predicates, and
  verifies the result.
- Prefer scoped eventful report subscriptions where verified, with bounded
  native catch-up for delivery ordering and plugin replacement. Enable events
  explicitly at simulation-tick frequency; paused counters do not imply broken
  events. Preserve native wound/blood sampling where the plugin has no complete
  event. Use the installed fastcombat overlay for presentation acceleration,
  under completion policy, without dismissing undelegated prompts or changing
  simulation timers. Fixture-only sandbox edits must stay in a separate save;
  restore the campaign checkpoint after testing.
- Guard known interfaces with native context, option identities/order, target
  IDs, filters, prompts and relevant character/world state. Keep text guards
  for undecoded interfaces and raw UI inputs; presentation changes alone should
  not invalidate a known semantic selection.
- Read only the fields owned by the active native interface mode; an inactive
  pointer can refer to freed state even when its struct field is readable.
  Revoke live execution leases and choice handles on world replacement, and scope
  handles across process restarts. Restore progress only from that save's DFHack
  persistent world data, at a verified fresh stage whose native checkpoint guard
  matches. Never restore an in-flight input or reinterpret old UI/effect IDs.
  Local map reloads are not world replacement. Persistent world data reaches
  disk when the game saves; it is not an immediate save or a recovery journal.
- Keep visibility predicates independent of the ASCII crop. Return all loaded
  visible units with explicit bounds, and stop delegated visibility checks when
  enumeration is truncated. Observation-window sizing is an execution mechanic;
  preserve the chosen destination and exclusions across local coordinate rebases.
  Coordinate targets in a sequence refer to its initial map, including stages
  that have not started yet; rebasing them is an execution mechanic.
- Keep routine controller tools focused on semantic actions and explicit native
  choices. Raw keys, clicks and full UI traces are explicit development
  operations in CLI/Python. Concise projections must identify omissions; comprehensive status
  and full diagnostic traces remain available through their explicit queries.
- A focused character query must skip omitted native profiles at the reader,
  not build comprehensive status and discard most of it at the controller.
  Reuse shared calculations and validation, and scope coverage to the readings
  actually requested. Unread sections are not verified complete.
- Keep execution observable. Preserve events and messages encountered during
  automation, and report whether the dispatch completed, needs a controller
  choice, hit an execution limit, or failed. Input delivery alone is not proof
  of completion.
- If a completion path is unsupported or cannot be verified, report that
  limitation explicitly. Do not silently substitute a different execution mode
  or claim success. Respect controller-specified interruption conditions and
  document technical execution limits.
- Interrupted or bounded execution must retain enough progress for an explicit
  resume without restarting completed steps. Expose interruption while a
  dispatch is running, and return compact state changes and concrete blockers
  so the controller can assess the next decision. Mechanical path constraints
  and execution limits must be explicit, rather than hidden threat assessments.
- A no-effect verifier must retain the pending-input checkpoint. An explicit
  resume may verify a late effect, but must not repeat an input just because
  verification consumed its marker before reporting failure.
- Completion authorizes bounded replanning after a native stale-state rejection
  that explicitly confirms no input was sent. Restore the accepted checkpoint,
  reread and recheck controller predicates before resolving the next input.
  Preserve initial guards, world boundaries, native refusals and uncertain
  delivery; never replay an input whose delivery is unknown.

## Existing legacy code

The rules above supersede an earlier keypress-only doctrine. Until the
following are retired, treat them as legacy and do not extend them:

- `character_calculations.lua` and its PE-timestamp gate; replacement requires
  working DFHack calculation helpers. `computeMovementSpeed` is still a stub
  in the pinned `53.16-r1.1` reference and needs upstream repair;
  `computeSlowdownFactor` does not supply burden or carrying capacity.
- `routing.py` step-by-step BFS and route extension remain only for explicit
  route constraints/frontier exploration or unavailable native path dependencies.
  Ordinary local movement and approaches use the game's native path command.
  Do not silently discard supplied constraints to remove this remaining adapter.
- The `.df-llm/*.asm` listings and every offset cited in docs; they are
  evidence of past verification, not a support basis.
- The options-screen geometry adapter for saving; use DFHack `quicksave` and a
  repaired `load-save`.
- The strike native observer and per-tile walking polls once native action
  submission is in place.

Remove this section when the list is empty.

## Controller response contract

- Design normal responses around the controller's next decision, not the shape
  of internal execution records. Use one shared outcome contract across actions.
- Return changed fields instead of before/after copies of whole entities. Omit
  unchanged metadata, completed-request/policy echoes and successful-stage prose.
  Keep concrete blockers and resume information when execution is unfinished.
- Give new recipe blockers explicit, bounded `details.facts` for the controller.
  Preserve those facts in compact receipts instead of requiring a central field
  allowlist update for every new capability. Keep raw menus and traces separate.
- Return useful objective results through bounded `details.value` records. The
  shared `values` projection puts these before events and returns each completed
  stage's value once across resumes. Keep execution receipts and native timing
  evidence in diagnostics; completion of an attempt does not imply a hit.
- Distinguish a resolved failed attempt from missing verification. A native
  cancelled swing has nothing to resume; an interrupted recovery must retain any
  already observed hit or miss. Attribute combat reports within the tracked
  action's interval, label language-dependent text attribution, and leave ambiguous
  actors or changed wording unknown. Native refusal text belongs in the blocker,
  scoped to the current objective and input rather than any report in the batch.
- Define the state needed to reassess each objective. Inventory changes return
  location, container integrity and resulting cached load/burden from unit state;
  strikes return the target's condition. These are bounded native readings,
  not additional comprehensive queries or inferred tactical recommendations.
  Group a departing container with the contents still observed inside it.
- Return dialogue replies once, separate from background reports. Return one
  grouped choice list when a decision is needed; do not duplicate it in error
  details, activity records or UI text. Prefer verified native subject IDs and
  short guarded choice handles over label hashes at the controller boundary.
- Preserve complete events, prompts and traces behind an explicit read-only
  dispatch-details query. Preservation does not require repeating them inline.
  Document retention and mark omissions. Output filtering must remain selectable
  by the controller and must not alter execution or interruption policy.
- Avoid retransmitting unchanged internal observations and full checkpoints.
  Versioned execution deltas must reconstruct the complete observation, reject
  a mismatched base before further input, and preserve full diagnostic receipts.
  Reuse a verified snapshot across mechanical stages until their reader needs
  change or native input requires a fresh observation.
- Controller read deltas must name an exact content reference, independently of
  the input state ID. Reuse the lossless transport delta format, bound the local
  cache, and return a fresh full reading on expired or incompatible bases. Cache
  failures must not turn a successful read into a retry. Keep comprehensive status
  unchanged, preserve changed warnings/unknowns, and measure follow-up reads too.
- While input is processing, narrow progress reads may collect reports and
  evaluate the controller's interruption predicates. Mark them separately from
  complete snapshots; they must never advance a snapshot revision, drive the
  next gameplay input, or replace a final diagnostic observation.
- Keep those progress reads independent of full input-guard construction. Do not
  traverse inventory or menu entries, hash a snapshot, or echo the active request
  only to discard it afterward. Request native watch data from the supplied
  predicates, and require a fresh complete guard before the next gameplay input.
- Additional controller predicates must request their own bounded native data,
  including during processing polls, and guard it again before input. Missing
  requested readings are concrete blockers, not negative matches or healthy
  defaults. Keep opt-in watch data out of unrelated routine observations.
- Avoid capturing ASCII for decoded native interfaces unless a caller requests
  full UI diagnostics. Unknown interfaces and raw UI inputs retain the ASCII
  guard. Mark omitted captures, and never persist lazy readers or native pointers
  in a snapshot; full character status and game-state verification remain intact.
- Preserve changed warnings, unknown readings, false and zero. Suppress passive
  timer increments only when their elapsed time and interpreted state are known.
- Test representative completed, blocked and resumed receipts for useful content,
  duplication and size, as well as testing whether the game input succeeded.

## Measuring controller effort

- Keep measurements passive and separate from gameplay receipts. Record local
  payload token counts, durations and correlated RPC costs without payload text.
  Logging/tokenizer failures must not change actions or trigger retries. Tokenizer
  downloads require explicit preparation, never an ordinary controller call.
- Evaluate whole instructions using explicit episode labels or documented idle
  grouping. Split explicit labels at idle gaps too, retaining the label and a
  segment identity so development pauses do not inflate active play time.
  Report harness time and gaps separately; gaps also include human
  pauses and other tools, so they are not proven LLM deliberation.
- Pair receipt token counts with follow-up reads per dispatch. Smaller receipts
  are not an improvement if the controller needs extra queries to reassess.
  Count discovery calls and same-target reissues, distinguishing resumes from
  bounces and marking missing target/timing data in historical records.
- Preserve test coverage for measurement boundaries, episode analysis and
  failure isolation. Compare equivalent objectives, not bytes alone.
- Run offline tests through `python -m tests.run` so they cannot inherit live
  controller policies or append fixture calls to play metrics.

## Local game reference

- Search `.df-llm/wiki/articles/` for game mechanics and tactics. The local
  MediaWiki source mirror includes templates, categories and modules; its
  manifest and page headers retain coverage, revision URLs and dates. See
  `docs/local-wiki.md` for offline lookups and explicit refresh commands.
- Wiki text is reference material, not execution policy. Check historical-version
  warnings and distinguish general mechanics from this unit's actual native
  attributes, creature flags, equipment and injuries.

## Character status contract

- Dispatch receipts should include observed skill XP and stored attribute changes
  when they occur. Use native total experience across rank changes, preserve
  unknown/truncated samples, and compare each resumed interval only once. Share
  native readers with character status; do not require a full character query
  just to learn what the dispatched activity gained.

- `status` is the comprehensive character query across CLI and Python.
  Keep the lightweight game/readiness query under `game-status` / `game_status`.
- Include new character-related capabilities in the status report and its
  coverage metadata. Keep physical state, inventory, mind, relationships,
  knowledge, abilities, reputation, history, and obligations accessible together.
- Status is read-only: no menu inputs, time advancement, prompt dismissal, or
  screenshot dependence. Controller dispatch policy does not change that.
- Preserve false and zero, distinguish absent optional records from failed
  reads, report truncation and unsupported calculations, and never label unknown
  state as healthy, empty, or complete. Text output must preserve all sections.
- Report the native cached load and HUD burden state as what the game uses.
  Report an aggregate from DFHack item helpers separately when it differs, and
  say which one the game acts on. Never refresh game caches or advance time
  merely to complete a status query.
- Use the shared DFHack Lua burden helper for status, brief and action receipts.
  It reads bounded root inventory caches and DFHack attribute/skill APIs without
  a screen scan or movement-model dependency. Keep display comparisons in tests.
  Unknown native readings remain unavailable; panel visibility is not a burden
  dependency. Do not duplicate the calculation in a second estimate.
- Follow verified native union tags; represent world object references by ID
  instead of recursively traversing the world's object graph.
