"""Execution coverage attached to read-only native dependency probes."""

from copy import deepcopy

from .policy import MAX_DISPATCH_INPUTS, MAX_WATCHED_UNITS, UNIT_HEALTH_FLAGS
from .routing import MAX_VISITED
from .rpc import POLL_MAX_SECONDS, POLL_MIN_SECONDS

GROUPS = (
    (
        ("trade",),
        ("core", "local_map", "inventory", "barter", "barter_submit"),
        "Exact native offer and guarded character-layer Trade button; verifies item quantities and player currency. Counteroffers return control. Held sale items only; containers unsupported. Live purchase, refusal, sale and no-input verification resume exercised.",
    ),
    (
        ("open_trade", "close_trade"),
        ("core", "local_map", "conversation", "barter"),
        "Explicit merchant and Shop zone; DF rebuilds the native catalog. Existing offers are preserved. Catalog selection does not transact.",
    ),
    (
        ("save_game",),
        ("core", "saving"),
        "Native save finishes and the requested world file is newly written",
    ),
    (
        ("pickup", "equip", "wield", "remove", "drop", "stow"),
        ("core", "local_map", "inventory", "ground_options"),
        "Requested location and equipment verified; worn drop/stow prerequisites are executed; results include contents integrity, cached load and burden from the DFHack unit helper",
    ),
    (
        ("eat", "drink"),
        ("core", "inventory", "consumption"),
        "Portion, native report and need effect verified",
    ),
    (
        ("walk_to", "use_stairs", "move"),
        ("core", "local_map"),
        "Requested position verified; walk_to uses native path goals when native_path dependencies are present and no explicit route constraints were supplied",
    ),
    (
        ("wait",),
        ("core", "local_map"),
        "One native short wait advances game time and settles; supports sequence and explicit resume without resending an unverified input",
    ),
    (
        ("empty_container",),
        ("core", "inventory", "emptying"),
        "The carried container is empty, with a native emptying report when contents existed; requires a liquid child option",
    ),
    (
        ("drink_from",),
        ("core", "local_map", "inventory", "environmental_consumption"),
        "Explicit native liquid source, per-portion drinking report and thirst effect verified",
    ),
    (
        ("make_campfire",),
        ("core", "local_map", "ground_options", "campfire"),
        "Campfire verified at the explicitly requested tile",
    ),
    (
        ("travel_to", "end_travel"),
        ("core", "travel"),
        "Requested travel coordinates verified; end_travel verifies the local adventurer is loaded",
    ),
    (("set_posture",), ("core", "posture"), "Requested standing/prone flag verified"),
    (("set_sneaking",), ("core", "sneaking"), "Requested native sneaking flag verified"),
    (
        ("sleep", "rest"),
        ("core", "rest"),
        "Configured native sleep/wait and explicit hours or next local dawn verified; dawn has separate dependency/adapter coverage",
    ),
    (
        ("thaw",),
        ("core", "local_map", "inventory", "heating"),
        "Specified container water becomes liquid with its portion count preserved",
    ),
    (
        ("fill_container",),
        ("core", "local_map", "inventory", "filling"),
        "Specified carried container reaches native capacity with the explicit source material",
    ),
    (
        ("set_gait",),
        ("core", "movement"),
        "Requested native gait selection verified in the current movement mode",
    ),
    (
        ("talk", "converse", "end_conversation"),
        ("core", "local_map", "conversation"),
        "Specified listener, topic and native reply verified; end_conversation closes the interface",
    ),
    (
        ("combat",),
        ("core", "local_map", "combat"),
        "Target/menu selection only; attack effects unverified",
    ),
    (
        ("strike",),
        ("core", "local_map", "combat", "strike"),
        "One aimed melee attempt; native wounds and phases, labelled English report-text miss/defense/cancellation attribution, conservative unknown outcomes, and bounded target condition; completion does not imply a hit",
    ),
    (
        ("sequence",),
        ("core",),
        "Each explicit stage verified under its own dependencies and shared policy",
    ),
)


def capability_report(native):
    result = deepcopy(native)
    result["format"] = "capabilities"
    result["actions"] = []
    for actions, dependencies, completion in GROUPS:
        unavailable = [
            key
            for key in dependencies
            if not result["features"].get(key, {}).get("dependencies_present")
        ]
        group = {
            "names": list(actions),
            "dependencies_present": not unavailable,
            "completion": completion,
        }
        if unavailable:
            group["missing_features"] = unavailable
        if "combat" in actions:
            group["partial"] = True
        result["actions"].append(group)
    result["limits"] = {
        "inputs_per_dispatch": MAX_DISPATCH_INPUTS,
        "seconds_per_dispatch": 300,
        "sequence_stages": 128,
        "retained_dispatches": 128,
        "native_menu_options": 500,
        "conversation_turns": 128,
        "route_search_positions": MAX_VISITED,
        "watched_units": MAX_WATCHED_UNITS,
        "wounds_per_watched_unit": 1024,
        "attack_observer_ticks": 8192,
        "pending_native_attacks": 256,
        "attack_target_wounds": 1024,
        "attack_report_window": 512,
        "pending_poll_pause_seconds": {"initial": POLL_MIN_SECONDS, "maximum": POLL_MAX_SECONDS},
        "visible_unit_scan": 32768,
        "nearby_item_radius": {"default": 20, "maximum": 50},
        "nearby_item_budget": 500,
        "nearby_container_depth": 4,
        "inventory_item_budget": 300,
        "conversation_targets": 32,
    }
    result["unverified"] = [
        "Continue/Stop/Finish prompt responses are implemented but not yet exercised live",
        "Successful live until-dawn rest completion has not been observed",
        "Native walkability caches can be stale; a stale cache is reported, never refreshed",
    ]
    result["readers"] = {
        "barter": "Active native trade catalog; item type filtering before detailed reads, explicit limits and unknown weights",
        "actions": "Local action reference and exact shared schemas; no game connection",
        "status": "Comprehensive character query; its per-section coverage is authoritative",
        "burden": "DFHack Lua helper reads unit/item state independently of panels; capacity, skill-adjusted load, load penalty and burden; no screen scan or cache refresh",
        "observe": "Local ASCII terrain, visible units/items, health, needs, current native choices",
        "navigation": "Native current site/biome, travel coordinates, site grid and character-known rumors",
        "locate": "Explicit gui/adv-finder world-record lookup by historical figure or artifact ID",
        "world_scan": "Search the bounded world site index by native type/subtype, flag or name; one native snapshot and one local pass",
        "unit": "Visible character inspection, native classifications and targetable anatomy; concise skips deep item reads",
        "dispatch_details": "Read saved outcomes, events, prompts and execution traces",
        "session": "Recent in-memory dispatch IDs; same-world resume across controller restarts, revoked on game restart or world reload",
    }
    result["remaining_semantic_work"] = [
        "Wrestling, defense, charge, multiattack and ranged combat",
        "Pouring between containers and drinking directly from wells or ground containers",
        "Swimming preferences and changing locomotion mode",
        "Trading containers and preparing equipped sale items inside trade; crafting, performances and abilities",
        "Companion orders, mounts and tracking",
        "Quest commitments and special interaction choices beyond conversation tacts",
        "Character creation and other title-screen flows beyond loading a save",
        "Trade button lookup in non-English UI text",
    ]
    result["unit_health_watches"] = {
        "dependencies_present": result["features"]
        .get("unit_health", {})
        .get("dependencies_present", False),
        "conditions": list(UNIT_HEALTH_FLAGS),
        "targets": "Explicit loaded, visible unit IDs; never inferred from companion or faction membership",
        "unknown": "needs_input before further input when a requested reading is unavailable",
        "validation": "Blood values and bounded native wound IDs are validated for each requested unit",
        "timing": "Checked in processing polls and again before input; does not cancel native actions already submitted",
    }
    return result
