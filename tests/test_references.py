import argparse
import unittest
from unittest.mock import patch

from dfharness.actions import ACTIONS
from dfharness.cli import unit_ref
from dfharness.client import Client
from dfharness.workflows import validate_action
from tests.support import Bridge
from tests.test_mount import riding


class ReferenceTests(unittest.TestCase):
    def client(self, bridge):
        client = Client(port=1, execution={"mode": "complete"}, metrics_path=False)
        patched = patch.object(client, "request", side_effect=bridge)
        patched.start()
        self.addCleanup(patched.stop)
        return client

    def test_figure_id_validates_like_unit_id_and_never_with_both(self):
        validate_action({"type": "mount", "figure_id": 5})
        validate_action({"type": "pack", "item_id": 3, "figure_id": 5})
        for bad in (
            {"type": "mount", "figure_id": 5, "unit_id": 7},
            {"type": "mount", "figure_id": -1},
            {"type": "walk_to", "x": 1, "y": 1, "z": 0, "figure_id": 5},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_action(bad)
        mount = next(a for a in ACTIONS if a["properties"]["type"]["const"] == "mount")
        self.assertNotIn("unit_id", mount["required"])
        self.assertEqual(mount["oneOf"], [{"required": ["unit_id"]}, {"required": ["figure_id"]}])

    def test_figure_resolves_to_the_current_unit_each_step_and_blocks_when_absent(self):
        before = riding("before")
        before["target_unit"] = {"id": 7, "figure_id": 5, "position": {"x": 6, "y": 5, "z": 0}}
        done = riding("done", rider=True, mount_id=7, queued=["Mount"])
        done["target_unit"] = dict(before["target_unit"])
        bridge = Bridge(before, [done])
        result = self.client(bridge).act({"type": "mount", "figure_id": 5})
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(
            bridge.inputs[0], {"type": "mount_command", "command": "mount", "unit_id": 7}
        )
        self.assertEqual(bridge.calls[0].get("target_figure_id"), 5)
        gone = riding("gone")
        gone["target_figure"] = {"id": 5, "known": True, "unit_id": None}
        result = self.client(Bridge(gone)).act({"type": "mount", "figure_id": 5})
        self.assertEqual(result["outcome"], "needs_input")
        self.assertEqual(result["blocker"]["kind"], "figure_unavailable")

    def test_figure_addressed_talk_summary_does_not_require_unit_id(self):
        from dfharness.composition import progress

        workflow = {
            "action": {"type": "talk", "figure_id": 5857, "topic": "OfferService"},
            "context": {"topic_sent": True},
        }
        self.assertEqual(progress(workflow)["awaiting"]["unit_id"], 5857)

    def test_prone_walk_stands_first(self):
        from tests.test_workflows import scene

        prone = scene("prone")
        prone["adventurer"]["on_ground"] = True
        prone["native_path"] = {"available": True, "goal": "None"}
        bridge = Bridge(prone, [prone])
        result = self.client(bridge).act({"type": "walk_to", "x": 9, "y": 9, "z": 0})
        self.assertEqual(bridge.inputs[0], {"type": "key", "key": "A_STANCE"})
        self.assertEqual(result["outcome"], "needs_input")
        self.assertEqual(result["blocker"]["kind"], "posture")

    def test_cli_unit_reference_parsing(self):
        self.assertEqual(unit_ref("12"), 12)
        self.assertEqual(unit_ref("hf:12884"), "hf:12884")
        for bad in ("hf:", "x1", "-3"):
            with self.subTest(bad=bad), self.assertRaises(argparse.ArgumentTypeError):
                unit_ref(bad)

    def test_walk_to_accepts_absolute_world_tiles(self):
        validate_action({"type": "walk_to", "x": 4200, "y": 19900, "z": 101, "absolute": True})
        with self.assertRaises(ValueError):
            validate_action({"type": "walk_to", "x": 1, "y": 1, "z": 0, "absolute": "yes"})
        validate_action({"type": "open_trade", "unit_id": 3, "shop_building_id": 86})
        with self.assertRaises(ValueError):
            validate_action({"type": "open_trade", "unit_id": 3})
