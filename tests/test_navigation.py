import unittest
from copy import deepcopy
from unittest.mock import patch

from dfharness.workflows import site_travel_step, validate_action
from tests.support import Bridge
from tests.support import FullClient as Client
from tests.test_workflows import scene


def travel_scene(name, x=1, y=1, *, active=True, exception="NONE", map_open=False):
    v = scene(name)
    v["status"]["can_move"] = not active
    v["status"]["travel"] = {
        "active": active,
        "position": {"x": x, "y": y, "z": 0},
        "world_size": {"x": 100, "y": 100},
        "exception": {"type": exception, "message": "native restriction"},
        "map_view": {
            "available": True,
            "open": map_open,
            "mode": "MapSite" if map_open else "MapNone",
            **({"close_key": "A_TRAVEL_MAP"} if map_open else {}),
        },
    }
    return v


class NavigationTests(unittest.TestCase):
    def client(self, bridge):
        c = Client(port=1, execution={"mode": "complete", "acknowledge": True})
        patcher = patch.object(c, "request", side_effect=bridge)
        patcher.start()
        self.addCleanup(patcher.stop)
        return c

    def test_posture_rejection_is_not_success_or_retried(self):
        before = scene("before")
        before["adventurer"]["on_ground"] = True
        after = deepcopy(before)
        after.update(
            state_id="after",
            effect_id="after",
            reports=[{"id": 1, "type": "CANNOT_STAND", "text": "Somebody is in the way."}],
        )
        b = Bridge(before, [after])
        r = self.client(b).act({"type": "set_posture", "posture": "standing"})
        self.assertEqual(r["dispatch"]["outcome"], "needs_input")
        self.assertEqual(r["dispatch"]["blocker"]["kind"], "native_refusal")
        self.assertEqual(r["dispatch"]["reason"], "Somebody is in the way.")
        self.assertEqual(r["dispatch"]["events"], after["reports"])
        self.assertEqual(len(b.inputs), 1)

    def test_posture_is_idempotent_and_verifies_false(self):
        before = scene("before")
        before["adventurer"]["on_ground"] = False
        b = Bridge(before)
        r = self.client(b).act({"type": "set_posture", "posture": "standing"})
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        self.assertEqual(b.inputs, [])

    def test_posture_change_is_reported(self):
        before, after = scene("before"), scene("after")
        before["adventurer"]["on_ground"], after["adventurer"]["on_ground"] = True, False
        b = Bridge(before, [after])
        r = self.client(b).act({"type": "set_posture", "posture": "standing"})
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        self.assertEqual(r["adventurer"]["on_ground"], False)

    def test_unknown_posture_does_not_send_a_toggle(self):
        b = Bridge(scene("unknown"))
        r = self.client(b).act({"type": "set_posture", "posture": "standing"})
        self.assertEqual(r["dispatch"]["outcome"], "needs_input")
        self.assertEqual(b.inputs, [])

    def test_travel_opens_moves_and_verifies_arrival(self):
        b = Bridge(
            travel_scene("local", active=False),
            [travel_scene("open"), travel_scene("move1", x=2), travel_scene("arrived", x=3)],
        )
        r = self.client(b).act({"type": "travel_to", "x": 3, "y": 1})
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        self.assertEqual([i["key"] for i in b.inputs], ["A_TRAVEL", "A_MOVE_E", "A_MOVE_E"])
        self.assertEqual(r["status"]["travel"]["position"]["x"], 3)

    def test_end_travel_requires_loaded_character_and_does_not_replay_old_reports(self):
        before = travel_scene("travel")
        before.pop("adventurer")
        before["report_cursor"] = 100
        after = travel_scene("local", active=False)
        after["status"]["map_loaded"] = True
        after["reports"] = [{"id": 99, "text": "old"}, {"id": 101, "text": "new"}]
        b = Bridge(before, [after])
        r = self.client(b).act({"type": "end_travel"})
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        self.assertEqual(b.inputs, [{"type": "key", "key": "A_END_TRAVEL"}])
        self.assertEqual([e["id"] for e in r["dispatch"]["events"]], [101])
        missing = deepcopy(after)
        missing.pop("adventurer")
        b = Bridge(missing, [])
        self.assertEqual(
            self.client(b).act({"type": "end_travel"})["dispatch"]["outcome"], "needs_input"
        )
        self.assertEqual(b.inputs, [])

    def test_enlarged_map_closes_before_travel_or_exit(self):
        for action, after, key in [
            ({"type": "travel_to", "x": 2, "y": 1}, travel_scene("arrived", x=2), "A_MOVE_E"),
            ({"type": "end_travel"}, travel_scene("local", active=False), "A_END_TRAVEL"),
        ]:
            with self.subTest(action=action):
                after["status"]["map_loaded"] = True
                b = Bridge(travel_scene("map", map_open=True), [travel_scene("closed"), after])
                r = self.client(b).act(action)
                self.assertEqual(r["dispatch"]["outcome"], "completed")
                self.assertEqual([i["key"] for i in b.inputs], ["A_TRAVEL_MAP", key])

    def test_explicit_development_key_can_open_and_leave_the_map_open(self):
        b = Bridge(travel_scene("closed"), [travel_scene("map", map_open=True)])
        r = self.client(b).act({"type": "key", "key": "A_TRAVEL_MAP"})
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        self.assertTrue(r["status"]["travel"]["map_view"]["open"])
        self.assertEqual([i["key"] for i in b.inputs], ["A_TRAVEL_MAP"])

    def test_map_closure_obeys_incremental_execution_and_resumes_once(self):
        b = Bridge(
            travel_scene("map", map_open=True),
            [travel_scene("closed"), travel_scene("arrived", x=2)],
        )
        c = self.client(b)
        first = c.act({"type": "travel_to", "x": 2, "y": 1}, execution={"mode": "step"})
        self.assertEqual(first["dispatch"]["outcome"], "in_progress")
        self.assertEqual([i["key"] for i in b.inputs], ["A_TRAVEL_MAP"])
        last = c.act(first["dispatch"]["resume_action"])
        self.assertEqual(last["dispatch"]["outcome"], "completed")
        self.assertEqual([i["key"] for i in b.inputs], ["A_TRAVEL_MAP", "A_MOVE_E"])

    def test_failed_map_toggle_is_not_repeated_even_on_resume(self):
        b = Bridge(travel_scene("map", map_open=True), [travel_scene("still-open", map_open=True)])
        c = self.client(b)
        first = c.act({"type": "travel_to", "x": 2, "y": 1}, result_format="compact")
        self.assertEqual(first["outcome"], "no_effect")
        again = c.act(first["resume"], result_format="compact")
        self.assertEqual(again["blocker"]["kind"], "travel_map_close")
        self.assertTrue(again["blocker"]["facts"]["map_view"]["open"])
        self.assertEqual([i["key"] for i in b.inputs], ["A_TRAVEL_MAP"])

    def test_unavailable_map_mode_or_binding_does_not_send_input(self):
        for panel in (
            None,
            {"available": False, "reason": "missing"},
            {"available": True},
            {"available": True, "open": True, "mode": "NewNativeMode"},
        ):
            with self.subTest(panel=panel):
                view = travel_scene("unknown")
                view["status"]["travel"]["map_view"] = panel
                b = Bridge(view)
                receipt = self.client(b).act({"type": "end_travel"}, result_format="compact")
                self.assertEqual(receipt["blocker"]["kind"], "travel_map_unavailable")
                self.assertEqual(b.inputs, [])

    def test_sequence_closes_map_once_and_shares_input_budget(self):
        b = Bridge(
            travel_scene("map", map_open=True),
            [travel_scene("closed"), travel_scene("middle", x=2), travel_scene("arrived", x=3)],
        )
        c = self.client(b)
        first = c.act(
            {
                "type": "sequence",
                "actions": [
                    {"type": "travel_to", "x": 2, "y": 1},
                    {"type": "travel_to", "x": 3, "y": 1},
                ],
            },
            execution={"max_steps": 2},
        )
        self.assertEqual(first["dispatch"]["outcome"], "limit_reached")
        last = c.act(first["dispatch"]["resume_action"])
        self.assertEqual(last["dispatch"]["outcome"], "completed")
        self.assertEqual([i["key"] for i in b.inputs], ["A_TRAVEL_MAP", "A_MOVE_E", "A_MOVE_E"])

    def test_observed_coarse_stride_stops_before_oscillating_around_an_exact_target(self):
        before, near = travel_scene("before", x=10), travel_scene("near", x=7)
        for view in (before, near):
            view["status"]["travel"]["site_zoom"] = False
        bridge = Bridge(before, [near])
        client = self.client(bridge)
        receipt = client.act({"type": "travel_to", "x": 8, "y": 1}, result_format="compact")
        self.assertEqual(receipt["outcome"], "needs_input")
        self.assertEqual(receipt["blocker"]["kind"], "travel_resolution")
        self.assertEqual(receipt["blocker"]["facts"]["observed_stride"], 3)
        self.assertEqual(receipt["blocker"]["facts"]["arrival_radius"], 0)
        resumed = client.act(receipt["resume"])["dispatch"]
        self.assertEqual(resumed["outcome"], "needs_input")
        self.assertEqual(bridge.inputs, [{"type": "key", "key": "A_MOVE_W"}])

    def test_controller_arrival_radius_accepts_the_coarse_endpoint(self):
        before, near = travel_scene("before", x=10), travel_scene("near", x=7)
        for view in (before, near):
            view["status"]["travel"]["site_zoom"] = False
        bridge = Bridge(before, [near])
        result = self.client(bridge).act({"type": "travel_to", "x": 8, "y": 1, "arrival_radius": 1})
        self.assertEqual(result["dispatch"]["outcome"], "completed")
        self.assertEqual(len(bridge.inputs), 1)

    def test_zoom_change_does_not_apply_the_previous_modes_stride(self):
        views = [travel_scene("before", x=10), travel_scene("near", x=7), travel_scene("done", x=8)]
        for view in views:
            view["status"]["travel"]["site_zoom"] = True
        views[0]["status"]["travel"]["site_zoom"] = False
        bridge = Bridge(views[0], views[1:])
        result = self.client(bridge).act({"type": "travel_to", "x": 8, "y": 1})
        self.assertEqual(result["dispatch"]["outcome"], "completed")
        self.assertEqual([i["key"] for i in bridge.inputs], ["A_MOVE_W", "A_MOVE_E"])

    def test_unexpected_travel_progress_keeps_coordinate_evidence_in_the_blocker(self):
        bridge = Bridge(travel_scene("before", x=5), [travel_scene("away", x=7)])
        result = self.client(bridge).act(
            {"type": "travel_to", "x": 3, "y": 1}, result_format="compact"
        )
        self.assertEqual(result["blocker"]["kind"], "travel_progress")
        self.assertEqual(result["blocker"]["facts"]["previous_position"]["x"], 5)
        self.assertEqual(result["blocker"]["facts"]["position"]["x"], 7)

    def test_end_travel_no_effect_does_not_repeat_input(self):
        b = Bridge(travel_scene("before"), [travel_scene("after")])
        self.assertEqual(
            self.client(b).act({"type": "end_travel"})["dispatch"]["outcome"], "no_effect"
        )
        self.assertEqual(len(b.inputs), 1)

    def test_travel_step_resumes_without_repeating_the_previous_move(self):
        b = Bridge(
            travel_scene("before"), [travel_scene("middle", x=2), travel_scene("arrived", x=3)]
        )
        c = self.client(b)
        first = c.act({"type": "travel_to", "x": 3, "y": 1}, execution={"mode": "step"})
        self.assertEqual(first["dispatch"]["outcome"], "in_progress")
        self.assertEqual(len(b.inputs), 1)
        last = c.act(first["dispatch"]["resume_action"])
        self.assertEqual(last["dispatch"]["outcome"], "completed")
        self.assertEqual(len(b.inputs), 2)

    def test_failed_direction_returns_control_instead_of_choosing_a_route(self):
        b = Bridge(travel_scene("before"), [travel_scene("blocked")])
        r = self.client(b).act({"type": "travel_to", "x": 3, "y": 1})
        self.assertEqual(r["dispatch"]["outcome"], "no_effect")
        self.assertEqual(len(b.inputs), 1)

    def test_forced_exit_does_not_restart_travel_automatically(self):
        b = Bridge(travel_scene("before"), [travel_scene("encounter", active=False)])
        c = self.client(b)
        r = c.act({"type": "travel_to", "x": 3, "y": 1})
        self.assertEqual(r["dispatch"]["outcome"], "needs_input")
        resumed = c.act(r["dispatch"]["resume_action"])
        self.assertEqual(resumed["dispatch"]["outcome"], "needs_input")
        self.assertEqual(len(b.inputs), 1)

    def test_restrictions_and_arrival_radius(self):
        for view, action, expected in [
            (
                travel_scene("restricted", exception="THIRST"),
                {"type": "travel_to", "x": 3, "y": 1},
                "needs_input",
            ),
            (
                travel_scene("near", x=2),
                {"type": "travel_to", "x": 3, "y": 1, "arrival_radius": 1},
                "completed",
            ),
            (travel_scene("outside"), {"type": "travel_to", "x": 100, "y": 1}, "needs_input"),
        ]:
            with self.subTest(expected=expected, action=action):
                b = Bridge(view)
                self.assertEqual(self.client(b).act(action)["dispatch"]["outcome"], expected)
                self.assertEqual(b.inputs, [])

    def test_action_validation(self):
        for action in [
            {"type": "set_posture", "posture": "run"},
            {"type": "travel_to", "x": True, "y": 1},
            {"type": "travel_to", "x": 1, "y": 1, "arrival_radius": -1},
        ]:
            with self.assertRaises(ValueError):
                validate_action(action)

    def test_native_travel_restriction_remains_explained_without_a_state_diff(self):
        bridge = Bridge(travel_scene("encounter", exception="ENCOUNTER"))
        client = self.client(bridge)
        first = client.act({"type": "travel_to", "x": 3, "y": 1}, result_format="compact")
        second = client.act(first["resume"], result_format="compact")
        for receipt in (first, second):
            self.assertEqual(receipt["blocker"]["kind"], "travel_restricted")
            self.assertEqual(receipt["blocker"]["facts"]["type"], "ENCOUNTER")
            self.assertEqual(receipt["blocker"]["facts"]["message"], "native restriction")
        self.assertEqual(bridge.inputs, [])

    def test_site_grid_routes_around_obstacles_without_a_controller_decision_per_turn(self):
        # East is blocked initially. The legal route goes north, east, east, south.
        grid = {
            "origin": {"x": 0, "y": 0},
            "width": 3,
            "height": 3,
            "masks": ["060c0a", "010001", "000000"],
            "blocked": ["000"] * 3,
        }
        positions = [(0, 1), (0, 0), (1, 0), (2, 0), (2, 1)]
        views = []
        for i, (x, y) in enumerate(positions):
            v = travel_scene(str(i), x=x, y=y)
            v["navigation"] = {"site_grid": deepcopy(grid)}
            views.append(v)
        b = Bridge(views[0], views[1:])
        r = self.client(b).act({"type": "travel_to", "x": 2, "y": 1})
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        self.assertEqual(
            [i["key"] for i in b.inputs], ["A_MOVE_N", "A_MOVE_E", "A_MOVE_E", "A_MOVE_S"]
        )
        grid["blocked"][0] = "010"
        self.assertIsNone(site_travel_step(grid, {"x": 0, "y": 1}, {"x": 2, "y": 1}, 0))


if __name__ == "__main__":
    unittest.main()
