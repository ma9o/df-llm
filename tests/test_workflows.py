import json
import unittest
from copy import deepcopy
from typing import Any
from unittest.mock import patch

from dfharness.rpc import DFHackError, DispatchError
from dfharness.state import compact_result
from dfharness.workflows import next_walk
from tests.support import Bridge
from tests.support import FullClient as Client


def item(item_id, mode=None, *, ground=False, container=None, x=1):
    location: dict[str, Any] = {"kind": "ground" if ground else "inventory"}
    result: dict[str, Any] = {
        "id": item_id,
        "description": "identical boot",
        "type": "SHOES",
        "quality": 2,
        "location": location,
    }
    if ground:
        location["position"] = {"x": x, "y": 1, "z": 0}
    if container is not None:
        location["container_id"] = container
    if mode:
        result.update(mode=mode, body_part_id=15)
        location.update(mode=mode, body_part_id=15)
    return result


def menu(kind, ids, *, visible=None, scroll=0, context_item=None, destinations=None):
    options = []
    for index, item_id in enumerate(ids):
        o = {
            "id": f"option:{kind}:{index}:{item_id}",
            "item_id": item_id,
            "index": index,
            "label": "identical boot",
            "kind": kind,
        }
        if visible is None or index in visible:
            o["visible"] = True
        if destinations:
            o["container_id"] = destinations[index]
        options.append(o)
    result = {
        "kind": "option_list" if kind.startswith("ENVIRONMENT_PICK") else "inventory",
        "context": kind,
        "scroll": scroll,
        "options": options,
    }
    if context_item is not None:
        result["context_item_id"] = context_item
    return result


def scene(name, carried=(), ground=(), *, choices=None, x=1, blood=1000, reports=(), units=()):
    return {
        "state_id": "state-" + name,
        "effect_id": name,
        "status": {
            "can_move": choices is None,
            "ready_for_input": True,
            "adventurer_id": 1,
            "position": {"x": x, "y": 1, "z": 0},
        },
        "adventurer": {
            "id": 1,
            "health": {"blood_count": blood, "wounds": 0},
            "inventory": list(carried),
        },
        "nearby_items": list(ground),
        "menu": choices,
        "reports": list(reports),
        "ui": {"rows": [{"y": 10, "text": name}]},
        "map": {
            "origin": {"x": 0, "y": 0, "z": 0},
            "walkable": ["11111"] * 3,
            "liquid_depths": ["00000"] * 3,
            "units": list(units),
        },
    }


class WorkflowTests(unittest.TestCase):
    def test_large_controller_budget_keeps_completion_limits_and_injury_checks(self):
        def walking_scene(x, *, blood=1000):
            value = scene(str(x), x=x, blood=blood)
            value["map"]["walkable"] = ["1" * 75] * 3
            value["map"]["liquid_depths"] = ["0" * 75] * 3
            return value

        action = {"type": "walk_to", "x": 71, "y": 1, "z": 0}
        for budget, injured, expected, inputs in (
            (70, False, "completed", 70),
            (65, False, "limit_reached", 65),
            (70, True, "interrupted", 65),
        ):
            with self.subTest(budget=budget, injured=injured):
                b = Bridge(
                    walking_scene(1),
                    [
                        walking_scene(x, blood=900 if injured and x >= 66 else 1000)
                        for x in range(2, 72)
                    ],
                )
                receipt = self.client(b).act(
                    action, execution={"max_steps": budget, "interrupt_on": {"blood_loss": True}}
                )
                self.assertEqual(receipt["dispatch"]["outcome"], expected)
                self.assertEqual(len(b.inputs), inputs)
                if expected == "limit_reached":
                    resumed = self.client(b).act(receipt["dispatch"]["resume_action"])
                    self.assertEqual(resumed["dispatch"]["outcome"], "completed")
                    self.assertEqual(len(b.inputs), 70)

    def test_pickup_reports_fresh_native_grasp_refusal_without_choosing_equipment(self):
        held = [item(8, "Weapon"), item(9, "Hauled")]
        ground = [item(2, ground=True)]
        for cursor in (10, 11):
            with self.subTest(report_cursor=cursor):
                offered = scene(
                    "menu", held, ground, choices=menu("ENVIRONMENT_PICK_UP_GROUND_ITEM", [2])
                )
                offered["report_cursor"] = cursor
                refusal = {"id": 11, "type": "NO_GRASP_FOR_PICKUP", "text": "No free grasp."}
                b = Bridge(
                    scene("before", held, ground),
                    [offered, scene("refused", held, ground, reports=[refusal])],
                )
                d = self.client(b).act({"type": "pickup", "item_id": 2})["dispatch"]
                self.assertEqual(d["outcome"], "needs_input")
                self.assertEqual([i["type"] for i in b.inputs], ["key", "select_option"])
                if cursor == 10:
                    self.assertEqual(d["details"]["blocker_kind"], "native_refusal")
                    self.assertEqual(
                        d["details"]["facts"],
                        {
                            "item_id": 2,
                            "type": "NO_GRASP_FOR_PICKUP",
                            "report_id": 11,
                            "held_item_ids": [8, 9],
                        },
                    )
                else:
                    self.assertNotEqual(d.get("details", {}).get("blocker_kind"), "native_refusal")

    def test_walking_retains_its_destination_across_a_local_map_rebase(self):
        before, middle, done = scene("before"), scene("middle"), scene("done", x=2)
        before["status"]["map_origin"] = {"x": 100, "y": 100, "z": 0}
        middle["status"]["map_origin"] = done["status"]["map_origin"] = {"x": 101, "y": 100, "z": 0}
        b = Bridge(before, [middle, done])
        c = Client(port=1, execution={"mode": "complete"})
        with patch.object(c, "request", side_effect=b):
            r = c.act({"type": "walk_to", "x": 3, "y": 1, "z": 0})
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        self.assertEqual(len(b.inputs), 2)
        polls = [p for p in b.calls if p["op"] == "poll" and "route_target" in p]
        self.assertEqual(polls[-1]["route_target"], {"absolute": {"x": 103, "y": 101, "z": 0}})

    def test_unit_on_another_z_level_does_not_block_the_local_route(self):
        v = scene("before", units=[{"id": 2, "position": {"x": 2, "y": 1, "z": 1}}])
        r = next_walk(v, {"x": 2, "y": 1, "z": 0}, {})
        self.assertEqual(r["pending"]["destination"], {"x": 2, "y": 1, "z": 0})

    def client(self, bridge, execution=None):
        c = Client(port=1, execution=execution or {"mode": "complete", "acknowledge": True})
        patcher = patch.object(c, "request", side_effect=bridge)
        patcher.start()
        self.addCleanup(patcher.stop)
        return c

    def test_displacement_replans_with_constraints_but_no_movement_is_not_retried(self):
        action = {
            "type": "walk_to",
            "x": 4,
            "y": 1,
            "z": 0,
            "blocked_tiles": [{"x": 2, "y": 1, "z": 0}],
        }
        displaced = scene("pushed", x=1)
        displaced["status"]["position"]["y"] = 0
        at_two = scene("two", x=2)
        at_two["status"]["position"]["y"] = 0
        b = Bridge(scene("before"), [displaced, at_two, scene("three", x=3), scene("done", x=4)])
        r = self.client(b).act(action)
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        self.assertEqual(b.inputs[1], {"type": "move", "direction": "e"})
        stopped = Bridge(scene("before"), [scene("unchanged")])
        c = self.client(stopped)
        r = c.act(action)
        self.assertEqual(r["dispatch"]["outcome"], "no_effect")
        self.assertEqual(c.act(r["dispatch"]["resume_action"])["dispatch"]["outcome"], "no_effect")
        self.assertEqual(len(stopped.inputs), 1)

    def test_pickup_approaches_scrolls_and_selects_by_id_among_identical_labels(self):
        ground = [item(2, ground=True, x=2), item(3, ground=True, x=2)]
        hidden = menu("ENVIRONMENT_PICK_UP_GROUND_ITEM", [3, 2], visible={0})
        shown = menu("ENVIRONMENT_PICK_UP_GROUND_ITEM", [3, 2], visible={1}, scroll=1)
        b = Bridge(
            scene("before", ground=ground),
            [
                scene("arrived", ground=ground, x=2),
                scene("menu", ground=ground, choices=hidden, x=2),
                scene("scroll", ground=ground, choices=shown, x=2),
                scene("picked", [item(2, container=99)], [ground[1]], x=2),
            ],
        )
        r = self.client(b).act({"type": "pickup", "item_id": 2})
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        self.assertEqual([a["type"] for a in b.inputs], ["move", "key", "key", "select_option"])
        self.assertEqual(b.inputs[-1]["option_id"], "option:ENVIRONMENT_PICK_UP_GROUND_ITEM:1:2")
        self.assertEqual(r["adventurer"]["inventory"][0]["id"], 2)

    def test_step_resume_continues_without_reopening_or_repeating_input(self):
        b = Bridge(
            scene("before", [item(2, "Weapon")]),
            [
                scene("menu", [item(2, "Weapon")], choices=menu("DROP_ITEM", [2])),
                scene("done", ground=[item(2, ground=True)]),
            ],
        )
        c = self.client(b)
        first = c.act({"type": "drop", "item_id": 2}, execution={"mode": "step"})
        self.assertEqual(first["dispatch"]["outcome"], "in_progress")
        self.assertEqual(len(b.inputs), 1)
        resumed = c.act(first["dispatch"]["resume_action"])
        self.assertEqual(resumed["dispatch"]["outcome"], "completed")
        self.assertEqual([a["type"] for a in b.inputs], ["key", "select_option"])

    def test_failed_pickup_does_not_complete_or_repeat_selection(self):
        ground = [item(2, ground=True)]
        b = Bridge(
            scene("before", ground=ground),
            [
                scene("menu", ground=ground, choices=menu("ENVIRONMENT_PICK_UP_GROUND_ITEM", [2])),
                scene("refused", ground=ground, reports=[{"id": 1, "text": "Cannot lift it."}]),
            ],
        )
        r = self.client(b).act({"type": "pickup", "item_id": 2})
        self.assertEqual(r["dispatch"]["outcome"], "needs_input")
        self.assertIn("postcondition", r["dispatch"]["reason"])
        self.assertEqual(len(b.inputs), 2)
        self.assertEqual(r["dispatch"]["events"][0]["text"], "Cannot lift it.")

    def test_equip_replaces_only_named_item_and_disposes_after_verified_wearing(self):
        old, other, new = item(2, "Worn"), item(4, "Worn"), item(3, container=99)
        held, worn = item(2, "Weapon"), item(3, "Worn")
        b = Bridge(
            scene("before", [old, other, new]),
            [
                scene("remove-menu", [old, other, new], choices=menu("REMOVE_ITEM", [4, 2])),
                scene("removed", [held, other, new]),
                scene("wear-menu", [held, other, new], choices=menu("WEAR_ITEM", [3])),
                scene("worn", [held, other, worn]),
                scene("drop-menu", [held, other, worn], choices=menu("DROP_ITEM", [2])),
                scene("done", [other, worn], [item(2, ground=True)]),
            ],
        )
        r = self.client(b).act(
            {"type": "equip", "item_id": 3, "replace": [2], "disposition": "drop"}
        )
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        selected = [a["option_id"] for a in b.inputs if a["type"] == "select_option"]
        self.assertEqual(
            selected, ["option:REMOVE_ITEM:1:2", "option:WEAR_ITEM:0:3", "option:DROP_ITEM:0:2"]
        )
        self.assertFalse(any(a.rsplit(":", 1)[-1] == "4" for a in selected))

    def test_unwearable_target_retains_old_gear_and_reports_choices(self):
        old, new, held = item(2, "Worn"), item(3, container=99), item(2, "Weapon")
        b = Bridge(
            scene("before", [old, new]),
            [
                scene("remove-menu", [old, new], choices=menu("REMOVE_ITEM", [2])),
                scene("removed", [held, new]),
                scene("wear-menu", [held, new], choices=menu("WEAR_ITEM", [2])),
            ],
        )
        r = self.client(b).act(
            {"type": "equip", "item_id": 3, "replace": [2], "disposition": "drop"}
        )
        self.assertEqual(r["dispatch"]["outcome"], "needs_input")
        self.assertFalse(any(a.get("key") == "A_INV_DROP" for a in b.inputs))
        self.assertEqual(r["menu"]["options"][0]["item_id"], 2)

    def test_stow_uses_container_id_and_verifies_destination(self):
        carried = [item(2, "Weapon"), item(99, "Worn"), item(98, "Worn")]
        b = Bridge(
            scene("before", carried),
            [
                scene("put-menu", carried, choices=menu("PUT_ITEM", [2])),
                scene(
                    "destinations",
                    carried,
                    choices=menu(
                        "ENVIRONMENT_PLACE_IN_IT_CONTAINER",
                        [2, 2],
                        context_item=2,
                        destinations=[98, 99],
                    ),
                ),
                scene("done", [item(2, container=99), *carried[1:]]),
            ],
        )
        r = self.client(b).act({"type": "stow", "item_id": 2, "container_id": 99})
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        self.assertEqual(b.inputs[-1]["option_id"], "option:ENVIRONMENT_PLACE_IN_IT_CONTAINER:1:2")

    def test_wrong_stow_destination_is_not_success_or_automatically_retried(self):
        carried = [item(2, "Weapon"), item(99, "Worn"), item(98, "Worn")]
        b = Bridge(
            scene("before", carried),
            [
                scene("put-menu", carried, choices=menu("PUT_ITEM", [2])),
                scene(
                    "destinations",
                    carried,
                    choices=menu(
                        "ENVIRONMENT_PLACE_IN_IT_CONTAINER", [2], context_item=2, destinations=[99]
                    ),
                ),
                scene("wrong", [item(2, container=98), *carried[1:]]),
            ],
        )
        r = self.client(b).act({"type": "stow", "item_id": 2, "container_id": 99})
        self.assertEqual(r["dispatch"]["outcome"], "needs_input")
        self.assertEqual(len(b.inputs), 3)

    def test_completion_mode_does_not_stop_for_damage_unless_controller_requests_it(self):
        for rules, expected in (({}, "completed"), ({"blood_loss": True}, "interrupted")):
            with self.subTest(rules=rules):
                ground = [item(2, ground=True)]
                b = Bridge(
                    scene("before", ground=ground),
                    [
                        scene(
                            "menu",
                            ground=ground,
                            choices=menu("ENVIRONMENT_PICK_UP_GROUND_ITEM", [2]),
                            blood=900,
                        ),
                        scene("done", [item(2)], blood=900),
                    ],
                )
                r = self.client(b).act(
                    {"type": "pickup", "item_id": 2}, execution={"interrupt_on": rules}
                )
                self.assertEqual(r["dispatch"]["outcome"], expected)
                self.assertEqual(len(b.inputs), 1 if rules else 2)

    def test_caller_visible_unit_condition_interrupts_before_initial_input(self):
        unit = {"id": 20, "position": {"x": 2, "y": 1, "z": 0}}
        for action in (
            {"type": "key", "key": "A_ATTACK"},
            {"type": "walk_to", "x": 3, "y": 1, "z": 0},
        ):
            b = Bridge(scene("before", units=[unit]))
            r = self.client(b).act(action, execution={"interrupt_on": {"visible_unit_ids": [20]}})
            self.assertEqual(r["dispatch"]["outcome"], "interrupted")
            self.assertEqual(b.inputs, [])

    def test_new_unit_and_report_predicates_are_observable(self):
        for rules, final in (
            (
                {"new_visible_units": True},
                scene("after", units=[{"id": 20, "position": {"x": 2, "y": 1, "z": 0}}]),
            ),
            ({"new_wounds": True}, scene("after")),
            (
                {"report_types": ["COMBAT_STRIKE_DETAILS"]},
                scene(
                    "after", reports=[{"id": 1, "type": "COMBAT_STRIKE_DETAILS", "text": "strike"}]
                ),
            ),
        ):
            if rules.get("new_wounds"):
                final["adventurer"]["health"]["wounds"] = 1
            b = Bridge(scene("before"), [final])
            r = self.client(b).act({"type": "wait"}, execution={"interrupt_on": rules})
            self.assertEqual(r["dispatch"]["outcome"], "interrupted")

    def test_resume_retains_reports_without_retriggering_an_already_reported_interruption(self):
        reports = [{"id": 1, "type": "COMBAT_STRIKE_DETAILS", "text": "strike"}]
        b = Bridge(
            scene("before", [item(2, "Weapon")]),
            [
                scene("menu", [item(2, "Weapon")], choices=menu("DROP_ITEM", [2]), reports=reports),
                scene("done", ground=[item(2, ground=True)], reports=reports),
            ],
        )
        c = self.client(
            b, {"mode": "complete", "interrupt_on": {"report_types": ["COMBAT_STRIKE_DETAILS"]}}
        )
        first = c.act({"type": "drop", "item_id": 2})
        self.assertEqual(first["dispatch"]["outcome"], "interrupted")
        resumed = c.act(first["dispatch"]["resume_action"])
        self.assertEqual(resumed["dispatch"]["outcome"], "completed")
        self.assertEqual(resumed["dispatch"]["events"], reports)
        self.assertEqual(len(b.inputs), 2)

    def test_external_interrupt_preserves_workflow_for_resume(self):
        b = Bridge(
            scene("before", [item(2, "Weapon")]),
            [
                scene("menu", [item(2, "Weapon")], choices=menu("DROP_ITEM", [2])),
                scene("done", ground=[item(2, ground=True)]),
            ],
        )
        c = self.client(b)

        def interrupt(game, request):
            game.input_hook = None
            c.interrupt(request["parent_dispatch"])

        b.input_hook = interrupt
        r = c.act({"type": "drop", "item_id": 2})
        self.assertEqual(r["dispatch"]["outcome"], "interrupted")
        self.assertEqual(len(b.inputs), 1)
        r = c.act(r["dispatch"]["resume_action"])
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        self.assertEqual(len(b.inputs), 2)

    def test_lost_input_reply_resumes_from_verified_effect_without_repeating(self):
        b = Bridge(
            scene("before", [item(2, "Weapon")]),
            [
                scene("menu", [item(2, "Weapon")], choices=menu("DROP_ITEM", [2])),
                scene("done", ground=[item(2, ground=True)]),
            ],
        )

        def disconnect(game, request):
            if request["action"]["type"] == "select_option":
                game.input_hook = None
                raise DFHackError("lost response")

        b.input_hook = disconnect
        c = self.client(b)
        with self.assertRaisesRegex(DispatchError, "lost response") as error:
            c.act({"type": "drop", "item_id": 2}, request_id="original")
        self.assertEqual(error.exception.dispatch_id, "original")
        self.assertEqual(
            error.exception.resume_action, {"type": "resume", "dispatch_id": "original"}
        )
        r = c.act({"type": "resume", "dispatch_id": "original"})
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        self.assertEqual(len(b.inputs), 2)
        self.assertEqual(len(r["dispatch"]["steps"]), 0)

    def test_step_limit_keeps_next_action_and_continuation(self):
        b = Bridge(
            scene("before", [item(2, "Weapon")]),
            [scene("menu", [item(2, "Weapon")], choices=menu("DROP_ITEM", [2]))],
        )
        r = self.client(b).act({"type": "drop", "item_id": 2}, execution={"max_steps": 1})
        self.assertEqual(r["dispatch"]["outcome"], "limit_reached")
        self.assertEqual(r["dispatch"]["next_action"]["type"], "select_option")
        self.assertEqual(r["dispatch"]["resume_action"]["dispatch_id"], r["dispatch"]["id"])

    def test_walk_verifies_position_not_only_changed_ui(self):
        b = Bridge(
            scene("before"),
            [scene("blocked", reports=[{"id": 1, "text": "Something blocks you."}])],
        )
        r = self.client(b).act({"type": "walk_to", "x": 2, "y": 1, "z": 0})
        self.assertEqual(r["dispatch"]["outcome"], "no_effect")
        self.assertEqual(len(b.inputs), 1)

    def test_walking_uses_explicit_route_constraints(self):
        v = scene("before", units=[{"id": 20, "position": {"x": 2, "y": 1, "z": 0}}])
        target = {"x": 2, "y": 1, "z": 0}
        blocked = next_walk(v, target, {})
        self.assertEqual(blocked["outcome"], "needs_input")
        self.assertEqual(blocked["details"]["facts"]["exclusions"], ["occupied"])
        self.assertEqual(blocked["details"]["facts"]["occupants"][0]["id"], 20)
        self.assertIn("input", next_walk(v, target, {"allow_occupied": True}))
        v["map"]["units"] = []
        v["map"]["liquid_depths"][1] = "00700"
        self.assertIn("input", next_walk(v, target, {}))
        self.assertEqual(next_walk(v, target, {"max_liquid_depth": 0})["outcome"], "needs_input")
        self.assertEqual(
            next_walk(v, target, {"blocked_tiles": [target]})["outcome"], "needs_input"
        )

    def test_walking_can_step_diagonally_past_an_occupied_neighbor(self):
        v = scene("before", units=[{"id": 20, "position": {"x": 1, "y": 2, "z": 0}}])
        v["map"]["walkable"][1] = "11011"
        target = {"x": 2, "y": 2, "z": 0}
        self.assertEqual(next_walk(v, target, {})["input"], {"type": "move", "direction": "se"})

    def test_duplicate_request_does_not_restart_finished_recipe(self):
        b = Bridge(scene("before", [item(2)]))
        c = self.client(b)
        original = c.act({"type": "pickup", "item_id": 2}, request_id="same")
        b.view = scene("new", ground=[item(2, ground=True)])
        replay = c.act({"type": "pickup", "item_id": 2}, request_id="same")
        self.assertTrue(replay["dispatch_replayed"])
        self.assertEqual(replay["dispatch"], original["dispatch"])
        self.assertEqual(b.inputs, [])
        with self.assertRaisesRegex(DFHackError, "different arguments"):
            c.act({"type": "pickup", "item_id": 2}, request_id="same", execution={"mode": "step"})

    def test_compact_result_omits_unchanged_map_ui_and_history(self):
        initial = scene("before", [item(2)])
        initial["ui"]["rows"] = [{"text": "x" * 40000, "y": 1}]
        b = Bridge(initial)
        c = self.client(b)
        compact = c.act({"type": "pickup", "item_id": 2}, result_format="compact")
        full = c.act({"type": "pickup", "item_id": 2}, result_format="full")
        self.assertNotIn("map", compact)
        self.assertNotIn("ui", compact)
        self.assertNotIn("reports", compact)
        self.assertLess(len(json.dumps(compact)), len(json.dumps(full)) / 10)

    def test_compact_deduplicates_help_but_preserves_text_and_encounter_order(self):
        a = {
            "modal": {"kind": "help", "text": ["Inventory help"]},
            "text": ["Inventory help"],
            "response": {"type": "dismiss"},
        }
        b = {
            "modal": {"kind": "announcement"},
            "text": ["Different message"],
            "response": {"type": "dismiss"},
        }
        v = scene("same")
        v["dispatch"] = {"prompts": [a, b, deepcopy(a)], "outcome": "completed"}
        compact = compact_result(v, v)
        self.assertEqual(compact["omitted"]["prompts"], {"help": 2, "announcement": 1})
        self.assertNotIn("Inventory help", json.dumps(compact))
        self.assertIn("text", v["dispatch"]["prompts"][0]["modal"])

    def test_compact_exposes_creature_changes_for_controller_threat_assessment(self):
        old = {"id": 20, "name": "Creature A", "position": {"x": 2, "y": 1, "z": 0}}
        moved = {**old, "position": {"x": 3, "y": 1, "z": 0}}
        arrived = {"id": 21, "name": "Creature B", "position": {"x": 0, "y": 1, "z": 0}}
        b = Bridge(scene("before", units=[old]), [scene("after", units=[moved, arrived])])
        r = self.client(b).act(
            {"type": "wait"},
            execution={"interrupt_on": {"new_visible_units": True}},
            result_format="compact",
        )
        self.assertEqual(r["changes"]["units"]["appeared"], [arrived])
        self.assertEqual(
            r["changes"]["units"]["moved"], [{"id": 20, "position": moved["position"]}]
        )
        self.assertEqual(r["outcome"], "interrupted")

    def test_stow_selection_closing_the_menu_returns_unverified_postcondition(self):
        carried = [item(2, "Weapon"), item(99, "Worn")]
        b = Bridge(
            scene("before", carried),
            [scene("menu", carried, choices=menu("PUT_ITEM", [2])), scene("closed", carried)],
        )
        r = self.client(b).act({"type": "stow", "item_id": 2, "container_id": 99})
        self.assertEqual(r["dispatch"]["outcome"], "needs_input")
        self.assertEqual(len(b.inputs), 2)

    def test_unchanged_menu_close_is_not_repeated_to_step_limit(self):
        v = scene("menu", [item(2)], choices=menu("DROP_ITEM", [2]))
        b = Bridge(v, [v])
        r = self.client(b).act({"type": "pickup", "item_id": 2})
        self.assertEqual(r["dispatch"]["outcome"], "no_effect")
        self.assertEqual(len(b.inputs), 1)

    def test_invalid_item_and_interruption_policies_never_reach_bridge(self):
        c = Client(port=1)
        actions = [
            {"type": "equip", "item_id": True},
            {"type": "equip", "item_id": 2, "replace": [2]},
            {"type": "equip", "item_id": 2, "replace": [3, 3]},
            {"type": "equip", "item_id": 2, "disposition": "stow"},
            {"type": "stow", "item_id": 2, "container_id": 2},
            {"type": "walk_to", "x": 0, "y": 0, "z": 0, "allow_occupied": 1},
            {"type": "move", "direction": "north"},
            {"type": "wait", "risk": "low"},
            {"type": "key"},
            {"type": "text", "text": "\n"},
            {"type": "click", "x": True, "y": 0},
        ]
        with patch.object(c, "request") as request:
            for action in actions:
                with self.assertRaises(ValueError):
                    c.act(action)
            for rules in (
                {"danger": True},
                {"blood_loss": 1},
                {"visible_unit_ids": [True]},
                {"report_types": "COMBAT"},
            ):
                with self.assertRaises(ValueError):
                    c.act({"type": "wait"}, execution={"interrupt_on": rules})
            request.assert_not_called()
