"""Consume explicit carried portions through native menus and verify each."""

from .selection import selection_input
from .state import inventory, inventory_complete
from .workflows import close_menu, menu_signature, result


def need_effect(counter, before, attempt, status):
    """A reduced/reset native need, allowing observed ticking after a reset."""
    frame, initial_frame = status.get("world_frame"), attempt.get("world_frame")
    elapsed = (
        frame - initial_frame
        if type(frame) is int
        and type(initial_frame) is int
        and status.get("local_map_epoch") == attempt.get("local_map_epoch")
        else None
    )
    return (
        counter < before
        or counter == before == 0
        or (elapsed is not None and elapsed >= 0 and 0 <= counter <= elapsed)
    )


def liquid_identity(item):
    fields = ("type", "subtype", "quality", "wear", "contaminants")
    if (
        any(k not in item for k in fields)
        or item.get("contaminants_unavailable")
        or item.get("contaminants_truncated")
    ):
        return None
    material = item.get("material_ref", {}).get("token")
    if not material:
        return None
    return {"material": material, **{k: item[k] for k in fields}}


def resolve_container(action, ctx, view):
    if "resolved_item_id" in ctx:
        return None
    container = inventory(view).get(action["container_id"])
    liquids = [
        i
        for i in (container or {}).get("contents", [])
        if i.get("type") in ("LIQUID_MISC", "DRINK")
    ]
    identity = liquid_identity(liquids[0]) if liquids else None
    ambiguous = len(liquids) > 1 and (
        identity is None or any(liquid_identity(i) != identity for i in liquids)
    )
    if not container or not inventory_complete(view) or not liquids or ambiguous:
        return result(
            "needs_input",
            "The specified container has no unambiguous fully observed liquid source.",
            {
                "blocker_kind": "source_ambiguous" if ambiguous else "source_not_liquid",
                "container_id": action["container_id"],
                "candidates": [
                    {
                        "item_id": i["id"],
                        "type": i.get("type"),
                        "material": i.get("material_ref", {}).get("token"),
                    }
                    for i in liquids
                ],
            },
        )
    # The controller selected this container. Equivalent native liquid stacks
    # are mechanical portions of that source, not a new material choice. Keep
    # the initial IDs fixed; neither resume nor depletion adopts a new item.
    ctx["source_ids"] = sorted(i["id"] for i in liquids)
    ctx["source_index"] = 0
    ctx["source_identity"] = identity
    ctx["resolved_item_id"] = ctx["source_ids"][0]
    return None


def next_consume(workflow, view):
    action, ctx = workflow["action"], workflow.setdefault("context", {})
    if "container_id" in action:
        if blocker := resolve_container(action, ctx, view):
            return blocker
        action = dict(action, item_id=ctx["resolved_item_id"])
    kind = action["type"]
    need = "thirst" if kind == "drink" else "hunger"
    event_type = "DRINK_ITEM" if kind == "drink" else "EAT_ITEM"
    before_key, after_key = need + "_before", need + "_after"
    attempt_key = kind + "_attempt"
    menu = view.get("menu")
    item = inventory(view).get(action["item_id"])
    counter = (view.get("adventurer") or {}).get("health", {}).get(need + "_timer")
    if type(counter) is not int:
        return result(
            "needs_input",
            f"The {need} counter is unavailable; consumption cannot be verified.",
            {"blocker_kind": "verification"},
        )
    attempt = ctx.get(attempt_key)
    if attempt:
        reports = [e for e in view.get("reports", []) if e["id"] > attempt["report_cursor"]]
        remaining = item.get("stack_size") if item else 0
        if (
            need_effect(counter, attempt[before_key], attempt, view["status"])
            and remaining == attempt["portions_before"] - 1
            and inventory_complete(view)
            and any(e.get("type") == event_type for e in reports)
        ):
            ctx.setdefault("receipts", []).append(
                {
                    "item_id": action["item_id"],
                    before_key: attempt[before_key],
                    after_key: counter,
                    "portions_remaining": remaining,
                    "report_ids": [e["id"] for e in reports if e.get("type") == event_type],
                }
            )
            ctx.pop(attempt_key)
            next_source = ctx.get("source_index", 0) + 1
            if (
                remaining == 0
                and len(ctx["receipts"]) < action.get("portions", 1)
                and next_source < len(ctx.get("source_ids", []))
            ):
                ctx["source_index"] = next_source
                ctx["resolved_item_id"] = ctx["source_ids"][next_source]
            # Save observed consumption separately from planning the next input.
            # A boundary before the next portion must never replay consumption.
            return {"advanced": True}
        return result(
            "no_effect",
            f"The requested {kind} has no verified portion consumption and {need} effect; selection will not be repeated.",
            {
                "blocker_kind": "verification",
                "item_id": action["item_id"],
                before_key: attempt[before_key],
                after_key: counter,
                "reports": reports,
            },
        )
    pending = ctx.pop("pending", None)
    if pending and menu_signature(view) == pending["before"]:
        return result("no_effect", "The consumption menu did not change; input was not repeated.")
    if len(ctx.get("receipts", [])) == action.get("portions", 1):
        if menu:
            return close_menu(view)
        return result(
            "completed",
            f"Every requested portion was consumed and its {need} effect verified.",
            {
                "item_id": action["item_id"],
                "portions_consumed": len(ctx["receipts"]),
                "consumption": ctx["receipts"],
            },
        )
    if not item:
        return result(
            "needs_input",
            "The specified item is not in the observed carried inventory.",
            {"blocker_kind": "target_unavailable", "item_id": action["item_id"]},
        )
    if ctx.get("source_identity") and liquid_identity(item) != ctx["source_identity"]:
        return result(
            "needs_input",
            "The pinned liquid source changed its material or item properties.",
            {"blocker_kind": "source_changed", "item_id": item["id"]},
        )
    if (
        "container_id" in action
        and item.get("location", {}).get("container_id") != action["container_id"]
    ):
        return result(
            "needs_input",
            "The selected liquid is no longer in the specified container.",
            {
                "blocker_kind": "target_unavailable",
                "container_id": action["container_id"],
                "item_id": item["id"],
            },
        )
    liquid = item.get("type") in ("LIQUID_MISC", "DRINK")
    if (kind == "drink" and not liquid) or (kind == "eat" and liquid):
        return result(
            "needs_input",
            "Select liquid contents by item ID; this target is not a liquid drink."
            if kind == "drink"
            else "Eating requires solid food; use drink for liquid contents.",
            {
                "blocker_kind": "source_not_liquid" if kind == "drink" else "source_not_food",
                "item_id": action["item_id"],
                "type": item.get("type"),
            },
        )
    if type(item.get("stack_size")) is not int or item["stack_size"] < 1:
        return result(
            "needs_input",
            "The remaining consumable quantity is unavailable.",
            {"blocker_kind": "verification"},
        )
    if menu:
        matches = [
            o
            for o in menu.get("options", [])
            if o.get("kind") == "EAT_DRINK_ITEM" and o.get("item_id") == action["item_id"]
        ]
        if len(matches) == 1:
            option = matches[0]
            selected = selection_input(menu, option, "select_option")
            if "outcome" in selected:
                return selected
            if selected["type"] == "select_option":
                ctx[attempt_key] = {
                    before_key: counter,
                    "world_frame": view["status"].get("world_frame"),
                    "local_map_epoch": view["status"].get("local_map_epoch"),
                    "portions_before": item["stack_size"],
                    "report_cursor": max((e["id"] for e in view.get("reports", [])), default=-1),
                }
                return {"input": selected}
            return {
                "input": selected,
                "pending": {"before": menu_signature(view)},
            }
        if len(matches) > 1 or ctx.get("opened"):
            return result(
                "needs_input",
                "The game offers no unique consume option for the requested item.",
                {"blocker_kind": "controller_choice", "options": menu.get("options", [])},
            )
        return close_menu(view)
    if not view["status"].get("can_move"):
        return result(
            "needs_input", "Opening the consumption menu requires the local adventure input view."
        )
    ctx["opened"] = True
    return {
        "input": {"type": "key", "key": "A_INV_EATDRINK"},
        "pending": {"before": menu_signature(view)},
    }
