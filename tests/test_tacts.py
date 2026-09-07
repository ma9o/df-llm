import io
import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from dfharness.cli import main
from dfharness.composition import expand
from dfharness.workflows import validate_action
from tests.support import Bridge
from tests.support import FullClient as Client
from tests.test_interactions import conversation

TOPIC = {
    "id": "topic:plots",
    "native_type": "FishForPlots",
    "label": "Ask about plots",
    "tact_required": True,
    "visible": True,
    "index": 0,
}
ACTION = {"type": "talk", "unit_id": 2, "topic": "FishForPlots", "tact": "Persuade"}


def tact_menu(name="tacts"):
    view = conversation(
        name,
        options=[
            {
                "id": "tact:" + tact,
                "native_type": tact,
                "kind": "tact",
                "index": i,
                "selection": {"method": "native_hotkey", "scroll_to": i},
            }
            for i, tact in enumerate(("Persuade", "Intimidate"))
        ],
    )
    view["conversation"].update(selecting_tact=True, tact_topic=deepcopy(TOPIC), tact_topic_index=0)
    return view


def replied():
    return conversation(
        "replied",
        turns=[
            {"index": 0, "speaker_id": 1, "native_type": "FishForPlots"},
            {"index": 1, "speaker_id": 2, "native_type": "NoKnowledge"},
        ],
        reports=[
            {"id": i, "speaker_id": i, "activity_id": 8, "activity_event_id": 0, "text": text}
            for i, text in ((1, "Please tell me."), (2, "I know nothing."))
        ],
    )


class TactTests(unittest.TestCase):
    def client(self, bridge):
        c = Client(port=1, execution={"mode": "complete", "acknowledge": True})
        p = patch.object(c, "request", side_effect=bridge)
        p.start()
        self.addCleanup(p.stop)
        return c

    def test_delegated_tact_completes_the_original_topic_and_returns_reply_once(self):
        b = Bridge(conversation("topics", options=[TOPIC]), [tact_menu(), replied()])
        r = self.client(b).act(ACTION, result_format="compact")
        self.assertEqual(r["outcome"], "completed")
        self.assertEqual([i["option_id"] for i in b.inputs], ["topic:plots", "tact:Persuade"])
        encoded = json.dumps(r, ensure_ascii=False)
        self.assertEqual(encoded.count("I know nothing."), 1)
        self.assertNotIn("choices", r)
        self.assertLess(len(encoded), 1400)

    def test_native_navigation_edge_reaches_the_question_without_an_extra_controller_choice(self):
        parent = dict(
            TOPIC, id="interrogate", native_type="Interrogate", opens_topics=["FishForPlots"]
        )
        b = Bridge(
            conversation("main", options=[parent]),
            [conversation("questions", options=[TOPIC]), tact_menu(), replied()],
        )
        r = self.client(b).act(ACTION)["dispatch"]
        self.assertEqual(r["outcome"], "completed")
        self.assertEqual(
            [i["option_id"] for i in b.inputs], ["interrogate", "topic:plots", "tact:Persuade"]
        )

    def test_step_resume_retains_topic_and_tact_without_repeating_either(self):
        b = Bridge(conversation("topics", options=[TOPIC]), [tact_menu(), replied()])
        c = self.client(b)
        first = c.act(ACTION, execution={"mode": "step"})["dispatch"]
        self.assertEqual(first["outcome"], "in_progress")
        second = c.act(first["resume_action"], execution={"mode": "step"})["dispatch"]
        self.assertEqual(second["outcome"], "completed")
        self.assertEqual(len(b.inputs), 2)

    def test_missing_tact_returns_choices_once_and_does_not_speak(self):
        b = Bridge(conversation("topics", options=[TOPIC]), [tact_menu()])
        c = self.client(b)
        r = c.act({k: v for k, v in ACTION.items() if k != "tact"}, result_format="compact")
        self.assertEqual(r["outcome"], "needs_input")
        self.assertEqual(set(r["choices"]["options"]), {"Persuade", "Intimidate"})
        self.assertEqual(r["choices"]["tact_topic"]["native_type"], "FishForPlots")
        c.act(r["resume"])
        self.assertEqual(len(b.inputs), 1)

    def test_existing_tact_menu_can_be_completed_with_a_matching_topic(self):
        b = Bridge(tact_menu(), [replied()])
        r = self.client(b).act(ACTION)["dispatch"]
        self.assertEqual(r["outcome"], "completed")
        self.assertEqual([i["option_id"] for i in b.inputs], ["tact:Persuade"])

    def test_changed_topic_or_listener_does_not_receive_a_delegated_tact(self):
        for changed in ("topic", "listener", "activity"):
            view = tact_menu()
            if changed == "topic":
                view["conversation"]["tact_topic"]["id"] = "other:plots"
            elif changed == "listener":
                view["conversation"]["participants"] = [1, 3]
            else:
                view["conversation"]["activity_id"] = 9
            b = Bridge(conversation("topics", options=[TOPIC]), [view])
            r = self.client(b).act(ACTION)["dispatch"]
            self.assertEqual(r["outcome"], "needs_input")
            self.assertEqual(r["blocker"]["kind"], "topic_changed")
            self.assertEqual(len(b.inputs), 1)

    def test_tact_no_effect_resume_verifies_late_reply_without_resending(self):
        view = tact_menu()
        b = Bridge(view, [view])
        c = self.client(b)
        first = c.act(ACTION)["dispatch"]
        self.assertEqual(first["outcome"], "no_effect")
        second = c.act(first["resume_action"])["dispatch"]
        self.assertEqual(second["outcome"], "no_effect")
        b.view = replied()
        self.assertEqual(c.act(second["resume_action"])["dispatch"]["outcome"], "completed")
        self.assertEqual(len(b.inputs), 1)

    def test_unknown_or_inapplicable_tact_does_not_silently_fall_back(self):
        for view, tact in (
            (tact_menu(), "Unrecognized"),
            (conversation("ordinary", options=[dict(TOPIC, tact_required=False)]), "Persuade"),
        ):
            b = Bridge(view)
            r = self.client(b).act(dict(ACTION, tact=tact))["dispatch"]
            self.assertEqual(r["outcome"], "needs_input")
            self.assertFalse(b.inputs)

    def test_waiting_receipt_exposes_listener_state_and_attributed_response_without_claiming_speech(
        self,
    ):
        own = replied()
        own["conversation"]["activity"]["turns"] = own["conversation"]["activity"]["turns"][:1]
        own["conversation"]["activity"]["turn_count"] = 1
        own["reports"][1].update(
            type="REGULAR_CONVERSATION", text="The listener appears to acquiesce."
        )
        own["reports"].append(
            {"id": 99, "type": "REGULAR_CONVERSATION", "speaker_id": 3, "text": "Ambient chatter"}
        )
        own["target_unit"] = {"id": 2, "health": {"unconscious": 2}}
        b = Bridge(tact_menu(), [own])
        c = self.client(b)
        r = c.act(ACTION, execution={"max_steps": 1}, result_format="compact")
        self.assertEqual(r["outcome"], "limit_reached")
        self.assertEqual(r["awaiting"]["listener_unconscious"], 2)
        self.assertNotIn("said", r)
        self.assertEqual(
            [e["text"] for e in r["events"] if e["speaker_id"] == 2],
            ["The listener appears to acquiesce."],
        )
        self.assertNotIn("Ambient chatter", json.dumps(r))
        self.assertLess(len(json.dumps(r)), 1600)
        b.view = replied()
        b.view["target_unit"] = {"id": 2, "health": {"unconscious": 0}}
        done = c.act(r["resume"], result_format="compact")
        self.assertEqual(done["outcome"], "completed")
        self.assertEqual(json.dumps(done).count("I know nothing."), 1)
        self.assertNotIn("appears to acquiesce", json.dumps(done))
        self.assertEqual(len(b.inputs), 1)

    def test_converse_preserves_per_topic_subjects_and_tacts_across_surfaces(self):
        questions = ["Greet", {"topic": "FishForPlots", "tact": "Persuade"}]
        action = {"type": "converse", "unit_ids": [2, 3], "topics": questions}
        validate_action(action)
        stages = expand(action)
        self.assertEqual(stages[2], dict(ACTION, completion="reply"))
        self.assertEqual(stages[5], dict(ACTION, unit_id=3, completion="reply"))
        with patch("dfharness.cli.Client") as cls, patch("sys.stdout", new_callable=io.StringIO):
            cls.return_value.act.return_value = {}
            self.assertEqual(
                main(
                    [
                        "converse",
                        "2",
                        "3",
                        "--topic",
                        "Greet",
                        "--topic-spec",
                        json.dumps(questions[1]),
                    ]
                ),
                0,
            )
            sent = cls.return_value.act.call_args.args[0]
            self.assertEqual({k: sent[k] for k in action}, action)

    def test_invalid_tact_and_topic_specs_are_rejected(self):
        for action in (
            dict(ACTION, tact=False),
            {"type": "talk", "unit_id": 2, "tact": "Persuade"},
            *[
                {"type": "converse", "unit_ids": [2], "topics": [topic]}
                for topic in (
                    {"tact": "Persuade"},
                    {"topic": "Greet", "unit_id": 9},
                    1,
                    {"topic": False},
                )
            ],
        ):
            with self.subTest(action=action), self.assertRaises(ValueError):
                validate_action(action)
