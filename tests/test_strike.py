import io
import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from dfharness.cli import main
from dfharness.rpc import BridgeError, DFHackError, DispatchError
from dfharness.state import render_receipt
from dfharness.workflows import validate_action
from tests.support import Bridge
from tests.support import FullClient as Client
from tests.test_workflows import scene

ACTION = {
    "type": "strike",
    "unit_id": 2,
    "body_part_id": 3,
    "item_id": 4,
    "attack_index": 0,
    "style": "quick",
}
TARGET = {"id": 2, "position": {"x": 3, "y": 1, "z": 0}}


def choice(name, **fields):
    return {"id": name, "index": 0, "selection": {"method": "native_hotkey"}, **fields}


def combat(mode=None, *, flags=(), options=None, x=2):
    view = scene(mode or "closed", x=x, units=[TARGET])
    view["strike_state"] = {"available": True, "unit_id": 1, "actions": []}
    if mode:
        defaults = {
            "UNIT_CHOICE": [choice("target", unit_id=2)],
            "CONFIRM": [choice("confirm", native_type="confirm")],
            "MOVE_CHOICE": [choice("strike", native_type="STRIKE")],
            "AIM_TARGET": [choice("head", body_part_id=3)],
            "AIM_ATTACK": [
                choice("hammer", kind="attack", body_part_id=3, item_id=4, attack_index=0)
            ],
        }
        view["status"]["can_move"] = False
        view["combat"] = {
            "open": True,
            "kind": "combat",
            "mode": mode,
            "target_unit_id": 2,
            "always_do_something": False,
            "options": defaults.get(mode, []) if options is None else options,
            "attack_flags": list(flags),
            "style_keys": {
                k: k.upper() + "_ATTACK"
                for k in ("quick", "heavy", "wild", "precise", "charge", "multi")
            },
        }
    return view


def evidence(phase="finished"):
    return {
        "kind": "strike",
        "available": True,
        "unit_id": 1,
        "target_unit_id": 2,
        "body_part_id": 3,
        "item_id": 4,
        "attack_index": 0,
        "phase": phase,
        "strike_observed": phase in ("finished", "recovering"),
        "recovery_observed": phase == "finished",
        "tracking": phase in ("preparing", "recovering"),
        "native_action": {"id": 50},
        "latest": {"strike_ticks": 0, "recovery_ticks": 1},
    }


def resolved(phase="finished"):
    view = combat()
    view.update(input_evidence=evidence(phase), effect_id=phase, state_id=phase)
    return view


class StrikeTests(unittest.TestCase):
    def client(self, bridge):
        client = Client(port=1, execution={"mode": "complete", "acknowledge": True})
        p = patch.object(client, "request", side_effect=bridge)
        p.start()
        self.addCleanup(p.stop)
        return client

    def test_targets_aim_and_style_are_executed_as_one_verified_dispatch(self):
        b = Bridge(
            combat(x=1),
            [
                combat(),
                combat("UNIT_CHOICE"),
                combat("CONFIRM"),
                combat("MOVE_CHOICE"),
                combat("AIM_TARGET"),
                combat("AIM_ATTACK"),
                combat("AIM_ATTACK", flags=["quick"]),
                resolved(),
            ],
        )
        r = self.client(b).act(ACTION)
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        self.assertEqual(
            [i["type"] for i in b.inputs],
            [
                "move",
                "key",
                "select_interaction",
                "select_interaction",
                "select_interaction",
                "select_interaction",
                "key",
                "select_interaction",
            ],
        )
        captured = [q for q in b.calls if q.get("capture")]
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["action"]["option_id"], "hammer")
        self.assertTrue(
            any(q.get("input_evidence_for") == captured[0]["request_id"] for q in b.calls)
        )
        self.assertEqual(r["dispatch"]["details"]["attack"]["native_action_id"], 50)

    def test_attack_style_never_inherits_charge_multi_or_previous_heavy_style(self):
        b = Bridge(
            combat("AIM_ATTACK", flags=["multi", "charge", "heavy"]),
            [
                combat("AIM_ATTACK", flags=["multi", "heavy"]),
                combat("AIM_ATTACK", flags=["multi"]),
                combat("AIM_ATTACK"),
                combat("AIM_ATTACK", flags=["quick"]),
                resolved(),
            ],
        )
        r = self.client(b).act(ACTION)
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        self.assertEqual(
            [i.get("key") for i in b.inputs[:-1]],
            ["CHARGE_ATTACK", "HEAVY_ATTACK", "MULTI_ATTACK", "QUICK_ATTACK"],
        )

    def test_no_effect_style_or_menu_is_not_repeated_on_resume(self):
        for mode in ("AIM_ATTACK", "MOVE_CHOICE"):
            b = Bridge(combat(mode), [combat(mode)])
            c = self.client(b)
            r = c.act(ACTION)
            self.assertEqual(r["dispatch"]["outcome"], "no_effect")
            r = c.act(r["dispatch"]["resume_action"])
            self.assertEqual(r["dispatch"]["outcome"], "no_effect")
            self.assertEqual(len(b.inputs), 1)

    def test_pending_attack_uses_shared_step_policy_and_resumes_without_resubmission(self):
        b = Bridge(combat("AIM_ATTACK", flags=["quick"]), [resolved("preparing"), resolved()])
        c = self.client(b)
        r = c.act(ACTION, execution={"mode": "step"})
        self.assertEqual(r["dispatch"]["outcome"], "in_progress")
        self.assertEqual(len(b.inputs), 1)
        r = c.act(r["dispatch"]["resume_action"])
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        self.assertEqual(b.inputs[-1], {"type": "wait"})
        self.assertEqual(len(b.inputs), 2)

    def test_injury_interrupt_keeps_input_evidence_for_explicit_resume(self):
        injured = resolved("recovering")
        injured["adventurer"]["health"]["wounds"] = 1
        b = Bridge(combat("AIM_ATTACK", flags=["quick"]), [injured, resolved()])
        c = self.client(b)
        r = c.act(ACTION, execution={"interrupt_on": {"new_wounds": True}})
        self.assertEqual(r["dispatch"]["outcome"], "interrupted")
        r = c.act(r["dispatch"]["resume_action"])
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        self.assertEqual(
            b.inputs, [{"type": "select_interaction", "option_id": "hammer"}, {"type": "wait"}]
        )

    def test_unverified_attack_is_not_resubmitted_but_late_evidence_can_complete(self):
        b = Bridge(combat("AIM_ATTACK", flags=["quick"]), [resolved("unverified")])
        c = self.client(b)
        r = c.act(ACTION)
        self.assertEqual(r["dispatch"]["outcome"], "no_effect")
        r = c.act(r["dispatch"]["resume_action"])
        self.assertEqual(len(b.inputs), 1)
        b.view = resolved()
        r = c.act(r["dispatch"]["resume_action"])
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        self.assertEqual(len(b.inputs), 1)

    def test_lost_submission_reply_recovers_evidence_from_the_native_checkpoint(self):
        b = Bridge(combat("AIM_ATTACK", flags=["quick"]), [resolved()])

        def request(q):
            answer = b(q)
            if q["op"] == "act":
                raise DFHackError("Lost input response")
            return answer

        c = self.client(request)
        with self.assertRaises(DispatchError) as error:
            c.act(ACTION)
        r = c.act(error.exception.resume_action)
        self.assertEqual(r["dispatch"]["outcome"], "completed")
        self.assertEqual(len(b.inputs), 1)

    def test_wrong_aim_identity_or_expired_evidence_blocks_without_new_input(self):
        for broken in (
            {"available": False},
            dict(evidence(), item_id=99),
            dict(evidence(), target_unit_id=99),
        ):
            after = resolved()
            after["input_evidence"] = broken
            b = Bridge(combat("AIM_ATTACK", flags=["quick"]), [after])
            r = self.client(b).act(ACTION)
            self.assertEqual(r["dispatch"]["outcome"], "needs_input")
            self.assertEqual(len(b.inputs), 1)

    def test_missing_target_aim_or_key_and_immediate_attack_confirmation_never_choose(self):
        cases = [
            combat("AIM_ATTACK", options=[]),
            combat("AIM_TARGET", options=[]),
            combat("CONFIRM"),
            combat("WRESTLE_GRASP"),
            combat("AIM_ATTACK"),
            combat("AIM_ATTACK", flags=["automatic_hit"]),
        ]
        cases[2]["combat"]["always_do_something"] = None
        cases[4]["combat"]["style_keys"] = {}
        for view in cases:
            b = Bridge(view)
            r = self.client(b).act(ACTION)
            self.assertEqual(r["dispatch"]["outcome"], "needs_input")
            self.assertFalse(b.inputs)

    def test_preexisting_aim_or_automatic_confirmation_reopens_explicit_aiming_once(self):
        for kind in ("target", "body", "confirmation"):
            initial = combat("CONFIRM" if kind == "confirmation" else "AIM_ATTACK")
            if kind == "target":
                initial["combat"]["target_unit_id"] = 99
            elif kind == "body":
                initial["combat"]["options"][0]["body_part_id"] = 99
            else:
                initial["combat"]["always_do_something"] = True
            b = Bridge(initial, [combat(), combat("AIM_ATTACK", flags=["quick"]), resolved()])
            r = self.client(b).act(ACTION)
            self.assertEqual(r["dispatch"]["outcome"], "completed")
            self.assertEqual(
                b.inputs[:2],
                [{"type": "key", "key": "LEAVESCREEN"}, {"type": "key", "key": "A_ATTACK"}],
            )
            b = Bridge(initial, [combat(), initial])
            r = self.client(b).act(ACTION)
            self.assertEqual(r["dispatch"]["outcome"], "needs_input")
            self.assertEqual(len(b.inputs), 2)

    def test_preflight_rejection_does_not_persist_an_unsent_evidence_id(self):
        b = Bridge(combat("AIM_ATTACK", flags=["quick"]))

        def request(q):
            if q["op"] == "act":
                raise BridgeError(
                    "native capture unavailable",
                    code="capture_unavailable",
                    input_sent=False,
                    details={"view": deepcopy(b.view)},
                )
            return b(q)

        c = self.client(request)
        r = c.act(ACTION)
        self.assertEqual(r["dispatch"]["outcome"], "needs_input")
        self.assertNotIn(
            "input_evidence_for", b.dispatches[r["dispatch"]["id"]]["workflow"]["context"]
        )

    def test_completed_receipts_are_small_and_composition_keeps_verification_in_full_trace(self):
        b = Bridge(combat("AIM_ATTACK", flags=["quick"]), [resolved()])
        r = self.client(b).act({"type": "sequence", "actions": [ACTION]}, result_format="compact")
        self.assertEqual(r["outcome"], "completed")
        self.assertLess(len(json.dumps(r)), 1000)
        self.assertNotIn("input_evidence", r)
        record = next(iter(b.dispatches.values()))
        self.assertTrue(record["dispatch"]["results"][0]["details"]["attack"]["strike_observed"])

    def test_compact_objective_values_lead_with_the_effect_and_do_not_repeat_on_resume(self):
        done = resolved()
        done["input_evidence"]["effect"] = {"resolution": "out_of_range", "report_id": 55}
        b = Bridge(combat("AIM_ATTACK", flags=["quick"]), [done])
        c = self.client(b)
        r = c.act(
            {"type": "sequence", "actions": [ACTION, {"type": "walk_to", "x": 9, "y": 9, "z": 0}]},
            result_format="compact",
        )
        self.assertEqual(r["outcome"], "needs_input")
        self.assertEqual(
            r["values"],
            [
                {
                    "stage": 0,
                    "kind": "strike",
                    "unit_id": 2,
                    "recovered": True,
                    "resolution": "out_of_range",
                    "target": {
                        "available": False,
                        "reason": "Target condition is not currently readable",
                    },
                }
            ],
        )
        self.assertIn("out_of_range", render_receipt(r))
        self.assertLess(list(r).index("values"), list(r).index("dispatch_id"))
        b.view["status"]["position"] = {"x": 9, "y": 9, "z": 0}
        resumed = c.act(r["resume"], result_format="compact")
        self.assertEqual(resumed["outcome"], "completed")
        self.assertEqual([value["kind"] for value in resumed["values"]], ["walk_to"])
        self.assertEqual(resumed["values"][0]["stage"], 1)
        self.assertEqual(len(b.inputs), 1)

    def test_strike_contract_requires_explicit_style_and_native_attack_identity(self):
        validate_action(ACTION)
        validate_action(dict(ACTION, item_id=-1))
        for key in ("unit_id", "body_part_id", "item_id", "attack_index", "style"):
            with self.assertRaises(ValueError):
                validate_action({k: v for k, v in ACTION.items() if k != key})
        for fields in (
            {"unit_id": True},
            {"item_id": -2},
            {"style": "charge"},
            {"attack_index": -1},
        ):
            with self.assertRaises(ValueError):
                validate_action(dict(ACTION, **fields))

    def test_a_dead_target_is_returned_before_opening_an_attack_menu(self):
        view = combat()
        view["target_unit"] = dict(TARGET, alive=False, condition={"available": True, "dead": True})
        b = Bridge(view)
        r = self.client(b).act(ACTION)
        self.assertEqual(r["dispatch"]["details"]["blocker_kind"], "attack_target_dead")
        self.assertEqual(b.inputs, [])

    def test_cli_passes_native_aim_and_policy_without_a_separate_field_allowlist(self):
        with patch("dfharness.cli.Client") as cls, patch("sys.stdout", new_callable=io.StringIO):
            cls.return_value.act.return_value = {}
            rc = main(
                [
                    "strike",
                    "2",
                    "--body-part-id",
                    "3",
                    "--item-id",
                    "4",
                    "--attack-index",
                    "0",
                    "--style",
                    "quick",
                    "--mode",
                    "complete",
                    "--max-steps",
                    "12",
                ]
            )
            self.assertEqual(rc, 0)
            args = cls.return_value.act.call_args.args
            validate_action(args[0])
            for key, value in ACTION.items():
                self.assertEqual(args[0][key], value)
            self.assertEqual(args[4], {"mode": "complete", "max_steps": 12})


if __name__ == "__main__":
    unittest.main()
