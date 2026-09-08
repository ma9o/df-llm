"""Public receipt behavior; execution internals are tested with full diagnostics."""

import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from dfharness.client import Client, render_observation
from dfharness.state import compact_result, field_changes
from tests.support import Bridge
from tests.test_interactions import conversation, option, speech
from tests.test_workflows import item, scene


def report(number, text, kind="REGULAR_CONVERSATION", speaker=2):
    return {
        "id": number,
        "text": text,
        "type": kind,
        "speaker_id": speaker,
        "activity_id": 8,
        "activity_event_id": 0,
    }


def receipt(view, outcome="completed", action=None, events=(), details=None):
    view["dispatch"] = {
        "id": "receipt-1",
        "outcome": outcome,
        "action": action or {"type": "key", "key": "A_SHORT_WAIT"},
        "execution": {"mode": "complete", "acknowledge": True},
        "reason": "Verified postcondition"
        if outcome == "completed"
        else "A further choice is required",
        "events": list(events),
        "prompts": [],
        "steps": [{"action": {"type": "key", "key": "A_SHORT_WAIT"}}],
        "details": details or {},
    }
    if outcome != "completed":
        view["dispatch"]["resume_action"] = {"type": "resume", "dispatch_id": "receipt-1"}
    return view


class ReceiptTests(unittest.TestCase):
    def test_route_blocker_preserves_explicit_facts_without_a_diagnostic_envelope(self):
        facts = {
            "destination": {"x": 3, "y": 1, "z": 0},
            "exclusions": ["unwalkable"],
            "tile": {"shape": "WALL", "material": "TREE", "liquid_depth": 0, "building": False},
        }
        r = compact_result(
            receipt(
                scene("blocked"),
                "needs_input",
                details={"blocker_kind": "route_excluded", "facts": facts},
            ),
            scene("before"),
        )
        self.assertEqual(r["blocker"]["facts"], facts)
        self.assertEqual(r["blocker"]["kind"], "route_excluded")
        self.assertLess(len(json.dumps(r)), 1000)
        self.assertNotIn("dispatch", r)

    def test_aiming_decision_preserves_tactics_and_native_identity_once(self):
        before = scene("before")
        after = deepcopy(before)
        after["combat"] = {
            "open": True,
            "kind": "combat",
            "mode": "AIM_ATTACK",
            "target_unit_id": 2,
            "always_do_something": False,
            "attack_flags": [],
            "charge_restriction": "None",
            "options": [
                {
                    "id": "native:attack:0",
                    "handle": "c7:0",
                    "kind": "attack",
                    "label": "punch (left hand)",
                    "item_id": -1,
                    "attack_index": 0,
                    "body_part_id": 53,
                    "required_body_part_id": 9,
                    "hit_chance_adjustment": 0,
                    "hit_squareness_adjustment": -2,
                    "flags": ["SMALL_AIM_MINUS"],
                    "selection": {"method": "native_hotkey", "scroll_to": 0},
                }
            ],
        }
        r = compact_result(
            receipt(
                after,
                "needs_input",
                action={"type": "combat", "unit_id": 2},
                details=after["combat"],
            ),
            before,
        )
        self.assertFalse(r["choices"]["always_do_something"])
        option = r["choices"]["options"]["attack"][0]
        self.assertEqual(option["id"], "c7:0")
        self.assertEqual(
            (option["attack_index"], option["body_part_id"], option["required_body_part_id"]),
            (0, 53, 9),
        )
        self.assertEqual(option["hit_chance_adjustment"], 0)
        self.assertNotIn("selection", option)
        self.assertEqual(json.dumps(r).count("punch (left hand)"), 1)

    def test_reloaded_map_never_turns_its_reset_counter_into_elapsed_ticks(self):
        before = scene("before")
        before["status"].update(world_frame=2, local_map_epoch="world.1", year=100, year_tick=100)
        after = deepcopy(before)
        after["status"].update(world_frame=35, local_map_epoch="world.3", year_tick=150)
        r = compact_result(receipt(after), before)
        self.assertNotIn("ticks", r)
        self.assertEqual(r["calendar_ticks"], 50)

    def test_passive_coating_measurements_do_not_repeat_but_phase_and_read_failures_do(self):
        coating = {
            "material": "WATER",
            "state": "Powder",
            "size": 100,
            "temperature": {"whole": 9976},
            "external": False,
        }
        before = scene("before", [dict(item(10), contaminants=[coating])])
        after = deepcopy(before)
        target = after["adventurer"]["inventory"][0]
        target["contaminants"][0].update(size=99, temperature={"whole": 9977})
        r = compact_result(receipt(after), before)
        self.assertNotIn("inventory", r.get("changes", {}))
        self.assertEqual(r["omitted"]["coating_measurements"], {"items": 1})
        target["contaminants"][0]["state"] = "Liquid"
        r = compact_result(after, before)
        delta = r["changes"]["inventory"]["changed"][0]["changed"]["contaminants"]
        self.assertEqual([cs[0]["state"] for cs in delta], ["Powder", "Liquid"])
        self.assertEqual(delta[1][0]["external"], False)
        self.assertNotIn("temperature", delta[1][0])
        self.assertEqual(target["contaminants"][0]["size"], 99)
        target.pop("contaminants")
        target["contaminants_unavailable"] = "Native material unreadable"
        r = compact_result(after, before)
        self.assertIn(
            "contaminants_unavailable", r["changes"]["inventory"]["changed"][0]["changed"]
        )

    def test_blocked_environment_menu_shows_the_requested_container_and_tile_once(self):
        v = scene("source mismatch")
        options = [
            {
                "id": "source:" + str(i),
                "kind": "NONE",
                "container_id": 10,
                "target_position": {"x": i, "y": 1, "z": 0},
                "material_ref": {"token": "WATER", "state": "Powder"},
            }
            for i in range(9)
        ]
        options.append(
            {
                "id": "other container",
                "kind": "NONE",
                "container_id": 11,
                "target_position": {"x": 2, "y": 1, "z": 0},
            }
        )
        v["menu"] = {"kind": "inventory", "options": options}
        r = compact_result(
            receipt(
                v,
                "needs_input",
                action={"type": "fill_container", "container_id": 10},
                details={"position": {"x": 2, "y": 1, "z": 0}},
            ),
            scene("before"),
        )
        self.assertEqual(r["choices"]["total"], 10)
        self.assertEqual(r["choices"]["omitted_options"], 9)
        self.assertEqual(r["choices"]["options"]["NONE"][0]["id"], "source:2")
        self.assertEqual(len(r["choices"]["options"]["NONE"]), 1)
        self.assertEqual(len(v["menu"]["options"]), 10)

    def test_ascii_crop_changes_do_not_look_like_creature_changes(self):
        before = scene("before", units=[{"id": 2, "in_map": False, "glyph": "u", "alive": True}])
        after = deepcopy(before)
        after["map"]["units"][0]["in_map"] = True
        self.assertNotIn("units", compact_result(receipt(after), before).get("changes", {}))
        after["map"]["units"][0]["alive"] = False
        change = compact_result(receipt(after), before)["changes"]["units"]["changed"][0]
        self.assertEqual(change, {"id": 2, "changed": {"alive": [True, False]}})

    def test_calendar_time_during_travel_survives_a_frozen_local_frame_counter(self):
        before = scene("travel")
        before["status"].update(world_frame=100, year=100, year_tick=17260, travel={"active": True})
        after = deepcopy(before)
        after["status"]["year_tick"] = 17261
        r = compact_result(receipt(after), before)
        self.assertEqual(r["ticks"], 0)
        self.assertEqual(r["calendar_ticks"], 1)
        after["status"].update(year=101, year_tick=0)
        r = compact_result(after, before)
        self.assertNotIn("calendar_ticks", r)
        self.assertEqual(r["calendar"][1], {"year": 101, "year_tick": 0})

    def test_unavailable_visible_units_do_not_look_like_creatures_leaving(self):
        before = scene("before", units=[{"id": 2, "alive": True}])
        after = scene("after", units=[])
        after["map"].update(
            units_available=False, units_unavailable="Native visibility read failed"
        )
        result = compact_result(receipt(after), before)
        self.assertEqual(result["changes"]["units"], {"unobserved": [2]})
        self.assertEqual(
            result["changes"]["units_coverage"][1],
            {
                "complete": False,
                "reason": "Native visibility read failed",
            },
        )
        restored = compact_result(receipt(deepcopy(before)), after)
        self.assertNotIn("appeared", restored["changes"]["units"])
        self.assertEqual(restored["changes"]["units"]["observed"][0]["id"], 2)
        after["map"] = {"units": [], "units_truncated": True}
        self.assertEqual(
            compact_result(receipt(after), before)["changes"]["units"], {"unobserved": [2]}
        )

    def test_map_offloading_is_not_reported_as_losing_the_character_inventory(self):
        before = scene("loaded", [item(1, "Weapon")])
        after = scene("travel")
        after.pop("adventurer")
        r = compact_result(receipt(after), before)
        self.assertEqual(r["changes"]["character_available"], [True, False])
        self.assertNotIn("inventory", r["changes"])
        self.assertNotIn("health", r["changes"])
        back = compact_result(receipt(deepcopy(before)), after)
        self.assertEqual(back["changes"]["character_available"], [False, True])
        self.assertNotIn("inventory", back["changes"])

    def test_truncated_inventory_distinguishes_observation_from_acquisition_or_loss(self):
        before = scene("partial", [dict(item(1), contents_truncated=True)])
        after = scene("full", [item(1), item(2)])
        r = compact_result(receipt(after), before)
        self.assertEqual(r["changes"]["inventory_complete"], [False, True])
        self.assertNotIn("added", r["changes"]["inventory"])
        self.assertEqual(r["changes"]["inventory"]["observed"][0]["id"], 2)
        reverse = compact_result(receipt(before), after)
        self.assertNotIn("removed", reverse["changes"]["inventory"])
        self.assertEqual(reverse["changes"]["inventory"]["unobserved"], [2])

    def test_reply_once_without_menu_activity_request_or_help_echo(self):
        before = conversation("before")
        answer = report(11, "The troglodyte is at Stopscars.")
        after = receipt(
            conversation("after", options=[option()]),
            action={"type": "talk", "unit_id": 2, "topic": "AskAboutProblems"},
            events=[
                report(10, "Any trouble?", speaker=1),
                answer,
                report(12, "Get your rhubarb!", speaker=3),
            ],
            details={
                "unit_id": 2,
                "topic": "AskAboutProblems",
                "replies": [answer],
                "conversation_reports": [answer],
            },
        )
        after["target_unit"] = {"id": 2, "large": "x" * 4000}
        after["dispatch"]["prompts"] = [{"modal": {"kind": "help"}, "text": ["Talk help" * 100]}]
        result = compact_result(after, before)
        encoded = json.dumps(result)
        self.assertEqual(encoded.count(answer["text"]), 1)
        self.assertEqual(
            result["said"], [{"unit": 2, "topic": "AskAboutProblems", "reply": answer["text"]}]
        )
        for field in (
            "dispatch",
            "action",
            "execution",
            "conversation",
            "target_unit",
            "choices",
            "progress",
        ):
            self.assertNotIn(field, result)
        self.assertEqual(
            result["omitted"], {"events": {"REGULAR_CONVERSATION": 2}, "prompts": {"help": 1}}
        )
        self.assertLess(len(encoded), 900)
        self.assertEqual(render_observation(result).count(answer["text"]), 1)
        self.assertNotIn("Talk help", render_observation(result))
        self.assertIn("replies", after["dispatch"]["details"])

    def test_submenu_once_grouped_by_type_with_guarded_handles(self):
        options = [
            {
                "id": "dialogue:8:AskAboutHf:" + str(i) + ":" + "a" * 32,
                "handle": f"c4:{i}",
                "native_type": "AskAboutHf",
                "index": i,
                "subject_hf_id": i,
                "subject_name": f"the human Person {i}",
                "label": f"Ask about the human Person {i}",
                "selection": {"method": "native_hotkey"},
            }
            for i in range(56)
        ]
        options.append(
            {
                "id": "long-return-id",
                "handle": "c4:56",
                "native_type": "ReturnToMain",
                "label": "Change the subject",
            }
        )
        before = conversation("before")
        after = receipt(
            conversation("submenu", options=options), "needs_input", details={"options": options}
        )
        result = compact_result(after, before)
        self.assertEqual(len(result["choices"]["options"]["AskAboutHf"]), 56)
        self.assertEqual(
            result["choices"]["options"]["AskAboutHf"][0],
            {"hf": 0, "name": "the human Person 0"},
        )
        encoded = json.dumps(result, separators=(",", ":"))
        self.assertEqual(encoded.count("the human Person 55"), 1)
        self.assertNotIn("a" * 32, encoded)
        self.assertNotIn("selection", encoded)
        self.assertLess(len(encoded), 4300)
        self.assertEqual(result["resume"]["dispatch_id"], "receipt-1")

    def test_field_diffs_preserve_false_zero_absent_and_invalid_weights(self):
        backpack = dict(
            item(4, "Worn"),
            description="backpack",
            weight_computed=True,
            weight_raw={"whole": 9, "fraction": 780000},
        )
        before = scene("before", [backpack])
        after = receipt(
            scene("after", [dict(backpack, weight_raw={"whole": 14, "fraction": 360000})])
        )
        changed = compact_result(after, before)["changes"]["inventory"]["changed"]
        self.assertEqual(changed, [{"id": 4, "changed": {"weight_kg": [9.78, 14.36]}}])
        self.assertEqual(
            field_changes({"a": True, "b": 1}, {"a": False, "b": 0, "c": None}),
            {"a": [True, False], "b": [1, 0], "c": [{"absent": True}, None]},
        )
        after["adventurer"]["inventory"][0]["weight_computed"] = False
        self.assertEqual(
            compact_result(after, before)["changes"]["inventory"]["changed"][0]["changed"],
            {"weight_kg": [9.78, None]},
        )

    def test_ticks_suppress_passive_counters_but_keep_warnings_drinking_and_unknowns(self):
        before = scene("before")
        before["status"]["world_frame"] = 100
        before["adventurer"]["health"]["thirst_timer"] = 57595
        before["adventurer"]["needs"] = {"thirst": {"severity": 0, "label": "No warning"}}
        after = deepcopy(before)
        after["status"]["world_frame"] = 110
        after["adventurer"]["health"]["thirst_timer"] = 57605
        after["adventurer"]["needs"]["thirst"] = {"severity": 1, "label": "Thirsty"}
        receipt(after)
        result = compact_result(after, before)
        self.assertEqual(result["ticks"], 10)
        self.assertNotIn("health", result["changes"])
        self.assertEqual(result["changes"]["needs.thirst.label"], ["No warning", "Thirsty"])
        after["adventurer"]["health"]["thirst_timer"] = 0
        self.assertEqual(
            compact_result(after, before)["changes"]["health"]["thirst_timer"], [57595, 0]
        )
        after["adventurer"].pop("needs")
        after["adventurer"]["health"]["thirst_timer"] = 57605
        self.assertEqual(
            compact_result(after, before)["changes"]["health"]["thirst_timer"], [57595, 57605]
        )

    def test_unknown_and_interruption_reports_survive_task_filter(self):
        before = scene("before")
        events = [
            report(1, "Ambient"),
            report(2, "New native event", "NEW_UNKNOWN_TYPE"),
            report(3, "Wounded", "COMBAT_STRIKE_DETAILS"),
        ]
        after = receipt(scene("after"), events=events)
        result = compact_result(after, before)
        self.assertEqual([e["id"] for e in result["events"]], [2, 3])
        self.assertEqual(
            [e["id"] for e in compact_result(after, before, "all")["events"]], [1, 2, 3]
        )
        after["dispatch"]["execution"]["interrupt_on"] = {"report_types": ["REGULAR_CONVERSATION"]}
        self.assertEqual([e["id"] for e in compact_result(after, before)["events"]], [1, 2, 3])

    def test_interrupted_native_counter_phase_is_not_three_spurious_health_changes(self):
        before = scene("input")
        before["status"].update(world_frame=1121, turn_phase="TAKING_INPUT")
        before["adventurer"]["health"].update(hunger_timer=182, thirst_timer=1121)
        before["adventurer"]["needs"] = {"hunger": {"severity": 0}, "thirst": {"severity": 0}}
        after = deepcopy(before)
        after["status"].update(
            world_frame=1178, turn_phase="MOVE_UNIT_PROCESSING", ready_for_input=False
        )
        after["adventurer"]["health"].update(hunger_timer=240, thirst_timer=1179)
        receipt(after, "interrupted")
        r = compact_result(after, before)
        self.assertEqual(r["ticks"], 57)
        self.assertNotIn("health", r.get("changes", {}))
        after["status"]["turn_phase"] = "UNKNOWN_NEW_PHASE"
        self.assertIn("health", compact_result(after, before)["changes"])
        after["status"]["turn_phase"] = "MOVE_UNIT_PROCESSING"
        after["adventurer"]["health"]["hunger_timer"] = 1
        self.assertEqual(
            compact_result(after, before)["changes"]["health"], {"hunger_timer": [182, 1]}
        )

    def test_retrieval_and_duplicate_keep_original_result_after_world_changes(self):
        before = scene("before")
        after = scene("after", reports=[report(1, "Nearby rumor")])
        bridge = Bridge(before, [after])
        client = Client(port=1, execution={"mode": "complete"})
        with patch.object(client, "request", side_effect=bridge):
            result = client.act({"type": "key", "key": "A_SHORT_WAIT"}, request_id="saved")
            bridge.view = scene("later", blood=20)
            cursor = len(bridge.calls)
            details = client.dispatch_details("saved")
            self.assertEqual([c["op"] for c in bridge.calls[cursor:]], ["dispatch_details"])
            self.assertEqual(details["value"][0]["text"], "Nearby rumor")
            again = client.act({"type": "key", "key": "A_SHORT_WAIT"}, request_id="saved")
            self.assertEqual(again, dict(result, replayed=True))
            self.assertFalse(client.dispatch_details("expired")["available"])
            full = client.dispatch_details("saved", "full")
            self.assertEqual(full["value"]["state_id"], "state-after")
        self.assertEqual(len(bridge.inputs), 1)

    def test_short_handle_and_native_hf_subject_select_the_canonical_option(self):
        for action in (
            {"type": "select_interaction", "option_id": "c1:0"},
            {"type": "talk", "unit_id": 2, "topic": "AskAboutHf", "subject_hf_id": 0},
        ):
            choice = dict(
                option(),
                id="canonical-long-id",
                handle="c1:0",
                native_type="AskAboutHf",
                subject_hf_id=0,
            )
            after = conversation(
                "said",
                turns=[dict(t, native_type="AskAboutHf") for t in speech(1, 2)],
                reports=[report(1, "Question", speaker=1), report(2, "Answer")],
            )
            bridge = Bridge(conversation("before", options=[choice]), [after])
            client = Client(port=1, execution={"mode": "complete"})
            with patch.object(client, "request", side_effect=bridge):
                result = client.act(action)
            self.assertEqual(result["outcome"], "completed")
            self.assertEqual(bridge.inputs[0]["option_id"], "canonical-long-id")

    def test_undecoded_decision_and_unresolved_quantity_remain_actionable(self):
        before = scene("before")
        after = receipt(scene("unsupported"), "needs_input")
        after["combat"] = {
            "kind": "combat",
            "open": True,
            "mode": "CONFIRM",
            "options": [],
            "selection_unavailable": "Unverified native binding",
        }
        result = compact_result(after, before)
        self.assertEqual(result["ui_text"], ["unsupported"])
        after.pop("combat")
        after["menu"] = {
            "kind": "inventory",
            "choosing_amount": True,
            "amount": 0,
            "amount_max": 30,
            "options": [],
        }
        result = compact_result(after, before)
        self.assertEqual(result["choices"]["amount"], 0)
        self.assertEqual(result["choices"]["amount_max"], 30)

    def test_reply_present_before_resume_is_returned_unless_already_in_a_receipt(self):
        answer = report(10, "An answer that arrived between dispatches")
        before = conversation("before", reports=[answer])
        after = receipt(
            deepcopy(before), details={"unit_id": 2, "topic": "Greet", "replies": [answer]}
        )
        self.assertEqual(compact_result(after, before)["said"][0]["reply"], answer["text"])
        self.assertNotIn("said", compact_result(after, before, seen_reply_ids=[10]))

    def test_python_exposes_readonly_receipt_retrieval(self):
        client = Client(port=1, execution={"mode": "complete", "acknowledge": True})
        with patch.object(client, "request", return_value={"available": False}) as request:
            self.assertEqual(
                client.dispatch_details("expired", section="full"), {"available": False}
            )
        request.assert_called_once_with(
            {"op": "dispatch_details", "dispatch_id": "expired", "section": "full"}
        )
