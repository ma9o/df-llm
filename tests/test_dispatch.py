import unittest
from copy import deepcopy
from unittest.mock import patch

from dfharness.policy import MAX_DISPATCH_INPUTS, execution_policy, interruption
from dfharness.rpc import DFHackError
from tests.support import Bridge
from tests.support import FullClient as Client

HELP = {"kind": "help", "button": "Okay", "dismissible": True}
MORE = {"kind": "announcement", "button": "More", "dismissible": True}
OKAY = {"kind": "announcement", "button": "Okay", "dismissible": True}
LONG = {"kind": "action_prompt", "dismissible": False}
WAITING = {"kind": "waiting_prompt", "dismissible": False, "responses": {"continue": "OPTION1"}}


def view(effect, modal=None, reports=()):
    status = {"ready_for_input": True}
    if modal:
        status["modal"] = deepcopy(modal)
    return {
        "state_id": "state-" + effect,
        "effect_id": effect,
        "status": status,
        "reports": list(reports),
        "ui": {"rows": [{"y": 7, "text": "page " + effect}]},
    }


def report(number):
    return {"id": number, "speaker_id": 123, "activity_id": 10, "text": f"report {number}"}


class DispatchTests(unittest.TestCase):
    def test_only_completed_dispatches_delegate_presentation_acceleration(self):
        for mode in ("step", "complete"):
            _, inputs = self.scripted([view("after")], policy={"mode": mode})
            self.assertEqual(inputs[0].get("fastcombat", False), mode == "complete")

    def test_delegated_dismiss_uses_the_native_guard_for_fully_decoded_help(self):
        before = view("native-help", HELP)
        before["ui_state_id"] = "u2:blinking-background"
        b = Bridge(before, [view("done")])
        c = Client(port=1, execution={"mode": "complete", "acknowledge": True})
        with patch.object(c, "request", side_effect=b):
            r = c.act({"type": "resume"})
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        sent = next(call for call in b.calls if call["op"] == "act")
        self.assertEqual(sent["expect"], before["state_id"])

    def test_controller_excludes_named_units_only_from_new_visibility_interruptions(self):
        before, after = view("before"), view("after")
        before["map"] = {"units": []}
        after["map"] = {"units": [{"id": 2}]}
        policy = execution_policy(
            {"interrupt_on": {"new_visible_units": True, "new_visible_units_except": [2]}}
        )
        self.assertIsNone(interruption(before, after, [], policy))
        after["map"]["units"].append({"id": 3})
        self.assertIn("[3]", interruption(before, after, [], policy)["reason"])
        policy["interrupt_on"]["visible_unit_ids"] = [2]
        policy["interrupt_on"]["new_visible_units"] = False
        self.assertIn("visible_unit_ids", interruption(before, after, [], policy)["reason"])
        with self.assertRaises(ValueError):
            execution_policy({"interrupt_on": {"new_visible_units_except": [-1]}})

    def test_visibility_interruptions_cover_units_outside_the_ascii_crop_and_unknown_bounds(self):
        before, after = view("before"), view("after")
        before["map"] = {"units": []}
        after["map"] = {"units": [{"id": 2, "in_map": False}]}
        policy = execution_policy({"interrupt_on": {"new_visible_units": True}})
        self.assertIn("new_visible_units", interruption(before, after, [], policy)["reason"])
        after["map"].update(units=[], units_truncated=True)
        self.assertIn(
            "cannot be fully evaluated", interruption(before, after, [], policy)["reason"]
        )
        self.assertIsNone(interruption(before, after, [], execution_policy()))

    def test_reloaded_player_is_not_a_new_encounter_but_explicit_ids_remain_literal(self):
        before, after = view("offloaded"), view("reloaded")
        before["map"] = {"units": []}
        after["status"]["adventurer_id"] = 0
        after["map"] = {"units": [{"id": 0}]}
        policy = execution_policy({"interrupt_on": {"new_visible_units": True}})
        self.assertIsNone(interruption(before, after, [], policy))
        after["map"]["units"].append({"id": 2})
        self.assertIn("[2]", interruption(before, after, [], policy)["reason"])
        policy = execution_policy({"interrupt_on": {"visible_unit_ids": [0]}})
        self.assertIn("visible_unit_ids", interruption(before, after, [], policy)["reason"])

    def scripted(self, views, *, policy=None, defaults=None, action=None):
        client = Client(port=1, execution=defaults)
        action = action or {"type": "key", "key": "A_TALK"}
        initial = view("before")
        if action["type"] == "move":
            initial["status"].update(can_move=True, position={"x": 1, "y": 1, "z": 0})
            views[-1]["status"].update(can_move=True, position={"x": 1, "y": 0, "z": 0})
        if action["type"] == "resume":
            initial, views = views[0], views[1:]
        bridge = Bridge(initial, views)
        with patch.object(client, "request", side_effect=bridge):
            result = client.act(
                action,
                expect=initial["state_id"],
                request_id="dispatch-1",
                execution=policy,
                result_format="full",
            )
        calls = bridge.calls
        inputs = [c for c in calls if c["op"] == "act"]
        self.assertEqual(calls[0]["expect"], initial["state_id"])
        self.assertEqual(inputs[0]["expect"], initial["state_id"])
        for i, sent in enumerate(inputs[1:]):
            self.assertEqual(sent["expect"], views[i]["state_id"])
            self.assertEqual(sent["parent_dispatch"], "dispatch-1")
        self.assertEqual(calls[-1]["dispatch"], result["dispatch"])
        return result["dispatch"], inputs

    def test_incremental_mode_leaves_undelegated_prompts(self):
        for modal in (HELP, LONG, WAITING, {"kind": "confirmation", "button": "Yes"}):
            with self.subTest(modal=modal):
                result, inputs = self.scripted([view("prompt", modal)])
                self.assertEqual(result["outcome"], "needs_input")
                self.assertEqual(len(inputs), 1)

    def test_complete_continues_a_waiting_only_prompt_without_inventing_finish(self):
        result, inputs = self.scripted(
            [view("waiting1", WAITING), view("waiting2", WAITING), view("done")],
            policy={"mode": "complete"},
            action={"type": "resume"},
        )
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(
            [r["action"] for r in inputs], [{"type": "action_prompt", "choice": "continue"}] * 2
        )

    def test_complete_handles_pages_then_finishes_without_continues(self):
        result, inputs = self.scripted(
            [
                view("help", HELP, [report(1)]),
                view("page-one", MORE, [report(2)]),
                view("page-two", MORE, [report(3)]),
                view("last-page", OKAY),
                view("long", LONG),
                view("done", reports=[report(4)]),
            ],
            policy={"mode": "complete", "acknowledge": True},
        )
        self.assertEqual(
            [r["action"] for r in inputs[1:]],
            [{"type": "dismiss"}] * 4 + [{"type": "action_prompt", "choice": "finish"}],
        )
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual([e["id"] for e in result["events"]], [1, 2, 3, 4])
        self.assertEqual(len(result["prompts"]), 5)
        self.assertIn("page page-one", result["prompts"][1]["text"])

    def test_acknowledgement_and_completion_are_independent(self):
        result, inputs = self.scripted([view("help", HELP)], policy={"mode": "complete"})
        self.assertEqual(result["outcome"], "needs_input")
        self.assertEqual(len(inputs), 1)
        result, inputs = self.scripted(
            [view("page", OKAY), view("long", LONG)], policy={"acknowledge": True}
        )
        self.assertEqual(result["outcome"], "needs_input")
        self.assertEqual(inputs[-1]["action"], {"type": "dismiss"})

    def test_completion_policy_does_not_depend_on_action_risk(self):
        for action in (
            {"type": "key", "key": "A_SHORT_WAIT"},
            {"type": "move", "direction": "n"},
            {"type": "key", "key": "A_ATTACK"},
            {"type": "click", "x": 1, "y": 1},
        ):
            with self.subTest(action=action):
                result, inputs = self.scripted(
                    [view("long", LONG), view("done")], policy={"mode": "complete"}, action=action
                )
                self.assertEqual(result["outcome"], "completed")
                self.assertEqual(inputs[1]["action"], {"type": "action_prompt", "choice": "finish"})

    def test_per_dispatch_policy_overrides_controller_defaults(self):
        result, inputs = self.scripted(
            [view("help", HELP)],
            defaults={"mode": "complete", "acknowledge": True},
            policy={"mode": "step", "acknowledge": False},
        )
        self.assertEqual(result["outcome"], "needs_input")
        self.assertEqual(len(inputs), 1)

    def test_unknown_prompt_returns_even_when_its_button_says_okay(self):
        result, inputs = self.scripted(
            [view("unknown", {"kind": "confirmation", "button": "Okay", "dismissible": True})],
            policy={"mode": "complete", "acknowledge": True},
        )
        self.assertEqual(result["outcome"], "needs_input")
        self.assertEqual(len(inputs), 1)

    def test_no_effect_prompt_is_not_repeated_despite_new_receipt_serial(self):
        same = view("same", MORE)
        same["state_id"] = "new-serial"
        result, inputs = self.scripted([view("same", MORE), same], policy={"acknowledge": True})
        self.assertEqual(result["outcome"], "no_effect")
        self.assertEqual(len(inputs), 2)

    def test_step_limit_returns_prompt_and_preserved_events(self):
        result, inputs = self.scripted(
            [view("one", MORE), view("two", MORE, [report(9)])],
            policy={"acknowledge": True, "max_steps": 2},
        )
        self.assertEqual(result["outcome"], "limit_reached")
        self.assertEqual(len(inputs), 2)
        self.assertEqual(result["events"], [report(9)])

    def test_resume_needs_no_original_game_input(self):
        result, inputs = self.scripted(
            [view("long", LONG), view("done")],
            action={"type": "resume"},
            policy={"mode": "complete"},
        )
        self.assertEqual([c["action"]["type"] for c in inputs], ["action_prompt"])
        self.assertEqual(result["outcome"], "completed")

    def test_duplicate_dispatch_does_not_act_on_new_prompt(self):
        for saved in (None, {"outcome": "completed", "steps": []}):
            client = Client(port=1)
            receipt = {
                "action_id": "old",
                "duplicate": True,
                "dispatch": saved,
                "view": view("new", LONG),
            }
            with patch.object(client, "request", return_value=receipt) as request:
                result = client.act(
                    {"type": "key", "key": "A_SHORT_WAIT"},
                    request_id="old",
                    execution={"mode": "complete"},
                )
            self.assertEqual([c.args[0]["op"] for c in request.call_args_list], ["begin_dispatch"])
            self.assertTrue(result["dispatch_replayed"])
            self.assertEqual(result["dispatch"]["outcome"], "completed" if saved else "needs_input")

    def test_automatic_input_connection_failure_is_not_retried(self):
        client = Client(port=1)
        bridge = Bridge(view("before"), [view("help", HELP), DFHackError("disconnect")])
        with (
            patch.object(client, "request", side_effect=bridge),
            self.assertRaisesRegex(DFHackError, "disconnect"),
        ):
            client.act({"type": "key", "key": "A_TALK"}, execution={"acknowledge": True})
        self.assertEqual(len(bridge.inputs), 2)
        self.assertEqual(bridge.inputs[-1], {"type": "dismiss"})

    def test_timeout_records_submitted_action_and_observed_events(self):
        client = Client(port=1)
        busy = view("busy", reports=[report(1)])
        busy["status"]["ready_for_input"] = False
        bridge = Bridge(view("before"), [busy])
        with (
            patch.object(client, "request", side_effect=bridge),
            patch("dfharness.dispatch.time.monotonic", side_effect=[0, 0, 2]),
        ):
            result = client.act({"type": "key", "key": "A_SHORT_WAIT"}, timeout=1)
        self.assertEqual(result["dispatch"]["outcome"], "limit_reached")
        self.assertEqual(len(result["dispatch"]["steps"]), 1)
        self.assertEqual(result["dispatch"]["events"], [report(1)])

    def test_readiness_is_rechecked_when_observation_shows_transition(self):
        client = Client(port=1)
        busy = view("offloading")
        busy["status"]["ready_for_input"] = False
        bridge = Bridge(view("before"), [busy])
        polls = 0

        def poll(game, request):
            nonlocal polls
            polls += 1
            if polls == 3:
                game.view = view("finished")
            return {"ready": True}

        bridge.poll_hook = poll
        with (
            patch.object(client, "request", side_effect=bridge),
            patch("dfharness.dispatch.time.sleep"),
        ):
            result = client.act({"type": "key", "key": "A_SHORT_WAIT"}, result_format="full")
        self.assertEqual(result["effect_id"], "finished")
        self.assertEqual(polls, 3)

    def test_processing_backoff_is_bounded_and_resets_for_each_native_input(self):
        initial, first, second = view("initial"), view("one", OKAY), view("two")
        bridge = Bridge(initial, [first, second])
        counts = {}

        def poll(game, request):
            count = len(game.inputs)
            if count:
                counts[count] = counts.get(count, 0) + 1
                if counts[count] <= 5:
                    return {"ready": False, "view": deepcopy(game.view)}
            return None

        bridge.poll_hook = poll
        client = Client(port=1)
        with (
            patch.object(client, "request", side_effect=bridge),
            patch("dfharness.dispatch.time.sleep") as pause,
        ):
            receipt = client.act(
                {"type": "key", "key": "A_SHORT_WAIT"},
                execution={"mode": "complete", "acknowledge": True},
            )
        self.assertEqual(receipt["dispatch"]["outcome"], "completed")
        self.assertEqual(
            [c.args[0] for c in pause.call_args_list], [0.05, 0.1, 0.2, 0.25, 0.25] * 2
        )
        self.assertEqual(len(bridge.inputs), 2)

    def test_processing_pause_cannot_extend_beyond_the_dispatch_deadline(self):
        busy = view("busy")
        busy["status"]["ready_for_input"] = False
        bridge = Bridge(view("before"), [busy])
        client = Client(port=1)
        with (
            patch.object(client, "request", side_effect=bridge),
            patch("dfharness.dispatch.time.monotonic", side_effect=[0, 0, 0.99, 1.01]),
            patch("dfharness.dispatch.time.sleep") as pause,
        ):
            receipt = client.act({"type": "key", "key": "A_SHORT_WAIT"}, timeout=1)
        self.assertEqual(receipt["dispatch"]["outcome"], "limit_reached")
        pause.assert_called_once()
        self.assertAlmostEqual(pause.call_args.args[0], 0.01)
        self.assertEqual(len(bridge.inputs), 1)

    def test_invalid_policy_is_rejected_before_dispatch(self):
        client = Client(port=1)
        for policy in (
            {"mode": "safe"},
            {"risk": "low"},
            {"acknowledge": "yes"},
            {"max_steps": True},
            {"max_steps": 0},
            {"max_steps": MAX_DISPATCH_INPUTS + 1},
        ):
            with self.subTest(policy=policy), patch.object(client, "request") as request:
                with self.assertRaises(ValueError):
                    client.act({"type": "key", "key": "A_SHORT_WAIT"}, execution=policy)
                request.assert_not_called()
