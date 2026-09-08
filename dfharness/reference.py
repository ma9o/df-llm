"""One reference for every dfctl command: summary, contract and argument help.

cli.py builds each subparser from this table, so ``dfctl COMMAND --help`` prints
the contract, and actions.py attaches the same text to ``dfctl actions NAME``.
A test enforces that every command and argument is covered, so this module is
the only place command behavior is documented.
"""

import argparse
from textwrap import dedent
from typing import TypedDict


def _text(value):
    return dedent(value).strip("\n")


OVERVIEW = _text(
    """
    Start with `dfctl guide` (offline). Each command's contract: `dfctl COMMAND --help`.
    Exact action JSON schemas: `dfctl actions NAME` (underscore names).

    Reads, no game input:
      look/observe brief status game-status unit item items navigation shops barter
      locate world-scan inspect session dispatch-details capabilities actions settings
      wait-ready
    Actions, one dispatch each; policy flags go after the command:
      --mode step|complete   --acknowledge/--no-acknowledge   --max-steps N (1..1024)
      --seconds N (<=300)    --interrupt-on JSON   --expect STATE_ID   --after look
      walk-to move wait use-stairs travel-to end-travel pickup equip wield remove drop
      stow empty-container fill-container thaw drink drink-from eat rest sleep
      set-posture set-gait set-sneaking make-campfire talk converse end-conversation
      combat strike open-trade trade close-trade save-game sequence act resume respond
      dismiss select-option select-interaction interrupt
    Development only:
      setup launch doctor run keys key click choose text select-unit load-game
      metrics audit-log

    Outcomes: completed | in_progress (step mode) | needs_input (choice or blocker)
      | interrupted (your predicate matched) | no_effect | limit_reached
      | failed (partial effects possible) | rejected (stale --expect; nothing sent)
    Receipt: values, said, outcome, changes, blocker{kind,why,facts}, choices,
      state_id (next --expect), resume{dispatch_id}, after (with --after look)
    """
)

# Help for argument destinations shared by several commands. A command's own
# ``args`` entry takes precedence.
SHARED_ARGS = {
    "x": "Local map x",
    "y": "Local map y",
    "z": "Local map z",
    "unit_id": "Native unit ID",
    "item_id": "Native item ID",
    "container_id": "Carried container ID",
    "portions": "Portions, 1..32 (default 1)",
    "seconds": "Dispatch time limit in seconds, up to 300 (overrides settings)",
    "since": "Previous read_ref; return only the fields that changed",
    "view": "concise or full",
    "limit": "Maximum rows to return",
    "radius": "Search radius in tiles, up to 50 (default 20)",
    "allow_occupied": "Legacy route adapter: allow routes through occupied tiles",
    "max_liquid_depth": "Legacy route adapter: deepest liquid to cross, 0..7",
    "blocked_tiles": "Legacy route adapter: JSON list of {x,y,z} tiles to avoid",
    "extend_route": "Legacy route adapter: advance through observed frontiers to reveal a route",
    "arrival_radius": "Stop within this many tiles of the target, 0..48 (default 0)",
    "result_format": "compact receipt (default) or full diagnostic record",
    "text": "Readable text instead of JSON",
    "dispatch_id": "Dispatch ID from a receipt or session",
    "option_id": "Guarded choice ID from the current choices",
    "replace": "Item IDs to remove first; nothing else is removed",
    "disposition": "hold (default), drop, or stow replaced items into --container-id",
    "body_part_id": "Require the item to end on this native body part",
    "material": "Exact native material token, for example WATER",
}

_ROUTE_NOTE = "Route flags switch to the legacy observed-route adapter; prefer the native default."


class Command(TypedDict, total=False):
    summary: str
    details: str
    args: dict[str, str]


COMMANDS: dict[str, Command] = {
    "guide": {
        "summary": "Print the offline agent guide; reads no settings and records no metrics.",
        "details": _text(
            """
            Start here. The guide covers reads, delegation, receipts, blockers and
            resume in about 120 lines. Load one command's contract with
            COMMAND --help and an action's exact JSON schema with actions NAME.
            """
        ),
    },
    "doctor": {
        "summary": "Find the CrossOver bottle, DFHack, saves and the RPC connection.",
        "details": _text(
            """
            Reports the discovered installation, the configured loopback port and
            whether DFHack answers on it. Port order: --port, DFHACK_PORT, the
            game's remote-server.json, then 5000. Run it when a connection fails.
            """
        ),
    },
    "audit-log": {
        "summary": "Summarize RPC and receipt sizes from JSONL --log files; no game connection.",
        "details": _text(
            """
            Separates processing polls from settled observations, reports RPC and
            payload size distributions, counts outcomes and errors, and lists the
            largest compact receipts with their largest fields. Sizes are minified
            JSON bytes.
            """
        ),
        "args": {"paths": "One or more JSONL files written with --log"},
    },
    "metrics": {
        "summary": "Summarize passive measurements offline, compare a baseline, or prepare a tokenizer.",
        "details": _text(
            """
            Measurement records operation, outcome, timing, bytes and correlated RPC
            costs per controller call, never payload text. It is off by default;
            enable it with settings --set '{"measurement":{"enabled":true,"run":"NAME"}}'
            or the global --metrics PATH flag. Token counts need a --log capture of
            the same calls plus --tokenizer NAME; --prepare-tokenizer NAME is the only
            step that may download. Reports split episodes at idle gaps; a gap is not
            proven thinking time.
            """
        ),
        "args": {"paths": "Measurement JSONL files (default: the path in settings)"},
    },
    "setup": {
        "summary": "Write the game's loopback RPC port into its DFHack config; restart DFHack after.",
        "details": _text(
            """
            Edits dfhack-config/remote-server.json with allow_remote false, backs up
            an existing file and preserves unrelated settings. Use --port here, not
            the global flag. The client always connects to 127.0.0.1.
            """
        ),
        "args": {"setup_port": "Loopback port to configure (default 5001)"},
    },
    "launch": {
        "summary": "Ask Steam in CrossOver to start Dwarf Fortress with DFHack.",
        "details": _text(
            """
            Do not launch while the game is already running. If Steam installs the
            DFHack hook but does not start the game, --direct starts the executable
            with that installed hook. Check readiness afterwards with game-status.
            """
        ),
    },
    "status": {
        "summary": "Comprehensive read-only character report: body, needs, skills, items, history.",
        "details": _text(
            """
            Returns every supported section with per-section coverage: identity,
            health, anatomy and wounds, attributes and skills, needs and personality,
            equipment and gaits, encumbrance and burden, relationships, knowledge,
            abilities, possessions, obligations, senses and history. Missing data is
            distinct from zero, false or empty; check character.coverage, unavailable
            and truncated. Sends no input and opens no menu. It is large: use look,
            brief or game-status in the control loop and status for a full
            assessment. character-status is an alias.
            """
        ),
        "args": {"text": "Readable summary followed by every section"},
    },
    "game-status": {
        "summary": "Mode, screen, input readiness, world time and versions; nothing else.",
        "details": _text(
            """
            Works while fast travel has offloaded the local map, when the full
            character reader cannot. Use it to check readiness or the loaded save,
            not for character state.
            """
        ),
    },
    "load-game": {
        "summary": "Development: load an exact save folder from the native title screen.",
        "details": _text(
            """
            Requires the title screen with no world loaded; it never quits a running
            adventure. Submits the native title choices once, polls read-only,
            verifies the loaded folder name and input readiness, and returns fresh
            choices and a state_id. The time limit never restarts loading; a
            different loaded save returns interrupted with both names. quickload is
            an alias.
            """
        ),
    },
    "session": {
        "summary": "List recent dispatch IDs held in the running DFHack session.",
        "details": _text(
            """
            The session keeps the last 128 dispatches in memory. Progress survives
            controller restarts while the same world and adventurer stay loaded;
            game restart or world reload revokes it and every choice handle. There
            is no cross-reload recovery.
            """
        ),
        "args": {"limit": "Most recent dispatches to list, 1..128 (default 20)"},
    },
    "brief": {
        "summary": "Character essentials: health, needs, attributes, skills, equipment, load, movement.",
        "details": _text(
            """
            A projection of status that labels what it omits. Skills carry xp as
            [current, next_threshold]. Encumbrance reports the native cached load
            and the DFHack burden helper's capacity, burden and load penalty.
            --since REF returns only fields changed since that read_ref; an expired
            base returns a full read.
            """
        ),
    },
    "unit": {
        "summary": "Inspect a visible unit: condition, body-part IDs, skills, attributes, equipment.",
        "details": _text(
            """
            The concise default keeps every body-part ID in body.parts and groups
            active status flags by flag, which is what strike needs. classifications
            carry DFHack's danger, wildlife and curse predicates with false and
            unavailable preserved; they do not predict an attack. --view full adds
            item definitions and container contents. An unloaded or invisible unit
            returns available false.
            """
        ),
        "args": {
            "unit_id": "Native unit ID from look or navigation",
            "view": "concise omits item definitions; full returns the complete inspection",
        },
    },
    "settings": {
        "summary": "Read or save controller defaults shared by the CLI and Python.",
        "details": _text(
            """
            Saved in .df-llm/controller.json (or --settings PATH / DFLLM_SETTINGS) and
            reread on every call. Precedence: built-in, saved, global CLI flags, then
            per-action flags. Built-ins: mode step, acknowledge false, max_steps 32,
            dispatch_timeout 30, result_format compact, event_detail task,
            observation_view concise. --set accepts JSON with those keys plus
            measurement.

            interrupt_on is a JSON object of factual predicates checked before every
            input and compared with the dispatch's first observation:
              blood_loss, new_wounds, new_visible_units        booleans
              visible_unit_ids [IDS], report_types [TYPES]     exact native lists
              new_visible_units_except [IDS]                   exclusions
              unit_health [{unit_id, blood_loss, new_wounds}]  up to 32 named units
            A missing requested reading blocks with needs_input; it is never treated
            as healthy. A per-action --interrupt-on replaces the whole saved object.
            """
        ),
        "args": {
            "settings_update": "JSON object merged into the saved settings",
            "setting_mode": "Save the default dispatch mode",
            "setting_acknowledge": "Save whether help and announcement pages are acknowledged automatically",
            "setting_max_steps": "Save the default input limit per dispatch, 1..1024",
            "setting_interrupt_on": "Save interruption conditions as a JSON object (replaces the saved object)",
            "setting_view": "Save the default observation view",
            "setting_seconds": "Save the default dispatch time limit in seconds, up to 300",
        },
    },
    "capabilities": {
        "summary": "Runtime support: native dependencies, per-action coverage, limits, remaining work.",
        "details": _text(
            """
            Probes the running game for the DFHack symbols each feature needs and
            reports which action groups can complete, what each verifies, numeric
            limits, reader scopes, watch support, unverified paths and the remaining
            semantic work. A present symbol proves availability, not behavior on an
            unverified build.
            """
        ),
    },
    "actions": {
        "summary": "Local action index, or one action's contract and exact JSON schema.",
        "details": _text(
            """
            Names use underscores (walk_to); CLI commands use hyphens (walk-to).
            Without a name, lists every action with required and optional fields.
            With a name, returns the same summary and details as COMMAND --help plus
            the schema that act and sequence validate against. sequence lists child
            schemas by reference; --expand inlines them. Needs no game connection.
            """
        ),
        "args": {"name": "Action name with underscores, for example walk_to"},
    },
    "dispatch-details": {
        "summary": "Read a saved dispatch's events, prompts, steps, summary or full record.",
        "details": _text(
            """
            Reads without executing anything or taking the dispatch lease. events are
            the reports collected during the dispatch, prompts the pages it handled,
            steps its native inputs with effect evidence, compact its receipt, full
            the final observation. The session retains 128 dispatches; expired IDs
            are explicit.
            """
        ),
        "args": {"section": "Part of the record to return (default events)"},
    },
    "character-status": {
        "summary": "Alias of status: the comprehensive character report.",
        "details": "Identical to status. Kept so existing scripts keep working.",
        "args": {"text": "Readable summary followed by every section"},
    },
    "observe": {
        "summary": "Scene: ASCII terrain, visible units, current choices, held items, burden, reports.",
        "details": _text(
            """
            look is observe --view concise: a 41x21 crop centred on the adventurer
            with a legend, all loaded visible units with positions, nearby ground
            items, held items and inventory count, burden, the current menu or prompt
            as native choices, and the latest four relevant reports with omission
            counts. Landmarks are inclusive [y, x_first, x_last] spans per z-level,
            shape and material. --view choices returns only the current menu or
            prompt. --view full adds the raw UI rows, detailed items and all 80
            recent reports. Unknown interfaces keep their UI text in every view.
            --since REF returns only the fields changed since that read_ref.
            state_id guards the next input; read_ref identifies content.
            """
        ),
        "args": {
            "width": "Crop width in tiles, up to 101",
            "height": "Crop height in tiles, up to 61",
            "center": "Crop centre instead of the adventurer",
            "no_map": "Omit the ASCII map and terrain grids",
        },
    },
    "items": {
        "summary": "Visible ground items with container contents, or one building's stored items.",
        "details": _text(
            """
            Concise profiles keep ID, description, material, quality, wear, stack,
            weight and location and omit definitions, temperatures and weapon
            attacks, which item ID and --view full retain. --type filters root items
            by native item type token (ARMOR, WEAPON, SHOES). --building ID reads
            visible furniture stock, which radius reads skip. Radius reads are
            bounded to 500 items and four container levels; truncation is explicit.
            """
        ),
        "args": {"view": "concise catalog profiles or full item records"},
    },
    "barter": {
        "summary": "Read the open trade's catalog, filtered by side and native item type.",
        "details": _text(
            """
            Requires an open trade (open-trade). take lists the merchant's goods,
            give your offered goods. Filtering happens before item profiles are
            built. base_value is the native value, not an accepted price; unknown
            weights stay unknown. An empty catalog keeps its zone identity and does
            not prove an empty shop.
            """
        ),
        "args": {
            "side": "take: merchant goods; give: your offered goods",
            "limit": "Rows to return, 1..500 (default 20)",
        },
    },
    "item": {
        "summary": "Inspect one carried, ground or furniture item, including weapon attack indices.",
        "details": _text(
            """
            Returns material, quality, wear, stack, mass and volume, container
            location, armor coverage and layer data, and weapon attack definitions
            with the indices strike needs. Items that are not carried, on visible
            ground or in visible furniture are rejected.
            """
        ),
        "args": {"item_id": "Native item ID from look, items or brief"},
    },
    "interrupt": {
        "summary": "Stop a running dispatch before its next input; progress is kept for resume.",
        "details": _text(
            """
            Works from another process while a dispatch runs. An input already
            submitted to the game is not undone; a native long action still needs an
            explicit respond. The dispatch returns interrupted with a resume ID.
            """
        ),
        "args": {"dispatch_id": "Dispatch ID from the running command's receipt or session"},
    },
    "keys": {
        "summary": "Development: list DF interface key names, optionally filtered.",
        "details": "Names are valid values for the key command. Listing sends no input.",
        "args": {"filter": "Case-insensitive substring, for example A_INV"},
    },
    "navigation": {
        "summary": "Travel coordinates, current site, lair entrance and character-known rumors.",
        "details": _text(
            """
            Rumors are group and beast leads the character knows, sorted by distance
            in travel tiles; they are leads, not verified enemies. Includes the
            current site with its bounds and, for a lair, the native entrance
            coordinates. --view full adds the site's native travel grid with
            direction masks. Works while the local map is offloaded.
            """
        ),
        "args": {
            "limit": "Maximum rumors to return, 1..100 (default 20)",
            "view": "concise omits the site travel grid; full includes it",
        },
    },
    "shops": {
        "summary": "Native shop records in the current or a loaded site, sorted by distance.",
        "details": _text(
            """
            --type takes exact site_shop_type tokens such as Armorsmith, FoodImports,
            GeneralImports, Carpenter or LeatherGoods. Results give travel
            destinations, loaded zone centres and building facing. --stock adds item
            counts from loaded Shop subzones and production allotments by category;
            use the Shop zone IDs it returns with open-trade. A record does not prove
            a shopkeeper or stock is present.
            """
        ),
        "args": {
            "site_id": "World site ID whose realization is loaded (default: current site)",
            "limit": "Shops to return, 1..100 (default 20)",
        },
    },
    "locate": {
        "summary": "World-record location of a historical figure or artifact by ID.",
        "details": _text(
            """
            Uses the exported gui/adv-finder readers without opening its interface.
            Returns plain IDs and coordinates from world records; it does not imply
            the character knows the location or can see it.
            """
        ),
        "args": {"kind": "figure or artifact", "id": "Historical figure ID or artifact ID"},
    },
    "world-scan": {
        "summary": "Search world site records by native type, flag, name or stocked material.",
        "details": _text(
            """
            Copies the site index once and filters it locally. --match any (default)
            matches an exact type or subtype, an active flag or a name substring.
            Tokens ignore case and separators (LAIR, CAVE_DETAILED, TREE_CITY).
            HAS_MARKET separates market towns from hamlets; RUINED is preserved for
            you to assess. --tokens lists the running game's catalog. Bounds: 32
            terms, 32,768 sites, 100 results per term; complete and truncated are
            explicit. Distances are Chebyshev distances to site centres in travel
            tiles, not routes. This searches world records, including places the
            character does not know.

            --material TOKEN (STEEL, INORGANIC:IRON) searches persistent resource
            allotments at every indexed site, including unloaded settlements, and
            identifies matching available shop sale records. Site tokens are
            optional; with both, a site must match both. Reads run in batches of 32
            sites; --limit bounds returned sites, not sites searched. Failed reads
            stay unknown and mark the search incomplete, listed under
            material_unavailable. Matches carry stock.resource_pile.quantities by
            allotment category and stock.sale_records with shop names, types and
            travel coordinates. These are abstract quantities and recorded
            allotments, not a living merchant, catalog, quality, fit or price;
            resource and sale quantities overlap and must not be added. Verify
            with barter before buying. --tokens cannot be combined with --material.
            """
        ),
        "args": {
            "match": "Restrict matching to type, name or flag",
            "material": "Native material token to search stock for, e.g. STEEL or INORGANIC:IRON",
        },
    },
    "inspect": {
        "summary": "One tile: terrain, biome, building, and the items and creatures on it.",
        "details": _text(
            """
            Reads a local tile by local coordinates. Unseen tiles return visible
            false. Building tiles include the building's kind and, for furniture,
            compact stock counts.
            """
        ),
    },
    "wait-ready": {
        "summary": "Wait until the game accepts input, without taking an action.",
        "details": _text(
            """
            Polls readiness until the adventure loop is taking input again or the
            limit expires. Use it after a lost reply before deciding whether to
            resume.
            """
        ),
        "args": {
            "seconds": "Maximum wait in seconds (default 30)",
            "action_id": "Also wait for this input receipt to settle",
        },
    },
    "run": {
        "summary": "Development: run a DFHack console command and print its output.",
        "details": "Bypasses every guard and receipt. Use it for diagnosis only.",
        "args": {"args": "The DFHack command and its arguments"},
    },
    "drink": {
        "summary": "Drink N portions from a carried liquid, verifying each portion's effect.",
        "details": _text(
            """
            Each portion needs a reduced source stack, a native DRINK_ITEM report and
            a verified thirst effect; a menu selection alone never completes it.
            With --from-container the ID is a container whose fully observed liquid
            contents are pinned for execution and resume. Frozen contents return
            source_not_liquid; different or unreadable contents block. Fullness
            warnings can appear in CONSUME_FAILURE reports even when drinking
            succeeds. Progress survives limits and works inside sequence. Values
            include the resulting load.
            """
        ),
        "args": {
            "item_id": "Carried liquid item ID, or a container ID with --from-container",
            "portions": "Portions to drink, 1..32 (default 1)",
        },
    },
    "eat": {
        "summary": "Eat N portions from a carried food item, verifying each portion's effect.",
        "details": _text(
            """
            Each portion needs a reduced source stack, a native EAT_ITEM report and a
            verified hunger effect. Native refusals and unchanged effects stop
            without repeating the selection; progress survives limits and works
            inside sequence.
            """
        ),
        "args": {
            "item_id": "Carried food item ID",
            "portions": "Portions to eat, 1..32 (default 1)",
        },
    },
    "sleep": {
        "summary": "Sleep for HOURS, or until dawn, verified against the native calendar.",
        "details": _text(
            """
            Configures the native sleep panel and verifies calendar progress across
            local map unloading and reloading; party sleeping flags keep the dispatch
            pending while the map is offloaded. An early stop returns the elapsed
            hours and a resumable checkpoint and never starts another sleep.
            Sleeping can leave the character prone; set-posture standing is a
            separate action. A native CANNOT_REST refusal returns rest_restricted and
            stays blocked on resume. --until-dawn uses the native dawn control and
            the local clock and longitude; a start exactly at dawn targets the next
            day. Live until-dawn completion has not been observed yet.
            """
        ),
        "args": {
            "hours": "Whole hours, 1..24; omit with --until-dawn",
            "until": "Rest until the next local dawn instead of a fixed duration",
        },
    },
    "rest": {
        "summary": "Wait awake for HOURS, or until dawn, verified against the native calendar.",
        "details": _text(
            """
            Configures the native wait panel and verifies calendar progress across
            local map unloading and reloading. An early stop returns the elapsed
            hours and a resumable checkpoint and never starts another rest. A native
            CANNOT_REST refusal returns rest_restricted and stays blocked on resume.
            --until-dawn uses the native dawn control and the local clock and
            longitude; a start exactly at dawn targets the next day. Live until-dawn
            completion has not been observed yet.
            """
        ),
        "args": {
            "hours": "Whole hours, 1..24; omit with --until-dawn",
            "until": "Rest until the next local dawn instead of a fixed duration",
        },
    },
    "sequence": {
        "summary": "Run an ordered JSON list of semantic actions as one dispatch.",
        "details": _text(
            """
            Each stage must reach its verified completion before the next begins;
            all stages share one input budget, time limit, interruption policy and
            event history. Stages are any semantic action, including converse, move
            and wait; nested sequences and raw inputs are rejected. Limits: 1..64
            actions, 128 expanded stages. Local coordinates in every stage refer to
            the map origin at the start of the sequence and stay on those world
            tiles across rebases; a lost frame returns coordinate_frame_changed. The
            receipt reports completed_stages, collected said replies, per-stage
            values with their stage index and the unresolved stage in blocker.
            Resume keeps completed stages and never reselects a sent topic. The
            sequence stops at the first unresolved stage; it never skips or invents a
            fallback.
            """
        ),
    },
    "converse": {
        "summary": "Visit each unit in order, ask each topic, collect replies, close the interface.",
        "details": _text(
            """
            Built on sequence: end_conversation, then for each unit each topic as a
            talk with completion reply, then end_conversation. It chooses no people,
            topics or tactics. Include Greet first for a new acquaintance if the
            native menu requires it. --topic-spec supplies per-topic tact or
            subject_hf_id and may be mixed with --topic in request order. Limits:
            1..32 units, 1..16 topics.
            """
        )
        + "\n"
        + _ROUTE_NOTE,
        "args": {"unit_ids": "Native unit IDs in visiting order"},
    },
    "talk": {
        "summary": "Approach a unit, open conversation, optionally say a topic and verify the reply.",
        "details": _text(
            """
            Without a topic, opens the conversation and returns the native choices.
            --topic takes an exact native label or a unique topic type; --choice-id
            an observed choice handle; --tact Persuade or Intimidate delegates the
            tact picker; --subject-hf-id names a historical-figure subject. The
            harness handles the target picker, scrolling, delegated help and the
            interrogation submenu, and never substitutes another topic. A supplied
            topic defaults to completion reply: our utterance must appear in the
            native turn history followed by a new utterance from the target with
            reports from the same activity; it takes bounded short waits under your
            policy and never reselects the topic. Replies arrive once in said.
            Submenus, ambiguous topics and undelegated tacts return needs_input with
            the choices.
            """
        )
        + "\n"
        + _ROUTE_NOTE,
        "args": {"unit_id": "Native unit ID of the listener"},
    },
    "end-conversation": {
        "summary": "Close the conversation interface and verify it closed.",
        "details": "Does not end the native social activity or suppress ambient speech.",
    },
    "open-trade": {
        "summary": "Approach a merchant, request Trade and select one loaded Shop catalog.",
        "details": _text(
            """
            Use the Shop zone IDs from shops --stock, not the site's Home zone. Both
            traders must be inside that shop and the merchant assigned to it. DF
            rebuilds the goods and currency lists; completion verifies the requested
            zone and a finished rebuild. Existing offers, quantity edits and
            nonempty filters block a catalog change. Opening a catalog is not a
            purchase; read it with barter and submit with trade.
            """
        ),
        "args": {
            "unit_id": "Merchant unit ID",
            "shop_id": "Loaded Shop zone ID from shops --stock",
        },
    },
    "close-trade": {
        "summary": "Close the native trade interface without transacting.",
        "details": "Pending offers are discarded by the game.",
    },
    "trade": {
        "summary": "Submit an exact offer in the open trade and verify the transfer.",
        "details": _text(
            """
            Flow: world-scan --material T to find stocked sites, shops --stock, open-
            trade UNIT --shop ZONE, barter --type T, then trade. --take and --give are
            JSON lists of {item_id, amount}; currency is in native units. The adapter
            validates the merchant, both sides, quantities, currency bounds and a
            unique visible Trade button before touching the draft, clicks that button
            so DF's own handler performs the trade, then verifies the exact source and
            destination quantities and your currency change. A refusal or counteroffer
            returns needs_input with the native reply and any counter amounts; you
            choose whether to submit a new explicit offer. base_value is not an
            accepted price. Sale items must be held: compose close_trade, remove,
            open_trade and trade to sell equipped items. Nonempty containers and
            contained rows are unsupported. The button lookup requires English UI
            text. An unverified submission is never repeated by resume.
            """
        ),
        "args": {
            "unit_id": "Merchant unit ID of the open trade",
            "offer_currency": "Currency you offer, native units",
            "request_currency": "Currency you ask for, native units",
        },
    },
    "save-game": {
        "summary": "Save the adventure as NAME through DFHack quicksave and verify the file.",
        "details": _text(
            """
            Names take 1..40 letters, digits, spaces, underscores and hyphens,
            starting with a letter or digit; native working and autosave folders are
            reserved. An existing name returns save_exists unless --overwrite.
            Completion requires the world file to be newly written and the game
            ready again; values include the verified name and file timestamp. Use
            --seconds 120 for a slow save. Save-and-quit and timeline selection are
            unsupported. quicksave is an alias.
            """
        ),
        "args": {"name": "Save folder name"},
    },
    "combat": {
        "summary": "Open the target's native combat choices and return them; discovery only.",
        "details": _text(
            """
            Approaches the unit, opens the combat menu and returns the native choices
            grouped by type. With --option-id it selects that choice and returns the
            next decision. It never resolves an attack; use strike for a complete
            aimed attempt. Defense, wrestling, charge, multiattack and ranged attacks
            are unsupported.
            """
        )
        + "\n"
        + _ROUTE_NOTE,
        "args": {"unit_id": "Target unit ID"},
    },
    "strike": {
        "summary": "One aimed melee attempt: approach, aim, set style, submit, verify the effect.",
        "details": _text(
            """
            Get body_part_id from unit ID, and item_id and attack_index from item ID
            (item_id -1 with a body-plan attack index for a natural attack). The
            strike clears residual charge and multiattack flags, verifies each style
            toggle, submits through the native menu and watches the queued native
            attack through its recovery. values report resolution wounded with new
            wound IDs, or missed, dodged, blocked, parried or out_of_range when an
            unambiguous English report says so (source report_text); unknown wording
            stays processed with damage unverified. A cancelled swing completes with
            recovered false and a cause. The target's condition accompanies the
            value, with existing impairments kept explicit and other fields diffed.
            Completion never implies a hit; a target still in flight from a previous
            blow settles first. It never picks another weapon, limb or target.
            """
        )
        + "\n"
        + _ROUTE_NOTE,
        "args": {
            "unit_id": "Target unit ID",
            "body_part_id": "Target body-part ID from unit ID",
            "attack_index": "Attack index from item ID, or the body-plan index for a natural attack",
            "style": "Attack style",
        },
    },
    "use-stairs": {
        "summary": "Approach the stairs at X Y Z and traverse one level up or down.",
        "details": _text(
            """
            You choose the stair tile and direction; the harness approaches it with
            the native path command and verifies arrival on the new level,
            accounting for map rebasing.
            """
        )
        + "\n"
        + _ROUTE_NOTE,
        "args": {"direction": "up or down"},
    },
    "make-campfire": {
        "summary": "Make a campfire at X Y Z and verify the tile.",
        "details": _text(
            """
            Approaches the tile, selects the native campfire option and verifies the
            campfire material at the requested tile. Native refusals are blockers.
            """
        )
        + "\n"
        + _ROUTE_NOTE,
    },
    "thaw": {
        "summary": "Heat a carried container at heat source X Y Z until its water is liquid.",
        "details": _text(
            """
            Selects the native heating option at the specified source. Further
            heating requires observed temperature or melting progress; unchanged
            readings stop it. Thawing can create a new liquid item ID. Values report
            the portion count.
            """
        )
        + "\n"
        + _ROUTE_NOTE,
        "args": {"x": "Heat source x", "y": "Heat source y", "z": "Heat source z"},
    },
    "fill-container": {
        "summary": "Fill a carried container from tile X Y Z with MATERIAL to native capacity.",
        "details": _text(
            """
            Existing contents must be fully observed and of the same material.
            Fullness is verified by capacity and summed volumes; additional
            selections require volume progress. Freezing or melting can change item
            IDs without changing the goal. A filled container is not necessarily
            drinkable; thaw ice separately.
            """
        )
        + "\n"
        + _ROUTE_NOTE,
        "args": {"x": "Source tile x", "y": "Source tile y", "z": "Source tile z"},
    },
    "drink-from": {
        "summary": "Drink N portions of MATERIAL from the native source at tile X Y Z.",
        "details": _text(
            """
            Approaches the tile, opens the native consumption menu and selects only
            that material in Liquid state. Terrain sources are supported; wells and
            ground containers are not. Equivalent native entries with the same
            material, phase and coordinates count as one choice. Each portion needs a
            new DRINK_ITEM report and a verified thirst effect.
            """
        )
        + "\n"
        + _ROUTE_NOTE,
        "args": {
            "x": "Source tile x",
            "y": "Source tile y",
            "z": "Source tile z",
            "portions": "Portions to drink, 1..32 (default 1)",
        },
    },
    "empty-container": {
        "summary": "Empty a carried container through its native option and verify it is empty.",
        "details": _text(
            """
            Pins the observed contents, selects one verified emptying option and
            requires empty contents plus an EMPTY_CONTAINER report. An already empty
            vessel takes no input. Because DF's drop on a contained liquid performs
            this broader operation, drop on such an item stops and points here.
            """
        ),
    },
    "set-posture": {
        "summary": "Stand up or lie prone, verified from unit state.",
        "details": "Toggles the native stance only when it differs from the request.",
        "args": {"posture": "standing or prone"},
    },
    "set-gait": {
        "summary": "Select a named gait in the current movement mode.",
        "details": _text(
            """
            Opens the movement panel and selects the gait by native name. It does
            not switch between walking, crawling, swimming or climbing.
            """
        ),
        "args": {"gait": "Native gait name as shown in brief or status"},
    },
    "set-sneaking": {
        "summary": "Turn sneaking on or off, verified from the unit's flags.",
        "details": "Toggles only when the current flag differs from the request.",
        "args": {"enabled": "on or off"},
    },
    "travel-to": {
        "summary": "Fast-travel toward travel-map coordinates X Y and verify arrival.",
        "details": _text(
            """
            Travel tiles are 16 local tiles; three make one embark tile. Uses native
            directional moves through the current site's travel grid and then
            overland; there is no native travel route command. Overland input can
            advance several tiles while the game still reports readiness, so each
            move waits for a short quiet window of unchanged travel state before
            verifying coordinates. Returns at blocked movement, a native restriction
            or a forced exit from travel, with native position, zoom, not-moved and
            exception facts. An unchanged pending move stays checkpointed so resume
            can verify a late arrival without moving again. The enlarged travel map
            is closed automatically before moving.
            """
        ),
        "args": {
            "x": "Travel-map x",
            "y": "Travel-map y",
            "arrival_radius": "Stop within this many travel tiles, 0..48 (default 0)",
        },
    },
    "end-travel": {
        "summary": "Leave travel mode and verify the local map loaded.",
        "details": "The game chooses the exact local arrival tile.",
    },
    "move": {
        "summary": "Step one tile in DIRECTION and verify the new position.",
        "details": _text(
            """
            Uses the native path command for one tile where available and verifies
            the position from unit state. Valid as a sequence stage. A game refusal
            is a blocker; the input is never repeated.
            """
        ),
        "args": {"direction": "n s e w ne nw se sw up down"},
    },
    "wait": {
        "summary": "One native short wait; verifies that game time advanced.",
        "details": "Valid as a sequence stage. Use rest or sleep for hours.",
    },
    "dismiss": {
        "summary": "Acknowledge one help or announcement page.",
        "details": _text(
            """
            With acknowledge delegated, dispatches handle these pages themselves;
            use dismiss for one page under step control.
            """
        ),
    },
    "resume": {
        "summary": "Continue a saved dispatch by ID, or settle the current native action.",
        "details": _text(
            """
            With a dispatch ID, continues that workflow from its last accepted
            checkpoint without repeating completed inputs, applying current settings
            plus this call's overrides; always resume the latest continuation ID.
            Without an ID, only waits for the current native action and prompts
            under your policy; it recovers no workflow. Never resume blindly after a
            lost reply: look first.
            """
        ),
    },
    "pickup": {
        "summary": "Approach and pick up item_id with its contents, verifying it is carried.",
        "details": _text(
            """
            Walks to the item with the native path command, opens the ground menu
            and selects the exact item. Quantity pickers return needs_input. Values
            include location, contents integrity and the resulting load.
            """
        ),
        "args": {"item_id": "Visible ground or furniture item ID"},
    },
    "equip": {
        "summary": "Wear item_id, removing only the listed replacements, then apply their disposition.",
        "details": _text(
            """
            Acquires the item if needed, removes each --replace ID, wears the target,
            verifies the wear, then holds, drops or stows the replacements as
            requested. It never chooses other gear to remove. --body-part-id makes
            the exact part a postcondition; a different native choice returns
            needs_input. Values include location and the resulting load.
            """
        ),
    },
    "wield": {
        "summary": "Hold item_id as a weapon, removing only the listed replacements first.",
        "details": _text(
            """
            Acquires the item if needed, removes each --replace ID, holds the target,
            verifies the grip, then applies the requested disposition to the
            replacements. It never chooses other gear to remove. A held garment also
            has role Weapon; use item type to tell weapons apart.
            """
        ),
    },
    "remove": {
        "summary": "Take off item_id into a hand; nothing else is moved.",
        "details": _text(
            """
            Returns location and the resulting load. It does not select other
            equipment to make room; a missing native option is a blocker naming the
            item, role and menu context.
            """
        ),
    },
    "drop": {
        "summary": "Drop item_id, removing it first if worn; container contents stay inside.",
        "details": _text(
            """
            Because a native drop on a contained liquid empties the whole container,
            that case stops and points to empty-container. Values include location,
            contents integrity, cached load and burden.
            """
        ),
    },
    "stow": {
        "summary": "Put item_id into carried container_id, removing it first if worn.",
        "details": _text(
            """
            Selects the exact destination in the two-stage native put menu. Values
            include the destination, contents integrity, cached load and burden.
            """
        ),
        "args": {"container_id": "Carried destination container ID"},
    },
    "walk-to": {
        "summary": "Walk to local tile X Y Z through the game's own path command.",
        "details": _text(
            """
            DF computes and follows the route; one path command is one input
            regardless of tile count, and arrival is verified from unit state. Step
            mode stops at the first movement boundary; resume keeps the destination.
            Interruption cancels the remaining goal; a move already submitted may
            finish. A stale native reachability cache returns a no-connection
            blocker and is never refreshed. --arrival-radius accepts an observed
            reachable neighbour. Supplying --allow-occupied, --max-liquid-depth,
            --blocked-tiles or --extend-route switches to the legacy observed-route
            adapter, which plans on one z-level through the observed crop; prefer
            the native default.
            """
        ),
    },
    "select-option": {
        "summary": "Select a menu option by its guarded ID from the current choices.",
        "details": _text(
            """
            The ID comes from look or a receipt's choices. The binding is rechecked
            inside the game; a changed option set or expired handle is rejected. One
            selection is one input; scrolling is handled.
            """
        ),
    },
    "select-interaction": {
        "summary": "Select a conversation or combat choice by its guarded ID.",
        "details": _text(
            """
            The ID comes from look, talk or combat choices. The binding is rechecked
            inside the game; a changed option set or expired handle is rejected.
            """
        ),
    },
    "respond": {
        "summary": "Answer the current Continue/Stop/Finish long-action prompt.",
        "details": _text(
            """
            Complete mode answers finish automatically; use respond under step
            control. The mapping is implemented but not yet verified live.
            """
        ),
        "args": {"choice": "continue, stop or finish"},
    },
    "select-unit": {
        "summary": "Development: click a visible unit inside the conversation creature picker.",
        "details": _text(
            """
            Only valid while the picker is open; the unit must be visible, inside the
            viewport and not covered by UI text.
            """
        ),
        "args": {"unit_id": "Visible unit ID to pick"},
    },
    "key": {
        "summary": "Development: send one named interface key and observe.",
        "details": _text(
            """
            No postcondition beyond input settlement; read the resulting menu and
            reports. Names come from keys.
            """
        ),
        "args": {"key": "Interface key name, for example A_TALK"},
    },
    "click": {
        "summary": "Development: click a zero-based UI character cell.",
        "details": "Coordinates are UI character cells from observe --view full, not map tiles.",
        "args": {"x": "UI column", "y": "UI row", "button": "Mouse button (default left)"},
    },
    "choose": {
        "summary": "Development: click a label that appears exactly once in the UI text.",
        "details": "Ambiguous or absent labels are rejected before input.",
        "args": {"label": "Exact visible label"},
    },
    "text": {
        "summary": "Development: type printable ASCII into the focused text field.",
        "details": "Use key for Enter and Escape.",
        "args": {"value": "1..200 printable ASCII characters"},
    },
    "act": {
        "summary": "Send one action as JSON, or - to read it from stdin.",
        "details": _text(
            """
            The general form of every action, including resume objects returned in
            receipts. Validate against actions NAME. Per-action flags after the
            command override saved policy.
            """
        ),
        "args": {"action_json": "Action object as JSON, or -"},
    },
}

# Action types whose CLI command name is not the underscore-to-hyphen form.
_ACTION_COMMANDS = {"action_prompt": "respond", "click_text": "choose"}


def parser_kwargs(name):
    """Keyword arguments for ``add_parser`` so ``--help`` prints the contract."""
    entry = COMMANDS[name]
    return {
        "help": entry["summary"],
        "description": entry["summary"],
        "epilog": entry["details"],
        "formatter_class": argparse.RawDescriptionHelpFormatter,
    }


def describe_arguments(parser, name):
    """Fill missing argument help from the command's table, then the shared table."""
    specific = COMMANDS[name].get("args", {})
    for action in parser._actions:
        if action.dest == "help" or action.help:
            continue
        text = specific.get(action.dest) or SHARED_ARGS.get(action.dest)
        if text:
            action.help = text


def action_text(action_type):
    """Summary and details for an action type, shared with ``actions NAME``."""
    entry = COMMANDS[_ACTION_COMMANDS.get(action_type, action_type.replace("_", "-"))]
    return entry["summary"], entry["details"]
