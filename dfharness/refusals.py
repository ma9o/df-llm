"""Native refusals scoped to the active objective's last mechanical input."""

from .state import inventory

# These are player-interface refusals, not ambient combat announcements.
# Scope by objective as well as cursor: another stage's denial is not this one.
REPORTS = {
    "set_posture": {"CANNOT_STAND"},
    "pickup": {"NO_GRASP_FOR_PICKUP"},
    "equip": {"NO_GRASP_FOR_PICKUP", "NO_GRASP_TO_DRAW_ITEM"},
    "wield": {"NO_GRASP_FOR_PICKUP", "NO_GRASP_TO_DRAW_ITEM"},
    "sleep": {"CANNOT_REST"},
    "rest": {"CANNOT_REST"},
    "make_campfire": {"CANNOT_MAKE_CAMPFIRE"},
    "walk_to": {"CANNOT_CLIMB"},
    "move": {"CANNOT_CLIMB"},
    "use_stairs": {"CANNOT_CLIMB"},
}


def native_refusal(workflow, view, events):
    action, ctx = workflow["action"], workflow.get("context", {})
    after = ctx.get("refusal_after")
    if type(after) is not int:
        return None
    candidates = [
        event
        for event in events
        if type(event.get("id")) is int
        and event["id"] > after
        and event.get("type") in REPORTS.get(action["type"], ())
        and isinstance(event.get("text"), str)
        and event["text"]
    ]
    if not candidates:
        return None
    event = max(candidates, key=lambda event: event["id"])
    facts = {"type": event["type"], "report_id": event["id"]}
    if event["type"] in {"NO_GRASP_FOR_PICKUP", "NO_GRASP_TO_DRAW_ITEM"}:
        tasks, index = ctx.get("tasks", []), ctx.get("task_index", 0)
        task = tasks[index] if 0 <= index < len(tasks) else action
        if "item_id" in task:
            facts["item_id"] = task["item_id"]
        facts["held_item_ids"] = sorted(
            i["id"] for i in inventory(view).values() if i.get("mode") in ("Weapon", "Hauled")
        )
    return {"reason": event["text"], "facts": facts}
