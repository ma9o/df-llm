import json
import unittest
from copy import deepcopy
from typing import Any
from unittest.mock import patch

from dfharness.client import Client
from dfharness.state import carrying_value, compact_result, contained_state, item_value
from tests.support import Bridge
from tests.test_receipts import receipt
from tests.test_strike import ACTION, combat, resolved
from tests.test_workflows import item, menu, scene


def bag(mode=None, ground=False):
    result = item(10, mode, ground=ground)
    child = item(11, ground=ground, container=10)
    child["stack_size"] = 1
    result.update(
        description="backpack",
        contents=[child],
        weight_computed=True,
        weight_raw={"whole": 5, "fraction": 0},
    )
    return result


def remaining():
    return dict(
        item(4, "Weapon"), weight_computed=True, weight_raw={"whole": 80, "fraction": 950500}
    )


class ObjectiveTests(unittest.TestCase):
    def test_drop_worn_bag_removes_then_drops_and_reports_what_the_controller_needs(self):
        worn, held, ground = bag("Worn"), bag("Weapon"), bag(ground=True)
        end = scene("end", [remaining()], [ground])
        end["adventurer"]["burden"] = {
            "available": True,
            "label": "Burdened",
            "source": "dfhack_lua_unit_burden",
        }
        bridge = Bridge(
            scene("start", [remaining(), worn]),
            [
                scene("remove", [remaining(), worn], choices=menu("REMOVE_ITEM", [10])),
                scene("held", [remaining(), held]),
                scene("drop", [remaining(), held], choices=menu("DROP_ITEM", [10])),
                end,
            ],
        )
        client = Client(port=1, execution={"mode": "complete", "acknowledge": True})
        with patch.object(client, "request", side_effect=bridge):
            result = client.act({"type": "drop", "item_id": 10})
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(
            [i.get("key") for i in bridge.inputs if i["type"] == "key"],
            ["A_INV_REMOVE", "A_INV_DROP"],
        )
        value = result["values"][0]
        self.assertTrue(value["contents"]["intact"])
        self.assertEqual(value["contents"]["ids"], [11])
        self.assertEqual(value["load"]["native_cached_weight_kg"], 80.9505)
        self.assertEqual(value["load"]["burden"]["label"], "Burdened")
        inventory = result["changes"]["inventory"]
        self.assertNotIn("removed", inventory)
        self.assertEqual(inventory["containers_removed"][0]["id"], 10)
        self.assertEqual(inventory["containers_removed"][0]["contents"], [11])
        self.assertLess(len(json.dumps(result)), 2000)
        self.assertFalse(any(q["op"] in ("character_status", "unit", "item") for q in bridge.calls))

    def test_remove_prerequisite_survives_step_resume_without_starting_again(self):
        worn, held, ground = bag("Worn"), bag("Weapon"), bag(ground=True)
        bridge = Bridge(
            scene("start", [worn]),
            [
                scene("remove", [worn], choices=menu("REMOVE_ITEM", [10])),
                scene("held", [held]),
                scene("drop", [held], choices=menu("DROP_ITEM", [10])),
                scene("end", ground=[ground]),
            ],
        )
        client = Client(port=1, execution={"mode": "complete"})
        with patch.object(client, "request", side_effect=bridge):
            result = client.act({"type": "drop", "item_id": 10}, execution={"mode": "step"})
            self.assertEqual(result["outcome"], "in_progress")
            for record in bridge.dispatches.values():
                record["workflow"] = json.loads(json.dumps(record["workflow"]))
            result = client.act(result["resume"])
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(len(bridge.inputs), 4)
        self.assertTrue(result["values"][0]["contents"]["intact"])

    def test_worn_stow_shares_the_same_prerequisite_and_never_discards_other_gear(self):
        worn, held = bag("Worn"), bag("Weapon")
        destination = item(12, "Worn")
        stowed = bag()
        stowed["location"]["container_id"] = 12
        bridge = Bridge(
            scene("start", [worn, destination]),
            [
                scene("remove", [worn, destination], choices=menu("REMOVE_ITEM", [12, 10])),
                scene("held", [held, destination]),
                scene("put", [held, destination], choices=menu("PUT_ITEM", [10])),
                scene(
                    "container",
                    [held, destination],
                    choices=menu(
                        "ENVIRONMENT_PLACE_IN_IT_CONTAINER",
                        [10],
                        context_item=10,
                        destinations=[12],
                    ),
                ),
                scene("end", [stowed, destination]),
            ],
        )
        client = Client(port=1, execution={"mode": "complete"})
        with patch.object(client, "request", side_effect=bridge):
            result = client.act({"type": "stow", "item_id": 10, "container_id": 12})
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(result["values"][0]["location"]["container_id"], 12)
        self.assertEqual(bridge.inputs[1]["option_id"], "option:REMOVE_ITEM:1:10")
        self.assertFalse(any(i.get("key") == "A_INV_DROP" for i in bridge.inputs))

    def test_missing_native_option_reports_facts_without_an_empty_choice_or_guesses(self):
        v = scene("blocked", [item(10, "Weapon")], choices=menu("DROP_ITEM", [20]))
        from dfharness.workflows import next_step

        decision = next_step(
            {"action": {"type": "drop", "item_id": 10}, "context": {"opened_for": ["drop", 10]}}, v
        )
        r = compact_result(
            receipt(
                v,
                "needs_input",
                action={"type": "drop", "item_id": 10},
                details=decision["details"],
            ),
            v,
        )
        self.assertEqual(r["blocker"]["facts"]["matching_options"], 0)
        self.assertEqual(r["blocker"]["facts"]["mode"], "Weapon")
        self.assertNotIn("choices", r)

    def test_load_and_contents_unknowns_are_not_zero_or_intact(self):
        before = contained_state(bag())
        after = bag(ground=True)
        after["contents_truncated"] = True
        view = scene("end", [item(4)], [after])
        value = item_value({"type": "drop", "item_id": 10}, view, before)
        self.assertIsNone(value["contents"]["intact"])
        self.assertNotIn("native_cached_weight_kg", value["load"])
        self.assertFalse(value["load"]["cached_weight_complete"])
        self.assertFalse(value["load"]["burden"]["available"])
        empty = carrying_value(scene("empty"))
        self.assertEqual(empty["native_cached_weight_kg"], 0)

    def test_strike_returns_target_condition_and_preserves_unknown_damage(self):
        after = resolved()
        condition = {
            "available": True,
            "alive": True,
            "prone": True,
            "conscious": True,
            "blood_count": 39982,
            "blood_max": 39999,
            "wounds": 5,
            "pain": 5,
            "exhaustion": 1699,
        }
        after["target_unit"] = {"id": 2, "condition": condition}
        bridge = Bridge(combat("AIM_ATTACK", flags=["quick"]), [after])
        client = Client(port=1, execution={"mode": "complete"})
        with patch.object(client, "request", side_effect=bridge):
            result = client.act(ACTION)
        value = result["values"][0]
        self.assertEqual(value["target"], condition)
        self.assertEqual(value["damage"], "unverified")
        self.assertEqual(result["outcome"], "completed")
        self.assertLess(len(json.dumps(result)), 1800)
        self.assertFalse(any(q["op"] == "unit" for q in bridge.calls))

    def test_missing_target_condition_does_not_reuse_a_different_target(self):
        after = resolved()
        after["target_unit"] = {"id": 999, "condition": {"alive": False}}
        from dfharness.strike import next_strike

        r = next_strike({"action": deepcopy(ACTION), "context": {"input_evidence_for": "a"}}, after)
        self.assertFalse(r["details"]["value"]["target"]["available"])

    def test_not_living_is_not_mistaken_for_a_dead_attack_target(self):
        view = combat("AIM_ATTACK", flags=["quick"])
        view["target_unit"] = {
            "id": 2,
            "alive": False,
            "condition": {"available": True, "dead": False},
        }
        from dfharness.strike import next_strike

        r = next_strike({"action": deepcopy(ACTION), "context": {}}, view)
        self.assertEqual(r["input"], {"type": "select_interaction", "option_id": "hammer"})

    def test_batches_return_one_current_load_and_each_targets_latest_condition(self):
        view = scene("batch", [remaining()])
        view["adventurer"]["burden"] = {"available": True, "label": "Burdened"}
        target = {"available": True, "prone": True, "conscious": True, "blood_count": 39982}
        stages: list[dict[str, Any]] = []
        for index in range(16):
            stages.append(
                {
                    "stage_index": index,
                    "details": {
                        "value": {
                            "kind": "stow",
                            "item_id": 100 + index,
                            "load": carrying_value(view),
                        }
                    },
                }
            )
        for index in range(16, 19):
            stages.append(
                {
                    "stage_index": index,
                    "details": {
                        "value": {
                            "kind": "strike",
                            "unit_id": 2,
                            "target": target,
                            "resolution": "processed",
                        }
                    },
                }
            )
        receipt(view, action={"type": "sequence", "actions": []})
        view["dispatch"]["results"] = stages
        result = compact_result(view, scene("before", [remaining()]))
        self.assertEqual(result["assessment"]["load"]["native_cached_weight_kg"], 80.9505)
        self.assertEqual(sum("target" in v for v in result["values"]), 1)
        self.assertEqual(result["values"][-1]["target"], target)
        self.assertFalse(any("load" in v for v in result["values"]))
        self.assertTrue(all("load" in s["details"]["value"] for s in stages[:16]))
        self.assertLess(len(json.dumps(result)), 2300)
