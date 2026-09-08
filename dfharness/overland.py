"""Overland travel routing: a coarse region plan, waypoint aiming and bounded sidesteps.

The world's region records give terrain type, elevation, temperature and the
rivers crossing each region. Ocean and lakes cannot be travelled; rivers are
thin lines with fords at their brook-like upstream stretches and ice where the
region is cold, so they are weighted, never walled off. The game still decides
every actual move; a refused move triggers a perpendicular sidestep search.
"""

import heapq

from .workflows import result

REGION_TILES = 48
IMPASSABLE = {"Ocean", "Lake"}  # Mountains are refused by the game as well
COLD_BELOW = 30  # region temperature parameter under which rivers are treated as ice
SIDESTEPS = (3, -3, 6, -6, 12, -12, 24, -24, 48, -48)
MAX_DETOURS = 24


EMBARK_TRAVEL_TILES = 3  # one overland travel move crosses one embark tile
WORLD_EMBARK_TILES = 16
DETAIL_CACHE: dict = {"epoch": None, "detail": None}


def cell_cost(cell, cold_below=COLD_BELOW):
    kind = cell.get("t")
    if kind in IMPASSABLE or kind == "Mountains":
        # The game refuses fast travel through mountains and over water.
        return None
    cost = 1.0
    if kind == "Glacier":
        cost += 1.0
    flow = cell.get("r")
    if flow is not None:
        temperature = cell.get("temp")
        if flow == 0:
            cost += 1.0  # brook or river source: fordable
        elif type(temperature) is int and temperature <= cold_below:
            cost += 1.5  # frozen: crossable ice, still a thin obstacle to probe
        else:
            cost += 4.0 + min(flow, 200) / 50.0
    return cost


def region_of(tile):
    return tile["x"] // REGION_TILES, tile["y"] // REGION_TILES


def plan(grid, start, goal, cold_below=COLD_BELOW):
    """Travel-tile waypoints from start to goal, or None when terrain seals the way."""
    rows, x0, y0 = grid["rows"], grid["x0"], grid["y0"]
    height, width = len(rows), len(rows[0]) if rows else 0

    def cell(rx, ry):
        cx, cy = rx - x0, ry - y0
        if 0 <= cy < height and 0 <= cx < width:
            return rows[cy][cx]
        return None

    origin, target = region_of(start), region_of(goal)
    if origin == target:
        return [[goal["x"], goal["y"]]]

    def heuristic(node):
        return max(abs(node[0] - target[0]), abs(node[1] - target[1]))

    best = {origin: 0.0}
    previous = {}
    queue = [(heuristic(origin), 0.0, origin)]
    while queue:
        _, cost, node = heapq.heappop(queue)
        if node == target:
            break
        if cost > best.get(node, float("inf")):
            continue
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if not dx and not dy:
                    continue
                nxt = (node[0] + dx, node[1] + dy)
                here = cell(*nxt)
                if here is None:
                    continue
                step = cell_cost(here, cold_below)
                if step is None:
                    continue
                total = cost + step * (1.4 if dx and dy else 1.0)
                if total < best.get(nxt, float("inf")):
                    best[nxt] = total
                    previous[nxt] = node
                    heapq.heappush(queue, (total + heuristic(nxt), total, nxt))
    if target not in best:
        return None
    path = [target]
    while path[-1] != origin:
        path.append(previous[path[-1]])
    path.reverse()
    waypoints = []
    for index in range(1, len(path) - 1):
        px, py = path[index - 1]
        x, y = path[index]
        nx, ny = path[index + 1]
        if (x - px, y - py) != (nx - x, ny - y):
            waypoints.append(
                [x * REGION_TILES + REGION_TILES // 2, y * REGION_TILES + REGION_TILES // 2]
            )
    waypoints.append([goal["x"], goal["y"]])
    return waypoints


def next_aim(action, ctx, view, position):
    """The tile to move toward now: a detour target, the current waypoint, or the destination."""
    target = {"x": action["x"], "y": action["y"]}
    if action.get("route", "auto") != "auto":
        return target, None
    detour = ctx.get("detour_target")
    if detour:
        if max(abs(detour[k] - position[k]) for k in ("x", "y")) <= 2:
            ctx.pop("detour_target")
        else:
            return detour, None
    if "overland_plan" not in ctx:
        origin, goal = region_of(position), region_of(target)
        if origin == goal:
            ctx["overland_plan"] = []
        else:
            grid = view.get("overland")
            if not grid:
                pad = 2
                ctx["overland_box"] = {
                    "x0": min(origin[0], goal[0]) - pad,
                    "y0": min(origin[1], goal[1]) - pad,
                    "x1": max(origin[0], goal[0]) + pad,
                    "y1": max(origin[1], goal[1]) + pad,
                }
                return target, {"input": {"type": "resume"}}
            if not grid.get("available"):
                return target, result(
                    "needs_input",
                    grid.get("reason", "The overland region records are unavailable."),
                    {"blocker_kind": "overland_unavailable"},
                )
            waypoints = plan(grid, position, target)
            ctx.pop("overland_box", None)
            if waypoints is None:
                return target, result(
                    "needs_input",
                    "No overland route reaches the destination without crossing ocean or lake.",
                    {
                        "blocker_kind": "overland_unreachable",
                        "facts": {"position": position, "destination": target},
                    },
                )
            ctx["overland_plan"] = waypoints
            ctx["waypoint"] = 0
    waypoints = ctx["overland_plan"]
    index = ctx.get("waypoint", 0)
    # Overland moves land on a lattice of whole embark tiles, so a waypoint
    # counts as reached from any tile touching its own.
    while (
        index < len(waypoints) - 1
        and max(abs(waypoints[index][0] - position["x"]), abs(waypoints[index][1] - position["y"]))
        <= 2 * EMBARK_TRAVEL_TILES - 1
    ):
        index += 1
    ctx["waypoint"] = index
    if waypoints and index < len(waypoints) - 1:
        return {"x": waypoints[index][0], "y": waypoints[index][1]}, None
    return target, None


def sidestep(ctx, position, pending, bounds):
    """A probe target after a refused move, or None when the budget is spent.

    Probes run perpendicular to the heading that was refused, at growing
    offsets on alternating sides of the tile where the refusal happened. The
    search continues from the same anchor while the heading stays blocked and
    is dropped as soon as a move toward the aim succeeds.
    """
    count = ctx.get("detours", 0)
    state: dict = ctx.get("sidestep") or {}
    if not state:
        direction = pending.get("direction", "")
        dx = ("E" in direction) - ("W" in direction)
        dy = ("S" in direction) - ("N" in direction)
        state = {"axis": "x" if abs(dy) >= abs(dx) else "y", "anchor": dict(position), "index": 0}
    axis: str = state["axis"]
    anchor: dict = state["anchor"]
    index: int = state["index"]
    limit = int(bounds.get(axis, 1 << 30))
    while index < len(SIDESTEPS) and count < MAX_DETOURS:
        offset = SIDESTEPS[index]
        index += 1
        count += 1
        target = {"x": int(anchor["x"]), "y": int(anchor["y"])}
        target[axis] = max(0, min(target[axis] + offset, max(0, limit - 1)))
        state["index"] = index
        if target != {"x": position["x"], "y": position["y"]}:
            ctx["sidestep"], ctx["detours"], ctx["detour_target"] = state, count, target
            return target
    state["index"] = index
    ctx["sidestep"], ctx["detours"] = state, count
    return None


def resolve_detail(view):
    """The embark-level terrain window from the view, or the cached copy it refers to."""
    detail = view.get("overland_detail")
    if not detail or not detail.get("available"):
        return None
    if detail.get("unchanged"):
        cached = DETAIL_CACHE.get("detail")
        return cached if cached and cached.get("epoch") == detail.get("epoch") else None
    DETAIL_CACHE["epoch"], DETAIL_CACHE["detail"] = detail.get("epoch"), detail
    return detail


def fine_step(detail, position, aim, cold_below=COLD_BELOW):
    """The next embark-tile move toward aim across the loaded terrain window.

    Returns None when the window does not cover the position. Otherwise a dict
    with ``progress`` (whether any reachable tile lies closer to the aim than
    the current one), ``direction`` as (dx, dy) in -1..1 for the first move of
    the shortest path to the closest reachable tile, and ``reaches`` when that
    tile is the aim's own.
    """
    tiles = {(t["x"], t["y"]): t for t in detail.get("tiles", [])}
    world, span = WORLD_EMBARK_TILES, EMBARK_TRAVEL_TILES

    def passable(ex, ey):
        tile = tiles.get((ex // world, ey // world))
        if tile is None or ex < 0 or ey < 0:
            return None
        char = tile["rows"][ey % world][ex % world]
        if char == ".":
            return True
        if char == "r":
            temperature = tile.get("temp")
            return type(temperature) is int and temperature <= cold_below
        return False

    start = (position["x"] // span, position["y"] // span)
    if passable(*start) is None:
        return None
    goal = (aim["x"] // span, aim["y"] // span)

    def gap(node):
        return max(abs(node[0] - goal[0]), abs(node[1] - goal[1]))

    parents: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    queue = [start]
    best = start
    while queue:
        node = queue.pop(0)
        if gap(node) < gap(best):
            best = node
        if node == goal:
            break
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nxt = (node[0] + dx, node[1] + dy)
                if (dx or dy) and nxt not in parents and passable(*nxt):
                    parents[nxt] = node
                    queue.append(nxt)
    if best == start:
        return {"progress": False, "reaches": False}
    node = best
    while (parent := parents[node]) is not None and parent != start:
        node = parent
    return {
        "progress": True,
        "reaches": best == goal,
        "direction": (node[0] - start[0], node[1] - start[1]),
    }


def heading(position, aim):
    dx, dy = aim["x"] - position["x"], aim["y"] - position["y"]
    return ("N" if dy < 0 else "S" if dy > 0 else "") + ("W" if dx < 0 else "E" if dx > 0 else "")
