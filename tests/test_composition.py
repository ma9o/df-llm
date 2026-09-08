import unittest
from copy import deepcopy
from typing import Any
from unittest.mock import patch

from dfharness.client import render_observation
from dfharness.composition import observation_args
from dfharness.rpc import BridgeError
from dfharness.workflows import validate_action
from tests.support import Bridge
from tests.support import FullClient as Client
from tests.test_interactions import conversation, option, speech, target
from tests.test_workflows import scene


def posture(name, prone=False, **kwargs):
    v = scene(name, **kwargs)
    v["adventurer"]["on_ground"] = prone
    return v


def sequence(*actions):
    return {"type": "sequence", "actions": list(actions)}


PRONE = {"type": "set_posture", "posture": "prone"}
STAND = {"type": "set_posture", "posture": "standing"}


class CompositionTests(unittest.TestCase):
    def test_completed_sequence_keeps_readers_required_by_its_receipt(self):
        workflow = {"action": sequence({"type": "drop", "item_id": 7}, STAND), "context": {}}
        self.assertTrue(observation_args(workflow)["receipt_state"])
        workflow["context"]["stage_index"] = 2
        self.assertTrue(observation_args(workflow)["receipt_state"])
        self.assertEqual(
            observation_args({"action": sequence(STAND), "context": {"stage_index": 1}}), {}
        )

    def client(self, bridge):
        c = Client(port=1, execution={"mode": "complete", "acknowledge": True})
        p = patch.object(c, "request", side_effect=bridge)
        p.start()
        self.addCleanup(p.stop)
        return c

    def test_one_lease_with_native_verification_for_each_stage(self):
        b = Bridge(posture("start"), [posture("down", True), posture("up")])
        d = self.client(b).act(sequence(PRONE, STAND))["dispatch"]
        self.assertEqual(d["outcome"], "completed")
        self.assertEqual(d["progress"]["completed_stages"], 2)
        self.assertEqual([r["state_id"] for r in d["results"]], ["state-down", "state-up"])
        self.assertEqual(sum(c["op"] == "begin_dispatch" for c in b.calls), 1)
        self.assertEqual({c["parent_dispatch"] for c in b.calls if c["op"] == "act"}, {d["id"]})

    def test_compact_receipts_keep_full_trace_replayable_without_new_input(self):
        b = Bridge(posture("start"), [posture("down", True), posture("up")])
        c = self.client(b)
        action = sequence(PRONE, STAND)
        compact = c.act(action, request_id="trace-test", result_format="compact")
        d = compact
        self.assertNotIn("steps", d)
        self.assertEqual(d["inputs"], 2)
        compact["status"].update(
            df_version="test", dfhack_version="test", mode="adventure", focus=[]
        )
        self.assertIn("2 inputs", render_observation(compact))
        full = c.act(action, request_id="trace-test", result_format="full")
        self.assertEqual(len(full["dispatch"]["steps"]), 2)
        self.assertTrue(full["dispatch_replayed"])
        self.assertEqual(len(b.inputs), 2)

    def test_step_and_limit_resume_do_not_repeat_completed_stage_or_commit_unsent_stage(self):
        for policy, outcome in (
            ({"mode": "step"}, "in_progress"),
            ({"max_steps": 1}, "limit_reached"),
        ):
            with self.subTest(policy=policy):
                b = Bridge(posture("start"), [posture("down", True), posture("up")])
                c = self.client(b)
                d = c.act(sequence(PRONE, STAND), execution=policy)["dispatch"]
                self.assertEqual(d["outcome"], outcome)
                self.assertEqual(d["progress"]["stage_index"], 1)
                saved = b.dispatches[d["id"]]["workflow"]["context"]
                self.assertNotIn("posture_sent", saved["stages"][1]["context"])
                done = c.act(d["resume_action"])["dispatch"]
                self.assertEqual(done["outcome"], "completed")
                self.assertEqual(len(done["results"]), 2)
                self.assertEqual(len(b.inputs), 2)

    def test_no_effect_stops_sequence_before_following_action(self):
        b = Bridge(posture("start"), [posture("unchanged")])
        d = self.client(b).act(sequence(PRONE, STAND))["dispatch"]
        self.assertEqual(d["outcome"], "no_effect")
        self.assertEqual(d["blocker"]["stage_index"], 0)
        self.assertEqual(d["results"], [])
        self.assertEqual(len(b.inputs), 1)

    def test_map_rebase_does_not_reinterpret_later_coordinate_targets(self):
        start, changed = posture("start"), posture("changed", True)
        start["status"]["map_origin"] = {"x": 100, "y": 100, "z": 0}
        changed["status"]["map_origin"] = {"x": 101, "y": 100, "z": 0}
        arrived = deepcopy(changed)
        arrived.update(state_id="arrived", effect_id="arrived")
        arrived["status"]["position"]["x"] = 0
        b = Bridge(start, [changed, arrived])
        d = self.client(b).act(
            sequence(PRONE, {"type": "walk_to", "x": 1, "y": 1, "z": 0, "posture": "keep"})
        )["dispatch"]
        self.assertEqual(d["outcome"], "completed")
        self.assertEqual(d["progress"]["completed_stages"], 2)
        self.assertEqual(
            b.inputs, [{"type": "key", "key": "A_STANCE"}, {"type": "move", "direction": "w"}]
        )

    def test_missing_coordinate_frame_remains_explicit(self):
        start, changed = posture("start"), posture("changed", True)
        changed["status"]["map_origin"] = {"x": 101, "y": 100, "z": 0}
        b = Bridge(start, [changed])
        d = self.client(b).act(sequence(PRONE, {"type": "walk_to", "x": 1, "y": 1, "z": 0}))[
            "dispatch"
        ]
        self.assertEqual(d["outcome"], "needs_input")
        self.assertEqual(d["blocker"]["kind"], "coordinate_frame_changed")
        self.assertEqual(len(b.inputs), 1)

    def test_next_stage_reader_uses_the_original_coordinate_frame(self):
        workflow: dict[str, Any] = {
            "action": sequence(PRONE, {"type": "walk_to", "x": 72, "y": 37, "z": 135}),
            "context": {"map_origin": {"x": 5520, "y": 14592, "z": -29}, "stage_index": 0},
        }
        observation_args(workflow)
        workflow["context"]["stage_index"] = 1
        self.assertEqual(
            observation_args(workflow)["route_target"],
            {"absolute": {"x": 5592, "y": 14629, "z": 106}},
        )

    def test_one_interruption_baseline_across_stages_and_resume_retains_events(self):
        b = Bridge(
            posture("start"),
            [posture("down", True), posture("up", blood=900, reports=[{"id": 3, "text": "ouch"}])],
        )
        c = self.client(b)
        d = c.act(sequence(PRONE, STAND, PRONE), execution={"interrupt_on": {"blood_loss": True}})[
            "dispatch"
        ]
        self.assertEqual(d["outcome"], "interrupted")
        self.assertEqual(d["progress"]["stage_index"], 1)
        self.assertEqual(len(b.inputs), 2)
        b.views.append(posture("down-again", True, blood=900))
        done = c.act(d["resume_action"])["dispatch"]
        self.assertEqual(done["outcome"], "completed")
        self.assertEqual(len(b.inputs), 3)
        self.assertEqual(done["events"], [{"id": 3, "text": "ouch"}])

    def test_stale_input_replans_without_repeating_verified_stages(self):
        b = Bridge(posture("start"), [posture("down", True), posture("up")])
        rejected = False

        def request(req):
            nonlocal rejected
            if req["op"] == "act" and len(b.inputs) == 1 and not rejected:
                rejected = True
                raise BridgeError("State changed", "stale_state", {"view": deepcopy(b.view)}, False)
            return b(req)

        c = self.client(request)
        d = c.act(sequence(PRONE, STAND))["dispatch"]
        self.assertIsNone(b.active)
        self.assertEqual(d["progress"]["stage_index"], 2)
        self.assertEqual(len(d["results"]), 2)
        self.assertEqual(d["outcome"], "completed")
        self.assertEqual(len(d["state_refreshes"]), 1)
        self.assertEqual(len(b.inputs), 2)

    def test_cancel_at_input_preflight_does_not_checkpoint_unsent_stage(self):
        b = Bridge(posture("start"), [posture("down", True)])

        def request(req):
            if req["op"] == "act":
                b.dispatches[req["parent_dispatch"]]["interrupted"] = True
            return b(req)

        d = self.client(request).act(sequence(PRONE))["dispatch"]
        self.assertEqual(d["outcome"], "interrupted")
        saved = b.dispatches[d["id"]]["workflow"]["context"]
        self.assertNotIn("posture_sent", saved["stages"][0]["context"])
        self.assertFalse(b.inputs)

    def test_delegated_prompts_share_budget_and_unresolved_choices_stop(self):
        modal = posture("prompt", True)
        modal["status"]["modal"] = {"kind": "announcement", "button": "Okay", "dismissible": True}
        b = Bridge(posture("start"), [modal, posture("acknowledged", True), posture("up")])
        c = self.client(b)
        d = c.act(sequence(PRONE, STAND), execution={"max_steps": 2})["dispatch"]
        self.assertEqual(d["outcome"], "limit_reached")
        self.assertEqual(d["progress"]["stage_index"], 1)
        self.assertEqual([a["type"] for a in b.inputs], ["key", "dismiss"])
        self.assertEqual(c.act(d["resume_action"])["dispatch"]["outcome"], "completed")

    def test_supported_menu_preparation_is_not_a_claim_of_attack_completion(self):
        v = scene("combat", units=[target()])
        v["combat"] = {
            "open": True,
            "mode": "MOVE_CHOICE",
            "target_unit_id": 2,
            "options": [dict(option(), id="strike")],
        }
        aim = deepcopy(v)
        aim["combat"].update(
            mode="AIM_TARGET", options=[], selection_unavailable="Unverified aim binding"
        )
        b = Bridge(v, [aim])
        d = self.client(b).act(
            sequence({"type": "combat", "unit_id": 2, "option_id": "strike"}, STAND)
        )["dispatch"]
        self.assertEqual(d["outcome"], "needs_input")
        self.assertEqual(d["blocker"]["kind"], "unsupported")
        self.assertEqual(d["results"], [])

    def test_validation_rejects_raw_input_nested_sequences_and_oversized_expansion(self):
        for action in (
            sequence({"type": "key", "key": "A_SHORT_WAIT"}),
            sequence(sequence(STAND)),
            sequence(),
            {"type": "converse", "unit_ids": [2, 2], "topics": ["GREET"]},
            {"type": "converse", "unit_ids": list(range(32)), "topics": ["GREET"] * 16},
        ):
            with self.subTest(action=action), self.assertRaises(ValueError):
                validate_action(action)

    def test_validation_accepts_composition_and_reply_completion(self):
        action = sequence(STAND, {"type": "converse", "unit_ids": [2, 3], "topics": ["GREET"]})
        validate_action(action)


class ConversationReplyTests(unittest.TestCase):
    def client(self, bridge):
        c = Client(port=1, execution={"mode": "complete", "acknowledge": True})
        p = patch.object(c, "request", side_effect=bridge)
        p.start()
        self.addCleanup(p.stop)
        return c

    def test_own_line_is_not_a_reply_waits_and_resumes_without_repeating_topic(self):
        own = conversation(
            "own",
            options=[option()],
            turns=speech(1),
            reports=[
                {
                    "id": 10,
                    "activity_id": 8,
                    "activity_event_id": 0,
                    "speaker_id": 1,
                    "text": "Hello",
                }
            ],
        )
        closed = scene("closed", x=2)
        closed["conversation_activity"] = deepcopy(own["conversation"]["activity"])
        reply = deepcopy(closed)
        reply.update(state_id="replied", effect_id="replied")
        reply["conversation_activity"].update(turns=speech(1, 2), turn_count=2)
        reply["reports"] = [
            {
                "id": 11,
                "activity_id": 8,
                "activity_event_id": 0,
                "speaker_id": 2,
                "text": "Greetings",
            }
        ]
        b = Bridge(conversation("topics", options=[option()]), [own, closed, reply])
        c = self.client(b)
        d = c.act({"type": "talk", "unit_id": 2, "topic": "GREET"}, execution={"max_steps": 2})[
            "dispatch"
        ]
        self.assertEqual(d["outcome"], "limit_reached")
        done = c.act(d["resume_action"])["dispatch"]
        self.assertEqual(done["outcome"], "completed")
        self.assertEqual([a["type"] for a in b.inputs], ["select_interaction", "key", "wait"])
        self.assertEqual(done["details"]["replies"][0]["text"], "Greetings")
        self.assertTrue(
            any(
                c.get("conversation_activity") == {"activity_id": 8, "activity_event_id": 0}
                for c in b.calls
            )
        )

    def test_other_speaker_or_event_is_not_target_reply(self):
        for speaker, event in ((99, 0), (2, 9)):
            own = conversation(
                "own",
                options=[option()],
                turns=speech(1, speaker),
                reports=[
                    {
                        "id": 9,
                        "activity_id": 8,
                        "activity_event_id": 0,
                        "speaker_id": 1,
                        "text": "Hello",
                    },
                    {
                        "id": 10,
                        "activity_id": 8,
                        "activity_event_id": event,
                        "speaker_id": speaker,
                        "text": "Unrelated",
                    },
                ],
            )
            b = Bridge(conversation("topics", options=[option()]), [own])
            d = self.client(b).act(
                {"type": "talk", "unit_id": 2, "topic": "GREET"}, execution={"max_steps": 1}
            )["dispatch"]
            self.assertEqual(d["outcome"], "limit_reached")
            self.assertNotIn("replies", d.get("details", {}))

    def test_missing_native_history_does_not_send_unverifiable_topic(self):
        v = conversation("topics", options=[option()])
        v["conversation"].pop("activity")
        b = Bridge(v)
        d = self.client(b).act({"type": "talk", "unit_id": 2, "topic": "GREET"})["dispatch"]
        self.assertEqual(d["blocker"]["kind"], "unsupported")
        self.assertFalse(b.inputs)

    def test_missing_report_or_truncated_turn_proof_is_explicit(self):
        for truncated in (False, True):
            replied = conversation(
                "reply",
                turns=speech(1, 2),
                reports=[
                    {
                        "id": 11,
                        "activity_id": 8,
                        "activity_event_id": 0,
                        "speaker_id": 2,
                        "text": "Hello",
                    }
                ],
            )
            b = Bridge(conversation("topics", options=[option()]), [replied])
            c = self.client(b)
            if truncated:
                replied["conversation"]["activity"].update(turns=speech(1), turn_count=1)
                b.views.clear()
                b.views.append(deepcopy(replied))
                d = c.act(
                    {"type": "talk", "unit_id": 2, "topic": "GREET"}, execution={"max_steps": 1}
                )["dispatch"]
                self.assertEqual(d["outcome"], "limit_reached")
                b.view["conversation"]["activity"].update(
                    turns=[dict(speech(2)[0], index=130)], turns_omitted=130, turn_count=131
                )
                d = c.act(d["resume_action"])["dispatch"]
            else:
                d = c.act({"type": "talk", "unit_id": 2, "topic": "GREET"})["dispatch"]
            self.assertEqual(d["outcome"], "needs_input")
            self.assertEqual(d["blocker"]["kind"], "verification")
            self.assertEqual(len(b.inputs), 1)

    def test_reply_wait_that_does_not_advance_time_is_not_repeated(self):
        own = conversation("own", turns=speech(1))
        closed = scene("closed", x=2)
        closed["status"].update(year=100, year_tick=0, world_frame=0)
        closed["conversation_activity"] = deepcopy(own["conversation"]["activity"])
        b = Bridge(conversation("topics", options=[option()]), [own, closed, closed])
        d = self.client(b).act({"type": "talk", "unit_id": 2, "topic": "GREET"})["dispatch"]
        self.assertEqual(d["outcome"], "no_effect")
        self.assertEqual(sum(a["type"] == "wait" for a in b.inputs), 1)

    def test_two_people_in_one_objective_collects_replies_by_target(self):
        first = conversation("first-topics", options=[option()])
        first_reply = conversation(
            "first-reply",
            turns=speech(1, 2),
            reports=[
                {
                    "id": 10,
                    "activity_id": 8,
                    "activity_event_id": 0,
                    "speaker_id": 1,
                    "text": "Hello",
                },
                {
                    "id": 11,
                    "activity_id": 8,
                    "activity_event_id": 0,
                    "speaker_id": 2,
                    "text": "First reply",
                },
            ],
        )
        second = conversation("second-topics", options=[option()])
        second["conversation"]["participants"] = [1, 3]
        second["conversation"]["activity"]["participants"] = [1, 3]
        second_reply = deepcopy(second)
        second_reply.update(state_id="second-reply", effect_id="second-reply")
        second_reply["conversation"]["activity"].update(turns=speech(1, 3), turn_count=2)
        second_reply["reports"] = [
            {
                "id": 12,
                "activity_id": 8,
                "activity_event_id": 0,
                "speaker_id": 1,
                "text": "Hello again",
            },
            {
                "id": 13,
                "activity_id": 8,
                "activity_event_id": 0,
                "speaker_id": 3,
                "text": "Second reply",
            },
        ]
        closed = scene("closed", x=2, units=[dict(target(), id=3)])
        b = Bridge(
            scene("start", x=2, units=[target()]),
            [first, first_reply, closed, second, second_reply, closed],
        )
        d = self.client(b).act({"type": "converse", "unit_ids": [2, 3], "topics": ["GREET"]})[
            "dispatch"
        ]
        self.assertEqual(d["outcome"], "completed")
        self.assertEqual(d["progress"]["completed_stages"], 5)
        replies = [
            (r["details"]["unit_id"], e["text"])
            for r in d["results"]
            for e in r.get("details", {}).get("replies", [])
        ]
        self.assertEqual(replies, [(2, "First reply"), (3, "Second reply")])
        queries = [
            c["target_unit_id"] for c in b.calls if c.get("observe") and c.get("target_unit_id")
        ]
        self.assertIn(2, queries)
        self.assertEqual(queries[-1], 3)
        self.assertEqual({e["id"] for e in d["events"]}, {10, 11, 12, 13})
