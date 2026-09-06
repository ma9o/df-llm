# Harness design instructions

These instructions apply throughout this repository.

## Product intent

This harness supports supervised LLM play of Dwarf Fortress through DFHack,
using ASCII and structured observations and actions. Production control must
not depend on screenshots. Supervised play should still automate routine
interaction so the controller does not spend a decision on every UI step or
game timestep.

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

## Character status contract

- `status` is the comprehensive character query across CLI, Python, and MCP.
  Keep the lightweight game/readiness query under `game-status` / `game_status`.
- Include new character-related capabilities in the status report and its
  coverage metadata. Keep physical state, inventory, mind, relationships,
  knowledge, abilities, reputation, history, and obligations accessible together.
- Status is read-only: no menu inputs, time advancement, prompt dismissal, or
  screenshot dependence. Controller dispatch policy does not change that.
- Preserve false and zero, distinguish absent optional records from failed
  reads, report truncation and unsupported calculations, and never label unknown
  state as healthy, empty, or complete. Text output must preserve all sections.
- Follow verified native union tags; represent world object references by ID
  instead of recursively traversing the world's object graph.
