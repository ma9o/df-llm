import unittest
from copy import deepcopy
from unittest.mock import patch

from dfharness.client import Client
from tests.support import Bridge
from tests.test_workflows import scene


def movement(name, selected=3, opened=False):
    v = scene(name)
    v["adventurer"]["movement"] = {
        "available": True,
        "sneaking": False,
        "selected_gaits": {"WALK": selected},
    }
    if opened:
        v["status"]["can_move"] = False
        v["menu"] = {
            "kind": "movement",
            "open": True,
            "unit_id": 1,
            "gait_type": "WALK",
            "options": [
                {
                    "id": f"gait:{i}",
                    "kind": "gait",
                    "gait_type": "WALK",
                    "gait_index": i,
                    "label": label,
                    "index": i,
                    "visible": True,
                }
                for i, label in enumerate(("Sprint", "Run", "Jog", "Walk"))
            ],
        }
    return v


class MovementTests(unittest.TestCase):
    def test_sneaking_is_explicit_idempotent_and_verifies_false(self):
        before = movement("before")
        before["adventurer"]["movement"]["sneaking"] = True
        after = movement("off")
        b = Bridge(before, [after])
        c = self.client(b)
        r = c.act({"type": "set_sneaking", "enabled": False})
        self.assertEqual(r["changes"]["movement.sneaking"], [True, False])
        self.assertEqual(b.inputs, [{"type": "key", "key": "A_SNEAK"}])
        self.assertEqual(c.act({"type": "set_sneaking", "enabled": False})["inputs"], 0)

    def client(self, bridge):
        c = Client(port=1, execution={"mode": "complete", "acknowledge": True})
        p = patch.object(c, "request", side_effect=bridge)
        p.start()
        self.addCleanup(p.stop)
        return c

    def test_named_gait_opens_selects_verifies_closes_and_reports_only_change(self):
        b = Bridge(
            movement("before"),
            [movement("open", opened=True), movement("jog", 2, True), movement("closed", 2)],
        )
        r = self.client(b).act({"type": "set_gait", "gait": "Jog"})
        self.assertEqual(r["outcome"], "completed")
        self.assertEqual(
            b.inputs,
            [
                {"type": "key", "key": "A_MOVEMENT"},
                {"type": "select_option", "option_id": "gait:2"},
                {"type": "key", "key": "LEAVESCREEN"},
            ],
        )
        self.assertEqual(r["changes"], {"movement.selected_gaits.WALK": [3, 2]})
        self.assertNotIn("choices", r)

    def test_no_effect_is_not_retried_and_undelegated_gait_is_not_substituted(self):
        for label, after, outcome in (
            ("Jog", [movement("wrong-gait", 0, True)], "no_effect"),
            ("Gallop", [], "needs_input"),
        ):
            b = Bridge(movement("menu", opened=True), after)
            r = self.client(b).act({"type": "set_gait", "gait": label})
            self.assertEqual(r["outcome"], outcome)
            self.assertEqual(len(b.inputs), len(after))
        self.assertIn("gait", r["choices"]["options"])

    def test_resume_after_selection_closes_without_selecting_again(self):
        b = Bridge(movement("menu", opened=True), [movement("jog", 2, True), movement("closed", 2)])
        c = self.client(b)
        r = c.act({"type": "set_gait", "gait": "jog"}, execution={"mode": "step"})
        self.assertEqual(r["outcome"], "in_progress")
        resumed = c.act(r["resume"])
        self.assertEqual(resumed["outcome"], "completed")
        self.assertEqual([a["type"] for a in b.inputs], ["select_option", "key"])

    def test_unknown_settings_wrong_target_and_failed_close_remain_explicit(self):
        for mutate in (
            lambda v: v["adventurer"].pop("movement"),
            lambda v: v["menu"].update(unit_id=2),
        ):
            v = movement("menu", opened=True)
            mutate(v)
            b = Bridge(v, [])
            self.assertEqual(
                self.client(b).act({"type": "set_gait", "gait": "Jog"})["outcome"], "needs_input"
            )
            self.assertEqual(b.inputs, [])
        before = movement("menu", opened=True)
        unchanged = deepcopy(before)
        unchanged["effect_id"] = "refresh"
        b = Bridge(before, [unchanged])
        r = self.client(b).act({"type": "set_gait", "gait": "Walk"})
        self.assertEqual(r["outcome"], "no_effect")
        self.assertEqual(len(b.inputs), 1)
