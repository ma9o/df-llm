import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dfharness.cli import main
from dfharness.client import Client
from dfharness.settings import read_settings, write_settings
from dfharness.views import character_brief, concise_observation, unit_brief
from tests.support import Bridge
from tests.test_workflows import scene


class SettingsViewTests(unittest.TestCase):
    def test_unit_query_keeps_healthy_body_part_ids_needed_for_a_strike(self):
        parts = [
            {"id": 0, "name": "head", "active_status_flags": []},
            {"id": 1, "name": "leg", "active_status_flags": ["broken"]},
        ]
        source = {"available": True, "unit": {"body": {"parts": parts}}}
        body = unit_brief(source)["unit"]["body"]
        self.assertEqual(body["parts"], [{"id": 0, "name": "head"}, {"id": 1, "name": "leg"}])
        self.assertEqual(body["parts_with_status_flags"], [parts[1]])
        self.assertEqual(source["unit"]["body"]["parts"], parts)

    def test_default_observation_is_concise_without_changing_execution_policy(self):
        c = Client(port=1)
        initial = scene("ready")
        with patch.object(c, "request", return_value=initial) as request:
            result = c.observe()
            self.assertEqual(result["format"], "concise_observation")
            self.assertTrue(result["omitted"])
            self.assertEqual(request.call_args.args[0]["ui_mode"], "native")
            self.assertEqual(c.observe(view="full"), initial)
        self.assertEqual(c.execution["mode"], "step")
        self.assertFalse(c.execution["acknowledge"])

    def test_choices_view_uses_a_narrow_native_read_and_keeps_undecoded_interfaces_visible(self):
        initial = scene("Name an item")
        initial["input_guard"] = {"native_complete": False}
        initial["status"]["focus"] = ["dungeonmode/NameCreator"]
        client = Client(port=1)
        with patch.object(client, "request", return_value=initial) as request:
            result = client.observe(view="choices")
        self.assertEqual(request.call_args.args[0]["scope"], "choices")
        self.assertEqual(request.call_args.args[0]["ui_mode"], "native")
        self.assertEqual(result["choices"], [])
        self.assertEqual(result["ui_text"], ["Name an item"])
        self.assertEqual(result["status"]["focus"], ["dungeonmode/NameCreator"])
        self.assertNotIn("adventurer", result)
        self.assertIn("omitted", result)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "controller.json"
        env = patch.dict(os.environ, {"DFLLM_SETTINGS": str(self.path)})
        env.start()
        self.addCleanup(env.stop)

    def test_settings_persist_across_clients_and_refresh_existing_mcp_client(self):
        old = Client(port=1)
        self.assertEqual(old.execution["mode"], "step")
        Client(port=1).settings(
            {
                "execution": {
                    "mode": "complete",
                    "acknowledge": True,
                    "interrupt_on": {"blood_loss": True},
                },
                "observation_view": "concise",
            }
        )
        self.assertEqual(old.execution["mode"], "complete")
        self.assertTrue(old.execution["acknowledge"])
        self.assertTrue(Client(port=1).execution["interrupt_on"]["blood_loss"])
        Client(port=1).settings({"execution": {"acknowledge": False}})
        self.assertEqual(old.execution["mode"], "complete")
        self.assertFalse(old.execution["acknowledge"])

    def test_precedence_and_dispatch_override_do_not_rewrite_saved_policy(self):
        write_settings({"execution": {"mode": "complete", "acknowledge": True}})
        c = Client(port=1, execution={"mode": "step"})
        b = Bridge(scene("before"), [scene("after")])
        with patch.object(c, "request", side_effect=b):
            r = c.act({"type": "wait"}, execution={"mode": "complete", "acknowledge": False})
        self.assertEqual(
            b.dispatches[r["dispatch_id"]]["dispatch"]["execution"]["mode"], "complete"
        )
        self.assertFalse(b.dispatches[r["dispatch_id"]]["dispatch"]["execution"]["acknowledge"])
        self.assertEqual(c.execution["mode"], "step")
        self.assertTrue(read_settings()["execution"]["acknowledge"])

    def test_invalid_update_leaves_existing_file_intact_and_reset_is_explicit(self):
        write_settings({"execution": {"mode": "complete"}})
        original = self.path.read_bytes()
        for update in (
            {"execution": {"mode": "safe"}},
            {"dispatch_timeout": 0},
            {"observation_view": "tiny"},
            {"risk": "low"},
        ):
            with self.assertRaises(ValueError):
                write_settings(update)
            self.assertEqual(self.path.read_bytes(), original)
        Client(port=1).settings(reset=True)
        self.assertEqual(read_settings()["execution"]["mode"], "step")

    def test_cli_settings_and_action_use_saved_policy_without_repeated_flags(self):
        with patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(
                main(
                    [
                        "--port",
                        "1",
                        "settings",
                        "--mode",
                        "complete",
                        "--acknowledge",
                        "--view",
                        "concise",
                    ]
                ),
                0,
            )
        b = Bridge(scene("before"), [scene("after")])
        with (
            patch.object(Client, "request", side_effect=b),
            patch("sys.stdout", new=io.StringIO()) as output,
        ):
            self.assertEqual(main(["--port", "1", "wait"]), 0)
            r = json.loads(output.getvalue())
        self.assertEqual(
            b.dispatches[r["dispatch_id"]]["dispatch"]["execution"]["mode"], "complete"
        )
        self.assertTrue(b.dispatches[r["dispatch_id"]]["dispatch"]["execution"]["acknowledge"])

    def test_full_status_is_not_filtered_or_turned_into_inputs_by_saved_settings(self):
        c = Client(port=1)
        c.settings(
            {"execution": {"mode": "complete", "acknowledge": True}, "observation_view": "concise"}
        )
        report = {
            "format": "character_status",
            "available": True,
            "character": {
                "health": {"wounds": 0, "flags": {"on_ground": False}},
                "personality": {"values": ["detail"]},
                "inventory": [],
                "unavailable": [{"path": "movement", "reason": "unknown"}],
            },
        }
        with patch.object(c, "request", return_value=report) as request:
            self.assertEqual(c.status(), report)
            brief = c.brief()
        self.assertEqual(
            [call.args[0]["op"] for call in request.call_args_list],
            ["character_status", "character_brief"],
        )
        self.assertIn("personality", brief["omitted_sections"])
        self.assertEqual(brief["character"]["health"]["wounds"], 0)
        self.assertIs(brief["character"]["health"]["flags"]["on_ground"], False)
        self.assertEqual(brief["character"]["unavailable"], report["character"]["unavailable"])

    def test_concise_view_preserves_choices_and_marks_omitted_reports(self):
        view = scene("modal")
        view["status"]["modal"] = {"kind": "unknown", "text": "Choose"}
        view["reports"] = [{"id": i, "text": str(i)} for i in range(20)]
        view["conversation"] = {
            "options": [{"id": "native-id", "label": "A choice", "visible": False}],
            "choices": [],
        }
        concise = concise_observation(view)
        self.assertEqual(concise["reports_omitted"], 8)
        self.assertEqual(concise["conversation"]["options"]["option"][0]["id"], "native-id")
        self.assertNotIn("visible", concise["conversation"]["options"]["option"][0])
        self.assertEqual(concise["status"]["modal"], view["status"]["modal"])
        self.assertNotIn("walkable", concise["map"])
        self.assertIn("walkable", view["map"])

    def test_dispatch_observes_full_internal_state_even_with_concise_saved_view(self):
        c = Client(port=1)
        c.settings({"execution": {"mode": "complete"}, "observation_view": "concise"})
        initial = scene("start")
        done = scene("end", x=2)
        b = Bridge(initial, [done])
        with patch.object(c, "request", side_effect=b):
            r = c.act({"type": "walk_to", "x": 2, "y": 1, "z": 0})
        self.assertEqual(r["outcome"], "completed")

    def test_absent_character_stays_unavailable_in_brief(self):
        report = {
            "available": False,
            "reason": "Map unloaded",
            "status": {"ready_for_input": False},
        }
        self.assertEqual(character_brief(report)["reason"], "Map unloaded")
        self.assertNotIn("character", character_brief(report))

    def test_brief_omits_native_history_but_preserves_conditions_and_unknown_needs(self):
        report = {
            "available": True,
            "character": {
                "health": {
                    "wounds": 0,
                    "paralysis": 0,
                    "flags": {"breathing_problem": False},
                    "native_counters": {"duplicated": "detail"},
                    "consumption_history": {"food": [1, 2]},
                },
                "physiology": {
                    "interpreted_needs": {
                        "available": False,
                        "reason": "Unsupported build",
                        "thirst": {"available": False, "reason": "Unknown", "counter": 0},
                    }
                },
            },
        }
        brief = character_brief(report)["character"]
        self.assertNotIn("native_counters", brief["health"])
        self.assertNotIn("consumption_history", brief["health"])
        self.assertEqual(brief["health"]["paralysis"], 0)
        self.assertIs(brief["health"]["flags"]["breathing_problem"], False)
        self.assertFalse(brief["physiology"]["interpreted_needs"]["available"])
        self.assertNotIn("label", brief["physiology"]["interpreted_needs"]["thirst"])
        self.assertIn("native_counters", report["character"]["health"])

    def test_concise_native_choices_omit_ui_boilerplate_and_keep_unknown_prompt_text(self):
        view = scene("tooltip")
        view["input_guard"] = {"native_complete": True}
        view["menu"] = {
            "options": [{"id": "target", "label": "Choice", "selection": {"key": "OPTION2"}}]
        }
        concise = concise_observation(view)
        self.assertNotIn("ui_text", concise)
        self.assertEqual(
            concise["menu"]["options"]["option"][0], {"id": "target", "label": "Choice"}
        )
        view["input_guard"]["native_complete"] = False
        self.assertEqual(concise_observation(view)["ui_text"], ["tooltip"])
