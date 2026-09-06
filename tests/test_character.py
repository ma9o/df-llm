import contextlib
import io
import json
import unittest
from unittest.mock import patch

from dfharness.cli import main
from dfharness.client import Client, make_program, render_observation
from dfharness.mcp import Server, TOOLS
from dfharness.state import compact_result


def sheet(available=True):
    result = {"format": "character_status", "schema_version": 2, "available": available,
              "state_id": "character-state", "effect_id": "unchanged",
              "status": {"df_version": "test", "dfhack_version": "test", "ready_for_input": False,
                         "modal": {"kind": "help"}}}
    if not available:
        result["reason"] = "No active adventurer is available"
        return result
    result["character"] = {
        "id": 5, "name": "Athis Pridesings", "position": {"x": 70, "y": 68, "z": 128},
        "identity": {"profession": "Hammerman"}, "health": {"wounds": 1, "flags": {"unconscious": False}},
        "attributes": {"physical": [{"name": "STRENGTH", "value": 1100, "effective": 950, "max_value": 2200}]},
        "skills": [{"name": "HAMMER", "rating": 1, "rating_name": "Novice", "effective": 0, "experience": 5}],
        "needs": {"physical": {"hunger_timer": 9261}},
        "body": {"parts": [{"id": 1, "name": "left hand", "active_status_flags": ["missing"]}],
                 "wounds": [{"id": 9, "parts": [{"body_part_id": 1, "bleeding": 77}]}]},
        "inventory": [{"id": 495, "description": "backpack", "mode": "Worn", "contents": [
            {"id": 14434, "description": "green jade gem", "location": {"container_id": 495}}]}],
        "encumbrance": {"weight_complete": True, "total_weight_kg": 98.46225, "known_weight_kg": 98.46225,
                        "by_mode": [{"mode": "Worn", "weight_complete": True, "weight_kg": 98.46225}],
                        "heaviest_items": [{"id": 495, "description": "backpack", "weight_kg": 17.51175}],
                        "capacity": {"available": False, "reason": "Unverified on this build"},
                        "load_penalty": {"available": False, "reason": "Unverified on this build"}},
        "movement": {"displayed_speed": {"value": 0.471, "text": "0.471", "gait": "Walk"}},
        "unavailable": [{"path": "movement.effective_speed", "reason": "Not supported"}],
        "truncated": [{"path": "personality.emotions", "total": 102, "limit": 100}],
    }
    return result


class CharacterStatusTests(unittest.TestCase):
    def test_status_alias_and_lightweight_game_status_are_distinct_read_only_requests(self):
        client = Client(port=1, execution={"mode": "complete", "acknowledge": True})
        with patch.object(client, "request", return_value=sheet()) as request:
            self.assertEqual(client.status(), sheet())
            request.assert_called_once_with({"op": "character_status"})
            request.reset_mock()
            client.game_status()
            request.assert_called_once_with({"op": "status"})

    def test_character_query_is_one_read_even_with_automatic_execution_defaults(self):
        client = Client(port=1, execution={"mode": "complete", "acknowledge": True})
        expected = sheet()
        with patch.object(client, "request", return_value=expected) as request:
            self.assertEqual(client.character_status(), expected)
        request.assert_called_once_with({"op": "character_status"})

    def test_large_character_reader_is_only_loaded_for_character_queries(self):
        marker = "Read-only character sheet. Loaded only for character_status requests."
        self.assertIn(marker, make_program({"op": "character_status"}))
        self.assertNotIn(marker, make_program({"op": "observe"}))
        self.assertNotIn(marker, make_program({"op": "status"}))
        details = "Character-owned profiles and capabilities. Only loaded by character queries."
        self.assertIn(details, make_program({"op": "character_status"}))
        self.assertNotIn(details, make_program({"op": "observe"}))
        calculations = "Read-only DF 53.16 Windows calculations"
        self.assertIn(calculations, make_program({"op": "character_status"}))
        self.assertNotIn(calculations, make_program({"op": "observe"}))
        self.assertNotIn(calculations, make_program({"op": "status"}))

    def test_mcp_character_query_is_read_only_and_rejects_execution_options(self):
        client = Client(port=1)
        server = Server(client)
        server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        tool = next(t for t in TOOLS if t["name"] == "df_character_status")
        self.assertTrue(tool["annotations"]["readOnlyHint"])
        self.assertFalse(tool["annotations"]["destructiveHint"])
        message = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                   "params": {"name": "df_character_status", "arguments": {}}}
        with patch.object(client, "request", return_value=sheet()) as request:
            result = server.handle(message)["result"]
            self.assertFalse(result["isError"])
            self.assertEqual(json.loads(result["content"][0]["text"])["state_id"], "character-state")
            self.assertEqual(json.loads(result["content"][0]["text"])["character"]["encumbrance"],
                             sheet()["character"]["encumbrance"])
            message["params"]["arguments"] = {"execution": {"acknowledge": True}}
            self.assertTrue(server.handle(message)["result"]["isError"])
            request.assert_called_once_with({"op": "character_status"})

    def test_cli_returns_the_character_sheet_without_dispatching(self):
        output = io.StringIO()
        with patch("dfharness.cli.Client") as client, contextlib.redirect_stdout(output):
            client.return_value.character_status.return_value = sheet()
            self.assertEqual(main(["--mode", "complete", "--acknowledge", "character-status"]), 0)
            client.return_value.character_status.assert_called_once_with()
            client.return_value.act.assert_not_called()
        self.assertEqual(json.loads(output.getvalue()), sheet())

    def test_status_cli_returns_full_character_report_and_text_sections(self):
        for text in (False, True):
            with self.subTest(text=text), patch("dfharness.cli.Client") as client, contextlib.redirect_stdout(io.StringIO()) as output:
                client.return_value.status.return_value = sheet()
                self.assertEqual(main(["status"] + (["--text"] if text else [])), 0)
                client.return_value.status.assert_called_once_with()
                client.return_value.act.assert_not_called()
                if text:
                    self.assertIn("Carried weight: 98.46225 kg", output.getvalue())
                else:
                    self.assertEqual(json.loads(output.getvalue()), sheet())

    def test_mcp_status_alias_and_lightweight_readiness_tool(self):
        client = Client(port=1)
        server = Server(client)
        server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        for name, op in (("df_status", "character_status"), ("df_game_status", "status")):
            tool = next(t for t in TOOLS if t["name"] == name)
            self.assertTrue(tool["annotations"]["readOnlyHint"])
            with self.subTest(tool=name), patch.object(client, "request", return_value=sheet()) as request:
                result = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                        "params": {"name": name, "arguments": {}}})["result"]
                self.assertFalse(result["isError"])
                request.assert_called_once_with({"op": op})

    def test_text_preserves_every_section_including_new_and_nested_data(self):
        result = sheet()
        result["character"].update({"abilities": {"body": [{"name": "Spit", "cooldown_raw": 0}]},
                                    "relationships": {"family": []}, "reputation": {"present": False},
                                    "future_section": {"nested": {"arbitrary_detail": False}}})
        text = render_observation(result)
        for key, value in result["character"].items():
            self.assertIn("# " + key.replace("_", " ").capitalize() + ": " + json.dumps(value, ensure_ascii=False), text)

    def test_no_adventurer_is_explicit_in_json_and_reading_view(self):
        client = Client(port=1)
        with patch.object(client, "request", return_value=sheet(False)):
            result = client.character_status()
        self.assertFalse(result["available"])
        self.assertNotIn("character", result)
        self.assertIn("No active adventurer", render_observation(result))

    def test_reading_view_preserves_impairments_items_and_missing_data(self):
        text = render_observation(sheet())
        for expected in ("STRENGTH: 1100 / 950 / 2200", "effective 0", '"bleeding": 77',
                         "left hand", "missing", "14434", '"container_id": 495',
                         "movement.effective_speed", "personality.emotions", "character-state"):
            self.assertIn(expected, text)

    def test_reading_view_includes_load_contributors_and_displayed_speed(self):
        text = render_observation(sheet())
        for expected in ("# Encumbrance", "Carried weight: 98.46225 kg", "Worn: 98.46225 kg",
                         "backpack — 17.51175 kg", "HUD movement: Walk 0.471",
                         "Carrying capacity: unavailable", "Load penalty: unavailable"):
            self.assertIn(expected, text)

    def test_reading_view_does_not_present_partial_load_as_a_total(self):
        result = sheet()
        load = result["character"]["encumbrance"]
        load.update(weight_complete=False, known_weight_kg=2.75,
                    unweighed_items=[{"id": 495, "reason": "Invalid weight cache"}])
        del load["total_weight_kg"]
        del result["character"]["movement"]["displayed_speed"]
        text = render_observation(result)
        self.assertIn("Carried weight: unknown; known subtotal 2.75 kg", text)
        self.assertIn("Invalid weight cache", text)
        self.assertIn("HUD movement: unavailable", text)

    def test_reading_view_preserves_zero_load_and_zero_displayed_speed(self):
        result = sheet()
        result["character"]["encumbrance"].update(total_weight_kg=0, known_weight_kg=0, by_mode=[], heaviest_items=[])
        result["character"]["movement"]["displayed_speed"].update(value=0, text="0.000")
        text = render_observation(result)
        self.assertIn("Carried weight: 0 kg", text)
        self.assertIn("HUD movement: Walk 0.000", text)

    def test_compact_changes_preserve_weight_cache_invalidation(self):
        item = {"id": 495, "weight_raw": {"whole": 17, "fraction": 511750}, "weight_computed": True}
        before = {"adventurer": {"inventory": [item]}}
        after = {"adventurer": {"inventory": [{**item, "weight_computed": False}]}}
        changed = compact_result(after, before)["changes"]["inventory_changed"]
        self.assertEqual(len(changed), 1)
        self.assertTrue(changed[0]["before"]["weight_computed"])
        self.assertFalse(changed[0]["after"]["weight_computed"])

    def test_reading_summary_includes_calculations_and_need_stages_without_hud(self):
        result = sheet()
        c = result["character"]
        c["encumbrance"]["capacity"] = {"available": True, "weight_kg": 63.04}
        c["encumbrance"]["load_penalty"] = {"available": True, "movement_cost_added": 1123,
                                             "speed_reduction_percent": 52.896844, "excess_weight_kg": 35.42}
        c["movement"] = {"effective_speed": {"available": True, "gait": "Walk", "displayed_text": "0.471",
                                             "unloaded": {"displayed_text": "1.000"}}}
        c["physiology"] = {"interpreted_needs": {"available": True,
            "hunger": {"label": "No warning", "severity": 0, "counter": 0,
                       "next_stage": {"label": "Hungry", "counter": 57600, "remaining_counter": 57600}},
            "thirst": {"label": "Dehydrated", "severity": 4, "counter": 345600},
            "sleep": {"label": "Not required", "severity": 0, "counter": 0}}}
        text = render_observation(result)
        for expected in ("Carrying capacity: 63.04 kg before movement penalty", "52.90% lower speed",
                         "HUD movement: unavailable", "Calculated movement: Walk 0.471", "unloaded 1.000",
                         "Hunger: No warning (severity 0; counter 0)", "next: Hungry at 57600",
                         "Thirst: Dehydrated", "Sleep: Not required"):
            self.assertIn(expected, text)

    def test_zero_load_penalty_is_rendered_and_unknown_percentage_is_not_zero(self):
        result = sheet()
        penalty = {"available": True, "movement_cost_added": 0, "excess_weight_kg": 0, "speed_reduction_percent": 0}
        result["character"]["encumbrance"]["load_penalty"] = penalty
        self.assertIn("0.00% lower speed", render_observation(result))
        del penalty["speed_reduction_percent"]
        text = render_observation(result)
        self.assertIn("Load penalty: +0 movement cost", text)
        self.assertNotIn("0.00% lower speed", text)

    def test_native_burden_label_is_prominent_and_unknown_is_not_unburdened(self):
        result = sheet()
        result["character"]["encumbrance"]["burden"] = {"available": True, "label": "Overburdened",
                                                          "capacity_used_percent": 156.186548}
        self.assertIn("Burden: Overburdened (156.19% of capacity)", render_observation(result))
        result["character"]["encumbrance"]["burden"] = {"available": False, "reason": "Invalid weight cache"}
        text = render_observation(result)
        self.assertIn("Burden: unavailable — Invalid weight cache", text)
        self.assertNotIn("Burden: Unburdened", text)
