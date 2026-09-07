"""One selection planner shared by recipes and explicit native-ID dispatches."""

from copy import deepcopy


def selection_input(menu, option, action_type):
    if reason := menu.get("selection_unavailable") or option.get("selection_unavailable"):
        return {"outcome": "needs_input", "reason": reason}
    binding = option.get("selection", {})
    if binding.get("method") in ("native_hotkey", "native_key"):
        # Native selection centers and normalizes the list inside the guarded
        # input request. Keys beyond the rendered page can be ignored even
        # when an OPTION enum exists, so never infer visibility from 20 enums.
        return {"type": action_type, "option_id": option["id"]}
    if option.get("visible"):
        return {"type": action_type, "option_id": option["id"]}
    visible = [o["index"] for o in menu.get("options", []) if o.get("visible")]
    first = min(visible) if visible else menu.get("scroll", 0)
    direction = "PAGEUP" if option["index"] < first else "PAGEDOWN"
    return {"type": "key", "key": "ADVENTURE_LIST_SCROLL_" + direction}


def next_selection(workflow, view):
    action, ctx = workflow["action"], workflow.setdefault("context", {})
    menus = (
        [view.get("menu")]
        if action["type"] == "select_option"
        else [view.get("conversation"), view.get("combat")]
    )
    if ctx.get("raw_sent"):
        changed = ctx["selection_effect"] != view.get("effect_id")
        return {
            "outcome": "completed" if changed else "no_effect",
            "reason": (
                "Native selection changed the observed state; gameplay effects require their own postconditions."
                if changed
                else "Native selection did not change the observed state; no input was repeated."
            ),
        }
    if ctx.pop("scroll_effect", None) == view.get("effect_id"):
        return {"outcome": "no_effect", "reason": "The menu did not scroll; no input was repeated."}
    matches = [
        (m, o)
        for m in menus
        if m
        for o in m.get("options", [])
        if action["option_id"] in (o["id"], o.get("handle"))
    ]
    if len(matches) != 1:
        return {"outcome": "needs_input", "reason": "Native option is absent or ambiguous."}
    menu, option = matches[0]
    selected = selection_input(menu, option, action["type"])
    if "outcome" in selected:
        return selected
    if selected["type"] == action["type"]:
        ctx["raw_sent"] = True
        ctx["selection_effect"] = view.get("effect_id")
    else:
        ctx["scroll_effect"] = view.get("effect_id")
    return {"input": deepcopy(selected)}
