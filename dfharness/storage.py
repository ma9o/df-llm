"""Explicit whole-container emptying through the verified native liquid action."""

from .selection import selection_input
from .state import inventory, inventory_complete
from .workflows import close_menu, menu_signature, result


def validate_empty(action):
    if set(action) != {"type", "container_id"} or (
        type(action["container_id"]) is not int or not 0 <= action["container_id"] <= 2147483647
    ):
        raise ValueError("empty_container requires one nonnegative container_id")


def next_empty(workflow, view):
    action, ctx = workflow["action"], workflow.setdefault("context", {})
    container_id = action["container_id"]
    container = inventory(view).get(container_id)
    facts = {"container_id": container_id}

    def blocked(kind, why, extra=None, outcome="needs_input"):
        return result(outcome, why, {"blocker_kind": kind, "facts": {**facts, **(extra or {})}})

    capacity = (container or {}).get("capacity_volume_raw")
    if (
        not container
        or not inventory_complete(view)
        or "contents" not in container
        or type(capacity) is not int
        or capacity <= 0
        or not isinstance(container.get("location"), dict)
    ):
        return blocked(
            "container_unavailable",
            "Emptying requires complete contents of the specified carried container.",
        )
    remaining = sorted(i["id"] for i in container["contents"])
    pending = ctx.pop("pending", None)
    menu = view.get("menu")
    if pending and pending["before"] == menu_signature(view) and not ctx.get("submitted"):
        return blocked(
            "verification",
            "The native emptying menu did not change; input was not repeated.",
            outcome="no_effect",
        )
    if ctx.get("submitted"):
        reports = [
            e
            for e in view.get("reports", [])
            if e["id"] > ctx["report_cursor"] and e.get("type") == "EMPTY_CONTAINER"
        ]
        if remaining or len(reports) != 1:
            return blocked(
                "verification",
                "The container has no verified native emptying effect; selection was not repeated.",
                {"remaining_item_ids": remaining},
                "no_effect",
            )
        if container.get("location") != ctx["container_location"]:
            return blocked("container_changed", "The container changed location during emptying.")
    if not remaining:
        if menu:
            return close_menu(view)
        return result(
            "completed",
            "The specified carried container is empty.",
            {
                "value": {
                    "kind": "empty_container",
                    "container_id": container_id,
                    "items_emptied": len(ctx.get("initial_items", []))
                    if ctx.get("submitted")
                    else 0,
                }
            },
        )
    initial = ctx.setdefault("initial_items", remaining)
    if remaining != initial:
        return blocked(
            "container_changed",
            "The container's contents changed before emptying was submitted.",
            {"expected_item_ids": initial, "actual_item_ids": remaining},
        )
    if menu:
        if menu.get("truncated"):
            return blocked(
                "choices_incomplete",
                "The native drop options are truncated; container emptying cannot be verified.",
            )
        choices = [
            o
            for o in menu.get("options", [])
            if o.get("operation") == "empty_container"
            and o.get("container_id") == container_id
            and o.get("item_id") in initial
            and not o.get("details_unavailable")
        ]
        if choices:
            # Each verified liquid child invokes the same native operation on
            # the explicitly chosen whole container. It is one emptying input.
            selected = selection_input(menu, choices[0], "select_option")
            if "outcome" in selected:
                return selected
            if selected["type"] == "select_option":
                ctx["submitted"] = True
                ctx["report_cursor"] = max((e["id"] for e in view.get("reports", [])), default=-1)
                ctx["container_location"] = container.get("location")
            return {"input": selected, "pending": {"before": menu_signature(view)}}
        if menu.get("kind") == "inventory" and (
            menu.get("context_name") == "DROP" or ctx.get("opened")
        ):
            return blocked(
                "emptying_unavailable",
                "No verified native whole-container emptying option is available; this adapter requires liquid contents.",
            )
        return close_menu(view)
    if not view["status"].get("can_move"):
        return blocked(
            "interface", "Opening the emptying menu requires the local adventure input view."
        )
    ctx["opened"] = True
    return {
        "input": {"type": "key", "key": "A_INV_DROP"},
        "pending": {"before": menu_signature(view)},
    }
