"""Compose verified recipes under one dispatch lease, policy and checkpoint.

Stages are explicit controller choices. There is no target selection, branching
on an inferred threat, or recursive dispatch here. Only the active stage can
produce a native input; completed stages are retained as receipts on resume.
"""

from copy import deepcopy
from typing import Any

from .routing import ROUTE_FIELDS

COMPOSITES = {"sequence", "converse"}
MAX_STAGES = 128
LOCAL_TARGET_ACTIONS = {
    "walk_to",
    "use_stairs",
    "make_campfire",
    "thaw",
    "fill_container",
    "drink_from",
}

MOUNT_ACTIONS = {"mount", "dismount", "claim_pet", "lead_animal", "stop_leading"}


def question(topic):
    return {"topic": topic} if isinstance(topic, str) else deepcopy(topic)


def expand(action):
    if action["type"] == "sequence":
        return [leaf for child in action["actions"] for leaf in expand(child)]
    if action["type"] == "converse":
        route = {k: action[k] for k in ROUTE_FIELDS if k in action}
        stages = []
        for unit_id in action["unit_ids"]:
            # Closing a menu is delegated by this objective. Ending the native
            # social activity itself is a different, unsupported postcondition.
            stages.append({"type": "end_conversation"})
            stages.extend(
                {
                    "type": "talk",
                    "unit_id": unit_id,
                    **question(topic),
                    "completion": "reply",
                    **route,
                }
                for topic in action["topics"]
            )
        stages.append({"type": "end_conversation"})
        return stages
    return [deepcopy(action)]


def validate_composite(action):
    from .workflows import SEMANTIC, validate_action

    if action["type"] == "sequence":
        if set(action) != {"type", "actions"}:
            raise ValueError("sequence requires only type and actions")
        children = action["actions"]
        if not isinstance(children, list) or not 1 <= len(children) <= 64:
            raise ValueError("sequence.actions must contain 1..64 semantic actions")
        for child in children:
            if not isinstance(child, dict) or child.get("type") not in SEMANTIC - {"sequence"}:
                raise ValueError(
                    "sequence stages must be semantic actions; nested sequences and raw inputs are unsupported"
                )
            validate_action(child)
    else:
        allowed = {"type", "unit_ids", "topics"} | ROUTE_FIELDS
        if {"unit_ids", "topics"} - action.keys() or action.keys() - allowed:
            raise ValueError(
                "converse requires unit_ids and topics, with optional route constraints"
            )
        units, topics = action["unit_ids"], action["topics"]
        if not isinstance(units, list) or not 1 <= len(units) <= 32:
            raise ValueError("converse.unit_ids must contain 1..32 distinct unit IDs")
        if any(type(u) is not int or not 0 <= u <= 2147483647 for u in units) or len(
            set(units)
        ) != len(units):
            raise ValueError("converse.unit_ids must be distinct nonnegative integers")
        if not isinstance(topics, list) or not 1 <= len(topics) <= 16:
            raise ValueError(
                "converse.topics must contain 1..16 exact native topic types or labels"
            )
        for topic in topics:
            if not isinstance(topic, (str, dict)) or (
                isinstance(topic, dict)
                and ("topic" not in topic or topic.keys() - {"topic", "tact", "subject_hf_id"})
            ):
                raise ValueError("Each topic must be a string or {topic, tact?, subject_hf_id?}")
            validate_action(
                {
                    "type": "talk",
                    "unit_id": units[0],
                    **question(topic),
                    **{
                        k: action[k]
                        for k in allowed - {"type", "unit_ids", "topics"}
                        if k in action
                    },
                }
            )
    if len(expand(action)) > MAX_STAGES:
        raise ValueError(f"A composed objective may expand to at most {MAX_STAGES} stages")


def active_workflow(workflow):
    if workflow["action"]["type"] not in COMPOSITES:
        return workflow
    ctx = workflow.setdefault("context", {})
    if "stages" not in ctx:
        ctx.update(
            stages=[{"action": a, "context": {}} for a in expand(workflow["action"])],
            stage_index=0,
            results=[],
        )
    index = ctx["stage_index"]
    return ctx["stages"][index] if index < len(ctx["stages"]) else None


def observation_args(workflow):
    leaf = active_workflow(workflow)
    args = {}
    item_actions = {"pickup", "drop", "stow", "pack", "unpack", "equip", "wield", "remove", "trade"}
    root_actions = workflow["action"].get("actions", [workflow["action"]])
    if any(a["type"] in item_actions for a in root_actions):
        args["receipt_state"] = True
    # Completing the final stage must not drop the reader required by the
    # sequence's resulting load assessment.
    if leaf is None:
        return args
    if leaf["action"]["type"] in item_actions - {"trade"}:
        action = leaf["action"]
        args["target_item_ids"] = sorted(
            {action["item_id"], *action.get("replace", [])}
            | ({action["container_id"]} if "container_id" in action else set())
        )
    if leaf["action"]["type"] == "save_game":
        args["save_name"] = leaf["action"]["name"]
    if leaf["action"]["type"] in ("sleep", "rest"):
        args["rest_state"] = True
    if leaf["action"]["type"] == "travel_to" and leaf["action"].get("route", "auto") == "auto":
        from .overland import DETAIL_CACHE

        context = leaf.get("context", {})
        box = context.get("overland_box")
        if box and "overland_plan" not in context:
            args["overland"] = box
        if context.get("travel_started"):
            # Embark-level terrain around the party; the reader skips the rows
            # when the loaded window has not changed since the cached epoch.
            args["overland_detail"] = {"epoch": DETAIL_CACHE.get("epoch")}
    if "unit_id" in leaf["action"]:
        args["target_unit_id"] = leaf["action"]["unit_id"]
    if "figure_id" in leaf["action"]:
        args["target_figure_id"] = leaf["action"]["figure_id"]
    ctx = leaf.get("context", {})
    if leaf["action"]["type"] == "trade":
        args["trade_watch"] = deepcopy(leaf["action"])
        if submitted := ctx.get("trade_submitted"):
            args["trade_watch"].update(verify=True, signatures=sorted(submitted["inventory"]))
    if leaf["action"]["type"] == "strike":
        args["strike_state"] = True
    if leaf["action"]["type"] in MOUNT_ACTIONS:
        action = leaf["action"]
        args["mount_state"] = (
            {"figure_id": action["figure_id"]}
            if "figure_id" in action
            else action.get("unit_id", True)
        )
    if leaf["action"]["type"] in item_actions | LOCAL_TARGET_ACTIONS | MOUNT_ACTIONS | {
        "talk",
        "combat",
        "strike",
        "move",
        "open_trade",
    }:
        args["native_path_state"] = True
    evidence = ctx.get("input_evidence_for") or ctx.get("path_evidence_for")
    if evidence:
        args["input_evidence_for"] = evidence
    if leaf["action"]["type"] in LOCAL_TARGET_ACTIONS:
        anchor = ctx.get("target_absolute", ctx.get("stairs_source"))
        if anchor is None and (origin := workflow.get("context", {}).get("map_origin")):
            anchor = {k: leaf["action"][k] + origin[k] for k in ("x", "y", "z")}
        args["route_target"] = (
            {"absolute": deepcopy(anchor)}
            if anchor is not None
            else {"position": {k: leaf["action"][k] for k in ("x", "y", "z")}}
        )
    sent = ctx.get("topic_sent") or ctx.get("pending", {})
    if sent.get("activity_id") is not None and sent.get("activity_event_id") is not None:
        args["conversation_activity"] = {k: sent[k] for k in ("activity_id", "activity_event_id")}
    return args


def progress(workflow):
    leaf = active_workflow(workflow)
    ctx = workflow.get("context", {})
    current = leaf.get("context", {}) if leaf else {}
    out: dict[str, Any] = {
        "task_index": current.get("task_index", 0),
        "task_count": len(current.get("tasks", [])),
    }
    if workflow["action"]["type"] in COMPOSITES:
        out.update(
            stage_index=ctx["stage_index"],
            stage_count=len(ctx["stages"]),
            completed_stages=len(ctx["results"]),
        )
        if leaf:
            out["current_action"] = leaf["action"]
    if leaf and leaf["action"]["type"] == "talk" and current.get("topic_sent"):
        out["awaiting"] = {
            "condition": leaf["action"].get("completion", "reply"),
            "unit_id": leaf["action"].get("unit_id", leaf["action"].get("figure_id")),
            "utterance_verified": bool(current.get("utterance")),
        }
    if leaf and leaf["action"]["type"] in ("drink", "eat", "drink_from"):
        out["portions_consumed"] = len(current.get("receipts", []))
        out["portions_requested"] = leaf["action"].get("portions", 1)
    if leaf and leaf["action"]["type"] == "travel_to" and "overland_plan" in current:
        # The coarse route in travel tiles, so the controller can see where the
        # harness is steering and how many refused moves it has probed around.
        out["route"] = {
            "waypoints": current["overland_plan"],
            "waypoint": current.get("waypoint", 0),
            "detours": current.get("detours", 0),
            **({"detour_target": current["detour_target"]} if current.get("detour_target") else {}),
        }
    return out


def next_composite(workflow, view):
    from .workflows import next_step, result

    leaf = active_workflow(workflow)
    if leaf is None:
        return result(
            "completed", "Every requested stage reached its verified completion condition."
        )
    ctx = workflow["context"]
    origin = view["status"].get("map_origin")
    initial_origin = ctx.setdefault("map_origin", deepcopy(origin))
    action = leaf["action"]
    coordinates = action["type"] in LOCAL_TARGET_ACTIONS
    if (
        (coordinates or action.get("blocked_tiles"))
        and initial_origin != origin
        and (initial_origin is None or origin is None)
    ):
        return result(
            "needs_input",
            "A local coordinate frame is unavailable; this stage's targets cannot be anchored to the original map.",
            {
                "blocker_kind": "coordinate_frame_changed",
                "original_map_origin": initial_origin,
                "current_map_origin": origin,
                "requested_action": action,
            },
        )
    if initial_origin is not None:
        # All coordinate targets in a sequence refer to its initial observation.
        # Native map rebasing is an execution mechanic, including for stages
        # that have not started yet. Keep the controller's world tiles fixed.
        def anchor(point):
            return {k: point[k] + initial_origin[k] for k in ("x", "y", "z")}

        state = leaf.setdefault("context", {})
        if coordinates:
            field = "stairs_source" if action["type"] == "use_stairs" else "target_absolute"
            state.setdefault(
                field,
                {k: action[k] for k in ("x", "y", "z")}
                if action.get("absolute")
                else anchor(action),
            )
        if action.get("blocked_tiles"):
            state.setdefault("blocked_absolute", [anchor(p) for p in action["blocked_tiles"]])
    decision = next_step(leaf, view)
    if decision.get("outcome") != "completed":
        return decision
    receipt = {
        "stage_index": ctx["stage_index"],
        "action": deepcopy(leaf["action"]),
        "outcome": "completed",
        "reason": decision["reason"],
        "state_id": view["state_id"],
    }
    if "details" in decision:
        receipt["details"] = decision["details"]
    ctx["results"].append(receipt)
    ctx["stage_index"] += 1
    # Commit observed progress separately from planning the next input. This is
    # essential when a step limit or preflight rejection stops the next stage.
    return {"advanced": True}
