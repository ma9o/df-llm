"""Delegate an explicit rest duration and verify native calendar progress."""

from .selection import selection_input
from .workflows import close_menu, menu_signature, result


def validate_rest(action):
    hours = action.get("hours")
    if not (
        (set(action) == {"type", "hours"} and type(hours) is int and 1 <= hours <= 24)
        or (set(action) == {"type", "until"} and action["until"] == "dawn")
    ):
        raise ValueError("sleep/rest requires either hours in [1, 24] or until='dawn'")


def calendar(status, model):
    year, tick = status.get("year"), status.get("year_tick")
    if type(year) is int and type(tick) is int and 0 <= tick < model["calendar_ticks_per_year"]:
        return year * model["calendar_ticks_per_year"] + tick
    return None


def next_rest(workflow, view):
    action, ctx = workflow["action"], workflow.setdefault("context", {})
    state, status = view.get("rest", {}), view["status"]
    model = state.get("model")
    if not state.get("available") or not model:
        return result(
            "needs_input",
            "Native rest settings or calendar model are unavailable.",
            {"blocker_kind": "verification"},
        )
    now = calendar(status, model)
    if now is None:
        return result(
            "needs_input",
            "The native calendar is unavailable; duration cannot be verified.",
            {"blocker_kind": "verification"},
        )
    menu = view.get("menu")

    def refused(facts):
        return result(
            "needs_input",
            "The game refused to begin this rest; no retry was sent.",
            {"blocker_kind": "rest_restricted", "facts": facts},
        )

    if ctx.get("refused"):
        return refused(ctx["refused"])
    started = ctx.get("rest_started")
    until_dawn = action.get("until") == "dawn"
    dawn = state.get("dawn", {})
    if until_dawn and not (
        dawn.get("available") is True
        and type(dawn.get("remaining_calendar_ticks")) is int
        and 1 <= dawn["remaining_calendar_ticks"] <= 24 * model["calendar_ticks_per_hour"]
        and type(dawn.get("world_region_x")) is int
        and dawn["world_region_x"] >= 0
    ):
        return result(
            "needs_input",
            "The native dawn calculation is unavailable; no duration was substituted.",
            {"blocker_kind": "dawn_unavailable", "facts": dawn},
        )
    if started:
        elapsed = now - started["calendar"]
        if until_dawn and dawn.get("world_region_x") != started.get("world_region_x"):
            return result(
                "needs_input",
                "The character's longitude changed after rest was submitted; dawn was not recalculated.",
                {
                    "blocker_kind": "rest_location_changed",
                    "facts": {
                        "expected_world_region_x": started.get("world_region_x"),
                        "actual_world_region_x": dawn.get("world_region_x"),
                    },
                },
            )
        if (
            elapsed >= started["required_ticks"]
            and state.get("sleeping") == 0
            and not (menu and menu.get("kind") == "rest")
        ):
            value = {
                "kind": action["type"],
                **({"until": "dawn"} if until_dawn else {"hours": action["hours"]}),
                "elapsed_calendar_ticks": elapsed,
            }
            return result(
                "completed",
                "The configured rest finished and its requested calendar duration elapsed.",
                {
                    **({"until": "dawn"} if until_dawn else {"hours": action["hours"]}),
                    "sleep": action["type"] == "sleep",
                    "elapsed_calendar_ticks": elapsed,
                    "value": value,
                },
            )
        return result(
            "needs_input",
            "Rest ended before its requested duration was verified; it will not be restarted automatically.",
            {
                "blocker_kind": "rest_incomplete",
                "facts": {
                    "elapsed_calendar_ticks": elapsed,
                    "required_calendar_ticks": started["required_ticks"],
                    "native_interrupt": state.get("sleep_interrupt"),
                },
            },
        )
    pending = ctx.pop("pending", None)
    if pending:
        if "report_cursor" in pending and not (menu and menu.get("kind") == "rest"):
            denials = [
                e
                for e in view.get("reports", [])
                if e["id"] > pending["report_cursor"] and e.get("type") == "CANNOT_REST"
            ]
            if denials:
                event = denials[-1]
                ctx["refused"] = {
                    "report_id": event["id"],
                    "type": event["type"],
                    "message": event["text"],
                }
                return refused(ctx["refused"])
        expected = pending.get("expected")
        if expected and any(state.get(k) != v for k, v in expected.items()):
            return result(
                "no_effect",
                "The rest control did not produce its expected setting; input was not repeated.",
                {"blocker_kind": "verification", "expected": expected},
            )
        if not expected and pending["before"] == menu_signature(view):
            return result("no_effect", "The rest interface did not change; input was not repeated.")
    if not menu or menu.get("kind") != "rest":
        if menu:
            return close_menu(view)
        if not status.get("can_move") and not status.get("travel", {}).get("active"):
            return result("needs_input", "Rest requires the local or travel input view.")
        return {
            "input": {
                "type": "key",
                "key": "A_TRAVEL_SLEEP" if status.get("travel", {}).get("active") else "A_SLEEP",
            },
            "pending": {
                "before": menu_signature(view),
                "report_cursor": view.get(
                    "report_cursor", max((e["id"] for e in view.get("reports", [])), default=-1)
                ),
            },
        }
    if menu.get("selection_unavailable"):
        return result("needs_input", menu["selection_unavailable"])
    if until_dawn and menu.get("no_sky") is not False:
        return result(
            "needs_input",
            "The native rest interface does not offer an observed sky for until dawn.",
            {"blocker_kind": "dawn_unavailable", "facts": {"no_sky": menu.get("no_sky")}},
        )
    sleep = action["type"] == "sleep"
    expected = {}
    if state["sleep_sleep"] != sleep:
        control = "sleep" if sleep else "wait"
        expected["sleep_sleep"] = sleep
    elif until_dawn:
        control = "confirm" if state["sleep_until_dawn"] else "dawn"
        if control == "dawn":
            expected["sleep_until_dawn"] = True
    elif state["sleep_hours"] != action["hours"]:
        difference = action["hours"] - state["sleep_hours"]
        step = model["page_hours"] if abs(difference) >= model["page_hours"] else 1
        control = ("page_" if step > 1 else "") + ("more" if difference > 0 else "less")
        expected.update(
            sleep_hours=state["sleep_hours"] + (step if difference > 0 else -step),
            sleep_until_dawn=False,
        )
    elif state["sleep_until_dawn"]:
        control = "dawn"
        expected["sleep_until_dawn"] = False
    else:
        control = "confirm"
    options = [o for o in menu.get("options", []) if o.get("native_type") == control]
    if len(options) != 1:
        return result(
            "needs_input",
            "The requested rest control is unavailable.",
            {"blocker_kind": "controller_choice"},
        )
    selected = selection_input(menu, options[0], "select_option")
    if "outcome" in selected:
        return selected
    if control == "confirm" and selected["type"] == "select_option":
        ctx["rest_started"] = {
            "calendar": now,
            "required_ticks": dawn["remaining_calendar_ticks"]
            if until_dawn
            else action["hours"] * model["calendar_ticks_per_hour"],
        }
        if until_dawn:
            ctx["rest_started"]["world_region_x"] = dawn["world_region_x"]
        return {"input": selected}
    return {"input": selected, "pending": {"before": menu_signature(view), "expected": expected}}
