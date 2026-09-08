"""Explicit environment targets, native menu mechanics and verified effects."""

from typing import Any

from .consumption import need_effect
from .routing import ROUTE_FIELDS
from .selection import selection_input
from .state import inventory, inventory_complete
from .workflows import (
    absolute,
    close_menu,
    menu_signature,
    next_walk,
    relative,
    result,
    validate_action,
    verify_walk,
)


def validate_environment(action):
    route = ROUTE_FIELDS
    required = {"x", "y", "z"}
    optional = set()
    if action["type"] in ("thaw", "fill_container"):
        required.add("container_id")
    if action["type"] in ("fill_container", "drink_from"):
        required.add("material")
        if not isinstance(action.get("material"), str) or not 0 < len(action["material"]) <= 200:
            raise ValueError("material must be an exact native material token")
    if action["type"] == "fill_container":
        optional.add("source_state")
        if "source_state" in action and (
            not isinstance(action["source_state"], str) or not 0 < len(action["source_state"]) <= 40
        ):
            raise ValueError("source_state must be a native matter-state name")
    if action["type"] == "drink_from":
        optional.add("portions")
        if type(action.get("portions", 1)) is not int or not 1 <= action.get("portions", 1) <= 32:
            raise ValueError("drink_from.portions must be an integer in [1, 32]")
    if required - action.keys() or action.keys() - {"type"} - required - route - optional:
        raise ValueError(
            action["type"]
            + " requires "
            + ", ".join(sorted(required))
            + " and optional route constraints"
        )
    if "container_id" in required and (
        type(action["container_id"]) is not int or not 0 <= action["container_id"] <= 2147483647
    ):
        raise ValueError("container_id must be a nonnegative integer")
    validate_action(
        {
            k: v
            for k, v in dict(action, type="walk_to").items()
            if k in route | {"type", "x", "y", "z"}
        }
    )


def water_state(view, container_id):
    container = inventory(view).get(container_id)
    if not container or not inventory_complete(view):
        return None
    entries = container.get("contents", [])
    if any(not i.get("material_ref", {}).get("token") for i in entries):
        return None
    water = [i for i in entries if i["material_ref"]["token"] == "WATER"]
    if any(
        type(i.get("stack_size")) is not int
        or i["stack_size"] < 1
        or i.get("type") not in ("GLOB", "POWDER_MISC", "LIQUID_MISC", "DRINK")
        for i in water
    ):
        return None
    solid = [i for i in water if i["type"] in ("GLOB", "POWDER_MISC")]
    temperatures = [i.get("temperature", {}).get("whole") for i in solid]
    return {
        "total": sum(i["stack_size"] for i in water),
        "solid": sum(i["stack_size"] for i in solid),
        "liquid_ids": [i["id"] for i in water if i not in solid],
        "temperature": min(temperatures)
        if temperatures and all(type(t) is int for t in temperatures)
        else None,
    }


def thaw_effect(action, ctx, view, _target):
    water = water_state(view, action["container_id"])
    if water is None or water["total"] == 0:
        return result(
            "needs_input",
            "Thawing requires observed water in the specified carried container with complete material/quantity readings.",
            {"container_id": action["container_id"], "blocker_kind": "verification"},
        )
    initial = ctx.setdefault("water_initial", water)
    if water["total"] != initial["total"]:
        return result(
            "needs_input",
            "The container's water quantity changed; thawing completion cannot be verified.",
            {"expected": initial, "actual": water, "blocker_kind": "verification"},
        )
    if water["solid"] == 0 and water["liquid_ids"]:
        return result(
            "completed",
            "All observed water in the specified container is liquid.",
            {"container_id": action["container_id"], "liquid_item_ids": water["liquid_ids"]},
        )
    if ctx.get("sent"):
        previous = ctx.get("water_before")
        if previous and (
            water["solid"] < previous["solid"]
            or (
                type(water["temperature"]) is int
                and type(previous["temperature"]) is int
                and water["temperature"] > previous["temperature"]
            )
        ):
            ctx.pop("sent")
            return {"advanced": True}
        return result(
            "needs_input",
            "Heating has no verified melting or temperature progress; input was not repeated.",
            {"blocker_kind": "verification", "actual": water},
        )
    ctx["water_before"] = water
    return None


def campfire_effect(_action, ctx, view, target):
    if any(
        t.get("position") == target and t.get("material") == "CAMPFIRE"
        for t in (view.get("map") or {}).get("landmarks", [])
    ):
        return result(
            "completed", "A campfire is verified at the requested tile.", {"position": target}
        )
    if ctx.get("sent"):
        return result(
            "needs_input",
            "No campfire is observed at the requested tile after selection; input was not repeated.",
            {"blocker_kind": "verification", "position": target},
        )
    return None


def fill_state(view, container_id, material):
    container = inventory(view).get(container_id)
    if not container or not inventory_complete(view):
        return None
    capacity = container.get("capacity_volume_raw")
    contents = container.get("contents", [])
    same = [i for i in contents if i.get("material_ref", {}).get("token") == material]
    # Solid objects such as coins share a waterskin in the game; only another
    # liquid or frozen material makes the fill ambiguous.
    other = [i for i in contents if i not in same]
    if (
        type(capacity) is not int
        or capacity <= 0
        or any(type(i.get("volume_raw")) is not int or i["volume_raw"] < 0 for i in contents)
        or any(i.get("type") not in ("COIN", "TOOL", "WEAPON", "AMMO") for i in other)
    ):
        return None
    return {
        "capacity_volume_raw": capacity,
        "contents_volume_raw": sum(i["volume_raw"] for i in contents),
        "material_volume_raw": sum(i["volume_raw"] for i in same),
        "item_ids": [i["id"] for i in same],
        "other_item_ids": [i["id"] for i in other],
        "material": material,
    }


def fill_effect(action, ctx, view, _target):
    current = fill_state(view, action["container_id"], action["material"])
    if current is None:
        return result(
            "needs_input",
            "Filling requires a carried container with known positive capacity and complete contents: the requested material, solid objects such as coins, or empty.",
            {"container_id": action["container_id"], "blocker_kind": "verification"},
        )
    initial = ctx.setdefault("fill_initial", current)
    if current["capacity_volume_raw"] != initial["capacity_volume_raw"]:
        return result(
            "needs_input",
            "Native container capacity changed during filling.",
            {"blocker_kind": "verification", "actual": current},
        )
    if current["contents_volume_raw"] >= current["capacity_volume_raw"]:
        return result(
            "completed",
            "The specified container is full of the requested material.",
            {"container_id": action["container_id"], **current},
        )
    if ctx.get("sent"):
        if current["material_volume_raw"] > ctx["fill_before"]["material_volume_raw"]:
            ctx.pop("sent")
            return {"advanced": True}
        return result(
            "needs_input",
            "Filling made no verified volume progress; input was not repeated.",
            {"blocker_kind": "verification", "actual": current},
        )
    ctx["fill_before"] = current
    return None


def drink_effect(action, ctx, view, target):
    counter = (view.get("adventurer") or {}).get("health", {}).get("thirst_timer")
    facts = {
        "position": target,
        "material": action["material"],
        "source_state": "Liquid",
        "portions_consumed": len(ctx.get("receipts", [])),
    }
    if type(counter) is not int or counter < 0:
        return result(
            "needs_input",
            "The native thirst counter is unavailable; drinking cannot be verified.",
            {"blocker_kind": "verification", "facts": facts},
        )
    attempt = ctx.get("drink_attempt")
    if attempt:
        reports = [e for e in view.get("reports", []) if e["id"] > attempt["report_cursor"]]
        drinks = [e["id"] for e in reports if e.get("type") == "DRINK_ITEM"]
        failures = [e["id"] for e in reports if e.get("type") == "CONSUME_FAILURE"]
        # CONSUME_FAILURE also carries fullness warnings after a successful
        # drink. The native drink report plus need effect prove consumption;
        # retain warnings as events without parsing their presentation text.
        if len(drinks) == 1 and need_effect(
            counter, attempt["thirst_before"], attempt, view["status"]
        ):
            ctx.setdefault("receipts", []).append(
                {
                    "thirst_before": attempt["thirst_before"],
                    "thirst_after": counter,
                    "report_id": drinks[0],
                }
            )
            ctx.pop("drink_attempt")
            ctx.pop("sent", None)
            return {"advanced": True}
        return result(
            "no_effect",
            "The specified source has no verified drinking report and thirst effect; selection was not repeated.",
            {
                "blocker_kind": "consumption_refused"
                if failures and not drinks
                else "verification",
                "facts": {
                    **facts,
                    "thirst_before": attempt["thirst_before"],
                    "thirst_after": counter,
                },
            },
        )
    if len(ctx.get("receipts", [])) == action.get("portions", 1):
        return result(
            "completed",
            "Each requested drink from the specified liquid source has a verified report and thirst effect.",
            {"value": {"kind": "drink_from", **facts}, "consumption": ctx["receipts"]},
        )
    return None


def requested_options(action, target, menu):
    operation = {
        "thaw": "heat_item",
        "fill_container": "fill_container",
        "make_campfire": "make_campfire",
        "drink_from": "ingest_material",
    }[action["type"]]
    options = [
        o
        for o in menu.get("options", [])
        if o.get("operation") == operation and o.get("target_position") == target
    ]
    if action["type"] == "thaw":
        options = [o for o in options if o.get("item_id") == action["container_id"]]
    elif action["type"] == "fill_container":
        options = [
            o
            for o in options
            if o.get("container_id") == action["container_id"]
            and o.get("material_ref", {}).get("token") == action["material"]
            and (
                "source_state" not in action
                or o["material_ref"].get("state") == action["source_state"]
            )
        ]
    elif action["type"] == "drink_from":
        options = [
            o
            for o in options
            if o.get("material_ref", {}).get("token") == action["material"]
            and o["material_ref"].get("state") == "Liquid"
        ]
        if len(options) > 1 and all(
            o.get("native_class") == "adventure_environment_ingest_materialst"
            and not o.get("details_unavailable")
            and o.get("player_position") is not None
            and o["player_position"] == options[0].get("player_position")
            for o in options
        ):
            # This native class contains only source/player coordinates and
            # material/phase. DFHack's token canonically identifies material;
            # builtin WATER can have -1 or 0 as its ignored material index.
            # Equivalent source entries are mechanical aliases, not a new
            # controller choice. Keep the native order and guarded identity.
            options = options[:1]
    if not options and "container_id" in action:
        options = [
            o
            for o in menu.get("options", [])
            if o.get("kind") == "INTERACT_WITH_ITEM" and o.get("item_id") == action["container_id"]
        ]
    return options


def next_environment(workflow, view):
    action: dict[str, Any] = workflow["action"]
    ctx = workflow.setdefault("context", {})
    target = {k: action[k] for k in ("x", "y", "z")}
    anchor = ctx.setdefault("target_absolute", absolute(view, target))
    target = relative(view, anchor)
    if action.get("blocked_tiles"):
        excluded = ctx.setdefault(
            "blocked_absolute", [absolute(view, p) for p in action["blocked_tiles"]]
        )
        action = dict(action, blocked_tiles=[relative(view, p) for p in excluded])
    menu = view.get("menu")
    pending = ctx.pop("pending", None)
    if pending:
        if pending["kind"] == "walk":
            if blocker := verify_walk(pending, view):
                return blocker
        elif pending["before"] == menu_signature(view) and not ctx.get("sent"):
            return result(
                "no_effect", "The environment menu did not change; input was not repeated."
            )
    effect = {
        "thaw": thaw_effect,
        "make_campfire": campfire_effect,
        "fill_container": fill_effect,
        "drink_from": drink_effect,
    }[action["type"]]
    if decision := effect(action, ctx, view, target):
        if decision.get("outcome") == "completed" and menu:
            if ctx.get("closed"):
                return result(
                    "no_effect", "The requested effect is verified but the menu did not close."
                )
            ctx["closed"] = True
            return close_menu(view)
        return decision
    if menu:
        if menu.get("truncated"):
            return result(
                "needs_input",
                "The native environment choices are truncated; a unique target cannot be verified.",
                {
                    "blocker_kind": "source_incomplete",
                    "position": target,
                    "facts": {
                        "position": target,
                        "total_options": menu.get("total"),
                        "returned_options": len(menu.get("options", [])),
                    },
                },
            )
        options = requested_options(action, target, menu)
        if len(options) == 1 and not options[0].get("details_unavailable"):
            selected = selection_input(menu, options[0], "select_option")
            if "outcome" in selected:
                return selected
            if selected["type"] == "select_option" and options[0].get("operation"):
                ctx["sent"] = True
                if action["type"] == "drink_from":
                    ctx["drink_attempt"] = {
                        "thirst_before": view["adventurer"]["health"]["thirst_timer"],
                        "world_frame": view["status"].get("world_frame"),
                        "local_map_epoch": view["status"].get("local_map_epoch"),
                        "report_cursor": max(
                            (e["id"] for e in view.get("reports", [])), default=-1
                        ),
                    }
            return {"input": selected, "pending": {"kind": "menu", "before": menu_signature(view)}}
        if (
            action["type"] == "drink_from"
            and menu.get("kind") == "inventory"
            and (menu.get("context_name") == "EAT_DRINK" or ctx.get("opened"))
        ):
            return result(
                "needs_input",
                "The native consumption menu has no unique liquid source matching the requested tile and material.",
                {
                    "blocker_kind": "source_unavailable",
                    "position": target,
                    "facts": {
                        "position": target,
                        "material": action["material"],
                        "source_state": "Liquid",
                        "portions_consumed": len(ctx.get("receipts", [])),
                    },
                },
            )
        if (
            menu.get("kind") == "option_list"
            or ("container_id" in action and menu.get("kind") == "inventory")
        ) and ctx.get("opened"):
            return result(
                "needs_input",
                "The game offers no unique requested environment action for this target and source.",
                {"position": target, "options": menu.get("options", [])},
            )
        return close_menu(view)
    if not view["status"].get("can_move"):
        return result(
            "needs_input", "Environment interaction requires the local adventure input view."
        )
    position = view["status"].get("position") or {}
    approach = dict(target)
    if type(position.get("z")) is int and abs(position["z"] - target["z"]) == 1:
        # A river surface or pool lies one level below its bank, and DF offers
        # the interaction from the bank tile. Approach on the character's level
        # and let the native option list decide whether the source is in reach.
        approach["z"] = position["z"]
    decision = next_walk(view, approach, action, arrival_radius=1, context=ctx)
    if decision.get("outcome") != "completed":
        return decision
    ctx["opened"] = True
    key = (
        "A_INV_EATDRINK"
        if action["type"] == "drink_from"
        else ("A_INTERACT" if "container_id" in action else "A_GROUND")
    )
    return {
        "input": {"type": "key", "key": key},
        "pending": {"kind": "open", "before": menu_signature(view)},
    }
