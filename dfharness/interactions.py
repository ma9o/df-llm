"""Semantic conversation, stair and combat-menu execution with explicit targets."""

from .routing import ROUTE_FIELDS
from .selection import selection_input
from .workflows import absolute, next_walk, relative, result, validate_action, verify_walk

ROUTE = ROUTE_FIELDS


def validate_interaction(action):
    kind = action["type"]
    required = {"use_stairs": {"x", "y", "z", "direction"}, "end_conversation": set()}.get(
        kind, {"unit_id"}
    )
    optional = {
        "talk": {"topic", "choice_id", "completion", "subject_hf_id", "tact"},
        "combat": {"option_id"},
    }.get(kind, set())
    route = ROUTE if kind != "end_conversation" else set()
    if required - action.keys() or action.keys() - required - optional - route - {"type"}:
        raise ValueError("Missing or unknown fields for " + kind)
    for key in required - {"direction"}:
        if type(action[key]) is not int or not 0 <= action[key] <= 2147483647:
            raise ValueError(key + " must be a nonnegative integer")
    if kind == "use_stairs" and action["direction"] not in ("up", "down"):
        raise ValueError("direction must be up or down")
    if "topic" in action and "choice_id" in action:
        raise ValueError("Supply a topic or choice_id, not both")
    if "tact" in action and not ("topic" in action or "choice_id" in action):
        raise ValueError("tact requires a topic or choice_id")
    if "subject_hf_id" in action and (
        action.get("topic") not in ("AskAboutHf", "AskForDirectionsToHf")
        or type(action["subject_hf_id"]) is not int
        or not 0 <= action["subject_hf_id"] <= 2147483647
    ):
        raise ValueError("subject_hf_id requires an HF topic and a nonnegative integer")
    if "completion" in action and (
        action["completion"] not in ("utterance", "reply")
        or not ("topic" in action or "choice_id" in action)
    ):
        raise ValueError(
            "talk.completion requires a topic/choice_id and must be utterance or reply"
        )
    for key in (optional - {"subject_hf_id"}) & action.keys():
        if not isinstance(action[key], str) or not 0 < len(action[key]) <= 1000:
            raise ValueError(key + " must be a nonempty string of at most 1000 characters")
    validate_action(
        {"type": "walk_to", "x": 0, "y": 0, "z": 0, **{k: action[k] for k in ROUTE & action.keys()}}
    )


def signature(menu):
    return (
        menu.get("open"),
        menu.get("selecting"),
        menu.get("selecting_tact"),
        menu.get("mode"),
        menu.get("activity_id"),
        menu.get("target_unit_id"),
        menu.get("filter"),
        menu.get("entering_filter"),
        menu.get("scroll"),
        [o["id"] for o in menu.get("options", [])],
    )


def send(action, pending):
    return {"input": action, "pending": pending}


def choose(menu, options, view, pending_kind):
    if len(options) != 1:
        return result(
            "needs_input",
            "The requested option is absent or ambiguous.",
            {"matches": len(options), "options": menu.get("options", [])},
        )
    o = options[0]
    if menu.get("selection_unavailable"):
        return result("needs_input", menu["selection_unavailable"], menu)
    selected = selection_input(menu, o, "select_interaction")
    if "outcome" in selected:
        return selected
    if selected["type"] == "select_interaction":
        return send(
            selected,
            {
                "kind": pending_kind,
                "menu": signature(menu),
                "option_id": o["id"],
                "report_cursor": max((e["id"] for e in view.get("reports", [])), default=-1),
                "activity_id": menu.get("activity_id"),
                "activity_event_id": menu.get("activity_event_id"),
                "turn_cursor": menu.get("activity", {}).get("turn_count"),
                "native_type": o.get("native_type"),
            },
        )
    return send(
        selected,
        {"kind": "scroll", "menu": signature(menu)},
    )


def approach(view, target, action, ctx):
    if not view["status"].get("can_move"):
        return result("needs_input", "Approaching the target requires the local adventure view.")
    return next_walk(view, target, action, arrival_radius=1, context=ctx)


def next_interaction(workflow, view):
    action, ctx = workflow["action"], workflow.setdefault("context", {})
    kind = action["type"]
    if action.get("blocked_tiles") and view["status"].get("position"):
        excluded = ctx.setdefault(
            "blocked_absolute", [absolute(view, p) for p in action["blocked_tiles"]]
        )
        action = dict(action, blocked_tiles=[relative(view, p) for p in excluded])
    pending = ctx.pop("pending", None)
    if pending and pending["kind"] == "walk" and (blocker := verify_walk(pending, view)):
        return blocker
    if kind == "use_stairs":
        return stairs(action, ctx, view)
    menu = view.get("conversation" if kind in ("talk", "end_conversation") else "combat") or {}
    if (
        pending
        and pending["kind"] in ("scroll", "close", "open", "target", "navigate_topic", "tact")
        and signature(menu) == pending["menu"]
    ):
        return result("no_effect", "The interaction menu did not change; no input was repeated.")
    if kind == "end_conversation":
        if not menu.get("open", bool(menu)):
            return result("completed", "Conversation interface is closed.")
        return send(
            {"type": "key", "key": "LEAVESCREEN"}, {"kind": "close", "menu": signature(menu)}
        )

    unit_id = action["unit_id"]
    if pending and pending["kind"] == "topic":
        ctx["topic_sent"] = pending
    if ctx.get("topic_sent"):
        if menu.get("selecting_tact"):
            return next_tact(action, ctx, view, menu)
        return await_speech(action, ctx, view, menu, pending)
    if pending and pending["kind"] == "combat_choice":
        ctx["combat_choice_sent"] = pending
    if ctx.get("combat_choice_sent"):
        # Opening a further combat decision is observable, but not a completed
        # strike. Subsequent tactics are always supplied by the controller.
        return result(
            "needs_input",
            "Combat selection was sent; another native decision or unverified effect remains.",
            dict(menu, blocker_kind="unsupported", completion="attack_not_verified"),
        )

    active = bool(menu) and menu.get("open", True)
    selected = (
        (unit_id in menu.get("participants", []) and not menu.get("selecting"))
        if kind == "talk"
        else (
            menu.get("target_unit_id") == unit_id
            and menu.get("mode") not in ("UNIT_CHOICE", "CONFIRM")
        )
    )
    if active and selected:
        if kind == "talk" and menu.get("selecting_tact"):
            return next_tact(action, ctx, view, menu)
        if menu.get("selection_unavailable"):
            return result(
                "needs_input",
                menu.get("selection_unavailable", "The game requires a conversation tact."),
                menu,
            )
        if kind == "talk":
            choice_id, topic = action.get("choice_id"), action.get("topic")
            if choice_id is None and topic is None:
                return result(
                    "completed", "Conversation with the requested unit is open; choose a topic."
                )
            options = (
                [o for o in menu.get("options", []) if choice_id in (o["id"], o.get("handle"))]
                if choice_id
                else [
                    o
                    for o in menu.get("options", [])
                    if o.get("label") == topic or o.get("native_type") == topic
                ]
            )
            activity = menu.get("activity", {})
            if "subject_hf_id" in action:
                options = [o for o in options if o.get("subject_hf_id") == action["subject_hf_id"]]
            if not options and topic:
                # An explicit topic determines this navigation step. Returning
                # to the main menu is not a substitute topic or a risk decision.
                # Each navigation edge is attempted once. BypassGreeting is
                # DF's explicit menu-only alternative to making a greeting.
                navigated = ctx.setdefault("navigated_topics", [])
                parents = [
                    o["native_type"]
                    for o in menu.get("options", [])
                    if topic in o.get("opens_topics", [])
                ]
                for native_type in (*parents, "ReturnToMain", "BypassGreeting"):
                    back = [
                        o for o in menu.get("options", []) if o.get("native_type") == native_type
                    ]
                    if len(back) == 1 and native_type not in navigated:
                        decision = choose(menu, back, view, "navigate_topic")
                        if decision.get("pending", {}).get("kind") == "navigate_topic":
                            navigated.append(native_type)
                        return decision
            if not activity.get("available") or menu.get("activity_event_id") is None:
                return result(
                    "needs_input",
                    "Native conversation turns are unavailable; topic completion cannot be verified.",
                    {"blocker_kind": "unsupported", "unit_id": unit_id},
                )
            if action.get("tact") and len(options) == 1 and not options[0].get("tact_required"):
                return result(
                    "needs_input",
                    "The requested topic has no verified tact choice; it was not sent.",
                    {
                        "blocker_kind": "tact_unavailable",
                        "facts": {"topic": options[0].get("native_type"), "tact": action["tact"]},
                    },
                )
            return choose(menu, options, view, "topic")
        if action.get("option_id"):
            return choose(
                menu,
                [
                    o
                    for o in menu.get("options", [])
                    if action["option_id"] in (o["id"], o.get("handle"))
                ],
                view,
                "combat_choice",
            )
        return result(
            "completed", "Combat menu targets the requested unit; no attack has been requested."
        )
    if active:
        picker = menu.get("selecting") if kind == "talk" else menu.get("mode") == "UNIT_CHOICE"
        if not picker:
            return result(
                "needs_input",
                "The open interaction requires a different target, confirmation or undelegated choice.",
                menu,
            )
        options = [
            o
            for o in menu.get("options", [])
            if o.get("unit_id") == unit_id or unit_id in o.get("participants", [])
        ]
        if kind == "talk" and not options:
            # DF's picker lists existing conversations, not every nearby unit.
            # The existing primitive rechecks visibility, viewport and UI overlap
            # before clicking the requested creature; the next pass verifies its ID.
            if ctx.get("map_target_sent"):
                return result(
                    "needs_input",
                    "The clicked creature did not become a selectable conversation target.",
                    menu,
                )
            ctx["map_target_sent"] = True
            return send(
                {"type": "select_unit", "unit_id": unit_id},
                {"kind": "target", "menu": signature(menu)},
            )
        return choose(menu, options, view, "target")
    if pending and pending["kind"] in ("open", "target"):
        return result("no_effect", "The requested interaction did not open.")
    target = view.get("target_unit") or next(
        (u for u in (view.get("map") or {}).get("units", []) if u["id"] == unit_id), None
    )
    if not target or target.get("id") != unit_id or not target.get("position"):
        return result(
            "needs_input", "The specified unit is not currently visible.", {"unit_id": unit_id}
        )
    decision = approach(view, target["position"], action, ctx)
    if decision.get("outcome") != "completed":
        return decision
    return send(
        {"type": "key", "key": "A_TALK" if kind == "talk" else "A_ATTACK"},
        {"kind": "open", "menu": signature(menu)},
    )


def next_tact(action, ctx, view, menu):
    """Complete only the requested pending topic, using the delegated native tact."""
    topic, sent = menu.get("tact_topic", {}), ctx.get("topic_sent")
    facts = {"unit_id": action["unit_id"], "topic": topic.get("native_type")}
    if sent:
        matches = (
            sent.get("option_id") == topic.get("id")
            and sent.get("activity_id") == menu.get("activity_id")
            and sent.get("activity_event_id") == menu.get("activity_event_id")
        )
    else:
        matches = (
            action.get("topic") is not None
            and action["topic"] in (topic.get("native_type"), topic.get("label"))
        ) or (action.get("choice_id") is not None and action["choice_id"] == topic.get("id"))
    if not matches or action["unit_id"] not in menu.get("participants", []):
        return result(
            "needs_input",
            "The pending tact belongs to a different or unverified conversation topic.",
            {"blocker_kind": "topic_changed", "facts": facts},
        )
    if menu.get("selection_unavailable"):
        return result("needs_input", menu["selection_unavailable"])
    if not action.get("tact"):
        return result(
            "needs_input",
            "The requested topic requires a tact; choose one explicitly.",
            {"blocker_kind": "controller_choice", "facts": facts},
        )
    if ctx.get("tact_sent"):
        return result(
            "no_effect",
            "The selected tact has not produced an utterance; it was not repeated.",
            {"blocker_kind": "verification", "facts": facts},
        )
    activity = menu.get("activity", {})
    if not activity.get("available") or menu.get("activity_event_id") is None:
        return result(
            "needs_input",
            "Native conversation turns are unavailable; tact completion cannot be verified.",
            {"blocker_kind": "verification", "facts": facts},
        )
    decision = choose(
        menu,
        [o for o in menu.get("options", []) if o.get("native_type") == action["tact"]],
        view,
        "tact",
    )
    if decision.get("pending", {}).get("kind") == "tact":
        ctx["tact_sent"] = action["tact"]
        if sent is None:
            # A fresh dispatch may continue an already-open tact decision. Its
            # requested native topic must match before the cursor is adopted.
            ctx["topic_sent"] = dict(
                decision["pending"],
                kind="topic",
                option_id=topic["id"],
                native_type=topic["native_type"],
            )
    return decision


def await_speech(action, ctx, view, menu, pending):
    decision = verify_speech(action, ctx, view, menu, pending)
    awaiting = {
        "condition": action.get("completion", "reply"),
        "unit_id": action["unit_id"],
        "utterance_verified": bool(ctx.get("utterance")),
    }
    target = view.get("target_unit") or {}
    if target.get("id") == action["unit_id"]:
        health = target.get("health", {})
        if "unconscious" in health:
            awaiting["listener_unconscious"] = health["unconscious"]
        if "health_unavailable" in target:
            awaiting["listener_state_unavailable"] = target["health_unavailable"]
    decision["progress"] = {"awaiting": awaiting}
    if ctx.get("utterance"):
        sent = ctx["topic_sent"]
        # A gesture/refusal may be an attributed report without a native speech
        # turn. Preserve it for the controller without calling it a spoken reply.
        decision["task_event_ids"] = [
            e["id"]
            for e in view.get("reports", [])
            if e["id"] > sent["report_cursor"]
            and e.get("activity_id") == sent["activity_id"]
            and e.get("activity_event_id") == sent["activity_event_id"]
            and e.get("speaker_id") == action["unit_id"]
        ]
    return decision


def verify_speech(action, ctx, view, menu, pending):
    """Wait for factual speech postconditions, never select another topic."""
    sent = ctx["topic_sent"]
    activity = view.get("conversation_activity") or menu.get("activity", {})
    if (
        not activity.get("available")
        or activity.get("activity_id") != sent["activity_id"]
        or activity.get("activity_event_id") != sent["activity_event_id"]
    ):
        return result(
            "needs_input",
            "The selected conversation can no longer be verified; selection will not be repeated.",
            {"blocker_kind": "verification", "activity": activity},
        )
    turns = activity.get("turns", [])
    if "utterance" not in ctx:
        if activity.get("turns_omitted", 0) > sent["turn_cursor"]:
            return result(
                "needs_input",
                "Native turn history was truncated before the selected utterance could be verified.",
                {
                    "blocker_kind": "verification",
                    "activity_id": sent["activity_id"],
                    "activity_event_id": sent["activity_event_id"],
                },
            )
        ctx["utterance"] = next(
            (
                t
                for t in turns
                if t["index"] >= sent["turn_cursor"]
                and t["speaker_id"] == view["status"].get("adventurer_id")
                and t.get("native_type") == sent["native_type"]
            ),
            None,
        )
        if ctx["utterance"] is None:
            ctx.pop("utterance")
            return result(
                "needs_input",
                "The selected topic has no verified player utterance; a further conversation choice may be required.",
                {"blocker_kind": "controller_choice", "options": menu.get("options", [])},
            )
    utterance = ctx["utterance"]
    events = [
        e
        for e in view.get("reports", [])
        if e["id"] > sent["report_cursor"]
        and e.get("activity_id") == sent["activity_id"]
        and e.get("activity_event_id") == sent["activity_event_id"]
    ]
    details = {
        "unit_id": action["unit_id"],
        "topic": action.get("topic"),
        "completion": action.get("completion", "reply"),
        "utterance": utterance,
        "activity_id": sent["activity_id"],
        "activity_event_id": sent["activity_event_id"],
        "conversation_reports": events,
    }
    if details["completion"] == "utterance":
        return result(
            "completed",
            "The requested player utterance was verified in the native conversation.",
            details,
        )
    if activity.get("turns_omitted", 0) > utterance["index"] + 1:
        return result(
            "needs_input",
            "Native turn history was truncated before reply verification.",
            dict(details, blocker_kind="verification"),
        )
    reply = next(
        (
            t
            for t in turns
            if t["index"] > utterance["index"] and t["speaker_id"] == action["unit_id"]
        ),
        None,
    )
    if reply:
        our_reports = [
            e["id"] for e in events if e.get("speaker_id") == view["status"].get("adventurer_id")
        ]
        if not our_reports:
            return result(
                "needs_input",
                "Native speech is verified, but the player report is missing; reply text cannot be attributed reliably.",
                dict(details, blocker_kind="verification"),
            )
        replies = [
            e
            for e in events
            if e.get("speaker_id") == action["unit_id"] and e["id"] > min(our_reports)
        ]
        if replies:
            details.update(reply=reply, replies=replies)
            return result(
                "completed",
                "The target spoke after the requested utterance; its conversation reports were collected.",
                details,
            )
    if action["unit_id"] not in activity.get("participants", []):
        return result(
            "needs_input",
            "The requested listener left the conversation before a reply was verified.",
            dict(details, blocker_kind="target_unavailable"),
        )
    if menu.get("open"):
        if menu.get("selecting_tact") or menu.get("selecting") or menu.get("entering_filter"):
            return result(
                "needs_input",
                "Waiting for a reply requires an undelegated conversation choice.",
                dict(details, blocker_kind="controller_choice", options=menu.get("options", [])),
            )
        return send(
            {"type": "key", "key": "LEAVESCREEN"}, {"kind": "close", "menu": signature(menu)}
        )
    if not view["status"].get("can_move"):
        return result(
            "needs_input",
            "Waiting for the reply requires the local adventure input view.",
            dict(details, blocker_kind="controller_choice"),
        )
    clock = [view["status"].get(k) for k in ("year", "year_tick", "world_frame")]
    if pending and pending["kind"] == "reply_wait" and pending["clock"] == clock:
        return result(
            "no_effect", "The reply wait did not advance the game; no wait was repeated.", details
        )
    return send({"type": "wait"}, {"kind": "reply_wait", "clock": clock})


def stairs(action, ctx, view):
    p = view["status"].get("position")
    if p is None:
        return result("needs_input", "Stair movement requires a loaded local map.")
    source = {k: action[k] for k in ("x", "y", "z")}
    anchor = ctx.setdefault("stairs_source", absolute(view, source))
    target = relative(view, anchor)
    if ctx.get("stairs_sent"):
        expected = dict(anchor, z=anchor["z"] + (1 if action["direction"] == "up" else -1))
        if absolute(view, p) == expected:
            return result("completed", "Stair traversal reached the requested adjacent z-level.")
        return result(
            "no_effect",
            "Stair input did not reach the expected tile; inspect the reports and blockers.",
            {"expected_absolute_position": expected, "actual_absolute_position": absolute(view, p)},
        )
    if not view["status"].get("can_move"):
        return result("needs_input", "Stair movement requires the local adventure input view.")
    landmark = next(
        (t for t in (view.get("map") or {}).get("landmarks", []) if t["position"] == target), None
    )
    shapes = {"STAIR_UPDOWN", "STAIR_UP" if action["direction"] == "up" else "STAIR_DOWN"}
    if not landmark or landmark.get("shape") not in shapes:
        return result(
            "needs_input",
            "The requested tile is not an observed stair in that direction.",
            {"tile": target, "landmark": landmark},
        )
    if p != target:
        return next_walk(view, target, action, context=ctx)
    ctx["stairs_sent"] = True
    return {"input": {"type": "move", "direction": action["direction"]}}
