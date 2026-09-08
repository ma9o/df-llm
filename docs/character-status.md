# Character status reference

For routine self-checks use `brief`; see the [agent guide](../dfharness/guide.md).
This page covers the comprehensive report and its calculation limits.

`./dfctl status` or `Client.status()` returns the current adventurer's
comprehensive character report; `character-status` and
`Client.character_status()` are aliases. JSON is the default; `--text` adds a
reading summary and preserves every section, including complete anatomy and
item definitions. Game and input state are nested under `status`; the
lightweight readiness query is `game-status`.

| Section | Contents |
|---|---|
| Identity and affiliation | Name, age, sex/orientation, race/caste, professions, historical figure ID, civilization, groups, occupations, site links, squad, kill count |
| Health | Blood, pain, exhaustion, hunger/thirst/sleep counters, stun, unconsciousness, suffocation, fever, paralysis, vision/breathing and other explicit condition flags |
| Body | Named body-part IDs, active damage/treatment flags, functional limbs, raw size, wounds, syndromes and effect targets, all tissue layers, temperatures, and healing state |
| Attributes and skills | Stored/effective physical and mental attributes, attribute maxima, native skill records, ratings, effective levels, XP thresholds, and rust |
| Needs and personality | Physiological counters and exemptions, psychological needs, focus, stress, traits, values, goals, emotions, memories, preferences, habits, mannerisms and temporary changes |
| Equipment and movement | Full inventory and nested contents with body-part names, selected/current gaits and raw parameters, following target and native action types |
| Encumbrance | Total carried kilograms, weight by native inventory mode, ten heaviest carried items, cache validity, and displayed HUD speed when readable; unsupported capacity and load penalty are explicit |
| Conditions and appearance | All unit flag groups, mood, pregnancy/ghost state, curse and transformation modifiers, appearance modifiers/genes/colors/styles and their definitions |
| Relationships and companions | Named historical and unit links, social records and attitudes, recent conversation partners, companion and party membership |
| Knowledge and performance | Known books and performance forms, secrets, creature knowledge, rumors and witness reports, scholarly/religious knowledge, performance skills |
| Abilities and combat | Body and granted interactions, item powers and cooldowns, natural attacks, opponent/last hit, attack awareness, wrestling and kill records |
| Possessions, career and reputation | Item values, carried currency, debts/accounts, owned/traded items, familiarity, assigned buildings, career and reputation profiles |
| Obligations and activity | Journal agreements with typed details, religious objective, requests/commands, sleep permissions, current job, social activity, tagged action payloads, waiting/sleep and travel state |
| Senses and history | Valid detection slots, vision/smell state, character report logs and historical profiles, including artistic works and whereabouts |
| Coverage and native sheet | Availability and truncation by section; native description/thought/health prose when already populated for this character's open unit sheet |

The response has `format: "character_status"`, `schema_version: 2`, `available`,
`state_id`, `effect_id`, the current game `status` and `character`. Without an
active adventurer it returns `available: false` with a reason.
`character.unavailable` identifies unreadable or unsupported fields and
`character.truncated` records list limits. Missing data is distinct from zero,
false or an empty list. Optional native profiles use `{present: false}` when
absent; an unreadable parent profile is unavailable instead.

`character.coverage.sections` marks each of the 29 sections `available`,
`partial` or `unavailable` with missing and truncated counts. `coverage.complete`
means no missing or truncated fields in the supported report, not that DFHack
exposes every game variable. Character-owned profiles are expanded; world
references use IDs. Native numeric enum fields carry `enum_labels`. Historical
profiles under `history` can differ from the loaded unit.

The query is a read-only snapshot under DFHack's core suspension: no input, no
menus, no waiting for a turn, no prompt dismissal. Health and need counters keep
native values; stored and effective attributes and skills are separate; body
dimensions, wound counters and gait parameters keep native units.
`health.recuperation_healing_rate` is the unit's native `effective_rate`.

Limits: 512 anatomical parts, 200 wounds with 512 parts each, 100 syndromes
with 200 symptoms each, 300 skill records, 100 needs, values or goals, the last
100 emotion records and 100 action records. Additional profiles are bounded to
4,096 entries per vector, 50,000 nodes, depth 10 and 16,000 bytes per string.
The inventory allows 4,096 items and container depth 16. Truncation is
explicit. The full report is large; use `look`, `brief` or `game-status` in the
control loop and `status` for a complete assessment.

Known gaps are explicit: the native attack, dodge and charge-defense preference
globals, and appearance prose unless the unit sheet is already populated.
Untagged unions are never read; quest, rumor and action payloads use verified
native type tags.

## Encumbrance, movement and physical needs

| Field | Meaning |
|---|---|
| `total_weight_kg` | Total carried mass from native caches; present only when all root and descendant caches pass validation and `weight_complete` is true |
| `known_weight_kg` | Subtotal of roots whose own and descendant caches are valid, even when the full load is unknown |
| `native_cached_weight_kg` | Aggregate of valid root caches, before skill discounts; may be stale while contained-item caches are invalid |
| `by_mode` | Weight and item counts by native inventory role, with completeness for each group; `Worn` includes backpacks, and `Weapon` can include held clothing |
| `heaviest_items` | Up to ten carried root items, descending by kilograms, with IDs and descriptions; each container's weight includes its contents |
| `unweighed_items` | Roots whose mass cannot be confirmed, including invalid/unreadable contained-item caches, with reasons |
| `capacity` | Native no-penalty capacity in kilograms, effective strength and body-size inputs, and calculation provenance; this is not a hard inventory limit |
| `burden` | `Unburdened`, `Burdened` or `Overburdened`, with percentage and thresholds, calculated by the DFHack Lua helper from unit/item state; independent of panels |
| `load_penalty` | Skill-adjusted load, capacity used, excess kilograms, added movement cost, and speed reduction relative to the same state without load |

Mass is `weight_raw.whole + weight_raw.fraction / 1000000` kilograms, as in
DF's mass structure. Valid container weights already include their contents and
stack weights include quantity, so the sum counts each carried root once. Native
cache validity does not guarantee every aggregate is fresh: a container cache
can be marked valid while a contained item's cache is invalid, so the reader
rejects a total when any descendant is invalid, a parent weighs less than its
contents or the containment scan is incomplete. It keeps the native root-cache
aggregate separately. The reader never calls `calculateWeight` or mutates
caches. Bounds are 4,096 root entries, 4,096 contained nodes, depth 16 and 100
unweighed-item details.

Full item observations include `weight_computed`; compact item changes use
`weight_kg`, null for an invalid cache. Character inventory entries include
`weight_kg` only for valid caches, otherwise `weight_unavailable_reason`.

`movement.displayed_speed` is the current gait and speed read from the game's
character layer, for example `{gait: "Walk", value: 0.471, units: "native_display"}`.
It requires the input-ready adventure view and a recognized gait; hidden or
unrecognized text is unavailable. It is the rounded displayed speed, not a load
measurement.

`movement.effective_speed` is calculated from native state independently of the
HUD: current gait, buildup, movement cost and delay, the rate at full buildup
and an unloaded comparison, with a component list. Rates use HUD units, not
tiles per second, and do not guarantee movement is possible.

`physiology.interpreted_needs` gives hunger, thirst and sleep warning labels,
numbered native stages, raw counters and the next stage's threshold. Creature
exemptions are explicit; below the first threshold the label is `No warning`.
Blood thirst is included when applicable. These are the game's warning stages,
not controller decisions.

The movement and need models are legacy code, listed in
[AGENTS.md](../AGENTS.md#legacy-code). They are gated to the installed DF 53.16
Windows Steam build and return explicit unavailability elsewhere, for mounted
movement, unverified vision states, missing inputs and arithmetic overflow.

Capacity, load penalty and burden come from the repository's read-only DFHack
Lua helper `dfharness/burden`, which uses `getPhysicalAttrValue`,
`getEffectiveSkill`, `item:isArmor()` and mapped inventory fields in one bounded
pass over root inventory caches. It serves status, brief and item receipts and
stays readable with panels or modals open. Missing inputs, invalid caches,
duplicate roots, inventories over 4,096 entries, overflow, mounted units and
hidden-curse variants return explicit unavailability, as does the effective
skill ambiguity at sleep counters 846000 to 863999 when it could change an
armor discount. Status never refreshes caches to fill a value.

DFHack scripts can call the helper directly:

```lua
local helper = dfhack.reqscript('Z:/Users/ma9o/Desktop/df-llm/dfharness/burden')
local load = helper.getBurden(dfhack.world.getAdventurer())
-- load.capacity, load.load_penalty, load.burden
```

Use your package's absolute path, or install the helper alone under
`hack/scripts/dfharness/`. Do not register the repository root as a script
search path.
