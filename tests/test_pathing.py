import io
import unittest
from unittest.mock import patch

from dfharness.cli import main
from dfharness.client import Client
from dfharness.pathing import next_native_walk
from tests.support import Bridge
from tests.test_workflows import scene


def native_scene(label, x=1):
    view = scene(label, x=x)
    view["native_path"] = {"available": True, "goal": "None"}
    return view


class NativePathTests(unittest.TestCase):
    def test_cli_does_not_invent_constraints_that_force_the_legacy_adapter(self):
        for argv in (["walk-to", "8", "1", "0"], ["talk", "2"], ["combat", "2"]):
            with (
                patch("dfharness.cli.Client") as factory,
                patch("sys.stdout", new_callable=io.StringIO),
            ):
                factory.return_value.act.return_value = {"outcome": "completed"}
                self.assertEqual(main(argv), 0)
                action = factory.return_value.act.call_args.args[0]
                self.assertFalse(
                    {"blocked_tiles", "allow_occupied", "max_liquid_depth", "extend_route"}
                    & action.keys()
                )

    def test_native_approach_evidence_is_not_mistaken_for_a_submitted_strike(self):
        from tests.test_strike import ACTION, combat, resolved

        before = combat(x=1)
        before["native_path"] = {"available": True, "goal": "None"}
        arrived = combat()
        arrived["input_evidence"] = {"kind": "walk", "available": True, "phase": "completed"}
        game = Bridge(before, [arrived, combat("AIM_ATTACK", flags=["quick"]), resolved()])
        client = Client(port=1)
        with patch.object(client, "request", side_effect=game):
            receipt = client.act(ACTION, execution={"mode": "complete"})
        self.assertEqual(receipt["outcome"], "completed")
        self.assertEqual(game.inputs[0]["type"], "path_to")
        self.assertEqual(game.inputs[0]["arrival_radius"], 1)
        self.assertEqual(len(game.inputs), 3)

    def test_one_native_path_input_replaces_direction_steps_and_verifies_arrival(self):
        game = Bridge(native_scene("start"), [native_scene("arrived", x=8)])
        client = Client(port=1)
        with patch.object(client, "request", side_effect=game):
            result = client.act(
                {"type": "walk_to", "x": 8, "y": 1, "z": 0}, execution={"mode": "complete"}
            )
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual([r["action"]["type"] for r in game.calls if r["op"] == "act"], ["path_to"])
        request = next(r for r in game.calls if r["op"] == "act")
        self.assertEqual(request["path_execution"]["mode"], "complete")
        self.assertGreater(request["path_timeout_ms"], 0)
        self.assertEqual(result["values"][0]["adapter"], "native_path")

    def test_constraints_remain_on_the_observed_route_adapter(self):
        target = {"x": 2, "y": 1, "z": 0}
        for rules in (
            {"max_liquid_depth": 0},
            {"blocked_tiles": []},
            {"allow_occupied": False},
            {"extend_route": True},
        ):
            self.assertIsNone(next_native_walk(native_scene("start"), target, rules, 0, {}))
        self.assertEqual(
            next_native_walk(native_scene("start"), target, {}, 1, {})["input"]["arrival_radius"], 1
        )

    def test_refusal_does_not_replay_and_another_native_goal_is_not_replaced(self):
        view = native_scene("blocked")
        view["input_evidence"] = {"kind": "walk", "phase": "blocked", "reason": "Native path ended"}
        target = {"x": 2, "y": 1, "z": 0}
        result = next_native_walk(view, target, {}, 0, {"path_evidence_for": "old"})
        self.assertEqual(result["outcome"], "needs_input")
        self.assertNotIn("input", result)
        view["native_path"]["goal"] = "AdventureAutomove"
        result = next_native_walk(view, target, {}, 0, {})
        self.assertEqual(result["details"]["blocker_kind"], "native_path_active")

    def test_transient_native_watch_change_is_assessed_by_the_shared_policy(self):
        before = native_scene("start")
        before["adventurer"]["health"] = {"blood_count": 100}
        after = native_scene("after", x=2)
        after["adventurer"]["health"] = {"blood_count": 100}
        after["input_evidence"] = {
            "kind": "walk",
            "available": True,
            "phase": "paused",
            "reason": "watch_changed",
            "watch_view": {"adventurer": {"health": {"blood_count": 80}}},
        }
        game = Bridge(before, [after])
        client = Client(port=1)
        with patch.object(client, "request", side_effect=game):
            result = client.act(
                {"type": "walk_to", "x": 8, "y": 1, "z": 0},
                execution={"mode": "complete", "interrupt_on": {"blood_loss": True}},
            )
        self.assertEqual(result["outcome"], "interrupted")
        self.assertEqual(result["blocker"]["facts"]["blood_count"], [100, 80])
        game.views.append(native_scene("arrived", x=8))
        with patch.object(client, "request", side_effect=game):
            resumed = client.act(
                {"type": "resume", "dispatch_id": result["dispatch_id"]},
                execution={"mode": "complete", "interrupt_on": {"blood_loss": True}},
            )
        self.assertEqual(resumed["outcome"], "completed")
        self.assertEqual(len(game.inputs), 2)

    def test_missing_or_unsettled_submitted_path_evidence_never_falls_back_or_replays(self):
        target = {"x": 8, "y": 1, "z": 0}
        context = {"path_evidence_for": "already-submitted"}
        for evidence in (
            {},
            {"available": False},
            {"kind": "walk", "available": True, "phase": "running"},
        ):
            for available in (False, True):
                view = native_scene("after", x=2)
                view["native_path"]["available"] = available
                view["input_evidence"] = evidence
                result = next_native_walk(view, target, {}, 0, context)
                self.assertEqual(result["outcome"], "needs_input")
                self.assertNotIn("input", result)


if __name__ == "__main__":
    unittest.main()
