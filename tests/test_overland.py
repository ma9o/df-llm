import unittest
from unittest.mock import patch

from dfharness.client import Client
from dfharness.overland import cell_cost, plan
from dfharness.workflows import validate_action
from tests.support import Bridge
from tests.test_navigation import travel_scene


def grid(rows, x0=0, y0=0):
    return {
        "available": True,
        "x0": x0,
        "y0": y0,
        "x1": x0 + len(rows[0]) - 1,
        "y1": y0 + len(rows) - 1,
        "rows": rows,
    }


def land(t="Grassland", **kw):
    return {"t": t, "e": 100, "temp": 20, **kw}


def wide(name, x, y):
    view = travel_scene(name, x=x, y=y)
    view["status"]["travel"]["world_size"] = {"x": 1000, "y": 1000}
    return view


class OverlandTests(unittest.TestCase):
    def test_costs_wall_off_water_and_weight_rivers_by_flow_and_cold(self):
        self.assertIsNone(cell_cost(land("Ocean")))
        self.assertIsNone(cell_cost(land("Lake")))
        self.assertEqual(cell_cost(land()), 1.0)
        self.assertLess(cell_cost(land(r=80, temp=10)), cell_cost(land(r=80, temp=60)))
        self.assertLess(cell_cost(land(r=0)), cell_cost(land(r=80, temp=60)))

    def test_plan_goes_around_an_ocean_wall_through_its_gap(self):
        rows = [[land() for _ in range(5)] for _ in range(5)]
        for y in range(4):
            rows[y][2] = land("Ocean")  # column 2 is sea except the bottom row
        waypoints = plan(grid(rows), {"x": 24, "y": 24}, {"x": 4 * 48 + 24, "y": 24})
        self.assertIsNotNone(waypoints)
        self.assertEqual(waypoints[-1], [4 * 48 + 24, 24])
        self.assertTrue(any(y >= 4 * 48 for _, y in waypoints[:-1]))  # dips to the gap row
        rows[4][2] = land("Ocean")
        self.assertIsNone(plan(grid(rows), {"x": 24, "y": 24}, {"x": 4 * 48 + 24, "y": 24}))
        self.assertEqual(plan(grid(rows), {"x": 1, "y": 1}, {"x": 5, "y": 7}), [[5, 7]])

    def client(self, bridge):
        client = Client(port=1, execution={"mode": "complete"}, metrics_path=False)
        patched = patch.object(client, "request", side_effect=bridge)
        patched.start()
        self.addCleanup(patched.stop)
        return client

    def test_auto_route_requests_the_region_box_then_aims_at_waypoints(self):
        before = wide("before", 24, 24)
        rows = [[land() for _ in range(4)] for _ in range(3)]
        rows[0][1] = land("Ocean")
        rows[1][1] = land("Ocean")  # the straight line east is sea; go under it
        with_grid = wide("grid", 24, 24)
        with_grid["overland"] = grid(rows)
        bridge = Bridge(before, [with_grid] + [wide("same", 24, 24)] * 30)
        result = self.client(bridge).act({"type": "travel_to", "x": 3 * 48 + 24, "y": 24})
        boxes = [c["overland"] for c in bridge.calls if c.get("overland")]
        self.assertEqual(boxes[0], {"x0": -2, "y0": -2, "x1": 5, "y1": 2})
        self.assertEqual(bridge.inputs[0], {"type": "resume"})  # observe the grid first
        # The plan dips south under the sea before turning east: the aim is the
        # first region centre, not the destination's bearing.
        self.assertEqual(bridge.inputs[1], {"type": "key", "key": "A_MOVE_S"})
        # Every probe refused: the trip stops with the plan and probe count.
        self.assertEqual(result["outcome"], "needs_input")
        self.assertEqual(result["blocker"]["kind"], "travel_blocked")
        self.assertEqual(result["blocker"]["facts"]["plan"][0], [24, 72])
        self.assertEqual(len(bridge.inputs), 12)
        route = result["route"]
        self.assertEqual(
            (route["waypoints"][0], route["waypoint"], route["detours"]), ([24, 72], 0, 10)
        )

    def test_refused_move_probes_sideways_instead_of_stopping(self):
        first = travel_scene("start", x=10, y=10)
        stuck = travel_scene("stuck", x=10, y=10)
        east = travel_scene("east", x=16, y=10)
        held = travel_scene("held", x=16, y=10)
        bridge = Bridge(first, [stuck, stuck, stuck, east, held, held, held, held])
        client = self.client(bridge)
        result = client.act({"type": "travel_to", "x": 10, "y": 30}, execution={"max_steps": 8})
        keys = [i["key"] for i in bridge.inputs][:6]
        # South refused: probe 3 east of the anchor, then 3 west, then 6 east,
        # which succeeds; the aim resumes toward the destination (now south-west)
        # and, refused again, the search continues from the same anchor (6 west).
        self.assertEqual(
            keys, ["A_MOVE_S", "A_MOVE_E", "A_MOVE_W", "A_MOVE_E", "A_MOVE_SW", "A_MOVE_W"]
        )
        self.assertNotEqual(result["outcome"], "no_effect")
        direct = Bridge(first, [stuck])
        self.assertEqual(
            self.client(direct).act({"type": "travel_to", "x": 10, "y": 30, "route": "direct"})[
                "outcome"
            ],
            "no_effect",
        )
        with self.assertRaises(ValueError):
            validate_action({"type": "travel_to", "x": 1, "y": 1, "route": "wander"})


def detail(tiles, temp=20):
    return {
        "available": True,
        "epoch": "e1",
        "tiles": [{"x": x, "y": y, "temp": temp, "rows": rows} for (x, y), rows in tiles.items()],
    }


def open_tile(char="."):
    return [char * 16 for _ in range(16)]


class FineRouterTests(unittest.TestCase):
    client = OverlandTests.client

    def test_pocket_coast_is_walked_around_instead_of_probed(self):
        from dfharness.overland import fine_step

        # The real coast north of Coveryouths: land at rows 11-15 with a water
        # inlet directly east and north of the party at embark (8,11).
        rows = open_tile("~")
        rows[11] = "~~~~~~~..~......"
        rows[12] = "~~~~~~.........."
        rows[13] = "~~~~~..........."
        rows[14] = "~~~~~..........."
        rows[15] = "~~~~~..........."
        rows[10] = "~~~~~~~~~~~....."
        rows[9] = "~~~~~~~~~~~....."
        rows[8] = "~~~~~~~~~~~....."
        window = detail({(2, 21): rows, (3, 20): open_tile()})
        position = {"x": 2 * 48 + 8 * 3, "y": 21 * 48 + 11 * 3 + 2}  # travel (120,1043)
        aim = {"x": 3 * 48 + 24, "y": 20 * 48 + 24}
        step = fine_step(window, position, aim)
        self.assertTrue(step["progress"])
        self.assertEqual(step["direction"], (1, 1))  # south-east around the inlet, not north-east
        self.assertIsNone(fine_step(window, {"x": 1000, "y": 1000}, aim))  # outside the window

    def test_rivers_block_only_when_warm_and_mountains_always(self):
        from dfharness.overland import fine_step

        rows = open_tile()
        rows[5] = "rrrrrrrrrrrrrrrr"  # a river across the tile
        position, aim = {"x": 24, "y": 3 * 3}, {"x": 24, "y": 12 * 3}
        cold = fine_step(detail({(0, 0): rows}, temp=10), position, aim)
        self.assertEqual((cold["progress"], cold["direction"][1], cold["reaches"]), (True, 1, True))
        # Warm rivers and mountains: the bank is approachable, the far side is not.
        warm = fine_step(detail({(0, 0): rows}, temp=60), position, aim)
        self.assertEqual((warm["progress"], warm["reaches"]), (True, False))
        rows[5] = "^^^^^^^^^^^^^^^^"
        self.assertFalse(fine_step(detail({(0, 0): rows}, temp=10), position, aim)["reaches"])
        at_bank = {"x": 24, "y": 4 * 3}
        self.assertFalse(fine_step(detail({(0, 0): rows}, temp=10), at_bank, aim)["progress"])

    def test_detail_cache_reuses_an_unchanged_window(self):
        from dfharness.overland import DETAIL_CACHE, resolve_detail

        DETAIL_CACHE.update(epoch=None, detail=None)
        window = detail({(0, 0): open_tile()})
        self.assertIs(resolve_detail({"overland_detail": window}), window)
        self.assertIs(
            resolve_detail(
                {"overland_detail": {"available": True, "epoch": "e1", "unchanged": True}}
            ),
            window,
        )
        self.assertIsNone(
            resolve_detail(
                {"overland_detail": {"available": True, "epoch": "e2", "unchanged": True}}
            )
        )
        self.assertIsNone(resolve_detail({}))

    def test_travel_follows_terrain_and_skips_an_unreachable_waypoint(self):
        from dfharness.overland import DETAIL_CACHE

        DETAIL_CACHE.update(epoch=None, detail=None)
        # Column 1 of world tiles is sea in the region grid, so the plan dips
        # south; the embark detail shows a water inlet forcing a south-east step.
        grid_rows = [[land() for _ in range(4)] for _ in range(3)]
        grid_rows[0][1] = land("Ocean")
        grid_rows[1][1] = land("Ocean")
        tile = open_tile()
        tile[7] = "~~~~~~~~~~......"  # the party at embark (8,8) sits in a coastal
        tile[8] = "~~~~~~~~.~......"  # pocket whose only exit is south-east
        tile[9] = "~~~~~~~~~......."
        window = detail({(0, 0): tile, (0, 1): open_tile(), (1, 1): open_tile()})
        start = wide("start", 8 * 3, 8 * 3)
        with_grid = wide("grid", 8 * 3, 8 * 3)
        with_grid["overland"] = grid(grid_rows)
        with_grid["overland_detail"] = window
        moved = wide("moved", 8 * 3 + 3, 8 * 3 + 3)
        moved["overland_detail"] = {"available": True, "epoch": "e1", "unchanged": True}
        bridge = Bridge(start, [with_grid, moved])
        result = self.client(bridge).act(
            {"type": "travel_to", "x": 3 * 48 + 24, "y": 24}, execution={"max_steps": 2}
        )
        keys = [i.get("key") for i in bridge.inputs]
        self.assertEqual(keys, [None, "A_MOVE_SE"])
        self.assertTrue(bridge.calls[-2].get("overland_detail"))
        self.assertEqual(result["route"]["detours"], 0)


class ArrivalTests(unittest.TestCase):
    client = OverlandTests.client

    def test_refused_last_step_within_one_stride_counts_as_arrival(self):
        # Sites cannot be entered from the travel map: the party stops beside
        # the destination tile and the game refuses the final move.
        beside = travel_scene("beside", x=10, y=12)
        bridge = Bridge(beside, [travel_scene("still", x=10, y=12)])
        result = self.client(bridge).act({"type": "travel_to", "x": 12, "y": 10})
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(len(bridge.inputs), 1)
        far = travel_scene("far", x=10, y=20)
        bridge = Bridge(far, [travel_scene("stuck", x=10, y=20)] * 3)
        result = self.client(bridge).act(
            {"type": "travel_to", "x": 10, "y": 10}, execution={"max_steps": 2}
        )
        self.assertNotEqual(result["outcome"], "completed")
