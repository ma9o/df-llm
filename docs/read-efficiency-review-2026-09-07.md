# Adventure read efficiency and DFHack reuse, 0.26.0

This pass addresses the follow-up review after the eventful/strike work in
0.25.0. Live checks were read-only while the human played. No combat, movement,
save, reload or prompt-dismissal inputs were sent.

## Controller reads

`unit` now requests a native brief inventory, so it does not construct detailed
item definitions and container contents only to discard them in Python. The
concise projection retains all read body-part IDs, effective attributes, skills,
equipment, condition, affiliations and coverage. Attributes share the existing
character-brief projector. Body-part names occur once in an ID map; repeated
injury flags are grouped by flag and native part IDs. A bounded condition summary
cannot hide additional injuries found by the complete anatomy read. Unknowns and
source truncation remain explicit. Full unit queries remain available.

Concise `observe` and `unit` support `since=read_ref` across CLI and Python.
The reference identifies the exact returned reading, independently of `state_id`,
which still guards game input. The SQLite cache beside controller settings holds
32 readings of at most 2 MB each and survives CLI process exits. It matches the
endpoint, world epoch, query arguments and projection settings before diffing.
An expired/mismatched/corrupt base returns a full resync, never an empty delta.
Cache failures preserve the successful fresh read and do not retry it.

The controller delta reuses the existing lossless execution-delta implementation.
`apply_read(previous, response)` verifies both content hashes before returning a
reconstructed snapshot. Full output wins whenever it is smaller than its delta.
No additional DFHack call is needed. This compacts controller traffic; it does
not eliminate the native read or its RPC response.

## Measurements and self-review

All token counts below use the explicitly prepared local `o200k_base` encoding.
These are local payload counts, not model-provider usage.

| Matched sample | Before | After |
| --- | ---: | ---: |
| Same live ettin snapshot, minified unit projection | 3,089 tokens | 2,307 tokens |
| Same snapshot, pretty unit projection | 5,540 tokens / 972 lines | 3,633 tokens / 501 lines |
| Unchanged live scene reread, minified | 4,197 tokens full | 70 tokens delta |
| Unchanged live unit reread, minified | 4,768 tokens full | 72 tokens delta |

The repeated-read pairs used different Python clients to exercise the cache
across client lifetimes. Both pairs had unchanged native input-state IDs. Each
call made one RPC; measured median duration was about 67 ms for observe and
60 ms for unit across these four calls. These are small read microbenchmarks,
not a claim about episode time or combat latency. Changed warnings, injuries,
unknowns, removed fields, false/zero values and menu/list replacements are covered
by round-trip fixtures, including wrong-base rejection.

The larger later unit sample revealed another repetition: a body with 114 missing
parts repeated `missing` and each part's name in both anatomy and condition.
The final grouping change addresses this without hiding those parts. The last
two table rows predate that final grouping; they measure delta transport, not
the final cost of a damaged unit's first full reading.

Local artifacts:

- `.df-llm/read-improvement-metrics.jsonl` and `read-improvement-trace.jsonl`:
  measured calls and RPCs, with an explicit read-only episode label.
- `.df-llm/read-comparison.json`, `observe-delta-live.json`, `unit-delta-live.json`:
  paired sizes and exact reconstructed readings.
- `.df-llm/unit-read-native-full.json`: fixed native sample used for the
  0.25.0-versus-0.26.0 projection comparison.

## Maintained DFHack helpers

Checked against the pinned 53.16-r1.1 references under `.df-llm/upstream/` and
the running installation:

- All nine requested unit predicates are available. They appear in unit reads
  and comprehensive character status under `affiliation.classifications`.
  Boolean false is preserved; missing APIs are unavailable, not false. These
  classifications do not predict an Adventure creature's next attack. The live
  ettin sample returned false for all nine.
- Visible-unit enumeration uses `getUnitsInBox` over the **whole loaded map**,
  then the existing native visibility/hidden predicates. The 500-result and
  32,768-active-unit bounds remain explicit. The old code scanned active units,
  not map blocks; the block scan in the bridge belongs to nearby **items**.
  DFHack's box helper itself scans active units, so this is maintained API reuse,
  not a claimed spatial-index speedup.
- Local site lookup uses `world.getCurrentSite`. The offloaded travel fallback
  remains because the shipped helper requires an adventurer unit. A failed
  helper read differs from a known absence of a current site.
- Navigation and visible tile inspection use the native tile/region biome
  helpers. Live results included region `(7,19)`, temperate shrubland, and all
  requested native properties with zero preserved. Biomes do not prove liquid
  water availability.
- `locate` wraps exported `gui/adv-finder` readers. Live figure 697 and artifact 0
  queries returned usable location records. Native references are copied as IDs
  and coordinates only. This is an explicit world-record query, separate from
  character knowledge and visibility.
- `gui/unit-info-viewer` in this release has no wound formatter. Its display
  covers identity/size and creature-product information. The harness keeps its
  verified native condition reader instead of inventing an exported formatter.

## Save-scoped checkpoints

`session` / `Client.session()` exposes a bounded persistent index. Dispatch registration
stores an active marker before native input; finishing stores the workflow,
summary and compact receipt. Fixed world-data slots retain 128 records of up to
128 KiB each, without uploading full observations or the whole index from Python.
Restoration is lazy. Normal in-memory execution and resume still work as before.
Storage failures leave normal gameplay on its in-memory checkpoint and add
`checkpoint_unavailable` to the receipt, without retrying input. Resuming an
eligible saved checkpoint requires recording its supersession first; a failed
write there rejects the resume before input.

`saveWorldData` stores data in DFHack memory; DF writes it to disk with the next
game save. It is not an immediate disk commit, an automatic game save, or recovery
for unsaved play. An older save restores its own stored checkpoint and continuation
relationships, replacing any newer RAM version of those IDs.

After reload, only an explicit resume at a verified fresh stage is eligible.
It must match the saved native state: adventurer, calendar, map frame, health,
inventory, visible units, reports and decoded interface. The portable guard
excludes process epochs, the resettable local frame counter, save-folder name and
render dimensions; it never substitutes for a fresh input guard. A native action
must not be queued, and the local default interface must be ready. Pending recipe
markers, uncertain input delivery, active dispatches and old choice handles never
become resumable through this mechanism. Their limitations remain visible.

Isolated Lua fixtures cover restart, older-save rewind, superseded continuations,
pending-input rejection, exact JSON types, corrupt data, storage errors, bounded
slots and lazy-memory retention. Native API presence and the read-only session
index were checked live. **Live save/reload/resume has not yet been exercised**
while the human is playing; this is the next integration check.

The full character report remains schema 2 with 29 sections. Added classifications
participate in its coverage. The existing cancelled-strike, native miss/refusal,
eventful-report and fastcombat fixes remain covered by the combined test suite.

Final checks: `make check` passes 428 Python tests, lint, formatting, types,
dead-code checks, Lua checks, shell checks and the 0.26.0 build. The in-game Lua
fixture runner passes 293 cases with zero game inputs. The MCP server,
CLI entry point, project configuration, transport schemas and dedicated tests
have been removed. CLI and Python share the same action discovery, execution,
readers and metrics. Gameplay validation tests now exercise those supported
boundaries directly. Historical metric rows remain readable. A persistent Python
process amortizes tokenizer setup; each DFHack RPC still opens its own socket.
