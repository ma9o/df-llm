"""Verified directional movement and one native short wait, usable in sequences."""

from copy import deepcopy

from .pathing import next_native_walk
from .workflows import absolute, relative, result

DIRECTIONS = {
    "n": (0, -1, 0),
    "s": (0, 1, 0),
    "e": (1, 0, 0),
    "w": (-1, 0, 0),
    "ne": (1, -1, 0),
    "nw": (-1, -1, 0),
    "se": (1, 1, 0),
    "sw": (-1, 1, 0),
    "up": (0, 0, 1),
    "down": (0, 0, -1),
}


def validate(action):
    if action["type"] == "wait":
        if set(action) != {"type"}:
            raise ValueError("wait requires only type; use rest for a duration")
    elif (
        set(action) != {"type", "direction"}
        or not isinstance(action.get("direction"), str)
        or action["direction"] not in DIRECTIONS
    ):
        raise ValueError("move requires a direction: n, s, e, w, ne, nw, se, sw, up, down")


def clock(status):
    # A short wait advances one simulation frame; the calendar can remain
    # unchanged. Frame comparisons are valid only in the same loaded map.
    if type(status.get("world_frame")) is int and status.get("local_map_epoch") is not None:
        return {
            "kind": "frame",
            "value": status["world_frame"],
            "local_map_epoch": status.get("local_map_epoch"),
        }
    if all(type(status.get(k)) is int for k in ("year", "year_tick")):
        return {"kind": "calendar", "value": [status["year"], status["year_tick"]]}
    return None


def next_locomotion(workflow, view):
    action, ctx, status = workflow["action"], workflow.setdefault("context", {}), view["status"]
    pending = ctx.get("locomotion_pending")
    if action["type"] == "wait":
        now = clock(status)
        if pending:
            before = pending["clock"]
            compatible = (
                now
                and now["kind"] == before["kind"]
                and now.get("local_map_epoch") == before.get("local_map_epoch")
            )
            if compatible and now["value"] > before["value"]:
                return result("completed", "Native short wait advanced game time and settled.")
            return result(
                "no_effect",
                "The short wait has no verified time advance; its input was not repeated.",
                {"blocker_kind": "wait_progress", "facts": {"clock": now, "started": before}},
            )
        if now is None:
            return result(
                "needs_input",
                "Native time is unavailable; a short wait cannot be verified.",
                {"blocker_kind": "wait_clock_unavailable", "facts": {"clock": None}},
            )
        pending = {"clock": now}
        planned = {"input": {"type": "wait"}}
    else:
        position = status.get("position")
        if not position or any(type(position.get(k)) is not int for k in ("x", "y", "z")):
            return result(
                "needs_input",
                "The local position is unavailable.",
                {"blocker_kind": "position_unavailable", "facts": {"position": position}},
            )
        if pending:
            if pending["origin_known"] != (status.get("map_origin") is not None):
                return result(
                    "needs_input",
                    "The movement coordinate frame is unavailable.",
                    {
                        "blocker_kind": "coordinate_frame_changed",
                        "facts": {"destination": pending["destination"]},
                    },
                )
            actual = absolute(view, position)
            if actual == pending["destination"]:
                return result("completed", "Directional movement reached the requested tile.")
            evidence = view.get("input_evidence") or {}
            if (
                pending.get("native_path")
                and status.get("can_move")
                and evidence.get("kind") == "walk"
                and evidence.get("available") is True
                and evidence.get("phase") == "paused"
            ):
                # A verified pause ended the previous owned goal. The shared
                # policy may continue toward the same target with a fresh goal;
                # absent/uncertain evidence must never authorize another input.
                continuation = next_native_walk(
                    view, relative(view, pending["destination"]), {}, 0, ctx
                )
                if continuation is not None:
                    return continuation
            return result(
                "no_effect",
                "The requested tile was not reached; the movement input was not repeated.",
                {
                    "blocker_kind": "movement_progress",
                    "facts": {
                        "destination": pending["destination"],
                        "position": actual,
                        "direction": action["direction"],
                        "native_path": view.get("input_evidence"),
                    },
                },
            )
        destination = {
            k: position[k] + delta
            for k, delta in zip(("x", "y", "z"), DIRECTIONS[action["direction"]], strict=True)
        }
        pending = {
            "destination": absolute(view, destination),
            "origin_known": status.get("map_origin") is not None,
        }
        planned = next_native_walk(view, relative(view, pending["destination"]), {}, 0, ctx)
        if planned is None:
            planned = {"input": deepcopy(action)}
        if "outcome" in planned:
            return planned
        pending["native_path"] = planned["input"]["type"] == "path_to"
    if not status.get("can_move"):
        return result(
            "needs_input",
            "Movement and short waits require the local adventure input view.",
            {
                "blocker_kind": "local_input_unavailable",
                "facts": {"open_panels": status.get("open_panels")},
            },
        )
    ctx["locomotion_pending"] = pending
    return planned
