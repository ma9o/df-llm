# Native pathing and controller-effort review, 0.24

Local movement now submits `df.adventure_movement_pathst:doRealize()`. The
game sets `unit.path.goal = AdventureAutomove`, computes the route and advances
the adventurer. Complete mode sets the native `dungeon_control` continuation
state and starts processing with one ordinary short-wait input. There is no
inserted Job, direction-selection loop, unit-position write or timer edit.

The path executor also serves item pickup, conversations, strike approaches,
stairs and environmental interactions. Positive arrival radii select a visible
endpoint with a native walkable connection; the game still computes the route.
Approach evidence is distinct from strike evidence so arriving beside a target
cannot be mistaken for submitting its attack.

## Verification and boundaries

Native frame callbacks watch only data required by the controller's supplied
predicates. A change pauses the owned goal, and the existing Python policy
engine decides whether it is an interruption. This avoids a second threat
policy in Lua. The retained sample preserves transient changes between RPCs;
each sample is assessed once across explicit resume.

External interruption, an execution deadline, an interface state or a watcher
failure cancels the remaining owned goal through `dfhack.units.setPathGoal`.
An already submitted native Move is allowed to settle. Another goal or a
replacement world is never overwritten. Incremental mode stops at the first
movement boundary; complete mode follows the remaining route without asking
the controller to continue at each tile.

`canWalkBetween` is a reachability check, not proof of successful travel. The
game may still refuse the goal. Its walkability cache can be stale while
paused; the harness returns a concrete blocker and does not refresh the cache.
The route vector is empty immediately after native command realization and is
filled during game processing, so it cannot preflight an entire constrained
route at submission time.

The native command has no excluded-tile, liquid-depth or occupancy restriction
fields. Explicit route restrictions and frontier exploration continue to use
the existing constrained adapter. Thus `routing.py` is **not retired**. Ordinary
CLI, Python and MCP requests omit those restrictions and use native pathing;
explicit false, zero and empty constraints remain explicit. Flat-ground paths,
positive radius, interruption and incremental/complete resume were tested live.
Cross-level goals use the same native connection check but have not yet had a
dedicated live traversal trial.

## Corrections to the proposed travel shortcut

The pinned `53.16-r1.1` structures expose a local path command distinct from
the one-step `adventure_movement_movest`. The live test confirms the path class
does follow a multi-tile route; it is not merely one clicked movement tile.

The proposed `travel_goal_count`, `travel_goal_abs_smm_x/y` and
`travel_goal_layer_depth` fields are original names in
`.df-llm/upstream/df-structures/df.adventure.xml`. Their exposed names are
`long_action_duration` and `travel_start_x/y/z`. The source documents long-action
offloading and the first fast-travel move, not an arbitrary route waypoint.
The live first-step coordinates remained `(297, 956)` while current travel
coordinates were `(347, 914)`, with the duration already zero. The proposed
destination writes were therefore not implemented. Travel retains its native
directional inputs and existing site-grid adapter until an actual route command
can be exposed and verified.

## Measurements

The two eight-tile trials used the same direction and endpoints, local
`(92, 72, 136)` to `(84, 72, 136)`, with the same adventurer and gear.

| Measure | Constrained adapter | Native path |
| --- | ---: | ---: |
| Inputs | 8 | 1 |
| RPCs | 36 | 9 |
| Harness duration | 3.912 s | 1.490 s |
| Receipt tokens, o200k_base | 318 | 315 |
| Simulation ticks | 215 | 151 |

These are individual live trials, not a latency distribution. Other native
eight-tile trials used 10 RPCs. The retained traces are
`.df-llm/pathing-trace.jsonl` and `.df-llm/pathing-metrics.jsonl`.

The external-interrupt trial stopped after one tile with `goal=None` and
`dungeon_control=PROMPT`; explicit resume completed the remaining 14 tiles with
one submission. Radius-one arrival stopped at `(83, 88, 136)` for target
`(84, 88, 136)`. Incremental execution toward `(91, 88, 136)` stopped at
`(84, 88, 136)`, then completed through explicit resume. No wounds or blood loss
occurred in these trials.

Old and new projections of identical native snapshots, pretty JSON with
`o200k_base`, produced:

| Reading | Before tokens | After tokens |
| --- | ---: | ---: |
| Concise scene | 6,027 | 2,205 |
| Character brief | 3,870 | 3,031 |

Scene reads now skip the native inventory profile, preserve held target IDs and
burden, and encode terrain landmark spans losslessly. Full status remains
comprehensive. Explicit metrics episode labels now split at idle gaps, retain
numbered segments, and do not connect bounces or follow-up reads across those
gaps. Gaps include human/tool pauses and are not labeled as proven LLM thinking.

## Controller connection and combat assessment

The project Codex MCP configuration is recognized by `codex mcp get
dwarf-fortress`; stdio initialization, 17-tool discovery and choices-only
observation passed. The already-running controller needs a client/session
reload to acquire the new tool set. Server launch respects persistent settings.

Strike receipts and unit inspection now share bounded native combat condition
reads: blood, consciousness, functional limbs, body-part status and current
grapples. Empty lists, zero limb counts, unavailable fields and truncation are
distinct. Comprehensive character status already exposes the complete anatomy
and wrestling profiles. Defense, dodge and wrestling **execution** remain
explicitly unsupported; this release does not claim that a combat menu or a
condition read completes those actions.

Validation includes the Python suite, isolated Lua fixtures, live path trials
and read-only agreement across CLI, Python and MCP for all 29 comprehensive
character-status sections. Build, format, lint, type and dead-code checks are
included in `make check`. Detailed check artifacts stay under `.df-llm`.
