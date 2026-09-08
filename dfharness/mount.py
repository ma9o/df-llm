"""Mount, dismount, claim, lead and release animals through DF's own movement options."""

from .workflows import next_walk, result

COMMANDS = {
    "mount": "mount",
    "dismount": "dismount",
    "claim_pet": "claim_pet",
    "lead_animal": "lead_animal",
    "stop_leading": "stop_leading",
}


def validate_mount(action):
    kind = action["type"]
    keys = {"type"} if kind == "dismount" else {"type", "unit_id"}
    if set(action) != keys:
        raise ValueError(
            "dismount accepts no targets; mount, claim_pet, lead_animal and stop_leading require unit_id"
        )
    unit_id = action.get("unit_id")
    if kind != "dismount" and (type(unit_id) is not int or not 0 <= unit_id <= 2147483647):
        raise ValueError("unit_id must be a nonnegative native unit ID")


def satisfied(kind, state, unit_id):
    animal = state.get("animal") or {}
    if kind == "mount":
        return state.get("rider") is True and state.get("mount_id") == unit_id
    if kind == "dismount":
        return state.get("rider") is False
    if kind == "claim_pet":
        return animal.get("owner_id") == state.get("adventurer_id")
    if kind == "lead_animal":
        return state.get("leading_id") == unit_id
    return state.get("leading_id") != unit_id


def next_mount(workflow, view):
    action, ctx = workflow["action"], workflow.setdefault("context", {})
    kind, unit_id = action["type"], action.get("unit_id")
    state = view.get("mount") or {}
    if not state.get("available"):
        return result(
            "needs_input",
            state.get("reason", "The native rider and animal state is unavailable."),
            {"blocker_kind": "mount_state_unavailable"},
        )
    animal = state.get("animal") or {}
    facts = {"command": kind, "unit_id": unit_id, "rider": state.get("rider"), "animal": animal}
    if satisfied(kind, state, unit_id):
        return result(
            "completed",
            "The native rider and animal state shows the requested result.",
            {"value": {"kind": kind, **facts, "mount_id": state.get("mount_id")}},
        )
    if ctx.get("sent"):
        # The realized option is a unit action that runs on the next game turn.
        # Advance one native short wait per queued action, bounded, then verify.
        queued = [a for a in state.get("queued", []) if a in ("Mount", "Dismount", "Move")]
        if queued and ctx.get("waits", 0) < 3:
            ctx["waits"] = ctx.get("waits", 0) + 1
            return {"input": {"type": "wait"}}
        return result(
            "no_effect",
            "The native command was accepted but its result is not observed; it was not repeated.",
            {"blocker_kind": "mount_verification", "facts": {**facts, "queued": queued}},
        )
    if kind != "dismount":
        if animal.get("present") is False or not animal.get("visible"):
            return result(
                "needs_input",
                "The specified animal is not currently visible.",
                {"blocker_kind": "animal_unavailable", "facts": facts},
            )
        if not animal.get("alive"):
            return result(
                "needs_input",
                "The specified animal is dead.",
                {"blocker_kind": "animal_unavailable"},
            )
        if kind == "mount" and not animal.get("mount_capable"):
            return result(
                "needs_input",
                "This creature cannot be ridden.",
                {"blocker_kind": "animal_unavailable", "facts": facts},
            )
        if not animal.get("adjacent"):
            if view.get("menu"):
                from .workflows import close_menu

                return close_menu(view)
            if not view["status"].get("can_move"):
                return result(
                    "needs_input", "Approaching the animal requires the default adventure view."
                )
            decision = next_walk(view, animal["position"], {}, arrival_radius=1, context=ctx)
            if decision.get("outcome") != "completed":
                return decision
    if not view["status"].get("can_move"):
        return result("needs_input", "Native animal commands require the default adventure view.")
    ctx["sent"] = True
    command = {"type": "mount_command", "command": COMMANDS[kind]}
    if unit_id is not None:
        command["unit_id"] = unit_id
    return {"input": command}
