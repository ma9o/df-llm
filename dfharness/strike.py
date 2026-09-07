"""One explicitly aimed melee strike, using native choices and action evidence."""

from .interactions import approach, choose, signature
from .routing import ROUTE_FIELDS
from .workflows import absolute, relative, result, validate_action, verify_walk

STYLES = ("normal", "quick", "heavy", "wild", "precise")


def validate_strike(action):
    required = {"type", "unit_id", "body_part_id", "item_id", "attack_index", "style"}
    if required - action.keys() or action.keys() - required - ROUTE_FIELDS:
        raise ValueError("strike requires unit_id, body_part_id, item_id, attack_index and style")
    for key in required - {"type", "style"}:
        low = -1 if key == "item_id" else 0
        if type(action[key]) is not int or not low <= action[key] <= 2147483647:
            raise ValueError(
                key + " must be a native nonnegative ID/index (-1 for a natural attack item)"
            )
    if action["style"] not in STYLES:
        raise ValueError("strike.style must be normal, quick, heavy, wild or precise")
    validate_action(
        {
            "type": "walk_to",
            "x": 0,
            "y": 0,
            "z": 0,
            **{k: action[k] for k in ROUTE_FIELDS & action.keys()},
        }
    )


def next_strike(workflow, view):
    action, ctx = workflow["action"], workflow.setdefault("context", {})
    unit_id = action["unit_id"]
    menu = view.get("combat") or {}
    target = view.get("target_unit") or {}
    condition = target.get("condition") if target.get("id") == unit_id else None
    condition = condition or {
        "available": False,
        "reason": "Target condition is not currently readable",
    }

    def blocked(kind, why, facts=None, outcome="needs_input"):
        return result(
            outcome,
            why,
            {
                "blocker_kind": kind,
                "facts": {
                    "unit_id": unit_id,
                    "target": condition,
                    **(facts or {}),
                },
            },
        )

    def reopen(cause):
        attempted = ctx.setdefault("reopened", [])
        if cause in attempted:
            return blocked(
                "attack_navigation",
                "The native combat interface returned to an incompatible choice.",
                {"cause": cause},
            )
        attempted.append(cause)
        # LEAVESCREEN closes these decoded modes without committing an attack.
        # Opening A_ATTACK again creates an explicit aimed-target interaction.
        return {
            "input": {"type": "key", "key": "LEAVESCREEN"},
            "pending": {"kind": "reopen", "menu": signature(menu)},
        }

    if ctx.get("input_evidence_for"):
        evidence = view.get("input_evidence") or {}
        if evidence.get("available") is not True or evidence.get("kind") != "strike":
            return blocked(
                "attack_evidence",
                "Submitted attack evidence is unavailable; no attack was repeated.",
                evidence,
            )
        if (
            any(evidence.get(k) != action[k] for k in ("body_part_id", "item_id", "attack_index"))
            or evidence.get("target_unit_id") != unit_id
        ):
            return blocked("attack_evidence", "Native evidence belongs to a different attack.")
        facts = {
            "phase": evidence.get("phase"),
            "strike_observed": evidence.get("strike_observed"),
            "recovery_observed": evidence.get("recovery_observed"),
            **evidence.get("latest", {}),
        }
        finished = (
            evidence.get("phase") == "finished"
            and evidence.get("strike_observed") is True
            and evidence.get("recovery_observed") is True
        )
        cancelled = (
            evidence.get("phase") == "cancelled"
            and evidence.get("tracking") is False
            and isinstance(evidence.get("effect", {}).get("cause"), dict)
            and isinstance(evidence["effect"]["cause"].get("type"), str)
            and evidence["effect"]["cause"].get("source") in ("report_text", "native_unit_flags")
            and (
                evidence["effect"].get("resolution") == "cancelled"
                or (
                    evidence.get("strike_observed") is True
                    and evidence["effect"].get("recovery") == "cancelled"
                )
            )
        )
        if finished or cancelled:
            return result(
                "completed",
                "The native attack ended; its value distinguishes the strike and recovery outcomes.",
                {
                    "value": {
                        "kind": "strike",
                        "unit_id": unit_id,
                        "recovered": finished,
                        "target": condition,
                        **{
                            k: v
                            for k, v in evidence.get(
                                "effect", {"resolution": "processed", "damage": "unverified"}
                            ).items()
                            if k != "report_id"
                        },
                    },
                    "attack": {
                        "unit_id": unit_id,
                        "native_action_id": evidence.get("native_action", {}).get("id"),
                        **facts,
                    },
                },
            )
        if evidence.get("phase") == "unverified" or evidence.get("tracking") is not True:
            return blocked(
                "attack_unverified",
                evidence.get("reason", "Native attack completion is unverified."),
                facts,
                "no_effect",
            )
        if not view["status"].get("can_move"):
            return blocked(
                "attack_pending",
                "The attack is pending; the current interface requires a separate decision.",
                facts,
            )
        pending = ctx.get("pending")
        if (
            pending
            and pending.get("kind") == "wait_attack"
            and pending.get("effect") == view.get("effect_id")
        ):
            return blocked(
                "attack_no_effect",
                "Waiting did not advance the pending attack; no input was repeated.",
                facts,
                "no_effect",
            )
        # Execution mode, limits and interruption predicates are applied by the
        # shared dispatcher before this mechanical wait, just like movement.
        return {
            "input": {"type": "wait"},
            "pending": {"kind": "wait_attack", "effect": view.get("effect_id")},
            "progress": {"awaiting": facts},
        }

    state = view.get("strike_state") or {}
    if state.get("available") is not True:
        return blocked("attack_reader", "Native attack-state verification is unavailable.", state)
    if state.get("actions"):
        return blocked(
            "attack_pending",
            "Another native attack is already pending.",
            {"actions": state["actions"]},
        )
    target = view.get("target_unit") or next(
        (u for u in (view.get("map") or {}).get("units", []) if u["id"] == unit_id), None
    )
    if condition.get("dead") is True:
        return blocked("attack_target_dead", "The requested unit is already dead.")
    pending = ctx.pop("pending", None)
    if pending and pending["kind"] == "walk":
        if blocker := verify_walk(pending, view):
            return blocker
    elif pending and pending["kind"] == "settle_target":
        if pending["effect"] == view.get("effect_id"):
            ctx["pending"] = pending
            return blocked(
                "attack_target_in_flight",
                "Waiting did not advance the target's native knockback; no input was repeated.",
                outcome="no_effect",
            )
    elif pending and pending["kind"] == "style":
        if menu.get("mode") != "AIM_ATTACK" or menu.get("target_unit_id") != unit_id:
            return blocked(
                "attack_menu_changed", "The aiming context changed while adjusting attack style."
            )
        enabled = pending["flag"] in menu.get("attack_flags", [])
        if enabled != pending["enabled"]:
            return blocked(
                "attack_style",
                "The native style key did not take effect; it was not repeated.",
                {"flag": pending["flag"], "requested": pending["enabled"], "actual": enabled},
                "no_effect",
            )
    elif pending and signature(menu) == pending["menu"]:
        return blocked(
            "attack_menu",
            "The native combat decision did not change; input was not repeated.",
            outcome="no_effect",
        )

    if condition.get("projectile") is True:
        if not view["status"].get("can_move"):
            return blocked(
                "attack_target_in_flight",
                "The target is being propelled; close the current interface before waiting.",
            )
        return {
            "input": {"type": "wait"},
            "pending": {"kind": "settle_target", "effect": view.get("effect_id")},
        }

    if menu.get("open"):
        mode = menu.get("mode")
        if menu.get("selection_unavailable"):
            return blocked("attack_binding", menu["selection_unavailable"], {"mode": mode})
        if mode != "UNIT_CHOICE" and menu.get("target_unit_id") != unit_id:
            if mode in ("CONFIRM", "MOVE_CHOICE", "AIM_TARGET", "AIM_ATTACK"):
                return reopen("target")
            return blocked(
                "attack_target",
                "The open combat decision has a different target.",
                {"actual_unit_id": menu.get("target_unit_id")},
            )
        options = menu.get("options", [])
        if mode == "UNIT_CHOICE":
            matches = [o for o in options if o.get("unit_id") == unit_id]
        elif mode == "CONFIRM":
            if menu.get("always_do_something") is True:
                return reopen("aimed_confirmation")
            if menu.get("always_do_something") is not False:
                return blocked(
                    "attack_confirmation",
                    "The native confirmation's effect is unknown; it was not selected.",
                )
            matches = [o for o in options if o.get("native_type") == "confirm"]
        elif mode == "MOVE_CHOICE":
            matches = [o for o in options if o.get("native_type") == "STRIKE"]
        elif mode == "AIM_TARGET":
            matches = [o for o in options if o.get("body_part_id") == action["body_part_id"]]
        elif mode == "AIM_ATTACK":
            parts = {o.get("body_part_id") for o in options}
            if parts and None not in parts and action["body_part_id"] not in parts:
                return reopen("body_part")
            matches = [
                o
                for o in options
                if all(o.get(k) == action[k] for k in ("body_part_id", "item_id", "attack_index"))
            ]
            if len(matches) != 1:
                return choose(menu, matches, view, "strike_menu")
            flags = menu.get("attack_flags")
            if not isinstance(flags, list):
                return blocked("attack_style", "Native attack flags are unavailable.")
            unknown = set(flags) - {"quick", "heavy", "wild", "precise", "charge", "multi"}
            if unknown:
                return blocked(
                    "attack_style",
                    "Additional native attack flags are active and have no verified control.",
                    {"flags": sorted(unknown)},
                )
            wanted = set() if action["style"] == "normal" else {action["style"]}
            # A single aimed strike excludes charge and multiattack. Disable
            # residual toggles explicitly; never inherit a previous tactic.
            remove, add = sorted(set(flags) - wanted), sorted(wanted - set(flags))
            if remove or add:
                flag, enabled = (remove[0], False) if remove else (add[0], True)
                key = menu.get("style_keys", {}).get(flag)
                if not key:
                    return blocked(
                        "attack_style",
                        "The required native style toggle is unverified.",
                        {"flag": flag},
                    )
                return {
                    "input": {"type": "key", "key": key},
                    "pending": {"kind": "style", "flag": flag, "enabled": enabled},
                }
        else:
            return blocked(
                "attack_mode",
                "The current combat phase has no verified strike navigation.",
                {"mode": mode},
            )
        decision = choose(menu, matches, view, "strike_menu")
        if mode == "AIM_ATTACK" and decision.get("input", {}).get("type") == "select_interaction":
            decision["capture"] = {"kind": "strike"}
        return decision

    if not target or target.get("id") != unit_id or not target.get("position"):
        return blocked("attack_target", "The specified unit is not currently visible.")
    if action.get("blocked_tiles"):
        excluded = ctx.setdefault(
            "blocked_absolute", [absolute(view, p) for p in action["blocked_tiles"]]
        )
        action = dict(action, blocked_tiles=[relative(view, p) for p in excluded])
    decision = approach(view, target["position"], action, ctx)
    if decision.get("outcome") != "completed":
        return decision
    return {
        "input": {"type": "key", "key": "A_ATTACK"},
        "pending": {"kind": "open", "menu": signature(menu)},
    }
