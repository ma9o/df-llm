"""Execution coverage attached to read-only native dependency probes."""

from copy import deepcopy

from .policy import MAX_DISPATCH_INPUTS, MAX_WATCHED_UNITS, UNIT_HEALTH_FLAGS
from .routing import MAX_VISITED
from .rpc import POLL_MAX_SECONDS, POLL_MIN_SECONDS

GROUPS = (
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
        ("walk_to", "use_stairs"),
        ("core", "local_map"),
        "Requested position verified; walk_to uses native path goals when native_path dependencies are present and no explicit route constraints were supplied",
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
        "One explicit aimed melee attempt and recovery; resulting target blood, consciousness, functional limbs, part damage and grapples are bounded native reads; phase completion is not guaranteed damage",
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
    }
    result["readers"] = {
        "actions": "Local action reference and exact shared schemas; no game connection",
        "status": "Comprehensive character query; its per-section coverage is authoritative",
        "burden": "DFHack Lua helper reads unit/item state independently of panels; capacity, skill-adjusted load, load penalty and burden; no screen scan or cache refresh",
        "observe": "Local ASCII terrain, visible units/items, health, needs, current native choices",
        "navigation": "Travel coordinates, site grid and character-known rumors",
        "unit": "Visible character inspection",
        "dispatch_details": "Read saved outcomes, events, prompts and execution traces",
    }
    result["remaining_semantic_work"] = [
        "Wrestling, defense, charge, multiattack and ranged combat",
        "Pouring between containers and drinking directly from wells or ground containers",
        "Swimming preferences and changing locomotion mode",
        "Barter, crafting, performances and abilities",
        "Companion orders, mounts and tracking",
        "Quest commitments and special interaction choices beyond conversation tacts",
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
