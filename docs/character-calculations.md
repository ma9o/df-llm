# Character calculation provenance

`dfharness/character_calculations.lua` contains the remaining movement and need
models. Capacity, load penalty and burden now live in the standalone DFHack Lua
helper `dfharness/burden.lua`, shared by status, brief and item receipts. That
helper uses DFHack's attribute/skill APIs and mapped root inventory caches; it
has no executable identity or HUD dependency. The source in its results is
`dfhack_lua_unit_burden`.

The remaining models use mapped DFHack fields and read-only getters; they never invoke
native movement or weight calculations, refreshes caches, sends inputs,
advances time, or needs screenshots. The native movement routine itself can
refresh body/weight caches and optionally train attributes, so calling it from
status would violate the read-only contract.

The movement/need models' supported build is DF 53.16 Windows Steam (`v0.53.16 win64 STEAM`), PE
timestamp `1785767641`, analyzed with DFHack 53.16-r1.1. The installed executable's
SHA-256 is `205770918fd54c96cbbcf89223ebd449e2e113c7c873ed81177c4511a3450db7`.
Runtime checks require that version string, Windows, and that PE timestamp.
Other builds leave those models unavailable. The fingerprint does not detect arbitrary
in-memory patches that retain the same build identity.

The audit read the user's installed executable and matched accesses against
runtime DFHack structure offsets. Addresses below are RVAs relative to the PE
image base, not runtime addresses. No executable or disassembly is required or
distributed with the production harness. Development artifacts are in the local
`.df-llm` directory; `pefile` and `capstone` are development-only analysis tools.
DFHack's [public movement helper is disabled](https://github.com/DFHack/dfhack/blob/53.16-r1/library/modules/Units.cpp),
and its commented pre-v50 carrying-capacity formula differs from this build.

| Native code | RVA / range | Use |
|---|---|---|
| Adventure movement calculation | `0x1334c10`–`0x13356b9` | Current gait, buildup, condition modifiers, attributes, inventory, final clamp |
| Inventory load and capacity | `0x13353e2`–`0x13355b1` | Armor discount, mass quantization, capacity, extra movement cost |
| Adventure HUD call site | `0xafaf0a`–`0xafaf3b` | Current/full gait calls and rate conversion |
| Adventure HUD burden icons | `0xafa2ac`–`0xafa3c7` | Capacity/load comparison, light and heavy burden thresholds |
| Effective skill | `0x133e7a0`–`0x133eacc` | Rust and health/need reductions for movement-related skills |
| Flight eligibility | `0x7e0610`–`0x7e069a` | Flight flag, functional wings, unconscious/web/paralysis checks |
| Swimming skill | `0x13ade30`–`0x13adf78` | Swim capability and skill multiplier |
| Adventure need labels | `0x164a6f`–`0x1654d9` | Need thresholds and native label strings |

Windows exception tables split the movement routine into chained unwind
fragments. Reading only its first exception-table range omits most of the
calculation. The audited range includes the complete routine and its branches.

## Capacity and load

Capacity is the threshold before a movement penalty, **not a hard maximum** on
inventory. Native capacity/load comparisons use 0.01 kg units. With `S` the
current body size and `A` effective strength:

```text
S < 300000: capacity = max(1, trunc(S * A / 1000))
otherwise: capacity = max(1, trunc(S / 1000) * A)
capacity_kg = capacity / 100
```

The burden helper obtains effective strength from `dfhack.units.getPhysicalAttrValue`.
It reports hidden-curse variants as unsupported. Physical
body size retains native units; it is not assumed to be the old DF size scale.

Inventory calculation reads each native root inventory entry once, using valid
mass caches. Container and stack caches already include their contents and
quantity. `total_weight_kg` remains undiscounted physical mass. For the penalty,
items with native `isArmor()` in `Worn` or `WrappedAround` roles receive the
effective Armor User skill discount. Held shields/weapons and worn containers
do not receive that discount unless they satisfy these native tests.

At skill 0 or 1 the full mass applies. For skills 2–14, each item's whole-kg
and fractional-milligram components are **separately** multiplied by
`(15 - skill) / 16` and truncated. At skill 15+ they contribute zero. This
separate-part rounding matters: 27.3075 kg at skill 2 becomes 21.249843 kg for
the penalty, not 22.18734375 kg. After summing the components, the native
comparison weight is `whole_kg * 100 + trunc(fraction / 10000)`.

For positive excess `E = weight - capacity`:

```text
E < 1000000: extra_cost = max(1, trunc(E * 2000 / capacity))
otherwise:  extra_cost = max(1, trunc(E / capacity) * 2000)
```

Adventure mode does not use the fortress-only 5000 extra-cost cap. The eventual
movement cost is clamped to 0–9999. Equipment-like/scuttle units ignore inventory
load; ghost and debug-turbospeed paths bypass normal modifiers. Invalid caches
produce unavailable calculations, never a zero or stale-mass estimate.

### Burden state

`encumbrance.burden` calculates the burden state separately from movement cost.
Using the same integer comparison weight and capacity, the native HUD chooses:

| Condition | State / label | Native icon |
|---|---|---|
| `weight <= capacity` | `unburdened` / Unburdened | None |
| `capacity < weight <= trunc(3 * capacity / 2)` | `burdened` / Burdened | `ADVENTURE_BURDEN_LIGHT` |
| `weight > trunc(3 * capacity / 2)` | `overburdened` / Overburdened | `ADVENTURE_BURDEN_HEAVY` |

The reported labels name these icon states; Unburdened means no burden icon.
Both boundaries use strict greater-than comparisons. The heavy state is distinct
from the first movement penalty: a 63.04 kg capacity gives a 94.56 kg heavy
threshold. The report returns the label, severity, `burdened` and `overburdened`
booleans, percentage and kilogram thresholds without reading the interface.

Unknown load/capacity leaves the entire burden state unavailable, including its
booleans. Mounted and hidden-curse HUD capacity variants are explicitly
unsupported. Speed exemptions are not assumed to suppress the HUD icon: native
HUD code compares carried mass even when a speed calculation ignores load.
The helper delegates effective armor skill to DFHack. Its known 846000–863999
sleep-boundary ambiguity is unavailable when it could affect a worn armor
discount; an integer result from that port cannot be reliably corrected without
the pre-division value. Burden never chooses action or interruption policy.

## Calculated movement

The active mode follows native state: climbing hold, swimming/floundering,
crawling, flight eligibility, or walking. The calculation uses
`enemy.gait_index`, not the selected menu command. It interpolates current gait
cost between start and full speed while buildup is incomplete.

The native sequence applies curse speed modifiers; swimming skill or wading
depth; baby/diving state; exhaustion, wounds/condition counters and soldier mood;
blood/hunger/thirst/sleep penalties; dragging, crutch, paralysis and webs; the
current gait's strength/agility/body-size scaling; stealth, stance loss and
melancholy; carried load; and the final clamp. Integer division order is retained.
The movement skill model uses native sleep threshold **864000**; DFHack's
public effective-skill helper currently uses 846000 at that particular stage.
Stored and DFHack effective skill records elsewhere in status remain unchanged.

For final movement cost `C`, the HUD computes:

```text
rate = 1000 / (C + 100)
displayed_rate = trunc(1000000 / (C + 100)) / 1000
```

The report supplies unrounded rate, formatted display value, cost, delay,
contributing components, rate at full gait buildup, and an unloaded comparison.
The unloaded comparison removes only the carried-load cost and retains every
other input and the final clamp. `speed_reduction_percent` compares those two
rates; `movement_delay_increase_percent` compares their inverse delays. These
are different percentages. Values use native HUD units, not wall-clock speed.
They describe the movement calculation, not whether an incapacitated character
can actually issue a move or reach a particular tile.

## Native need stages

Threshold comparisons are inclusive. These are native counter units, not a
prediction of wall-clock time or number of controller dispatches remaining.
Some adjacent stages use the same text with different UI emphasis; numeric
severity preserves their order instead of merging them.

| Need | First warning | Later stages |
|---|---|---|
| Hunger | 57600: Hungry | 172800: Hungry; 1209600: Very hungry; 2592000: Starving |
| Thirst | 57600: Thirsty | 115200: Thirsty; 172800: Very thirsty; 345600: Dehydrated |
| Sleep | 115200: Drowsy | 172800: Drowsy; 259200: Drowsy; 345600: Very drowsy; 864000: Slumberous |
| Blood thirst, when applicable | 172800: Thirsty | 1209600: Thirsty; 2419200: Thirsty! |

Below the first threshold, the harness label is `No warning`, `severity` is 0,
and `native_label` is absent; the UI has no warning label to return. This does
not claim the character is full or has just rested. Creature flags `NO_EAT`,
`NO_DRINK`, and `NO_SLEEP` produce `Not required`/`state: exempt`, preserving
the counter. Debug timer overrides are reported separately. Each required need
includes the next stage's label, counter threshold, and remaining counter units,
unless already at the last stage. Labels never choose controller actions,
dispatch completion, or interruption policy.

## Verification and limits

Live read-only CLI and Python queries must agree. The live check compares
calculated display speed with the ASCII HUD when visible, and checks unchanged
time, action serial, position, health, inventory, focus, panels, and modal state.
Synthetic Lua fixtures exercise every need boundary and arithmetic/state
branches without creating units or changing the adventurer.

For Athis (unit 8525), size 5731, strength 1100, Armor User 1, and 98.46225 kg
carried produce capacity 63.04 kg, native excess 35.42 kg and extra cost 1123.
Walk cost 900 becomes 2023: rate 0.4710315591, displayed **0.471**, matching the
native HUD. The unloaded rate is 1.000; isolated speed reduction is 52.89684409%.
Hunger/thirst/sleep counters 9261 all have no warning. This is one observed live
state; remaining scenarios have fixture coverage, not live gameplay validation.

Unsupported versions, mounted travel, missing/invalid gait or body caches,
unknown vision adjustments, missing inputs, and calculations that would exceed
native signed 32-bit arithmetic return explicit unavailability. Inventory scans
are limited to 4096 entries. Capacity, added load cost, need interpretation, and
effective speed report availability separately, so one missing value does not
erase other known status. No UI availability is required for these calculations.
The character query targets the adventurer; native follower speed matching is
not extrapolated into a companion travel calculation.
