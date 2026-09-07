import unittest
from copy import deepcopy
from unittest.mock import patch

from dfharness.interactions import next_interaction
from dfharness.rpc import BridgeError
from tests.support import Bridge
from tests.support import FullClient as Client
from tests.test_workflows import scene


def target(x=3):
    return {"id": 2, "position": {"x": x, "y": 1, "z": 0}, "name": "Listener"}


def speech(*speakers):
    return [
        {"index": i, "speaker_id": speaker, "native_type": "GREET", "year": 100, "ticks": i}
        for i, speaker in enumerate(speakers)
    ]


def conversation(name, *, selecting=False, options=(), scroll=0, reports=(), x=2, turns=()):
    v = scene(name, x=x, reports=reports, units=[target()])
    v["status"]["can_move"] = False
    v["conversation"] = {
        "open": True,
        "selecting": selecting,
        "activity_id": 8,
        "activity_event_id": 0,
        "participants": [] if selecting else [1, 2],
        "options": list(options),
        "scroll": scroll,
        "activity": {
            "available": True,
            "activity_id": 8,
            "activity_event_id": 0,
            "turn_count": len(turns),
            "turns": list(turns),
            "participants": [1, 2],
            "turns_omitted": 0,
        },
    }
    return v


def option(name="Greet", *, visible=True, index=0):
    return {
        "id": "topic:greet",
        "label": name,
        "native_type": "GREET",
        "kind": "topic",
        "visible": visible,
        "index": index,
    }


class InteractionTests(unittest.TestCase):
    def client(self, bridge):
        c = Client(port=1, execution={"mode": "complete", "acknowledge": True})
        p = patch.object(c, "request", side_effect=bridge)
        p.start()
        self.addCleanup(p.stop)
        return c

    def test_talk_approaches_selects_native_target_and_topic_then_verifies_reports(self):
        b = Bridge(
            scene("start", units=[target()]),
            [
                scene("near", x=2, units=[target()]),
                conversation(
                    "picker", selecting=True, options=[dict(option(), id="listener:2", unit_id=2)]
                ),
                conversation("topics", options=[option()]),
                conversation(
                    "said",
                    options=[option()],
                    reports=[
                        {
                            "id": 9,
                            "activity_id": 8,
                            "activity_event_id": 0,
                            "speaker_id": 1,
                            "text": "Greetings",
                        },
                        {
                            "id": 10,
                            "activity_id": 8,
                            "activity_event_id": 0,
                            "speaker_id": 2,
                            "text": "Hello.",
                        },
                    ],
                    turns=speech(1, 2),
                ),
            ],
        )
        r = self.client(b).act(
            {
                "type": "talk",
                "unit_id": 2,
                "topic": "GREET",
                "blocked_tiles": [{"x": 2, "y": 0, "z": 0}, {"x": 2, "y": 2, "z": 0}],
            }
        )
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        self.assertEqual(
            [i["type"] for i in b.inputs],
            ["move", "key", "select_interaction", "select_interaction"],
        )
        self.assertEqual(b.inputs[-1]["option_id"], "topic:greet")
        self.assertEqual(r["dispatch"]["details"]["replies"][0]["text"], "Hello.")

    def test_talk_step_resume_does_not_repeat_open_or_selection(self):
        b = Bridge(
            scene("near", x=2, units=[target()]),
            [
                conversation(
                    "picker", selecting=True, options=[dict(option(), id="listener:2", unit_id=2)]
                ),
                conversation("topics", options=[option()]),
            ],
        )
        c = self.client(b)
        r = c.act({"type": "talk", "unit_id": 2}, execution={"mode": "step"})
        self.assertEqual(r["dispatch"]["outcome"], "in_progress")
        done = c.act(r["dispatch"]["resume_action"])
        self.assertEqual(done["dispatch"]["outcome"], "completed")
        self.assertEqual(len(b.inputs), 2)

    def test_new_conversation_clicks_the_specified_creature_when_not_in_existing_list(self):
        b = Bridge(
            conversation("picker", selecting=True, options=[]),
            [conversation("topics", options=[option()])],
        )
        r = self.client(b).act({"type": "talk", "unit_id": 2})
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        self.assertEqual(b.inputs, [{"type": "select_unit", "unit_id": 2}])

    def test_ambiguous_topic_and_wrong_conversation_never_choose(self):
        for v in (
            conversation("ambiguous", options=[option(), dict(option(), id="other")]),
            conversation("other", options=[option()]),
        ):
            if v["effect_id"] == "other":
                v["conversation"]["participants"] = [1, 3]
            b = Bridge(v)
            r = self.client(b).act({"type": "talk", "unit_id": 2, "topic": "GREET"})
            self.assertEqual(r["dispatch"]["outcome"], "needs_input")
            self.assertFalse(b.inputs)

    def test_requested_topic_returns_to_main_and_resumes_without_repeating_navigation(self):
        back = dict(option(), id="back", native_type="ReturnToMain", label="Return to main")
        b = Bridge(
            conversation("submenu", options=[back]),
            [
                conversation("main", options=[option()]),
                conversation(
                    "said",
                    reports=[
                        {"id": 9, "activity_id": 8, "activity_event_id": 0, "speaker_id": 1},
                        {
                            "id": 10,
                            "activity_id": 8,
                            "activity_event_id": 0,
                            "speaker_id": 2,
                            "text": "Hello.",
                        },
                    ],
                    turns=speech(1, 2),
                ),
            ],
        )
        c = self.client(b)
        r = c.act({"type": "talk", "unit_id": 2, "topic": "GREET"}, execution={"mode": "step"})
        self.assertEqual(r["dispatch"]["outcome"], "in_progress")
        r = c.act(r["dispatch"]["resume_action"])
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        self.assertEqual([i["option_id"] for i in b.inputs], ["back", "topic:greet"])

    def test_return_to_main_is_bounded_and_not_used_for_stale_choice_handles(self):
        back = dict(option(), id="back", native_type="ReturnToMain", label="Return to main")
        initial = conversation("submenu", options=[back])
        for view in (initial, conversation("changed", options=[dict(back, id="other-back")])):
            b = Bridge(initial, [view])
            c = self.client(b)
            r = c.act({"type": "talk", "unit_id": 2, "topic": "GREET"})
            self.assertIn(r["dispatch"]["outcome"], ("needs_input", "no_effect"))
            c.act(r["dispatch"]["resume_action"])
            self.assertEqual(len(b.inputs), 1)
        b = Bridge(initial)
        r = self.client(b).act({"type": "talk", "unit_id": 2, "choice_id": "expired"})
        self.assertEqual(r["dispatch"]["outcome"], "needs_input")
        self.assertFalse(b.inputs)

    def test_unrelated_chatter_is_not_proof_of_topic_completion(self):
        b = Bridge(
            conversation("topics", options=[option()]),
            [
                conversation(
                    "still",
                    options=[option()],
                    reports=[
                        {"id": 11, "speaker_id": 99, "activity_id": 77, "text": "Ambient speech"}
                    ],
                ),
            ],
        )
        c = self.client(b)
        r = c.act({"type": "talk", "unit_id": 2, "choice_id": "topic:greet"})
        self.assertEqual(r["dispatch"]["outcome"], "needs_input")
        self.assertEqual(
            c.act(r["dispatch"]["resume_action"])["dispatch"]["outcome"], "needs_input"
        )
        self.assertEqual(len(b.inputs), 1)

    def test_topic_scroll_then_resume_and_no_blind_scroll_loop(self):
        b = Bridge(
            conversation("offscreen", options=[option(visible=False, index=20)]),
            [
                conversation("shown", options=[option(index=20)], scroll=20),
                conversation(
                    "said",
                    reports=[
                        {
                            "id": 10,
                            "activity_id": 8,
                            "activity_event_id": 0,
                            "speaker_id": 1,
                            "text": "Greetings",
                        }
                    ],
                    turns=speech(1),
                ),
            ],
        )
        r = self.client(b).act(
            {"type": "talk", "unit_id": 2, "topic": "GREET", "completion": "utterance"}
        )
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        self.assertEqual(b.inputs[0]["key"], "ADVENTURE_LIST_SCROLL_PAGEDOWN")
        same = conversation("same", options=[option(visible=False, index=20)])
        b = Bridge(same, [same])
        self.assertEqual(
            self.client(b).act({"type": "talk", "unit_id": 2, "topic": "GREET"})["dispatch"][
                "outcome"
            ],
            "no_effect",
        )

    def test_tact_is_an_undelegated_choice_even_in_complete_mode(self):
        v = conversation("tact")
        v["conversation"]["selecting_tact"] = True
        b = Bridge(v)
        self.assertEqual(
            self.client(b).act({"type": "talk", "unit_id": 2, "topic": "GREET"})["dispatch"][
                "outcome"
            ],
            "needs_input",
        )
        self.assertFalse(b.inputs)

    def test_route_exclusions_remain_on_the_same_world_tiles_after_rebase(self):
        v = scene("before", units=[target()])
        v["status"].update(map_origin={"x": 100, "y": 100, "z": 0}, can_move=False)
        workflow = {
            "action": {"type": "talk", "unit_id": 2, "blocked_tiles": [{"x": 3, "y": 1, "z": 0}]}
        }
        next_interaction(workflow, v)
        v["status"].update(map_origin={"x": 101, "y": 100, "z": 0}, can_move=True)
        v["map"]["walkable"] = ["00000", "01110", "00000"]
        decision = next_interaction(workflow, v)
        self.assertEqual(decision["outcome"], "needs_input")
        self.assertNotIn("input", decision)

    def test_close_conversation_verifies_closed_flag(self):
        b = Bridge(conversation("open"), [scene("closed")])
        self.assertEqual(
            self.client(b).act({"type": "end_conversation"})["dispatch"]["outcome"], "completed"
        )
        self.assertEqual(b.inputs, [{"type": "key", "key": "LEAVESCREEN"}])

    def test_stairs_approach_and_verify_z_change_including_map_rebase(self):
        start = scene("start")
        start["map"]["landmarks"] = [{"position": {"x": 2, "y": 1, "z": 0}, "shape": "STAIR_UP"}]
        at = deepcopy(start)
        at.update(state_id="at", effect_id="at")
        at["status"]["position"]["x"] = 2
        done = scene("up", x=2)
        done["status"].update(map_origin={"x": 0, "y": 0, "z": 1})
        b = Bridge(start, [at, done])
        r = self.client(b).act({"type": "use_stairs", "x": 2, "y": 1, "z": 0, "direction": "up"})
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        self.assertEqual(b.inputs[-1], {"type": "move", "direction": "up"})

    def test_stairs_wrong_shape_no_input_blocked_stair_no_fake_completion(self):
        v = scene("stairs")
        b = Bridge(v)
        a = {"type": "use_stairs", "x": 1, "y": 1, "z": 0, "direction": "up"}
        self.assertEqual(self.client(b).act(a)["dispatch"]["outcome"], "needs_input")
        self.assertFalse(b.inputs)
        v["map"]["landmarks"] = [{"position": {"x": 1, "y": 1, "z": 0}, "shape": "STAIR_UP"}]
        b = Bridge(v, [v])
        self.assertEqual(self.client(b).act(a)["dispatch"]["outcome"], "no_effect")
        self.assertEqual(len(b.inputs), 1)

    def test_combat_target_selection_does_not_confirm_or_invent_an_attack(self):
        v = scene("attack-picker", x=2, units=[target()])
        v["combat"] = {
            "open": True,
            "mode": "UNIT_CHOICE",
            "scroll": 0,
            "options": [dict(option(), id="combat-unit:2", unit_id=2)],
        }
        confirmed = deepcopy(v)
        confirmed["combat"] = {"open": True, "mode": "CONFIRM", "target_unit_id": 2, "options": []}
        b = Bridge(v, [confirmed])
        r = self.client(b).act({"type": "combat", "unit_id": 2})
        self.assertEqual(r["dispatch"]["outcome"], "needs_input")
        self.assertEqual(len(b.inputs), 1)
        self.assertEqual(r["combat"]["mode"], "CONFIRM")

    def test_stale_preflight_returns_fresh_state_without_fictitious_resume(self):
        fresh = scene("fresh")
        c = Client(port=1)
        error = BridgeError(
            "State changed", "stale_state", {"view": fresh, "expected": "old"}, False
        )
        with patch.object(c, "request", side_effect=error):
            r = c.act({"type": "wait"}, expect="old")
        self.assertEqual(r["dispatch"]["outcome"], "rejected")
        self.assertNotIn("resume_action", r["dispatch"])
        self.assertEqual(r["state_id"], "state-fresh")
        self.assertIn("map", r)
        self.assertIn("health", r["adventurer"])

    def test_stale_mid_dispatch_replans_native_selection_from_fresh_state(self):
        b = Bridge(
            scene("near", x=2, units=[target()]),
            [
                conversation(
                    "picker", selecting=True, options=[dict(option(), id="listener:2", unit_id=2)]
                ),
                conversation("topics", options=[option()]),
            ],
        )
        rejected = False

        def request(req):
            nonlocal rejected
            if req["op"] == "act" and len(b.inputs) == 1 and not rejected:
                rejected = True
                b.view["state_id"] = "external-change"
                raise BridgeError("State changed", "stale_state", {"view": deepcopy(b.view)}, False)
            return b(req)

        c = Client(port=1, execution={"mode": "complete"})
        with patch.object(c, "request", side_effect=request):
            r = c.act({"type": "talk", "unit_id": 2})
            self.assertIsNone(b.active)
            self.assertEqual(len(r["dispatch"]["steps"]), 2)
            self.assertEqual(len(r["dispatch"]["state_refreshes"]), 1)
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        self.assertEqual([i["type"] for i in b.inputs], ["key", "select_interaction"])
