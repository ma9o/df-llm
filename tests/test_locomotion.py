import unittest
from copy import deepcopy
from unittest.mock import patch

from dfharness.client import Client
from dfharness.workflows import validate_action
from tests.support import Bridge
from tests.test_workflows import scene


def state(name, x=1, tick=0):
    value = scene(name, x=x)
    value["status"].update(year=100, year_tick=tick, map_origin={"x": 0, "y": 0, "z": 0})
    return value


class LocomotionTests(unittest.TestCase):
    def client(self, bridge):
        client = Client(port=1, execution={"mode": "complete"}, metrics_path=False)
        patched = patch.object(client, "request", side_effect=bridge)
        patched.start()
        self.addCleanup(patched.stop)
        return client

    def test_sequence_moves_then_waits_under_one_budget_and_resumes_without_repeating_move(self):
        bridge = Bridge(state("start"), [state("moved", 2, 1), state("waited", 2, 2)])
        client = self.client(bridge)
        action = {
            "type": "sequence",
            "actions": [{"type": "move", "direction": "e"}, {"type": "wait"}],
        }
        validate_action(action)
        first = client.act(action, execution={"max_steps": 1})
        self.assertEqual(first["outcome"], "limit_reached")
        self.assertEqual(first["completed_stages"], 1)
        done = client.act(first["resume"])
        self.assertEqual(done["outcome"], "completed")
        self.assertEqual(done["completed_stages"], 2)
        self.assertEqual(bridge.inputs, action["actions"])

    def test_ineffective_move_keeps_checkpoint_and_late_arrival_can_resume(self):
        bridge = Bridge(state("start"), [state("refused", tick=1)])
        client = self.client(bridge)
        first = client.act({"type": "move", "direction": "e"})
        self.assertEqual(first["outcome"], "no_effect")
        self.assertEqual(first["blocker"]["facts"]["destination"], {"x": 2, "y": 1, "z": 0})
        again = client.act(first["resume"])
        self.assertEqual(again["outcome"], "no_effect")
        bridge.view = state("late", 2, 2)
        done = client.act(again["resume"])
        self.assertEqual(done["outcome"], "completed")
        self.assertEqual(len(bridge.inputs), 1)

    def test_wait_requires_time_and_never_resends_an_unchanged_wait(self):
        bridge = Bridge(state("start"), [state("no-time")])
        client = self.client(bridge)
        first = client.act({"type": "wait"})
        self.assertEqual(first["outcome"], "no_effect")
        again = client.act(first["resume"])
        self.assertEqual(again["outcome"], "no_effect")
        bridge.view = state("late", tick=1)
        self.assertEqual(client.act(again["resume"])["outcome"], "completed")
        self.assertEqual(len(bridge.inputs), 1)
        missing = Bridge(scene("unknown-clock"))
        self.assertEqual(
            self.client(missing).act({"type": "wait"})["blocker"]["kind"], "wait_clock_unavailable"
        )
        self.assertFalse(missing.inputs)

    def test_move_uses_native_path_when_present_and_preserves_target_across_rebase(self):
        before, after = state("before"), state("after", x=0, tick=1)
        before["native_path"] = {"available": True, "goal": "None"}
        after["status"]["map_origin"]["x"] = 2
        bridge = Bridge(before, [after])
        done = self.client(bridge).act({"type": "move", "direction": "e"})
        self.assertEqual(done["outcome"], "completed")
        self.assertEqual(
            bridge.inputs,
            [{"type": "path_to", "destination": {"x": 2, "y": 1, "z": 0}, "arrival_radius": 0}],
        )

    def test_wait_frame_rebase_and_unknown_clock_do_not_imply_elapsed_time(self):
        before = scene("before")
        before["status"].update(world_frame=0, local_map_epoch="old")
        after = deepcopy(before)
        after["status"].update(world_frame=500, local_map_epoch="new")
        bridge = Bridge(before, [after])
        done = self.client(bridge).act({"type": "wait"})
        self.assertEqual(done["outcome"], "no_effect")

    def test_verified_native_pause_can_resume_toward_the_original_adjacent_tile(self):
        before, paused, arrived = state("before"), state("paused", tick=1), state("arrived", 2, 2)
        before["native_path"] = paused["native_path"] = {"available": True, "goal": "None"}
        paused["input_evidence"] = {"kind": "walk", "available": True, "phase": "paused"}
        bridge = Bridge(before, [paused, arrived])
        client = self.client(bridge)
        first = client.act({"type": "move", "direction": "e"}, execution={"max_steps": 1})
        self.assertEqual(first["outcome"], "limit_reached")
        resumed = client.act(first["resume"])
        self.assertEqual(resumed["outcome"], "completed")
        self.assertEqual(len(bridge.inputs), 2)
        self.assertEqual(bridge.inputs[0]["destination"], bridge.inputs[1]["destination"])

    def test_short_wait_can_advance_a_frame_without_advancing_the_calendar(self):
        before, after = state("before"), state("after")
        before["status"].update(world_frame=10, local_map_epoch="one")
        after["status"].update(world_frame=11, local_map_epoch="one")
        bridge = Bridge(before, [after])
        self.assertEqual(self.client(bridge).act({"type": "wait"})["outcome"], "completed")
        self.assertEqual(bridge.inputs, [{"type": "wait"}])

    def test_a_frame_without_its_map_identity_cannot_verify_a_wait(self):
        before = scene("before")
        before["status"]["world_frame"] = 10
        bridge = Bridge(before)
        self.assertEqual(self.client(bridge).act({"type": "wait"})["outcome"], "needs_input")
        self.assertFalse(bridge.inputs)

    def test_unknown_directions_are_rejected_before_input(self):
        for value in ([], None, 1, "north"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_action({"type": "move", "direction": value})
