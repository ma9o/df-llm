# DFHack reuse audit, 2026-09-07

Sources: the installed DF 0.53.16 Windows Steam / DFHack 53.16-r1.1 bundle
and pinned clones under `.df-llm/upstream/{dfhack,scripts,structures}`.
Tests used a separate `dfharness-combat-fixture` save. Campaign restoration
uses the backed-up `ettin-entrance-2026-09-07` checkpoint.

## Delivered changes

- The native `reqscript` loader receives absolute paths for the entry and each
  dependency. It no longer registers the repository root. DFHack's recursive
  module discovery had loaded duplicate overlays from the reference clones,
  including a second fastcombat and conversation overlay. Removing the old
  script path and rescanning left zero reference overlays and the installed
  canonical overlays enabled. A read-only check preserved the game tick.
- Strike observers and route report watches use `eventful.onReport`, explicitly
  enabled at frequency **one**. Each active observer retains copied report
  scalars in a bounded window. Synchronous cursor catch-up covers delivery
  ordering and unavailable/reloaded plugins. Completion, failure and map/world
  unload remove the observer's callbacks. Overflow and cursor reset are errors,
  never empty successful samples. Full evidence exposes callback/catch-up counts.
- Completed dispatches call the installed fastcombat overlay's `onInput` while
  their submitted input processes. A single deferred frame covers processing
  that starts after the native input handler returns. World/dispatch identity,
  interruption, current screen and readiness guard that activation. The overlay
  owns presentation acceleration. No simulation timers are edited, no overlay
  is enabled against its configuration, and no read query activates it.
- Announcement acknowledgements remain ordinary delegated dispatch inputs.
  Fastcombat activation never dismisses a ready-input announcement or a
  Continue/Stop/Finish prompt. Events and interruption predicates remain intact.
- Target conditions now expose `projectile`. After a knockback, the next strike
  settles this native state before approaching and opening the combat menu.
  It shares completion/step policy, limits, interruption checks and resume state.
  A wait that does not advance the effect is retained and not repeated.

## What the live tests established

The initial paused read immediately after reload showed `world.frame_counter=0`.
The claim that this implied broken event scheduling was incorrect. A precise
strike advanced it to **8**, delivered report **1621** through `onReport` at
frequency one, and resolved as a dodge. Adventure simulation advances this
counter; pausing holds it steady. `cur_year_tick` remained 18686 during these
local turns. EventManager's frequency check tolerates backwards counter resets.
Its absolute tick-queue scheduling is a separate mechanism, not used by the
report subscriptions. See `library/modules/EventManager.cpp`.

A subsequent quick strike produced wound **1**, attributed natively to
adventurer **8525** on sandbox rabbit **11483**, and reports **1622–1623**.
`onReport` delivered them; `onUnitAttack` delivered **zero** events. Both units'
three combat report logs were empty. The pinned EventManager attack code maps
`COMBAT_STRIKE_DETAILS` through those logs and requires two relevant units.
This is why attack callbacks cannot replace native wound attribution here.
An exploratory frequency-zero check did not repair that missing attribution;
its callbacks were removed and the plugin reloaded before integration testing.
Production requests frequency one only.

The integrated strike `89c77577-2deb-4cf7-abab-491f5d82b7cb` waited for knockback,
approached and wounded the target. Its attack observer recorded **3 callback
reports, 0 catch-up reports**, then closed. No harness report subscriptions
remained afterward. Presentation activation was recorded for processing inputs.
The final receipt exposed the new wound and the target's new projectile state.

That objective took **21 inputs, 42 simulation ticks, 56 RPCs, 3.785 seconds**,
and returned **1,257 o200k_base tokens** as pretty JSON. It included landing
reports, an approach and four acknowledged announcements. This is not a matched
latency comparison with the earlier adjacent strikes. The mechanical waits
still incur RPCs; callback reuse does not eliminate those dispatch round trips.
Development probes are outside these measured gameplay interactions. Logs:
`.df-llm/integration-trace.jsonl`, `.df-llm/play-metrics.jsonl`, and
`.df-llm/eventful-live-probe.json`.

## Proposals that are not drop-in replacements

| Proposal | Verified scope and decision |
| --- | --- |
| `onUnitAttack` | Incomplete in this Adventure test. Retain wound IDs plus labelled report-text fallback for misses/defenses. |
| `onUnitDeath`, `onInventoryChange`, `onSyndrome` | Available plugin events, but not substitutes for ongoing blood loss or all new wounds. Do not enable global scans without a consuming feature and a measured benefit. |
| `gui/notify` | The bleeding/suffocation `adv_fn` entries return display bars; underlying blood/breath helpers are local. `injured` is a fortress citizen notification, and wildlife applies its own membership filters. Keep exact native health and controller-selected visibility predicates. |
| `gui/sitemap` | Lists current-site people, artifacts and abstract-building locations. Its local location reader is not the lair-subtype entrance reader. Do not replace the verified entrance coordinates with this unrelated list. |
| `advtools.conversation` | Canonical overlay already enabled. Its native topic insertion remains useful precedent; existing semantic selection uses native identities and hotkeys. |
| `gui/sandbox` | Used successfully to create the live weak-creature fixture. The name is `gui/sandbox`, not `sandbox`. Old `modtools/create-unit` is marked unavailable in the pinned documentation. |
| `bodyswap`, `resurrect-adv`, `flashstep` | Suitable explicitly requested test utilities, unnecessary for this fixture. No test-generated unit, XP or injury should be retained in the campaign. |

## Regression coverage and remaining limits

Python tests cover completion-only presentation delegation and the knockback
prerequisite, including failed-wait resume. Lua fixtures cover absolute package
loading, report delivery/deduplication, native catch-up, plugin absence, bounded
windows, cleanup, route report typing, overlay ownership and prompt protection.
The full character contract remains read-only and reports all 29 sections.

Final validation: `make check` passed **435 Python tests** plus lint, format,
type, dead-code, Lua lint, shell and package-build checks. **276 isolated Lua
fixtures** passed inside DFHack. The campaign was restored at `(94,80,134)`
with **5600/5600 blood, zero wounds and zero exhaustion**; the sandbox unit is
absent. The full CLI/Python/MCP character check verified read-only agreement
across all 29 sections. No reference-clone overlays reappeared after reload.

Active grapple counts are available, but this build exposes the underlying
shared-pointer hold records opaquely. Detailed holds remain explicitly
unavailable. `load-save` is also outdated in the installed scripts (obsolete
title/load-screen fields); restoring this checkpoint used the native title UI.
Neither a capability probe nor an enabled plugin is evidence that these gaps
have been fixed.

The earlier schema-3 projection comparison re-rendered seven identical strike
receipts: **15.5% fewer tokens in total**, median 874 to 741, retaining outcomes,
XP and current impairments. This is a projection measurement, not a claim about
simulation latency. Full traces preserve the native evidence behind each value.
