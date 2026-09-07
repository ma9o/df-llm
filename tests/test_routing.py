import unittest
from unittest.mock import patch

from dfharness.workflows import next_walk, validate_action
from tests.support import Bridge
from tests.support import FullClient as Client
from tests.test_workflows import scene


def corridor(name, x, *, reveal=True, offset=0):
    view = scene(name, x=x - offset)
    view["status"]["map_origin"] = {"x": 100 + offset, "y": 0, "z": 0}
    view["status"]["map_size"] = {"x": 10, "y": 3, "z": 1}
    end = min(10, (x if reveal else 1) + 3 - offset)
    row = "1" * end + "0" * (10 - end)
    view["map"].update(
        walkable=["0" * 10, row, "0" * 10],
        visible=["1" * 10, row, "1" * 10],
        liquid_depths=["0" * 10, "0" * end + "?" * (10 - end), "0" * 10],
    )
    return view


class RoutingTests(unittest.TestCase):
    def test_a_confirmed_corpse_does_not_block_a_walkable_destination(self):
        target = {"x": 2, "y": 1, "z": 0}
        view = corridor("start", 1)
        view["map"]["units"] = [{"id": 12, "position": target, "alive": False}]
        self.assertEqual(next_walk(view, target, {})["input"], {"type": "move", "direction": "e"})
        for alive in (True, None):
            view["map"]["units"][0]["alive"] = alive
            self.assertEqual(next_walk(view, target, {})["outcome"], "needs_input")

    def client(self, bridge):
        client = Client(port=1, execution={"mode": "complete"})
        mock = patch.object(client, "request", side_effect=bridge)
        mock.start()
        self.addCleanup(mock.stop)
        return client

    def test_one_objective_reveals_a_route_and_verifies_the_original_destination(self):
        bridge = Bridge(corridor("start", 1), [corridor(str(x), x) for x in range(2, 9)])
        result = self.client(bridge).act(
            {"type": "walk_to", "x": 8, "y": 1, "z": 0, "extend_route": True}
        )
        self.assertEqual(result["dispatch"]["outcome"], "completed")
        self.assertEqual(result["status"]["position"], {"x": 8, "y": 1, "z": 0})
        self.assertEqual(bridge.inputs, [{"type": "move", "direction": "e"}] * 7)

    def test_extension_is_explicit_and_does_not_override_target_exclusions(self):
        view, target = corridor("start", 1), {"x": 8, "y": 1, "z": 0}
        self.assertEqual(next_walk(view, target, {})["outcome"], "needs_input")
        for constraints in (
            {"blocked_tiles": [target]},
            {"blocked_tiles": [{"x": 2, "y": 1, "z": 0}]},
        ):
            result = next_walk(view, target, {"extend_route": True, **constraints}, context={})
            self.assertEqual(result["outcome"], "needs_input")
        for value in (1, "true", None):
            with self.assertRaisesRegex(ValueError, "extend_route must be boolean"):
                validate_action({"type": "walk_to", **target, "extend_route": value})

    def test_frontiers_obey_occupancy_and_liquid_constraints(self):
        target = {"x": 8, "y": 1, "z": 0}
        view = corridor("start", 1)
        view["map"]["units"] = [{"id": 2, "position": {"x": 2, "y": 1, "z": 0}}]
        self.assertEqual(
            next_walk(view, target, {"extend_route": True}, context={})["outcome"], "needs_input"
        )
        self.assertIn(
            "input",
            next_walk(view, target, {"extend_route": True, "allow_occupied": True}, context={}),
        )
        view["map"]["units"] = []
        view["map"]["liquid_depths"][1] = "0070??????"
        self.assertEqual(
            next_walk(view, target, {"extend_route": True, "max_liquid_depth": 0}, context={})[
                "outcome"
            ],
            "needs_input",
        )

    def test_no_new_visibility_exhausts_frontiers_without_oscillation(self):
        bridge = Bridge(
            corridor("start", 1, reveal=False),
            [corridor(str(x), x, reveal=False) for x in (2, 3, 0)],
        )
        result = self.client(bridge).act(
            {"type": "walk_to", "x": 8, "y": 1, "z": 0, "extend_route": True}
        )
        self.assertEqual(result["dispatch"]["outcome"], "needs_input")
        self.assertEqual(result["dispatch"]["details"]["blocker_kind"], "no_unvisited_frontier")
        self.assertEqual(len(bridge.inputs), 2)

    def test_route_checkpoint_survives_step_resume_and_coordinate_rebase(self):
        bridge = Bridge(
            corridor("start", 1),
            [corridor(str(x), x, offset=int(x >= 3)) for x in range(2, 9)],
        )
        client = self.client(bridge)
        first = client.act(
            {"type": "walk_to", "x": 8, "y": 1, "z": 0, "extend_route": True},
            execution={"mode": "step"},
        )
        self.assertEqual(first["dispatch"]["outcome"], "in_progress")
        result = client.act(first["dispatch"]["resume_action"])
        self.assertEqual(result["dispatch"]["outcome"], "completed")
        self.assertEqual(len(bridge.inputs), 7)
        self.assertEqual(result["status"]["position"], {"x": 7, "y": 1, "z": 0})

    def test_missing_visibility_is_not_permission_to_enter_unknown_terrain(self):
        view = corridor("missing", 1)
        view["map"].pop("visible")
        result = next_walk(view, {"x": 11, "y": 1, "z": 0}, {"extend_route": True}, context={})
        self.assertEqual(result["outcome"], "needs_input")
        self.assertEqual(result["details"]["blocker_kind"], "visibility_grid_unavailable")

    def test_unknown_liquid_depth_is_not_assumed_to_be_zero(self):
        view, target = corridor("unknown", 1), {"x": 2, "y": 1, "z": 0}
        view["map"]["liquid_depths"][1] = "00?0??????"
        result = next_walk(view, target, {"max_liquid_depth": 0})
        self.assertEqual(result["outcome"], "needs_input")
        self.assertEqual(result["details"]["facts"]["exclusions"], ["liquid_depth_unavailable"])
        view["map"].pop("liquid_depths")
        result = next_walk(view, target, {"max_liquid_depth": 0})
        self.assertEqual(result["outcome"], "needs_input")
        self.assertEqual(result["details"]["blocker_kind"], "liquid_depths_unavailable")

    def test_known_impassable_destination_is_not_an_exploration_objective(self):
        view = corridor("wall", 1)
        view["map"]["visible"][1] = "1111111111"
        view["map"]["liquid_depths"][1] = "0000000000"
        result = next_walk(view, {"x": 8, "y": 1, "z": 0}, {"extend_route": True}, context={})
        self.assertEqual(result["outcome"], "needs_input")
        self.assertEqual(result["details"]["facts"]["exclusions"], ["unwalkable"])

    def test_explicit_arrival_radius_finishes_near_an_impassable_target(self):
        before, after = corridor("start", 1), corridor("arrived", 2)
        # The requested tile itself is a visible tree; its neighbor is walkable.
        for view in (before, after):
            view["map"]["walkable"][1] = "1110000000"
            view["map"]["visible"][1] = "1111000000"
        bridge = Bridge(before, [after])
        result = self.client(bridge).act(
            {"type": "walk_to", "x": 3, "y": 1, "z": 0, "arrival_radius": 1}
        )
        self.assertEqual(result["dispatch"]["outcome"], "completed")
        self.assertEqual(len(bridge.inputs), 1)
        self.assertEqual(result["status"]["position"], {"x": 2, "y": 1, "z": 0})

    def test_search_memory_limit_is_explicit_and_does_not_restart_the_route(self):
        bridge = Bridge(corridor("start", 1), [corridor("second", 2)])
        with patch("dfharness.routing.MAX_VISITED", 1):
            client = self.client(bridge)
            result = client.act({"type": "walk_to", "x": 8, "y": 1, "z": 0, "extend_route": True})
            self.assertEqual(result["dispatch"]["outcome"], "needs_input")
            self.assertEqual(result["dispatch"]["details"]["blocker_kind"], "route_search_limit")
            resumed = client.act(result["dispatch"]["resume_action"])
            self.assertEqual(resumed["dispatch"]["details"]["blocker_kind"], "route_search_limit")
        self.assertEqual(len(bridge.inputs), 1)
