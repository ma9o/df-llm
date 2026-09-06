"""Observable action recipes. Decisions about objectives and risk belong to callers.

Recipes produce ordinary game inputs and verify their effects. They never move
items through DFHack mutation APIs or choose replacement equipment themselves.
"""

from collections import deque
from copy import deepcopy

from .state import all_items, inventory

SEMANTIC = {"pickup", "equip", "wield", "remove", "drop", "stow", "walk_to"}
PRIMITIVES = {
    "move",
    "wait",
    "dismiss",
    "resume",
    "action_prompt",
    "key",
    "click",
    "click_text",
    "text",
    "select_unit",
    "select_option",
}
PICKUP_KINDS = {
    "ENVIRONMENT_PICK_UP_GROUND_ITEM",
    "ENVIRONMENT_TAKE_ITEM_FROM_CONTAINER",
    "ENVIRONMENT_PICK_UP_BUILDING_ITEM",
    "ENVIRONMENT_PICK_UP_BUILDING_ITEM_CONTENTS",
}
MENU_ACTIONS = {
    "pickup": ("A_GROUND", PICKUP_KINDS, "option_list"),
    "wear": ("A_INV_WEAR", {"WEAR_ITEM"}, "inventory"),
    "remove": ("A_INV_REMOVE", {"REMOVE_ITEM"}, "inventory"),
    "wield": ("A_INV_REMOVE", {"REMOVE_ITEM"}, "inventory"),
    "drop": ("A_INV_DROP", {"DROP_ITEM"}, "inventory"),
    "stow": ("A_INV_PUTIN", {"PUT_ITEM"}, "inventory"),
}
DIRECTIONS = [
    (0, -1, "n"),
    (-1, -1, "nw"),
    (-1, 0, "w"),
    (-1, 1, "sw"),
    (0, 1, "s"),
    (1, 1, "se"),
    (1, 0, "e"),
    (1, -1, "ne"),
]


def validate_action(action):
    if not isinstance(action, dict) or action.get("type") not in SEMANTIC | PRIMITIVES:
        raise ValueError("Unknown action type")
    kind = action["type"]
    if kind not in SEMANTIC:
        required, optional = {
            "move": ({"direction"}, set()),
            "wait": (set(), set()),
            "dismiss": (set(), set()),
            "resume": (set(), {"dispatch_id"}),
            "action_prompt": ({"choice"}, set()),
            "key": ({"key"}, set()),
            "click": ({"x", "y"}, {"button"}),
            "click_text": ({"text"}, set()),
            "text": ({"text"}, set()),
            "select_unit": ({"unit_id"}, set()),
            "select_option": ({"option_id"}, set()),
        }[kind]
        if required - action.keys() or action.keys() - {"type"} - required - optional:
            raise ValueError("Missing or unknown fields for " + kind)
        for field in (required | optional) & action.keys():
            value = action[field]
            if field in ("x", "y", "unit_id"):
                if type(value) is not int or not 0 <= value <= 2147483647:
                    raise ValueError(field + " must be a nonnegative integer")
            elif not isinstance(value, str) or not value:
                raise ValueError(field + " must be a nonempty string")
        if kind == "move" and action["direction"] not in (
            "n",
            "s",
            "e",
            "w",
            "ne",
            "nw",
            "se",
            "sw",
            "up",
            "down",
        ):
            raise ValueError("Invalid movement direction")
        if kind == "action_prompt" and action["choice"] not in ("continue", "stop", "finish"):
            raise ValueError("Invalid action prompt choice")
        if kind == "click" and action.get("button", "left") not in ("left", "right", "middle"):
            raise ValueError("Invalid mouse button")
        if kind == "text" and (
            len(action["text"]) > 200 or any(not 32 <= ord(c) <= 126 for c in action["text"])
        ):
            raise ValueError("text must be 1..200 printable ASCII characters")
        if kind == "resume" and len(action.get("dispatch_id", "")) > 100:
            raise ValueError("dispatch_id must be at most 100 characters")
        return
    allowed = {"type", "item_id"}
    if kind in ("equip", "wield"):
        allowed |= {"replace", "disposition", "container_id", "body_part_id"}
    if kind == "stow":
        allowed.add("container_id")
    if kind == "walk_to":
        allowed = {"type", "x", "y", "z", "allow_occupied", "max_liquid_depth", "blocked_tiles"}
    if action.keys() - allowed:
        raise ValueError("Unknown action fields: " + ", ".join(sorted(action.keys() - allowed)))

    def integer(value, label):
        if type(value) is not int or not 0 <= value <= 2147483647:
            raise ValueError(label + " must be a nonnegative integer")

    for field in ("x", "y", "z") if kind == "walk_to" else ("item_id",):
        integer(action.get(field), field)
    if "body_part_id" in action:
        integer(action["body_part_id"], "body_part_id")
    if "container_id" in action:
        integer(action["container_id"], "container_id")
    replacement = action.get("replace", [])
    if not isinstance(replacement, list) or len(replacement) > 16:
        raise ValueError("replace must be a list of at most 16 item IDs")
    for item_id in replacement:
        integer(item_id, "replace item")
    if len(set(replacement)) != len(replacement) or action.get("item_id") in replacement:
        raise ValueError("Replacement IDs must be distinct and exclude the target")
    if action.get("disposition", "hold") not in ("hold", "drop", "stow"):
        raise ValueError("disposition must be hold, drop, or stow")
    if kind == "stow" or action.get("disposition") == "stow":
        integer(action.get("container_id"), "container_id")
        if action["container_id"] in [action["item_id"], *replacement]:
            raise ValueError("The destination container must differ from the equipment")
    if "allow_occupied" in action and type(action["allow_occupied"]) is not bool:
        raise ValueError("allow_occupied must be boolean")
    depth = action.get("max_liquid_depth", 7)
    if type(depth) is not int or not 0 <= depth <= 7:
        raise ValueError("max_liquid_depth must be in [0, 7]")
    tiles = action.get("blocked_tiles", [])
    if not isinstance(tiles, list) or len(tiles) > 500:
        raise ValueError("blocked_tiles must contain at most 500 coordinates")
    for tile in tiles:
        if not isinstance(tile, dict) or set(tile) != {"x", "y", "z"}:
            raise ValueError("Each blocked tile requires x, y, z")
        for coordinate in tile.values():
            integer(coordinate, "blocked coordinate")


def result(outcome, reason, details=None):
    answer = {"outcome": outcome, "reason": reason}
    if details is not None:
        answer["details"] = details
    return answer


def next_walk(view, target, constraints):
    start = view["status"].get("position")
    if start == target:
        return result("completed", "Reached the requested tile.")
    if not start or start["z"] != target["z"]:
        return result("needs_input", "Local walking supports the current z-level only.")
    m = view.get("map")
    if not m or "walkable" not in m:
        return result("needs_input", "No local walkability data is available.")
    origin = m["origin"]
    if origin["z"] != start["z"]:
        return result("needs_input", "The observed map is on another z-level.")
    start_xy, goal = (start["x"], start["y"]), (target["x"], target["y"])
    blocked = {
        (p["x"], p["y"]) for p in constraints.get("blocked_tiles", []) if p["z"] == start["z"]
    }
    if not constraints.get("allow_occupied", False):
        blocked |= {
            (u["position"]["x"], u["position"]["y"])
            for u in m.get("units", [])
            if u["id"] != view["status"].get("adventurer_id")
        }
    allowed = set()
    for y, row in enumerate(m["walkable"]):
        for x, cell in enumerate(row):
            depth = m.get("liquid_depths", ["0" * len(row)] * len(m["walkable"]))[y][x]
            p = (origin["x"] + x, origin["y"] + y)
            if (
                cell == "1"
                and depth.isdigit()
                and int(depth) <= constraints.get("max_liquid_depth", 7)
                and p not in blocked
            ):
                allowed.add(p)
    if goal not in allowed:
        x, y = goal[0] - origin["x"], goal[1] - origin["y"]
        in_crop = 0 <= y < len(m["walkable"]) and 0 <= x < len(m["walkable"][y])
        occupants = [u for u in m.get("units", []) if u.get("position") == target]
        depth = m.get("liquid_depths", [])[y][x] if in_crop and m.get("liquid_depths") else None
        reasons = []
        if not in_crop:
            reasons.append("outside_observed_map")
        elif m["walkable"][y][x] != "1":
            reasons.append("unobserved_or_unwalkable")
        if occupants and not constraints.get("allow_occupied", False):
            reasons.append("occupied")
        if target in constraints.get("blocked_tiles", []):
            reasons.append("excluded_tile")
        if depth is not None and (
            not depth.isdigit() or int(depth) > constraints.get("max_liquid_depth", 7)
        ):
            reasons.append("excluded_liquid_depth")
        return result(
            "needs_input",
            "Destination is excluded from this route: " + ", ".join(reasons),
            {"destination": target, "blockers": occupants, "route_exclusions": reasons},
        )
    queue: deque[tuple[tuple[int, int], tuple[int, int, str] | None]] = deque([(start_xy, None)])
    seen = {start_xy}
    while queue:
        p, first = queue.popleft()
        if p == goal:
            assert first is not None  # start and goal equality was handled above
            dx, dy, direction = first
            return {
                "input": {"type": "move", "direction": direction},
                "pending": {
                    "kind": "walk",
                    "destination": {"x": start["x"] + dx, "y": start["y"] + dy, "z": start["z"]},
                },
            }
        for dx, dy, direction in DIRECTIONS:
            n = (p[0] + dx, p[1] + dy)
            if n in seen or n not in allowed:
                continue
            seen.add(n)
            queue.append((n, first or (dx, dy, direction)))
    return result(
        "needs_input",
        "No route through the currently observed walkable tiles satisfies the supplied constraints.",
    )


def tasks_for(action):
    kind, target = action["type"], action.get("item_id")
    if kind == "walk_to":
        return [{"kind": "walk_to", "target": {k: action[k] for k in ("x", "y", "z")}}]
    if kind in ("equip", "wield"):
        tasks = [{"kind": "pickup", "item_id": target}]
        tasks += [{"kind": "remove", "item_id": i} for i in action.get("replace", [])]
        tasks += [
            {
                "kind": "wear" if kind == "equip" else "wield",
                "item_id": target,
                "body_part_id": action.get("body_part_id"),
            }
        ]
        disposition = action.get("disposition", "hold")
        if disposition != "hold":
            tasks += [
                {"kind": disposition, "item_id": i, "container_id": action.get("container_id")}
                for i in action.get("replace", [])
            ]
        return tasks
    return [{"kind": kind, "item_id": target, "container_id": action.get("container_id")}]


def satisfied(task, view):
    if task["kind"] == "walk_to":
        return view["status"].get("position") == task["target"]
    item = all_items(view).get(task["item_id"])
    if not item:
        return False
    carried = task["item_id"] in inventory(view)
    kind = task["kind"]
    if kind == "pickup":
        return carried
    if kind == "drop":
        return (
            not carried
            and item.get("location", {}).get("kind") == "ground"
            and item["location"].get("container_id") is None
        )
    if kind == "stow":
        return carried and item.get("location", {}).get("container_id") == task["container_id"]
    if kind in ("remove", "wield"):
        return (
            carried
            and item.get("mode") == "Weapon"
            and (
                task.get("body_part_id") is None or item.get("body_part_id") == task["body_part_id"]
            )
        )
    if kind == "wear":
        return (
            carried
            and item.get("mode") == "Worn"
            and (
                task.get("body_part_id") is None or item.get("body_part_id") == task["body_part_id"]
            )
        )
    return False


def menu_signature(view):
    m = view.get("menu") or {}
    return [
        m.get("kind"),
        m.get("context"),
        m.get("scroll"),
        [o["id"] for o in m.get("options", []) if o.get("visible")],
    ]


def close_menu(view):
    return {
        "input": {"type": "key", "key": "LEAVESCREEN"},
        "pending": {"kind": "close", "before": menu_signature(view)},
    }


def next_step(workflow, view):
    action, ctx = workflow["action"], workflow.setdefault("context", {})
    kind = action["type"]
    if kind not in SEMANTIC:
        if kind == "resume" or ctx.get("raw_sent"):
            return result(
                "completed", "Dispatch settled at a game input boundary; inspect the game outcome."
            )
        ctx["raw_sent"] = True
        return {"input": deepcopy(action)}
    tasks = ctx.setdefault("tasks", tasks_for(action))
    index = ctx.setdefault("task_index", 0)
    pending = ctx.pop("pending", None)
    if pending:
        if pending["kind"] == "walk" and view["status"].get("position") != pending["destination"]:
            return result(
                "no_effect", "The movement input did not reach the expected adjacent tile."
            )
        if pending["kind"] == "scroll" and menu_signature(view) == pending["before"]:
            return result("no_effect", "The item list did not scroll; no selection was retried.")
        if pending["kind"] == "close" and menu_signature(view) == pending["before"]:
            return result("no_effect", "The menu did not close; the input was not repeated.")
        if pending["kind"] == "open" and not view.get("menu"):
            return result(
                "needs_input", "The game did not offer the requested inventory/pickup menu."
            )
        if pending["kind"] == "select" and index < len(tasks) and not satisfied(tasks[index], view):
            if (view.get("menu") or {}).get("choosing_amount"):
                return result(
                    "needs_input",
                    "The game requires a pickup quantity; the item has not yet been acquired.",
                )
            # Put-in is a two-stage menu. The second stage chooses the caller's
            # specified destination; all other unverified selections stop.
            if (
                tasks[index]["kind"] != "stow"
                or pending.get("destination")
                or (view.get("menu") or {}).get("context_item_id") != tasks[index]["item_id"]
            ):
                return result(
                    "needs_input",
                    "The selected item action did not satisfy its inventory postcondition.",
                )
            ctx["stow_destination"] = True
    while index < len(tasks) and satisfied(tasks[index], view):
        index += 1
        ctx["task_index"] = index
        ctx.pop("stow_destination", None)
    if index == len(tasks):
        if view.get("menu"):
            return close_menu(view)
        return result("completed", "All requested item/location postconditions are verified.")
    task = tasks[index]
    if task["kind"] == "walk_to":
        if view.get("menu"):
            return close_menu(view)
        if not view["status"].get("can_move"):
            return result("needs_input", "Local walking requires the default adventure view.")
        return next_walk(view, task["target"], action)
    item = all_items(view).get(task["item_id"])
    if not item:
        return result(
            "needs_input",
            "Target item is not in the carried or visible nearby item state; it may have moved or the list may be truncated.",
        )
    if task["kind"] == "pickup":
        destination = item.get("location", {}).get("position")
        if not destination:
            return result("needs_input", "The target has no accessible ground position.")
        if destination != view["status"].get("position"):
            if view.get("menu"):
                return close_menu(view)
            if not view["status"].get("can_move"):
                return result("needs_input", "Pickup approach requires the default adventure view.")
            return next_walk(view, destination, {})
    elif task["item_id"] not in inventory(view):
        return result("needs_input", "The requested inventory item is no longer carried.")
    if task["kind"] == "stow" and task["container_id"] not in inventory(view):
        return result("needs_input", "The specified destination container is not carried.")
    key, kinds, family = MENU_ACTIONS[task["kind"]]
    menu = view.get("menu")
    if menu:
        if menu.get("choosing_amount"):
            return result(
                "needs_input",
                "The game requires a pickup quantity; the item has not yet been acquired.",
            )
        target = task["container_id"] if ctx.get("stow_destination") else task["item_id"]
        matches = [
            o
            for o in menu.get("options", [])
            if (
                ctx.get("stow_destination")
                and o.get("container_id") == target
                and o.get("kind") == "ENVIRONMENT_PLACE_IN_IT_CONTAINER"
            )
            or (
                not ctx.get("stow_destination")
                and o.get("item_id") == target
                and o.get("kind") in kinds
            )
        ]
        if matches:
            if len(matches) != 1:
                return result(
                    "needs_input",
                    "Multiple native actions match the item; choose the intended option explicitly.",
                )
            option = matches[0]
            if option.get("visible"):
                return {
                    "input": {"type": "select_option", "option_id": option["id"]},
                    "pending": {"kind": "select", "destination": bool(ctx.get("stow_destination"))},
                }
            direction = "PAGEUP" if option["index"] < menu.get("scroll", 0) else "PAGEDOWN"
            return {
                "input": {"type": "key", "key": "ADVENTURE_LIST_SCROLL_" + direction},
                "pending": {"kind": "scroll", "before": menu_signature(view)},
            }
        if menu.get("kind") == family and (
            ctx.get("opened_for") == [task["kind"], task["item_id"]] or ctx.get("stow_destination")
        ):
            return result(
                "needs_input",
                "The game does not offer this item action now; fit, capacity, conflicting equipment, or the current menu may prevent it.",
            )
        return close_menu(view)
    if not view["status"].get("can_move"):
        return result(
            "needs_input",
            "Return to the default adventure view before starting this item operation.",
        )
    ctx["opened_for"] = [task["kind"], task["item_id"]]
    return {"input": {"type": "key", "key": key}, "pending": {"kind": "open"}}
