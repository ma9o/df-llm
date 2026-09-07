"""Bounded route extension through observed tiles toward an explicit destination.

The caller delegates extension and supplies its usual route constraints. Unknown
tiles are never traversal edges. Reached frontiers and the current intermediate
destination are world coordinates so a resumed search survives local map shifts.
"""

DIRECTIONS = (
    (0, -1, "n"),
    (-1, -1, "nw"),
    (-1, 0, "w"),
    (-1, 1, "sw"),
    (0, 1, "s"),
    (1, 1, "se"),
    (1, 0, "e"),
    (1, -1, "ne"),
)
ROUTE_FIELDS = {"allow_occupied", "max_liquid_depth", "blocked_tiles", "extend_route"}
MAX_VISITED = 4096


def grid_available(m, field):
    grid, walkable = m.get(field), m["walkable"]
    return (
        isinstance(grid, list)
        and len(grid) == len(walkable)
        and all(
            isinstance(row, str) and len(row) == len(base)
            for row, base in zip(grid, walkable, strict=True)
        )
    )


def record_position(view, target, context):
    world = view["status"].get("map_origin") or {}

    def absolute(p):
        return [p[k] + world.get(k, 0) for k in ("x", "y", "z")]

    destination = absolute(target)
    state = context.setdefault("route", {})
    if state.get("destination") != destination:
        state.clear()
        state.update(destination=destination, visited=[])
    current = absolute(view["status"]["position"])
    if current not in state["visited"]:
        if len(state["visited"]) >= MAX_VISITED:
            return "route_search_limit"
        state["visited"].append(current)
    return None


def frontier_step(view, target, constraints, reachable, context):
    """Return a first step or a concrete search blocker, never a new objective."""
    m = view["map"]
    if not grid_available(m, "visible") or any(set(row) - {"0", "1"} for row in m["visible"]):
        return None, "visibility_grid_unavailable"
    visibility = m["visible"]
    origin, world = m["origin"], view["status"].get("map_origin") or {}

    state = context["route"]
    position = view["status"]["position"]
    current_z = position["z"] + world.get("z", 0)
    visited = {tuple(p) for p in state["visited"]}

    def local(p):
        return tuple(p[i] - world.get(k, 0) for i, k in enumerate(("x", "y")))

    def world_xy(p):
        return (p[0] + world.get("x", 0), p[1] + world.get("y", 0), current_z)

    previous = state.get("frontier")
    if previous is not None and tuple(previous) not in visited:
        planned = reachable.get(local(previous))
        if planned and planned[0] is not None:
            return planned[0], None
    state.pop("frontier", None)

    size = view["status"].get("map_size") or {}
    excluded = {
        (p["x"], p["y"]) for p in constraints.get("blocked_tiles", []) if p["z"] == position["z"]
    }

    def unknown(x, y):
        if x < 0 or y < 0 or x >= size.get("x", 2147483647) or y >= size.get("y", 2147483647):
            return False
        if (x, y) in excluded:
            return False
        ix, iy = x - origin["x"], y - origin["y"]
        return (
            not 0 <= iy < len(visibility)
            or not 0 <= ix < len(visibility[iy])
            or visibility[iy][ix] == "0"
        )

    frontiers = [
        p
        for p, (first, _) in reachable.items()
        if first is not None
        and world_xy(p) not in visited
        and any(unknown(p[0] + dx, p[1] + dy) for dx, dy, _ in DIRECTIONS)
    ]
    if not frontiers:
        return None, "no_unvisited_frontier"
    chosen = min(
        frontiers,
        key=lambda p: (
            max(abs(p[0] - target["x"]), abs(p[1] - target["y"])),
            reachable[p][1],
            p,
        ),
    )
    state["frontier"] = list(world_xy(chosen))
    return reachable[chosen][0], None
