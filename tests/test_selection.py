import unittest
from unittest.mock import patch

from dfharness.selection import selection_input
from tests.support import Bridge
from tests.support import FullClient as Client
from tests.test_workflows import item, menu, scene


class NativeSelectionTests(unittest.TestCase):
    def test_shared_selection_honors_panel_blockers_for_recipes(self):
        initial, _ = self.fixtures()
        initial["menu"]["selection_unavailable"] = "Finish entering the quantity first"
        bridge = Bridge(initial)
        client = Client(port=1, execution={"mode": "complete"})
        with patch.object(client, "request", side_effect=bridge):
            result = client.act({"type": "equip", "item_id": 7})
        self.assertEqual(result["dispatch"]["outcome"], "needs_input")
        self.assertIn("quantity", result["dispatch"]["reason"])
        self.assertFalse(bridge.inputs)

    def test_rendered_ambiguity_returns_a_choice_blocker_without_blind_scrolling(self):
        initial = scene("ambiguous", choices=menu("WEAR_ITEM", [7]))
        option = initial["menu"]["options"][0]
        option.update(selection_unavailable="Rendered option labels are ambiguous on this page")
        bridge = Bridge(initial)
        client = Client(port=1, execution={"mode": "complete"})
        with patch.object(client, "request", side_effect=bridge):
            result = client.act({"type": "select_option", "option_id": option["id"]})
        self.assertEqual(result["dispatch"]["outcome"], "needs_input")
        self.assertIn("ambiguous", result["dispatch"]["reason"])
        self.assertFalse(bridge.inputs)

    def fixtures(self):
        initial = menu("WEAR_ITEM", [7])
        option = initial["options"][0]
        option.pop("visible")
        option.update(index=48, selection={"method": "native_hotkey", "scroll_to": 48})
        before = scene("initial", [item(7, "Hauled")], choices=initial)
        completed = scene("worn", [item(7, "Worn")])
        return before, completed

    def test_offscreen_equip_normalizes_and_selects_in_one_guarded_input(self):
        before, done = self.fixtures()
        bridge = Bridge(before, [done])

        def request(value):
            result = bridge(value)
            if value["op"] == "act":
                result.update(input_key="OPTION9", ui_adjustment={"requested": 48, "effective": 40})
            return result

        client = Client(port=1, execution={"mode": "complete"})
        with patch.object(client, "request", side_effect=request):
            result = client.act({"type": "equip", "item_id": 7})
        self.assertEqual([a["type"] for a in bridge.inputs], ["select_option"])
        self.assertEqual(result["dispatch"]["outcome"], "completed")
        self.assertEqual(len(result["dispatch"]["steps"]), 1)
        self.assertEqual(result["dispatch"]["steps"][0]["input_key"], "OPTION9")
        self.assertEqual(result["dispatch"]["steps"][0]["ui_adjustment"]["effective"], 40)

    def test_step_and_resume_do_not_repeat_completed_selection(self):
        before, equipped = self.fixtures()
        bridge = Bridge(before, [equipped, scene("arrived", [item(7, "Worn")], x=2)])
        client = Client(port=1)
        with patch.object(client, "request", side_effect=bridge):
            step = client.act(
                {
                    "type": "sequence",
                    "actions": [
                        {"type": "equip", "item_id": 7},
                        {"type": "walk_to", "x": 2, "y": 1, "z": 0},
                    ],
                }
            )
            self.assertEqual(step["dispatch"]["outcome"], "in_progress")
            done = client.act(step["dispatch"]["resume_action"], execution={"mode": "complete"})
        self.assertEqual(done["dispatch"]["outcome"], "completed")
        self.assertEqual([a["type"] for a in bridge.inputs], ["select_option", "move"])

    def test_explicit_option_dispatch_handles_its_own_scroll(self):
        initial, done = self.fixtures()
        bridge = Bridge(initial, [done])
        client = Client(port=1, execution={"mode": "complete"})
        with patch.object(client, "request", side_effect=bridge):
            result = client.act(
                {"type": "select_option", "option_id": initial["menu"]["options"][0]["id"]}
            )
        self.assertEqual(result["dispatch"]["outcome"], "completed")
        self.assertEqual(len(bridge.inputs), 1)

    def test_selection_without_verified_equipping_is_not_retried(self):
        initial, _ = self.fixtures()
        bridge = Bridge(initial, [initial])
        client = Client(port=1, execution={"mode": "complete"})
        with patch.object(client, "request", side_effect=bridge):
            result = client.act({"type": "equip", "item_id": 7})
        self.assertEqual(result["dispatch"]["outcome"], "needs_input")
        self.assertIn("postcondition", result["dispatch"]["reason"])
        self.assertEqual(len(bridge.inputs), 1)

    def test_option_enum_range_does_not_predict_rendered_page_size(self):
        initial, done = self.fixtures()
        initial["menu"]["options"][0].update(
            index=15, selection={"method": "native_hotkey", "scroll_to": 15}
        )
        bridge = Bridge(initial, [done])
        client = Client(port=1, execution={"mode": "complete"})
        with patch.object(client, "request", side_effect=bridge):
            result = client.act({"type": "equip", "item_id": 7})
        self.assertEqual(result["dispatch"]["outcome"], "completed")
        self.assertEqual([a["type"] for a in bridge.inputs], ["select_option"])

    def test_raw_ui_input_uses_ui_guard_but_recipe_key_uses_native_guard(self):
        for action in ({"type": "key", "key": "A_INV_WEAR"}, {"type": "equip", "item_id": 7}):
            initial = scene("initial", [item(7, "Hauled")])
            initial["ui_state_id"] = "u2:rendered"
            bridge = Bridge(initial, [scene("open", [item(7, "Worn")])])
            client = Client(port=1, execution={"mode": "complete"})
            with patch.object(client, "request", side_effect=bridge):
                client.act(action)
            sent = next(c for c in bridge.calls if c["op"] == "act")
            self.assertEqual(
                sent["expect"], "u2:rendered" if action["type"] == "key" else initial["state_id"]
            )

    def test_conversation_scroll_direction_uses_visible_options_not_line_offset(self):
        choices = {
            "kind": "conversation",
            "scroll": 48,
            "options": [
                {"index": 15, "visible": True},
                {"index": 16, "visible": True},
            ],
        }
        for index, direction in [(18, "PAGEDOWN"), (4, "PAGEUP")]:
            selected = selection_input(
                choices, {"id": "target", "index": index}, "select_interaction"
            )
            self.assertEqual(selected, {"type": "key", "key": "ADVENTURE_LIST_SCROLL_" + direction})
