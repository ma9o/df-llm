"""Observable action recipes. Decisions about objectives and risk belong to callers.

Recipes produce ordinary game inputs and verify their effects. They never move
items through DFHack mutation APIs or choose replacement equipment themselves.
"""

from collections import deque
from copy import deepcopy

from .routing import DIRECTIONS, ROUTE_FIELDS, frontier_step, grid_available, record_position
from .selection import next_selection, selection_input
from .state import all_items, contained_state, inventory, inventory_complete, item_value

SEMANTIC = {
    "pickup",
    "equip",
    "wield",
    "remove",
    "drop",
    "stow",
    "walk_to",
    "travel_to",
    "end_travel",
    "make_campfire",
    "thaw",
    "fill_container",
    "set_posture",
    "set_gait",
    "set_sneaking",
    "talk",
    "end_conversation",
    "use_stairs",
    "combat",
    "strike",
    "sequence",
    "converse",
    "drink",
    "drink_from",
    "eat",
    "sleep",
    "rest",
    "save_game",
    "empty_container",
}
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
    "select_interaction",
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


def validate_action(action):
    if not isinstance(action, dict) or action.get("type") not in SEMANTIC | PRIMITIVES:
        raise ValueError("Unknown action type")
    kind = action["type"]
    if kind == "strike":
        from .strike import validate_strike

        validate_strike(action)
        return
    if kind == "empty_container":
        from .storage import validate_empty

        validate_empty(action)
        return
    if kind == "save_game":
        from .saving import validate_save

        validate_save(action)
        return
    if kind in ("sleep", "rest"):
        from .rest import validate_rest

        validate_rest(action)
        return
    if kind in ("make_campfire", "thaw", "fill_container", "drink_from"):
        from .environment import validate_environment

        validate_environment(action)
        return
    if kind == "end_travel":
        if set(action) != {"type"}:
            raise ValueError("end_travel accepts no targets or options")
        return
    if kind in ("set_gait", "set_sneaking"):
        from .movement import validate_movement

        validate_movement(action)
        return
    if kind in ("drink", "eat"):
        target_key = "container_id" if kind == "drink" and "container_id" in action else "item_id"
        if (
            action.keys() - {"type", target_key, "portions"}
            or type(action.get(target_key)) is not int
            or not 0 <= action[target_key] <= 2147483647
        ):
            raise ValueError(
                kind
                + " requires one nonnegative item_id (or container_id for drink) and optional portions"
            )
        if type(action.get("portions", 1)) is not int or not 1 <= action.get("portions", 1) <= 32:
            raise ValueError(kind + ".portions must be an integer in [1, 32]")
        return
    if kind in ("sequence", "converse"):
        from .composition import validate_composite

        validate_composite(action)
        return
    if kind in ("talk", "end_conversation", "use_stairs", "combat"):
        from .interactions import validate_interaction

        validate_interaction(action)
        return
    if kind == "set_posture":
        if set(action) != {"type", "posture"} or action["posture"] not in ("standing", "prone"):
            raise ValueError("set_posture requires posture=standing or prone")
        return
    if kind == "travel_to":
        if action.keys() - {"type", "x", "y", "arrival_radius"}:
            raise ValueError("Unknown travel_to fields")
        for field in ("x", "y"):
            if type(action.get(field)) is not int or not 0 <= action[field] <= 2147483647:
                raise ValueError(field + " must be a nonnegative integer")
        radius = action.get("arrival_radius", 0)
        if type(radius) is not int or not 0 <= radius <= 48:
            raise ValueError("arrival_radius must be an integer in [0, 48]")
        return
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
            "select_interaction": ({"option_id"}, set()),
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
        allowed = {"type", "x", "y", "z", "arrival_radius"} | ROUTE_FIELDS
    if action.keys() - allowed:
        raise ValueError("Unknown action fields: " + ", ".join(sorted(action.keys() - allowed)))

    def integer(value, label):
        if type(value) is not int or not 0 <= value <= 2147483647:
            raise ValueError(label + " must be a nonnegative integer")

    for field in ("x", "y", "z") if kind == "walk_to" else ("item_id",):
        integer(action.get(field), field)
    radius = action.get("arrival_radius", 0)
    if type(radius) is not int or not 0 <= radius <= 48:
        raise ValueError("arrival_radius must be an integer in [0, 48]")
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
    for flag in ("allow_occupied", "extend_route"):
        if flag in action and type(action[flag]) is not bool:
            raise ValueError(flag + " must be boolean")
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


def absolute(view, p):
    origin = view["status"].get("map_origin", {})
    return {k: p[k] + origin.get(k, 0) for k in ("x", "y", "z")}


def relative(view, p):
    origin = view["status"].get("map_origin", {})
    return {k: p[k] - origin.get(k, 0) for k in ("x", "y", "z")}


def verify_walk(pending, view):
    """Verify movement, allowing a fresh constrained route after displacement."""
    p = view["status"].get("position")
    actual = absolute(view, p) if p else None
    expected = pending.get("absolute_destination")
    if actual == expected if expected is not None else p == pending["destination"]:
        return None
    source = pending.get("absolute_source")
    if actual and source and actual != source and actual["z"] == source["z"]:
        # The objective is the destination, not each planned intermediate tile.
        # The next planner call applies the caller's route constraints again.
        # Injury/report/unit interruptions have already been checked by dispatch.
        return None
    return result(
        "no_effect",
        "The movement input has no verified progress on this level.",
        {
            "expected": expected or pending["destination"],
            "actual": actual,
            "blocker_kind": "verification",
        },
    )


def next_walk(view, target, constraints, arrival_radius=0, *, context=None):
    start = view["status"].get("position")
    if start == target:
        return result("completed", "Reached the requested tile.")
    if not start or start["z"] != target["z"]:
        return result("needs_input", "Local walking supports the current z-level only.")
    if max(abs(start[k] - target[k]) for k in ("x", "y")) <= arrival_radius:
        return result("completed", "Reached the requested distance from the target.")
    m = view.get("map")
    if not m or "walkable" not in m:
        return result("needs_input", "No local walkability data is available.")
    origin = m["origin"]
    if origin["z"] != start["z"]:
        return result("needs_input", "The observed map is on another z-level.")
    if not grid_available(m, "liquid_depths"):
        return result(
            "needs_input",
            "Liquid depths are unavailable; route constraints cannot be verified.",
            {"blocker_kind": "liquid_depths_unavailable"},
        )
    if constraints.get("extend_route"):
        if context is None:
            return result("needs_input", "Route extension requires a resumable execution context.")
        if blocker := record_position(view, target, context):
            return result(
                "needs_input",
                "Route search reached its technical position limit.",
                {"blocker_kind": blocker},
            )
    start_xy, goal = (start["x"], start["y"]), (target["x"], target["y"])
    blocked = {
        (p["x"], p["y"]) for p in constraints.get("blocked_tiles", []) if p["z"] == start["z"]
    }
    if not constraints.get("allow_occupied", False):
        blocked |= {
            (u["position"]["x"], u["position"]["y"])
            for u in m.get("units", [])
            if u["id"] != view["status"].get("adventurer_id")
            and u.get("alive") is not False
            and u.get("position", {}).get("z") == start["z"]
        }
    allowed = set()
    for y, row in enumerate(m["walkable"]):
        for x, cell in enumerate(row):
            depth = m["liquid_depths"][y][x]
            p = (origin["x"] + x, origin["y"] + y)
            if (
                cell == "1"
                and depth.isdigit()
                and int(depth) <= constraints.get("max_liquid_depth", 7)
                and p not in blocked
            ):
                allowed.add(p)
    goals = {p for p in allowed if max(abs(p[0] - goal[0]), abs(p[1] - goal[1])) <= arrival_radius}
    exclusions = None
    if not goals:
        x, y = goal[0] - origin["x"], goal[1] - origin["y"]
        in_crop = 0 <= y < len(m["walkable"]) and 0 <= x < len(m["walkable"][y])
        occupants = [
            u
            for u in m.get("units", [])
            if u.get("position") == target and u.get("alive") is not False
        ]
        depth = m.get("liquid_depths", [])[y][x] if in_crop and m.get("liquid_depths") else None
        reasons = []
        visible = m.get("visible", [])
        observed = 0 <= y < len(visible) and 0 <= x < len(visible[y]) and visible[y][x] == "1"
        if not in_crop:
            reasons.append("outside_observed_map")
        elif m["walkable"][y][x] != "1":
            reasons.append("unwalkable" if observed else "unobserved_or_unwalkable")
        if occupants and not constraints.get("allow_occupied", False):
            reasons.append("occupied")
        if target in constraints.get("blocked_tiles", []):
            reasons.append("excluded_tile")
        if (
            depth is not None
            and depth.isdigit()
            and int(depth) > constraints.get("max_liquid_depth", 7)
        ):
            reasons.append("excluded_liquid_depth")
        elif depth is not None and not depth.isdigit() and m["walkable"][y][x] == "1":
            reasons.append("liquid_depth_unavailable")
        facts = {"destination": target, "exclusions": reasons}
        if occupants:
            facts["occupants"] = [
                {k: u[k] for k in ("id", "name", "position") if k in u} for u in occupants
            ]
        if terrain := (m.get("routing_window") or {}).get("target_tile"):
            facts["tile"] = terrain
        exclusions = result(
            "needs_input",
            "Destination is excluded from this route: " + ", ".join(reasons),
            {"blocker_kind": "route_excluded", "facts": facts},
        )
        # Extension may reveal a route, but cannot satisfy a known exclusion.
        if not constraints.get("extend_route"):
            return exclusions
        if arrival_radius == 0:
            unseen = 0 <= y < len(visible) and 0 <= x < len(visible[y]) and visible[y][x] == "0"
            if reasons != ["outside_observed_map"] and not (
                reasons == ["unobserved_or_unwalkable"] and unseen
            ):
                return exclusions
    queue: deque[tuple[tuple[int, int], tuple[int, int, str] | None]] = deque([(start_xy, None)])
    reachable = {start_xy: (None, 0)}
    step = None
    while queue:
        p, first = queue.popleft()
        if p in goals:
            assert first is not None
            step = first
            break
        for dx, dy, direction in DIRECTIONS:
            n = (p[0] + dx, p[1] + dy)
            if n in reachable or n not in allowed:
                continue
            next_first = first or (dx, dy, direction)
            reachable[n] = (next_first, reachable[p][1] + 1)
            queue.append((n, next_first))
    if step is None and constraints.get("extend_route"):
        assert context is not None
        step, blocker = frontier_step(view, target, constraints, reachable, context)
        if step is None:
            return result(
                "needs_input",
                "The observed route cannot be extended within the supplied constraints.",
                {"destination": target, "blocker_kind": blocker},
            )
    if step is not None:
        dx, dy, direction = step
        destination = {"x": start["x"] + dx, "y": start["y"] + dy, "z": start["z"]}
        return {
            "input": {"type": "move", "direction": direction},
            "pending": {
                "kind": "walk",
                "destination": destination,
                "absolute_source": absolute(view, start),
                "absolute_destination": absolute(view, destination),
            },
        }
    if exclusions:
        return exclusions
    return result(
        "needs_input",
        "No route through the currently observed walkable tiles satisfies the supplied constraints.",
    )


def tasks_for(action):
    kind, target = action["type"], action.get("item_id")
    if kind == "walk_to":
        return [
            {
                "kind": "walk_to",
                "target": {k: action[k] for k in ("x", "y", "z")},
                "arrival_radius": action.get("arrival_radius", 0),
            }
        ]
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
        start, target = view["status"].get("position"), task["target"]
        return (
            bool(start)
            and start["z"] == target["z"]
            and max(abs(start[k] - target[k]) for k in ("x", "y")) <= task.get("arrival_radius", 0)
        )
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
        m.get("context_item_id"),
        m.get("context_position"),
        m.get("scroll"),
        m.get("choosing_amount"),
        [o["id"] for o in m.get("options", [])],
    ]


def close_menu(view):
    return {
        "input": {"type": "key", "key": "LEAVESCREEN"},
        "pending": {"kind": "close", "before": menu_signature(view)},
    }


def site_travel_step(grid, p, target, radius):
    """Shortest mechanical route on DF's native directed site grid.

    Outside the current site, choose a reachable exit by path length plus
    remaining tile distance. This cost makes no assessment of creatures/risk.
    """
    ox, oy = grid["origin"]["x"], grid["origin"]["y"]
    w, h = grid["width"], grid["height"]
    start = (p["x"] - ox, p["y"] - oy)
    if not (0 <= start[0] < w and 0 <= start[1] < h):
        return None
    goal = (target["x"] - ox, target["y"] - oy)
    goal_inside = 0 <= goal[0] < w and 0 <= goal[1] < h
    bits = {"n": 1, "s": 2, "e": 4, "w": 8, "nw": 16, "sw": 32, "ne": 64, "se": 128}
    opposite = {
        "n": "s",
        "s": "n",
        "w": "e",
        "e": "w",
        "nw": "se",
        "se": "nw",
        "ne": "sw",
        "sw": "ne",
    }

    def mask(x, y):
        return int(grid["masks"][y][x * 2 : x * 2 + 2], 16)

    queue: deque[tuple[tuple[int, int], tuple[int, int, str] | None, int]] = deque(
        [(start, None, 0)]
    )
    seen, exits = {start}, []
    while queue:
        (x, y), first, length = queue.popleft()
        if max(abs(x - goal[0]), abs(y - goal[1])) <= radius:
            return first
        if grid["blocked"][y][x] == "1":
            continue
        source = mask(x, y)
        for dx, dy, direction in DIRECTIONS:
            if not source & bits[direction]:
                continue
            nx, ny = x + dx, y + dy
            step = first or (dx, dy, direction)
            if not (0 <= nx < w and 0 <= ny < h):
                if not goal_inside:
                    exits.append(
                        (length + 1 + max(abs(nx - goal[0]), abs(ny - goal[1])), length + 1, step)
                    )
                continue
            if (
                (nx, ny) in seen
                or grid["blocked"][ny][nx] == "1"
                or not mask(nx, ny) & bits[opposite[direction]]
            ):
                continue
            seen.add((nx, ny))
            queue.append(((nx, ny), step, length + 1))
    return min(exits, key=lambda e: (e[0], e[1]))[2] if exits else None


def next_travel(workflow, view):
    action, ctx = workflow["action"], workflow.setdefault("context", {})
    travel = view["status"].get("travel")
    if not travel:
        return result("needs_input", "Structured travel state is unavailable.")
    if action["type"] == "end_travel":
        if not travel.get("active"):
            if view["status"].get("map_loaded") and view.get("adventurer"):
                return result("completed", "Travel is closed and the local adventurer is loaded.")
            return result(
                "needs_input", "Travel is closed but the local adventurer is unavailable."
            )
        if ctx.get("end_sent"):
            return result("no_effect", "Travel did not close; input was not repeated.")
        ctx["end_sent"] = True
        return {"input": {"type": "key", "key": "A_END_TRAVEL"}}
    if not travel.get("active"):
        if ctx.get("travel_started") or ctx.get("travel_open_sent"):
            return result(
                "needs_input",
                "Travel ended before arrival; assess the current local state before starting another trip.",
                travel,
            )
        if not view["status"].get("can_move"):
            return result("needs_input", "Close the current interface before starting travel.")
        ctx["travel_open_sent"] = True
        return {"input": {"type": "key", "key": "A_TRAVEL"}}
    ctx["travel_started"] = True
    p = travel.get("position")
    if not p or p.get("z") != 0:
        return result(
            "needs_input", "This travel recipe requires a known surface travel position.", travel
        )
    bounds = travel.get("world_size", {})
    if any(action[k] >= bounds.get(k, 0) for k in ("x", "y")):
        return result("needs_input", "The destination is outside the travel map.")
    distance = max(abs(action["x"] - p["x"]), abs(action["y"] - p["y"]))
    if distance <= action.get("arrival_radius", 0):
        return result(
            "completed", "Arrival verified in travel coordinates; travel mode remains open."
        )
    pending = ctx.pop("travel_pending", None)
    if pending and p == pending["position"]:
        return result(
            "no_effect",
            "Travel did not advance. Supply another waypoint after inspecting the map or blocker.",
            travel,
        )
    if pending and pending.get("expected") and p != pending["expected"]:
        return result(
            "needs_input",
            "The site travel step reached different coordinates than expected.",
            travel,
        )
    if pending and not pending.get("expected") and distance >= pending["distance"]:
        return result(
            "needs_input",
            "Travel changed position without approaching the waypoint; inspect the observed coordinates.",
            {
                "blocker_kind": "travel_progress",
                "facts": {
                    "position": p,
                    "destination": {k: action[k] for k in ("x", "y")},
                    "previous_position": pending["position"],
                    "distance": distance,
                    "previous_distance": pending["distance"],
                    "site_zoom": travel.get("site_zoom"),
                },
            },
        )
    if pending and not pending.get("expected"):
        if (
            type(travel.get("site_zoom")) is bool
            and pending.get("site_zoom") == travel["site_zoom"]
        ):
            delta = [abs(p[k] - pending["position"][k]) for k in ("x", "y")]
            # Record observed movement granularity, scoped to the native zoom mode.
            # This avoids an immediate overshoot without changing the arrival radius.
            ctx["travel_stride"] = {"size": max(delta), "site_zoom": travel["site_zoom"]}
        else:
            ctx.pop("travel_stride", None)
    if travel.get("exception", {}).get("type") != "NONE":
        return result(
            "needs_input",
            "The game reports a travel restriction.",
            {"blocker_kind": "travel_restricted", "facts": travel.get("exception", {})},
        )
    grid = (view.get("navigation") or {}).get("site_grid")
    if grid:
        step = site_travel_step(grid, p, action, action.get("arrival_radius", 0))
        if step is None:
            return result(
                "needs_input",
                "No route to the destination or a site exit exists in the native travel grid.",
            )
        dx, dy, direction = step
        ctx["travel_pending"] = {
            "position": deepcopy(p),
            "distance": distance,
            "expected": {"x": p["x"] + dx, "y": p["y"] + dy, "z": p["z"]},
        }
        return {"input": {"type": "key", "key": "A_MOVE_" + direction.upper()}}
    dx, dy = action["x"] - p["x"], action["y"] - p["y"]
    direction = ("N" if dy < 0 else "S" if dy > 0 else "") + (
        "W" if dx < 0 else "E" if dx > 0 else ""
    )
    stride = ctx.get("travel_stride", {})
    if stride.get("size", 0) > 1 and stride.get("site_zoom") == travel.get("site_zoom"):
        size = stride["size"]
        projected = max(abs(d - (size if d > 0 else -size if d < 0 else 0)) for d in (dx, dy))
        if projected >= distance:
            return result(
                "needs_input",
                "The last native travel stride would overshoot this exact destination; no further move was sent.",
                {
                    "blocker_kind": "travel_resolution",
                    "facts": {
                        "position": p,
                        "destination": {k: action[k] for k in ("x", "y")},
                        "observed_stride": size,
                        "distance": distance,
                        "arrival_radius": action.get("arrival_radius", 0),
                        "site_zoom": travel.get("site_zoom"),
                    },
                },
            )
    ctx["travel_pending"] = {
        "position": deepcopy(p),
        "distance": distance,
        "site_zoom": travel.get("site_zoom"),
    }
    return {"input": {"type": "key", "key": "A_MOVE_" + direction}}


def next_step(workflow, view):
    action, ctx = workflow["action"], workflow.setdefault("context", {})
    kind = action["type"]
    if kind == "empty_container":
        from .storage import next_empty

        return next_empty(workflow, view)
    if kind == "strike":
        from .strike import next_strike

        return next_strike(workflow, view)
    if kind == "save_game":
        from .saving import next_save

        return next_save(workflow, view)
    if kind in ("sleep", "rest"):
        from .rest import next_rest

        return next_rest(workflow, view)
    if kind in ("select_option", "select_interaction"):
        return next_selection(workflow, view)
    if kind in ("make_campfire", "thaw", "fill_container", "drink_from"):
        from .environment import next_environment

        return next_environment(workflow, view)
    if kind in ("set_gait", "set_sneaking"):
        from .movement import next_movement

        return next_movement(workflow, view)
    if kind in ("drink", "eat"):
        from .consumption import next_consume

        return next_consume(workflow, view)
    if kind in ("sequence", "converse"):
        from .composition import next_composite

        return next_composite(workflow, view)
    if kind in ("talk", "end_conversation", "use_stairs", "combat"):
        from .interactions import next_interaction

        return next_interaction(workflow, view)
    if kind == "set_posture":
        from .movement import next_toggle

        return next_toggle(
            workflow,
            view,
            (view.get("adventurer") or {}).get("on_ground"),
            action["posture"] == "prone",
            "A_STANCE",
        )
    if kind in ("travel_to", "end_travel"):
        return next_travel(workflow, view)
    if kind not in SEMANTIC:
        if kind == "resume" or ctx.get("raw_sent"):
            return result(
                "completed", "Dispatch settled at a game input boundary; inspect the game outcome."
            )
        ctx["raw_sent"] = True
        return {"input": deepcopy(action)}
    tasks = ctx.setdefault("tasks", tasks_for(action))
    if kind != "walk_to" and "item_before" not in ctx:
        original = all_items(view).get(action["item_id"])
        if original is not None and "contents" in original:
            ctx["item_before"] = contained_state(original)
    if kind == "walk_to":
        target = tasks[0]["target"]
        anchor = ctx.setdefault("target_absolute", absolute(view, target))
        tasks[0]["target"] = relative(view, anchor)
        if action.get("blocked_tiles"):
            excluded = ctx.setdefault(
                "blocked_absolute", [absolute(view, p) for p in action["blocked_tiles"]]
            )
            action = dict(action, blocked_tiles=[relative(view, p) for p in excluded])
    index = ctx.setdefault("task_index", 0)
    pending = ctx.pop("pending", None)
    if pending:
        if pending["kind"] == "walk" and (blocker := verify_walk(pending, view)):
            return blocker
        if pending["kind"] == "scroll" and menu_signature(view) == pending["before"]:
            return result("no_effect", "The item list did not scroll; no selection was retried.")
        if pending["kind"] == "close" and menu_signature(view) == pending["before"]:
            return result("no_effect", "The menu did not close; the input was not repeated.")
        if pending["kind"] == "open" and not view.get("menu"):
            return result(
                "needs_input", "The game did not offer the requested inventory/pickup menu."
            )
        if pending["kind"] == "select" and index < len(tasks) and not satisfied(tasks[index], view):
            cursor = pending.get("report_cursor")
            refusals = [
                r
                for r in view.get("reports", [])
                if r.get("type") == "NO_GRASP_FOR_PICKUP"
                and type(cursor) is int
                and r.get("id", -1) > cursor
            ]
            if refusals:
                return result(
                    "needs_input",
                    "The game refused the pickup: no free grasp.",
                    {
                        "blocker_kind": "native_refusal",
                        "facts": {
                            "item_id": tasks[index]["item_id"],
                            "native_refusal": "NO_GRASP_FOR_PICKUP",
                            "report_id": refusals[-1]["id"],
                            "held_item_ids": sorted(
                                i["id"]
                                for i in inventory(view).values()
                                if i.get("mode") in ("Weapon", "Hauled")
                            ),
                        },
                    },
                )
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
        return result(
            "completed",
            "All requested item/location postconditions are verified.",
            {"value": item_value(action, view, ctx.get("item_before"))}
            if kind != "walk_to"
            else None,
        )
    task = tasks[index]
    if task["kind"] == "walk_to":
        if view.get("menu"):
            return close_menu(view)
        if not view["status"].get("can_move"):
            return result("needs_input", "Local walking requires the default adventure view.")
        return next_walk(view, task["target"], action, task.get("arrival_radius", 0), context=ctx)
    item = all_items(view).get(task["item_id"])
    if not item:
        return result(
            "needs_input",
            "The target item is absent from the current carried and nearby item readings.",
            {
                "blocker_kind": "item_unavailable",
                "facts": {
                    "item_id": task["item_id"],
                    "inventory_complete": inventory_complete(view),
                    "nearby_items_truncated": view.get("nearby_items_truncated", False),
                },
            },
        )
    # Removing worn equipment is a prerequisite of the controller's drop/stow
    # objective. Retain it as an ordinary checkpointed task under the same policy.
    # Never select or dispose of any other equipment to make room in the hands.
    if task["kind"] in ("drop", "stow") and item.get("mode") in ("Worn", "WrappedAround"):
        tasks.insert(index, {"kind": "remove", "item_id": task["item_id"]})
        return next_step(workflow, view)
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
            if task["kind"] == "drop" and (
                option.get("operation") == "empty_container" or option.get("details_unavailable")
            ):
                return result(
                    "needs_input",
                    "The native option empties the whole container; use an explicit empty_container objective."
                    if option.get("operation") == "empty_container"
                    else "The native drop effect is unavailable; no item was selected.",
                    {
                        "blocker_kind": "drop_effect",
                        "facts": {
                            "item_id": task["item_id"],
                            "container_id": option.get("container_id"),
                            "native_operation": option.get("operation"),
                            "details_unavailable": option.get("details_unavailable"),
                        },
                    },
                )
            selected = selection_input(menu, option, "select_option")
            if "outcome" in selected:
                return selected
            if selected["type"] == "select_option":
                return {
                    "input": selected,
                    "pending": {
                        "kind": "select",
                        "destination": bool(ctx.get("stow_destination")),
                        "report_cursor": view.get(
                            "report_cursor",
                            max((r.get("id", -1) for r in view.get("reports", [])), default=-1),
                        ),
                    },
                }
            return {
                "input": selected,
                "pending": {"kind": "scroll", "before": menu_signature(view)},
            }
        if menu.get("kind") == family and (
            ctx.get("opened_for") == [task["kind"], task["item_id"]] or ctx.get("stow_destination")
        ):
            return result(
                "needs_input",
                "The current native menu has no matching action for the requested item.",
                {
                    "blocker_kind": "item_action_unavailable",
                    "facts": {
                        "item_id": task["item_id"],
                        "operation": task["kind"],
                        "location": item.get("location"),
                        "mode": item.get("mode"),
                        "menu_context": menu.get("context"),
                        "matching_options": 0,
                    },
                },
            )
        return close_menu(view)
    if not view["status"].get("can_move"):
        return result(
            "needs_input",
            "Return to the default adventure view before starting this item operation.",
        )
    ctx["opened_for"] = [task["kind"], task["item_id"]]
    return {"input": {"type": "key", "key": key}, "pending": {"kind": "open"}}
