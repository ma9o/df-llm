# Development notes

## 2026-09-06: adventure action prompt (deferred)

While starting the room-conversation test, the Premium UI displayed three buttons:
`a Continue action`, `b Stop action`, and `c Finish action`. All three labels were
readable in the ASCII character layer; a development-only window capture
confirmed they were visible. No screenshot capability is part of the harness.

DFHack reported `dungeonmode/Default`, no known open panels, and usually
`TAKING_INPUT`. The harness therefore incorrectly reported `can_move=true`.
Direct `A_TALK`, character input, a label click, `CUSTOM_B`, and `OPTION2` had no
visible effect on the prompt. A diagnostic RemoteFortressReader
`PassKeyboardEvent` key-down/key-up for B also had no visible effect. A later
attempt was rejected by the harness because the turn was processing.

The user manually chose **Finish action** and asked to defer this investigation
and resume the conversation test. Afterward the player remained at
`(76,73,128)`; hunger/thirst/sleep timers increased from 33 to 743, and an
announcement panel with **Okay** appeared. This is consistent with game time
advancing during the action. The action's identity and the exact differences
between Continue/Stop/Finish were not established. We did not verify a working
harness response to that prompt.

Follow-up: combine character-layer prompts with structured UI state; distinguish
input delivery from actual effects; allow answering input phases such as
`TAKING_TOO_LONG_INPUT`; prevent movement when an unresolved prompt is present.
The controller decides whether to delegate Finish, including the game time it
may advance. The harness must not make that policy decision from its own risk
assessment; see [AGENTS.md](AGENTS.md).

Local evidence: `.df-llm/conversations.jsonl`. Diagnostic source downloads under
`/tmp/df-llm-*` are disposable and are not runtime dependencies.

Later in the conversation test, the bridge gained character-layer detection for
this three-choice prompt and disables `can_move` when it is detected. At that
stage it only exposed the prompt. Separate help and announcement prompts gained
a live-verified `dismiss` action; this did not establish a working response to
Continue/Stop/Finish.

## 2026-09-06: controller-selected dispatch policy

The CLI, MCP, and Python interfaces now share one dispatch driver. Controller
defaults and per-dispatch overrides select `step` or `complete`, independently
delegate help/announcement acknowledgements, and bound execution by steps and
time. Complete mode maps the long-action prompt to Finish (`OPTION3`); explicit
Continue/Stop/Finish responses are also exposed. No action risk classification
selects the execution policy.

The driver preserves observed reports and handled prompt text, returns explicit
outcomes, and stops if a delegated response leaves the same observed prompt.
`resume` applies policy to the current state without repeating the initial input.
Duplicate request IDs return the recorded result and a fresh observation without
starting more automation.

During development, a one-hour wait briefly reported `TAKING_INPUT` while the UI
said **Offloading site...**. The initial readiness check returned too early. The
wait subsequently completed naturally, with the year tick changing from 17259
to 17309 and the local world frame resetting on reload. Readiness now includes
the offload, long-action, sleep, and wait counters and is checked again after
observation. A subsequent live wait settled correctly at tick 17310.

Validation: all 30 offline tests pass, including simulated help/More/Okay/Finish
chains, policy overrides, limits, readiness races, and replay behavior. Live CLI
and MCP checks verified automatic Talk-help acknowledgement, an override that
returns the help page, resumption with inherited acknowledgement, and duplicate
replay without another input. These menu checks left position `(76,73,128)`,
health, and game time unchanged and returned to the default adventure view.
Local evidence: `.df-llm/dispatch-policy-live.jsonl` and
`.df-llm/dispatch-policy-live-results.json`.

The original Continue/Stop/Finish prompt has not reappeared. Its response mapping
remains marked `response_verified: false`; the controller-policy branch has
offline coverage, but the game input path is not live-verified. The user explicitly
deferred further investigation until the case occurs again.

## 2026-09-06: room looting and equipment replacement

Completed through normal game inputs without screenshots. Replaced the leather
helm with an iron cap, copper greaves with bronze greaves, leather boots with a
pair of bronze high boots, and the starting copper gauntlets and shield with
higher-quality copper versions. Kept the copper war hammer and breastplate;
also collected a rope and a cut green jade gem. Replaced equipment was dropped
in the room. Final item IDs and Worn/Weapon roles were checked against the
starting inventory. The adventurer remains uninjured at `(70,68,128)`, with the
default adventure view ready for input.

The game hid replacement armor from the Wear menu until the old piece was
removed. `A_INV_REMOVE` also takes an item out of a carried container, which
allowed equipping the replacement shield. `A_INV_DRAW_WEAPON` toggles drawing
and strapping weapons; it does not open an item picker. A held removed garment
can have inventory role `Weapon`, so that role alone does not identify a weapon.
`ADVENTURE_LIST_SCROLL_PAGEDOWN` exposes additional pickup/inventory entries;
visible letter shortcuts change after scrolling.

Observation gap at the time: tile inspection listed loose containers but omitted
their contents. The native pickup menu exposed those contents. For comparisons,
a read-only query through the DFHack RPC escape hatch inspected the known
containers' contents, item types, quality, and weapon definitions. In particular,
the available iron "thranan hammer" is a TOOL, not a war hammer. These item details
became the structured inspection and semantic actions described below.

Evidence: `.df-llm/looting.jsonl`, `looting-before.json`, `looting-after.json`,
`looting-item-details.json`, and `looting-result.json` in the same local directory.
The displayed movement value changed from `0.591` to `0.471` with the final load.

## 2026-09-06: semantic execution and controller-owned interruption

The looting log showed 108 controller dispatches, 29 Inventory-help
acknowledgements, and 153 individual tile inspections over roughly eight
minutes. Full observations averaged about 28,500 characters. The controller
was spending most of its work on discovery and UI mechanics.

Added `df_items` and `df_item` for nearby ground/container contents and carried
item details. The observations now include material, quality, wear, raw mass
and volume, maker species, armor/weapon definitions, and native menu options
bound to item and destination-container IDs. Matching an item by label is no
longer necessary for the supported inventory workflows. Native Wear-menu
eligibility remains distinct from proven fit/equipment state.

Added semantic `pickup`, `equip`, `wield`, `remove`, `drop`, `stow`, and local
`walk_to` actions. One shared driver implements step/complete mode, acknowledgements,
execution limits, and explicit interruption across both semantic and primitive
actions. Equipment replacement only acts on the IDs and disposition supplied
by the controller; the target must be verified as equipped before old items
are dropped or stowed. All changes use normal game input.

Workflow progress is checkpointed in DFHack before input and resumes by dispatch
ID across client processes. Root dispatch deduplication is separate from input
receipts. A lost reply is not retried; errors expose the dispatch ID so the
controller can inspect and explicitly resume. An active-dispatch lease prevents
two clients from interleaving inputs. MCP action workers keep status and
interruption available while an action runs, including MCP cancellation.

Interruption rules are caller-selected factual predicates: blood loss, new
wounds, newly visible creatures, specified visible IDs, and exact report types.
The harness does not infer threats or rank gear. Resumed dispatches retain
history without retriggering already returned report interruptions. A resume
uses controller defaults plus the new call's overrides, so persistent rules
belong in controller configuration.

Compact action results contain inventory/position/health/creature changes,
events, prompts, and current choices or route blockers. Repeated prompts are
stored once with their encounter sequence; Inventory help is read from its
native markup words. Full observations and episode logs remain available.

Live checks on this game verified:

- Incremental drop followed by an explicit resume and a complete pickup, with
  automatic scrolling to the selected item ID and verified backpack contents.
- Equipping boot 14429 in place of 14438 and stowing 14438 into backpack 495 in
  one dispatch (15 native inputs), then restoring 14438 and dropping 14429 in
  one dispatch (11 inputs). All original equipment roles and body parts were
  restored. An already-equipped item completed without sending any input.
- Wielding the jade gem 14434 and stowing it back into backpack 495, using three
  and four inputs respectively, including delegated Inventory help.
- MCP interruption after the first walking input, concurrent status, and resume
  to `(70,66,128)`. The return initially reported an occupied target: our tame
  capybara was at `(70,68,128)`. The controller explicitly supplied
  `allow_occupied: true`, and the return completed.
- A specified visible creature causing `interrupted` before any game input.

The first crowded-room walking probe also exposed an overly restrictive
diagonal corner rule, which was removed. It treated an occupied neighbor like
a wall and caused unnecessary detours. Native movement still verifies the
expected adjacent position. Occupancy and route constraints remain explicit;
the harness does not wait, attack, or choose a new destination when no route
is available under the supplied constraints.

All 57 offline tests pass. They cover semantic postconditions, wrong-item and
wrong-container avoidance, failed selections, limits, step/resume, dropped
replies, compact output, factual predicates, and concurrent MCP interruption.
The live checks restored inventory, body-part assignments, backpack contents,
and position `(70,68,128)`. Blood remains 5600 and wounds zero; native game time
advanced during verification.

Evidence: `.df-llm/workflow-development.jsonl`,
`workflow-replacement-live.json`, `workflow-walk-interrupt-live.json`,
`workflow-walk-return.json`, `workflow-mcp-live.jsonl`, and
`workflow-final-live.json` in the same local directory. The original
Continue/Stop/Finish issue remains deferred and unverified live. Quantity
pickers and unsupported item/fit choices return to the controller explicitly.

## 2026-09-06: comprehensive character status

Added the read-only `character-status` CLI command, `df_character_status` MCP
tool, and `Client.character_status()`. The existing `status` query continues
to report game/input state. The new query reads the adventurer directly,
without opening the character screen, dispatching inputs, advancing time, or
applying acknowledgement/interrupt policy. It works independently of the
current menu/input readiness.

The sheet includes identity/affiliation, detailed health and condition flags,
named anatomy, wounds, syndrome effects, physical/mental attributes, skills
and effective ratings, physiological and psychological needs, focus/stress,
personality traits/values/goals/emotions, full equipment with body-part names,
native gait parameters, and current action types. Missing and truncated data
are explicit. Values are factual native state; assessment remains with the
controller. The detailed Lua reader is included only in character-status
requests, so regular observations do not acquire this extra payload.

Version-specific findings: body-part names and gait action strings are pointers
to strings and require `.value`; gait definitions use `full_speed`, `start_speed`,
and `buildup_time`. The installed Lua API explicitly documents
`computeMovementSpeed` as broken, so computed speed is marked unavailable.
The optional-read helper was corrected to retain boolean false values.

Validation: 63 offline tests pass. Read-only live verification through Python,
CLI and MCP returned character 8525 with 89 anatomical parts, six physical
attributes, 13 mental attributes, eight recorded skills and 22 needs. The
adventurer remains at `(70,68,128)`, with blood 5600 and zero wounds. Action
serial, game time, focus/panels, health and inventory were unchanged by the
queries. Six Lua fixtures, executed with synthetic characters in an isolated
environment, also cover injured/missing parts, syndrome effect targets,
unavailable data, false/zero preservation and bounded emotion history. No
characters were injured or inserted into the world for testing.

Run `python3 -m tests.live_character_status --port 5001` to repeat these
read-only checks while an adventurer is loaded. Initial development snapshots
and the episode log are under `.df-llm/character-status-*.json*`.

## 2026-09-06: encumbrance in character status

Added `character.encumbrance` to the existing character query, CLI text view,
and MCP tool (server 0.4.1). It reports carried kilograms, weight by native
inventory role, ten heaviest root items, cache validity and incomplete-weight
details. Aggregation reads the native inventory separately from the bounded
equipment display and deduplicates item IDs. Valid container caches include
their contents; stack caches include the stack quantity. Neither is multiplied
or added again. An invalid cache leaves the total unknown and reports a known
subtotal, without forcing a game-side weight calculation. Ordinary item reads
and compact changes now retain `weight_computed` as well.

The reader also extracts the native gait and displayed speed from the ASCII
HUD's final two character rows, checking the view state, alignment and gait
name. It returns unavailable when the HUD is hidden or unrecognized. No menu
inputs or screenshots are used. Carrying capacity and isolated load penalty
remain explicitly unsupported: the installed API's movement computation is
broken and its old encumbrance formula is disabled. We do not present the old
formula or the historical speed change as a verified load penalty. Inspection
also identified `unit.effective_rate` as `heal_rate_recuperation`; it now appears
as `health.recuperation_healing_rate` instead of a movement field.

Validation: 67 offline tests and 14 isolated Lua fixtures pass. Coverage includes
container/stack accounting, invalid and missing caches, zero mass, duplicate
references, inventory scan/output limits, hidden or malformed HUD text, and
cache invalidation in compact changes. Live Python, CLI and MCP queries agree:
98.46225 kg carried; Flask 0.5394 kg, Weapon 16.967 kg, Worn 80.95585 kg; HUD
Walk 0.471. Worn includes the filled backpack. The largest contributors are
bronze greaves (27.3075 kg), breastplate (22.5036 kg), filled backpack
(17.51175 kg), and shield (13.395 kg). Queries left game time, input serial,
position, health, inventory and menus unchanged. Final snapshots are
`.df-llm/encumbrance-final.json` and `.df-llm/encumbrance-final.txt`.

## 2026-09-06: status becomes the complete supported character report

`status`, `Client.status()` and MCP `df_status` now return character schema 2,
including the nested game/input status. The `character-status` aliases remain;
`game-status`, `Client.game_status()` and `df_game_status` provide the previous
lightweight readiness response. MCP is now 0.5.0 with 11 tools. This is an
intentional response-shape change for callers of `status`.

Added a separate character details reader, loaded only for character queries.
The report covers 29 sections: physical state and anatomy, equipment and weight,
personality/needs, appearance, relationships/companions, knowledge/performance,
abilities/combat, possessions/career/reputation, obligations/activity, senses,
historical profiles, and available native sheet prose. Abilities retain cooldowns
and resolve body-plan indexes separately from granted interaction effect IDs.
Quest and rumor data use their native tagged union members. World object
references retain IDs without recursively expanding the world. Fixed detection
and attack-awareness arrays are bounded by their valid entries; stale slots are
excluded. Optional profiles distinguish absence from a failed read, and text
output preserves all returned sections and nested details.

Character inventory has a separate 4096-item/depth-16 budget. All additional
profile lists, depth, node and string limits feed explicit truncation metadata.
Coverage reports availability and missing/truncated counts per section. The
six current unavailable fields are capacity, isolated load penalty, computed
movement speed, interpreted physiological severity, combat preference globals,
and native appearance prose while the matching character sheet is not populated.
The sheet target check follows the installed unit-info-viewer implementation's
use of `view_sheets.active_id` as a unit ID and also requires the UNIT sheet type.
The query sends no inputs, opens no menus, advances no game time, and uses no
screenshots. AGENTS.md now states this status contract.

Validation: 71 offline tests and 26 isolated Lua fixtures pass. Fixtures include
false/zero/absent profiles, missing parents, pointer boundaries, method exclusion,
known versus unknown union tags, body/granted abilities, curse flag overrides,
unused combat slots, tagged actions, stale sheet text and coverage limits.
Live CLI/Python/MCP status aliases return identical full character data, and the
readiness aliases remain lightweight. Game time, action serial, position, health,
inventory, focus, panels and modal state were unchanged by verification.

For Athis (8525), the report includes 89 body parts, 249 tissue layers, 64 social
records, companion Getak (capybara), Pet animal and Spit, known works and creature
knowledge, and Offer Service to the Order of Luck with deity Akmol. Carried mass
remains 98.46225 kg and HUD speed Walk 0.471. There are no truncated sections for
this character. Example reports are `.df-llm/status-comprehensive.json` and
`.df-llm/status-comprehensive.txt`.

## 2026-09-06: native capacity, load penalty, movement, and need labels

Added a pure Lua calculation module to character status across CLI, Python,
and MCP. Schema 2 remains additive; MCP is now 0.6.0. The text reading summary
shows capacity, isolated load penalty, calculated current/unloaded movement,
and hunger/thirst/sleep warning stages with their next thresholds. Structured
data retains raw inputs, calculation provenance, arithmetic components, and
explicit availability. Controller dispatch and threat policy are unchanged.

DFHack's public movement calculation is disabled, so the implementation was
reconstructed from the installed DF 53.16 Windows Steam executable. The current
capacity formula uses body size times effective strength; the older disabled
formula is not used. Native movement code was located through the adventure
HUD's call sites. The audit also verified armor discount rounding, gait buildup
and attribute scaling, need labels, and the current 864000 sleep threshold.
[Calculation documentation](docs/character-calculations.md) records the exact
build fingerprint, native code RVAs, formulas, semantic limits, and validation.
Analysis dependencies and disassemblies remain development-only in `.df-llm`.

Runtime calculations are gated by the exact DF version string, OS, and PE
timestamp. Missing/stale inputs, unsupported mounted/vision states, bounded
scans, and arithmetic overflow are unavailable rather than guessed. Production
reads require no HUD, screenshots, menu actions, native movement calls, cache
updates, random numbers, or attribute training.

Validation passed: 73 offline tests and 45 isolated Lua fixtures, including every
need threshold boundary, zero/exempt/unknown needs, armor skill and separate mass
rounding, capacity/load thresholds, large-body arithmetic, gait buildup, movement
modes, health/terrain/curse modifiers, clamping, and operation without UI data.
Live CLI, Python, and MCP aliases agree. The calculated HUD-formatted speed
matches the native ASCII HUD; input serial, game time, position, health,
inventory, focus, panels, and modal state were unchanged by verification.

Athis carries 98.46225 kg, with 63.04 kg no-penalty capacity. Native rounding
gives 35.42 kg excess and +1123 movement cost: current Walk rate 0.4710315591
(HUD 0.471), versus 1.000 unloaded. The isolated load reduction is 52.89684409%.
Hunger, thirst, and sleep counters are all 9261, below their first warning stages.
Current status has no truncation and only two remaining unavailable fields:
combat preference globals and unpopulated native appearance prose. Results are
in `.df-llm/status-calculated.json`, `.df-llm/status-calculated.txt`, and
`.df-llm/verification-calculated.json`.

## 2026-09-06: expose the native burden indicator

The user noticed the UI's overburdened state was missing from status despite
the numeric load and speed calculations. Added `encumbrance.burden` to the same
read-only query and a prominent `Burden: Overburdened` line in text output. The
structured object includes state/label, native icon, severity, explicit booleans,
capacity percentage, and thresholds. MCP 0.6.1 advertises this field.

The installed HUD code at RVAs 0xafa2ac–0xafa3c7 compares skill-adjusted native
load against capacity and then `trunc(3 * capacity / 2)`, using strict greater-than
checks. Thus the heavy icon starts above 150%, while a movement penalty starts
above 100%. The current character is at 156.186548% and reports Overburdened,
matching the user's UI observation. No screenshot, hover or input is required.
Unknown load, mounted HUD calculations and hidden-curse capacity variants stay
explicitly unavailable. These states do not alter controller dispatch policy.

Validation: 74 offline tests and 47 isolated Lua fixtures pass. New checks cover
the exact 100%/150% boundaries, odd integer capacities, armor discounts, unknown
weights, independent speed exemptions, and readable output. Live CLI/Python/MCP
queries agree and preserve game time, input serial, position, inventory, health,
focus, panels and modals. Report: `.df-llm/verification-burden.json`.

Inventory advice was evaluated without moving items. The worn finely crafted
bronze greaves are undamaged, 27.3075 kg, versus the old standard copper greaves
on the floor at 29.5583 kg. They are a real upgrade and save 2.2508 kg. Putting
them in the backpack would retain their load but remove their protection;
current Armor User 1 supplies no discount, so the predicted Walk speed stays
0.471. Offloading the greaves would reduce mass to 71.15475 kg and predict Walk
0.795, with lost leg armor. Offloading the 7.6 kg rope instead retains protection,
reduces mass to 90.86225 kg, and predicts Walk 0.531: still Burdened but below the
heavy warning. Those are calculated alternatives, not executed inventory actions.
