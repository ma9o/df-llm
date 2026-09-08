# Gameplay reference

For routine play, load the [agent guide](../dfharness/guide.md), then
`./dfctl actions NAME` for the exact schema and `./dfctl COMMAND --help` for
flags. Examples run from the repository root; replace the IDs and coordinates
with fresh readings. All actions share the
[dispatch policy](controller.md#dispatch-policy). `./dfctl capabilities` reports
runtime availability and limits.

## Trading

Find stock with `shops --stock` and `items --building ID`, open a specific shop
with `open-trade UNIT --shop ZONE`, read its catalog with `barter --type ARMOR`,
and submit an explicit offer with `trade`:

```sh
./dfctl act '{"type":"trade","unit_id":12388,"take":[{"item_id":130480,"amount":1}],"give":[],"offer_currency":113}' --mode complete
```

`base_value` is not an accepted price. The merchant may refuse or counteroffer;
the receipt returns the native reply and any counter amounts, and the controller
chooses whether to submit a new explicit offer. No pricing or item selection is
automatic.

The adapter validates the native context, both sides, quantities, currency
bounds and a unique visible `Trade` button before changing the draft. It then
clicks that button so DF's own handler performs the trade, and verifies the
exact source and destination quantities plus the player's native currency
change. The merchant's amount-entry maximum is not a conserved balance and is
not checked. Missing or ambiguous buttons block before any write. An unverified
submission is never repeated by resume. The button lookup requires English UI
text.

Sale items must be held separately: compose `close_trade`, `remove`,
`open_trade` and `trade` to sell equipped items. Nonempty containers and
contained rows are unsupported because their native selection scope is broader.
Compact values include items, currency change and resulting load.

`shops --type Armorsmith --limit 3` reads native shop records in the current
site, or in another loaded site with `--site-id`. Types are native
`site_shop_type` tokens such as `FoodImports`, `GeneralImports`, `Carpenter`
and `LeatherGoods`. Results are sorted by distance and give loaded zone centers
and building facing; a record does not prove a shopkeeper or stock is present.
`--stock` adds item counts from loaded Shop subzones plus production allotments
by category. `stock_allotments.armor_materials` groups armor allotments by native
material token, with `armor_materials_complete` and bounded errors for missing
references. These records cover the site's shops even when their local tiles
are unloaded; they do not provide actual item IDs, quality, fit, weight or prices.
Sales can leave allotments out of date. Check `barter` or loaded items before
buying. `shops --stock --limit 100` surveys up to 100 shops; check `truncated`.
The site's primary zone is often Home; its currency chest is not proof of sale
stock. An armorer can trade directly from Home through `talk UNIT --topic Trade`
even when no separate Shop subzone exists. `items --building ID --type ARMOR --limit 20` reads matching
stored items, and `item ID` accepts visible furniture stock.

`open-trade MERCHANT_ID --shop ZONE_ID` approaches the merchant, requests Trade
and selects that merchant's Shop catalog, using the zone IDs from
`shops --stock`. Both traders must be inside the shop and the merchant assigned
to it. Existing offers, quantity edits and nonempty filters block a catalog
change. `barter --side give` reads the player's offered goods. `close-trade`
closes the interface.

## Sequences and collected results

`sequence` runs an ordered list of semantic actions as one dispatch. Each stage
must reach its verified completion condition before the next begins. Stages
share one input budget, timeout, interruption policy and event history.

```sh
# Explicit equipment choices, then a posture goal, in one dispatch.
./dfctl sequence '[{"type":"equip","item_id":14427,"replace":[14426],"disposition":"stow","container_id":14382},{"type":"set_posture","posture":"standing"}]' --mode complete --acknowledge

# Explicit people and topics; approach each, collect the reply, close the UI.
./dfctl converse 10657 10660 --topic AskAboutCurrentState --mode complete --acknowledge
```

The same actions work through `Client.act` with an `execution` object of
`mode`, `acknowledge`, `max_steps` and `interrupt_on`.

Compact composed receipts report `completed_stages`, collected `said` replies
and the unresolved stage in `blocker`. Resume after a limit or interruption
keeps completed stages and never reselects a sent topic. The sequence stops at
the first unresolved stage; it does not skip failures or invent a fallback.

Limits: 1 to 64 actions per sequence and at most 128 expanded stages;
`converse` accepts 1 to 32 distinct unit IDs and 1 to 16 topics. A sequence may
contain `converse`; nested sequences and raw inputs are unsupported. The shared
input budget defaults to 32 and can be raised to 1,024. Local coordinates and
excluded tiles in a sequence refer to its initial map origin, including stages
that have not started, and stay on those world tiles across map rebases. If a
coordinate frame becomes unavailable the harness returns
`coordinate_frame_changed`. Targets chosen after travel need a fresh reading.

Item receipts return `values` with the resulting location, cached carried load
and burden from unit state. For containers, `contents.intact` compares item
identities, parent containers and stack quantities with the initial
observation; missing or truncated readings produce null, and content IDs are
bounded to 64. `changes.inventory.containers_removed` groups a departing
container with the contents still observed inside it. For a sequence,
`assessment.load` reports the load once and stage values omit repeated load
blocks.

## Items and equipment

`items` reads visible nearby ground items and nested container contents; `item`
inspects one carried, ground or furniture item. Both expose IDs, material,
quality, wear, stack size, raw mass and volume, container location, armor
coverage and layer data, the native `shaped` flag, and weapon definitions.
Mass is `weight_raw.whole/fraction` with `weight_computed` marking cache
validity. A held garment also has role `Weapon`; use the item `type` to tell
weapons apart. `fit.wearable_now` stays unknown until a native Wear menu
establishes eligibility.

`equip` and `wield` accept `replace: [ITEM_IDS]` and
`disposition: "hold" | "drop" | "stow"`; stowing needs `container_id`. The
workflow acquires the target, removes only the named replacements, equips the
target, then applies the disposition after verifying the new equipment. It
never selects better gear or infers what to remove. An optional `body_part_id`
is an exact postcondition; if the game chooses another part the dispatch
returns for controller input.

```sh
./dfctl equip 14429 --replace 14438 --disposition stow \
  --container-id 495 --body-part-id 15 --mode complete --acknowledge
```

`drop` and `stow` remove a worn item first, under the same budget and
checkpoint. They never discard other equipment to free a hand. If the native
menu has no matching operation, the blocker names the item, role and menu
context.

Menu options expose native item and container IDs, labels and option IDs.
Semantic actions scroll and select the requested ID even when labels repeat.
`select-option OPTION_ID` selects a controller-chosen option, including one
that needs scrolling; the binding is rechecked inside the game before input.
One selection is one input. Reads never scroll. Active scroll dragging, filter
editing and undelegated quantity entry block selection.

## Saving and loading

`quicksave NAME` (alias `save-game`) writes an adventure checkpoint through the
repository's DFHack quicksave extension in one request. Names take 1 to 40
letters, digits, spaces, underscores and hyphens, starting with a letter or
digit; native working and autosave folders are reserved. An existing name
returns `save_exists` unless `--overwrite` delegates replacement. Completed
receipts include the verified name and file timestamp; no save is claimed
because a menu closed. Use `--seconds 120` for a slow save; the dispatch's
remaining time also bounds its RPC waits. Save-and-quit and timeline selection
are unsupported.

`quickload NAME` (alias `load-game`, Python `Client.load_game`) loads an exact
folder from the title screen with no world loaded. It does not quit a running
adventure. `--seconds 120` bounds loading, which is never restarted. The client
submits once, polls read-only, verifies the loaded name and readiness, and
returns fresh choices and a `state_id`.

## Inspecting units

`unit ID` inspects a visible character's health, attributes, skills, equipment,
anatomy, affiliations and native opponent reference. DFHack's danger, wildlife
and curse predicates appear as `classifications`, including false and
unavailable values; they do not predict an attack. The concise default keeps
every body-part ID in `body.parts` and groups active `body.status_flags` by
flag, which is what `strike` needs. `unit ID --view full` adds item definitions
and container contents. Unloaded or invisible units return `available: false`.

## Food, liquids and containers

`drink ID --portions N` consumes 1 to 32 portions of a carried liquid;
`drink CONTAINER_ID --from-container` resolves fully observed liquid contents
and pins their IDs. `eat ID --portions N` does the same for food. Each portion
requires a reduced source stack, a native `DRINK_ITEM` or `EAT_ITEM` report and
a verified need effect; a menu selection alone never completes it. Different,
unreadable or frozen contents block; frozen contents return
`source_not_liquid`. Fullness warnings can appear in the `CONSUME_FAILURE`
category even when drinking succeeds; the verified effect decides completion.

`drink-from X Y Z MATERIAL --portions N` approaches the tile and selects only
that material in `Liquid` state from the native menu. It supports terrain
sources; wells and ground containers are unsupported. Equivalent native source
entries with the same material, phase and coordinates are treated as one choice.

`thaw CONTAINER_ID X Y Z` heats a carried container at the specified heat
source; further heating requires observed temperature or melting progress.
`fill-container CONTAINER_ID X Y Z MATERIAL --source-state STATE` fills to
native capacity, verified by capacity and summed volumes; freezing or melting
can change item IDs without changing the goal. `empty-container CONTAINER_ID`
empties the whole vessel through its native option and requires empty contents
plus an `EMPTY_CONTAINER` report. Because DF's drop on a contained liquid
performs that broader operation, `drop LIQUID_ITEM_ID` stops before selecting it.

## Rest and sleep

`rest HOURS` waits awake; `sleep HOURS` sleeps as necessary. Both configure the
native panel and verify calendar progress across local map unloading and
reloading. An early stop returns the elapsed duration and a resumable
checkpoint and never starts another rest. Sleep can leave the character prone;
standing is a separate action. A native `CANNOT_REST` refusal returns
`rest_restricted` and stays blocked on resume.

`--until-dawn` is exclusive with hours. It uses the native dawn control and the
local clock and longitude; `status` shows the calculation under
`activity.next_dawn`. Unknown clock data, arena mode and no visible sky are
blockers. A start exactly at dawn targets the following day. Successful live
until-dawn completion has not yet been observed.

## Local movement and stairs

Local walking submits the game's path command and lets DF compute and follow
the route. The same executor approaches items, conversation partners, combat
targets and environmental targets. One path command is one input regardless of
its tile count. Step mode stops at the first movement boundary; resume keeps
the destination. Interruption cancels the remaining owned goal; an already
submitted move may finish. Reachability uses `canWalkBetween`, whose cache can
be stale; the harness reports a no-connection blocker and never refreshes it.
The native goal may cross to another loaded z-level when DFHack reports a
connection.

`arrival_radius` (0 to 48, Chebyshev, on the target z-level) permits arrival at
an observed reachable neighbor. Stairs require the controller to name the tile
and direction with `use-stairs X Y Z up|down`; arrival verification accounts
for map rebasing.

The native command has no excluded-tile, depth or occupancy fields. Supplying
`allow_occupied`, `max_liquid_depth`, `blocked_tiles` or `extend_route`
switches that dispatch to the legacy observed-route adapter, which plans on the
current z-level through the observed crop, expanded toward the destination up
to 101 by 61 tiles. With that adapter `allow_occupied` defaults to false,
`max_liquid_depth` to 7 and `blocked_tiles` to empty. A blocked destination
returns its exclusion reasons and occupants. `extend_route` advances through
observed frontiers to reveal a route and stops when no unvisited frontier is
reachable or its 4,096-position memory is full. Unseen terrain is never assumed
walkable. These are route constraints, not a threat classifier.

Travel uses native directional moves and the site-grid adapter; there is no
native travel route command. Travel tiles are 16 local tiles; three make one
embark tile. Overland input can advance up to three tiles while the game still
reports input readiness, so the receipt waits for a short quiet window of
unchanged travel state, then verifies coordinates. `travel_to` returns at
blocked movement, a native restriction or a forced exit from travel, with
bounded native position, zoom, not-moved and exception facts. An unchanged
pending move stays checkpointed so resume can verify a late arrival without
repeating it. `end-travel` returns to local mode and verifies map loading. The
enlarged travel map is reported in `open_panels`; semantic objectives close it
with its native toggle before continuing.

## Combat

`strike` performs one requested melee attempt: approach, target, aim, style,
submission and recovery. Supply the target's native `body_part_id`, the
weapon's `item_id` and `attack_index`, and `style=normal|quick|heavy|wild|precise`.
`item` exposes attack indices; `unit` exposes body-part IDs. For a natural
attack use `item_id=-1` with its body-plan attack index. A strike clears
residual charge and multiattack flags, verifies each style toggle and reopens
an incompatible aiming menu as needed. It never chooses another weapon, limb or
target.

```sh
./dfctl strike 8182 --body-part-id 3 --item-id 485 --attack-index 0 \
  --style quick --mode complete --acknowledge
```

The receipt captures the queued native attack and verifies its preparation and
recovery. A strike value reports `resolution=wounded` with new wound IDs, or
`missed`, `dodged`, `blocked`, `parried` or `out_of_range` when an unambiguous
English report says so, labelled `source=report_text`. Unknown wording stays
`processed` with `damage=unverified`. A vanished attack with an attributable
player dodge or knockdown completes as `cancelled` with `recovered=false`; an
unexplained disappearance returns a blocker and is not repeated. A target
propelled by a previous blow settles before the next strike opens its menu.
Target conditions keep life state, consciousness, posture, wound count and any
existing bleeding, impairment or grapple explicit, and diff other fields against
the dispatch's starting sample. Finishing an attempt does not promise injury.

Native refusals for standing, pickup, rest, climbing and campfires use the
game's text as the blocker reason with its report type and ID as facts. Resume
verifies existing progress without replaying the refused input.

`combat` opens the target's native combat choices and returns them; it is
discovery, not execution. Defense, wrestling, charge, multiattack and ranged
attacks are unsupported.

## Navigation and world

`navigation` returns travel coordinates and character-known group and beast
rumors sorted by distance, plus the current site and, for a lair, its native
entrance. Rumors are leads, not verified enemies. `--view full` adds the site
travel grid. `locate figure ID` and `locate artifact ID` query world records
through the exported `gui/adv-finder` readers; they do not imply the character
knows the location. `world-scan` searches site records by type, flag or name;
see [world scan](world-scan.md). `inspect X Y Z` reads a tile with its items,
creatures, building and biome. `game-status` keeps player identity, world time
and party need counters while fast travel offloads the local map.

Map features include visible buildings, door flags, wells and connected water,
magma, ice and brook regions with nearest tiles. A well does not prove usable
water. Posture is returned as `on_ground`.

## Conversations

`talk ID` approaches and opens the conversation. `talk ID --topic LABEL_OR_TYPE`
selects an exact native label or a unique topic type; `--choice-id ID` selects
an observed choice; `--tact Persuade|Intimidate` delegates the tact picker for
a topic that needs one; `--subject-hf-id HF` names a historical-figure subject.
The harness handles the target picker, scrolling, delegated help and the
interrogation submenu. Unrelated topics are never substituted.

A supplied topic defaults to `completion="reply"`: our utterance must appear in
the native turn history, followed by a new utterance from the target and reports
from the same activity. Another speaker or conversation does not prove a reply.
The harness closes the menu and takes bounded short waits under the dispatch
policy; it does not reselect the topic. `--completion utterance` stops after our
speech. Submenus, ambiguous topics and undelegated tacts return `needs_input`.
`end-conversation` verifies the interface closed; it does not end the native
social activity.

`converse UNIT... --topic T` visits each person in order, asks each topic,
collects replies and closes the interface. It chooses no people, topics or
tactics. Include `Greet` first for a new acquaintance if the menu requires it.
`--topic-spec '{"topic":"FishForPlots","tact":"Persuade"}'` supplies per-topic
arguments and may be mixed with `--topic`.

Reports carry stable IDs, speaker IDs and activity IDs; match both to tell a
reply from nearby chatter. Ordinary reads keep the last 80 reports; dispatches
collect forward pages.
