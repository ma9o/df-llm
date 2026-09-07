"""Select explicit native movement settings and verify their persisted values."""

from .selection import selection_input
from .workflows import close_menu, menu_signature, result


def validate_movement(action):
    if action["type"] == "set_sneaking":
        if set(action) != {"type", "enabled"} or type(action["enabled"]) is not bool:
            raise ValueError("set_sneaking requires enabled=true or false")
        return
    if (
        set(action) != {"type", "gait"}
        or not isinstance(action["gait"], str)
        or not 0 < len(action["gait"]) <= 100
    ):
        raise ValueError("set_gait requires a native gait name, such as Walk")


def next_movement(workflow, view):
    action, ctx = workflow["action"], workflow.setdefault("context", {})
    menu = view.get("menu")
    state = (view.get("adventurer") or {}).get("movement") or {}
    if action["type"] == "set_sneaking":
        return next_toggle(workflow, view, state.get("sneaking"), action["enabled"], "A_SNEAK")
    if not state.get("available"):
        return result(
            "needs_input",
            "Native movement settings are unavailable.",
            {"blocker_kind": "verification"},
        )
    expected = ctx.get("selected")
    if expected:
        if state.get("selected_gaits", {}).get(expected["type"]) != expected["index"]:
            return result(
                "no_effect", "The requested native gait was not selected; input was not repeated."
            )
        if menu and menu.get("kind") == "movement":
            if ctx.get("closed"):
                return result("no_effect", "The movement menu did not close.")
            ctx["closed"] = True
            return close_menu(view)
        return result(
            "completed",
            "Requested native gait verified.",
            {"gait": action["gait"], "gait_type": expected["type"]},
        )
    pending = ctx.pop("pending", None)
    if pending and pending["before"] == menu_signature(view):
        return result("no_effect", "The movement interface did not change; input was not repeated.")
    if menu:
        if menu.get("kind") != "movement":
            return close_menu(view)
        if menu.get("unit_id") != view["status"].get("adventurer_id"):
            return result("needs_input", "The movement menu targets another character.")
        if menu.get("selection_unavailable"):
            return result("needs_input", menu["selection_unavailable"])
        matches = [
            o
            for o in menu.get("options", [])
            if o.get("label", "").casefold() == action["gait"].casefold()
        ]
        if len(matches) != 1:
            return result(
                "needs_input",
                "The requested gait is absent or ambiguous in the current movement mode.",
                {"options": menu.get("options", [])},
            )
        option = matches[0]
        expected = {"type": option["gait_type"], "index": option["gait_index"]}
        if state["selected_gaits"].get(expected["type"]) == expected["index"]:
            ctx["selected"] = expected
            return {"advanced": True}
        selected = selection_input(menu, option, "select_option")
        if "outcome" in selected:
            return selected
        if selected["type"] == "select_option":
            ctx["selected"] = expected
        return {"input": selected, "pending": {"before": menu_signature(view)}}
    if not view["status"].get("can_move"):
        return result("needs_input", "Selecting a gait requires the local adventure input view.")
    return {
        "input": {"type": "key", "key": "A_MOVEMENT"},
        "pending": {"before": menu_signature(view)},
    }


def next_toggle(workflow, view, current, desired, key):
    ctx = workflow.setdefault("context", {})
    if type(current) is not bool:
        return result("needs_input", "The requested movement setting is unavailable.")
    if current == desired:
        return result("completed", "Requested native movement setting verified.")
    if ctx.get("toggle_sent") or ctx.get("posture_sent"):
        return result("no_effect", "The movement setting did not change; input was not repeated.")
    pending = ctx.pop("pending", None)
    if pending and pending["before"] == menu_signature(view):
        return result("no_effect", "The current menu did not close; input was not repeated.")
    if view.get("menu"):
        return close_menu(view)
    if not view["status"].get("can_move"):
        return result(
            "needs_input", "Changing movement settings requires the local adventure input screen."
        )
    ctx["toggle_sent"] = True
    return {"input": {"type": "key", "key": key}}
