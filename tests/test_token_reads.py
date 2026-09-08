import io
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import patch

from dfharness.cli import main
from dfharness.client import Client, render_observation
from dfharness.readings import apply_read, read_value
from tests.support import Bridge
from tests.test_navigation import travel_scene
from tests.test_workflows import scene


class TokenReadTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.client = Client(
            port=1,
            settings_path=Path(directory.name) / "settings.json",
            metrics_path=False,
            execution={"mode": "complete"},
        )

    def test_machine_json_is_lossless_compact_and_pretty_is_explicit_on_either_side(self):
        sample = {
            "zero": 0,
            "false": False,
            "unknown": None,
            "name": "é",
            "nested": {"items": [1, 2]},
        }
        for flags in (["game-status"], ["--pretty", "game-status"], ["game-status", "--pretty"]):
            with (
                patch.object(Client, "game_status", return_value=sample),
                patch("sys.stdout", new_callable=io.StringIO) as output,
            ):
                self.assertEqual(main(["--port", "1", *flags]), 0)
                text = output.getvalue()
                self.assertEqual(json.loads(text), sample)
                self.assertEqual(text.count("\n") == 1, "--pretty" not in flags)

    def test_ground_filters_and_full_view_reach_native_reader(self):
        sample = {"status": {"world_epoch": "one"}, "items": [], "truncated": False}
        with patch.object(self.client, "request", return_value=sample) as send:
            result = self.client.items(radius=7, item_type="ARMOR", limit=3)
            self.assertEqual(
                send.call_args.args[0],
                {
                    "op": "items",
                    "radius": 7,
                    "item_type": "ARMOR",
                    "limit": 3,
                    "item_view": "concise",
                },
            )
            self.assertIn("read_ref", result)
            self.assertEqual(self.client.items(view="full"), sample)
            self.assertEqual(send.call_args.args[0]["item_view"], "full")

    def test_navigation_and_items_deltas_preserve_zero_unknown_and_scope(self):
        sample: dict[str, Any] = {
            "status": {"world_epoch": "one", "position": {"x": 0, "y": 0, "z": 0}},
            "navigation": {"leads": [], "site_grid_omitted": True},
            "items": [{"id": i, "wear": 0, "weight_unavailable": "missing"} for i in range(20)],
            "truncated": False,
        }
        with patch.object(self.client, "request", return_value=sample) as send:
            for method in (self.client.navigation, self.client.items):
                before = method()
                delta = method(since=before["read_ref"])
                self.assertEqual(delta["format"], "reading_delta")
                self.assertEqual(apply_read(before, delta), before)
                changed = deepcopy(sample)
                changed["status"]["world_epoch"] = "two"
                send.return_value = changed
                self.assertIn("resync", method(since=before["read_ref"])["read_cache"])
                send.return_value = sample
            self.client.navigation()
            self.assertIs(send.call_args.args[0]["navigation_grid"], False)
            self.assertEqual(self.client.navigation(view="full"), sample)
            self.assertIs(send.call_args.args[0]["navigation_grid"], True)

    def test_missing_world_identity_disables_cache_without_retry(self):
        with patch.object(
            self.client, "request", return_value={"items": [], "truncated": True}
        ) as send:
            result = self.client.items(since="old")
            self.assertFalse(result["read_cache"]["available"])
            self.assertTrue(result["truncated"])
            send.assert_called_once()

    def test_brief_uses_the_same_cache_without_a_comprehensive_read(self):
        sample = {"status": {"world_epoch": "one"}, "character": None, "coverage": {}}
        with patch.object(self.client, "request", return_value=sample) as send:
            before = self.client.brief()
            after = self.client.brief(since=before["read_ref"])
            self.assertEqual(read_value(apply_read(before, after)), read_value(before))
            self.assertTrue(all(c.args[0]["op"] == "character_brief" for c in send.call_args_list))

    def test_after_scene_reuses_final_snapshot_and_shares_look_cache(self):
        before, after = scene("before"), scene("after")
        before["adventurer"]["on_ground"] = False
        after["adventurer"]["on_ground"] = True
        bridge = Bridge(before, [after])
        with patch.object(self.client, "request", side_effect=bridge):
            reading = self.client.observe()
            bridge.calls.clear()
            result = self.client.act(
                {"type": "set_posture", "posture": "prone"}, after="look", since=reading["read_ref"]
            )
            self.assertEqual(result["outcome"], "completed")
            self.assertFalse(any(c["op"] == "observe" for c in bridge.calls))
            restored = apply_read(reading, result["after"])
            followup = self.client.observe(since=restored["read_ref"])
            self.assertEqual(apply_read(restored, followup), restored)
            self.assertTrue(restored["adventurer"]["on_ground"])
            self.assertIn("After", render_observation(result))

    def test_after_failure_to_cache_keeps_receipt_and_never_retries_input(self):
        before, after = scene("before"), scene("after")
        before["adventurer"]["on_ground"], after["adventurer"]["on_ground"] = False, True
        bridge = Bridge(before, [after])
        assert self.client.settings_path is not None
        cache = Path(self.client.settings_path).parent / "readings.sqlite3"
        cache.write_text("broken")
        with patch.object(self.client, "request", side_effect=bridge):
            result = self.client.act({"type": "set_posture", "posture": "prone"}, after="look")
            self.assertEqual(result["outcome"], "completed")
            self.assertFalse(result["after"]["read_cache"]["available"])
            self.assertEqual(len(bridge.inputs), 1)
            self.assertEqual(read_value(result["after"])["state_id"], after["state_id"])

    def test_after_uses_the_look_report_window_and_omits_execution_only_item_targets(self):
        value = scene("same")
        report = {"id": 1, "type": "COMBAT_STRIKE_DETAILS", "text": "An earlier report"}
        value.update(reports=[report], reports_truncated=7)
        with patch.object(self.client, "request", return_value=value):
            before = self.client.observe()
        dispatch = deepcopy(value)
        dispatch.update(
            reports=[],
            reports_truncated=0,
            reports_after=1,
            nearby_items=[{"id": 99, "description": "an execution target"}],
            scene_nearby_items=[],
            scene_reports={"reports": [report], "reports_truncated": 7},
        )
        after = self.client._after_scene(dispatch, "task", [], before["read_ref"])
        self.assertEqual(apply_read(before, after), before)

    def test_travel_blocker_preserves_native_facts_and_resume_does_not_repeat_input(self):
        before = travel_scene("start")
        before["status"]["travel"].update(site_zoom=False, not_moved=False)
        after = deepcopy(before)
        after["state_id"] = after["effect_id"] = "no-progress"
        after["status"]["travel"]["exception"].update(id=0, message="")
        bridge = Bridge(before, [after])
        with patch.object(self.client, "request", side_effect=bridge):
            first = self.client.act({"type": "travel_to", "x": 3, "y": 1})
            facts = first["blocker"]["facts"]
            self.assertEqual(facts["destination"], {"x": 3, "y": 1})
            self.assertIs(facts["site_zoom"], False)
            self.assertEqual(facts["exception"], {"id": 0, "type": "NONE", "message": ""})
            self.assertEqual(facts["attempt"]["direction"], "E")
            self.assertLess(len(json.dumps(first, separators=(",", ":"))), 1600)
            resumed = self.client.act(first["resume"])
            self.assertEqual(resumed["outcome"], "no_effect")
            self.assertEqual(len(bridge.inputs), 1)
            bridge.view = travel_scene("late-arrival", x=3)
            self.assertEqual(self.client.act(resumed["resume"])["outcome"], "completed")
            self.assertEqual(len(bridge.inputs), 1)

    def test_bad_after_arguments_are_rejected_before_input(self):
        with patch.object(self.client, "request") as send:
            for kwargs in (
                {"after": "status"},
                {"since": "r1:test"},
                {"after": "look", "since": ""},
            ):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    self.client.act({"type": "wait"}, **kwargs)
            send.assert_not_called()
