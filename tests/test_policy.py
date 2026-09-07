"""Controller-selected health watches through execution, polling and resume."""

import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from dfharness.actions import INTERRUPT
from dfharness.client import Client
from dfharness.mcp import validate
from dfharness.policy import execution_policy, interruption, watch_options
from dfharness.rpc import BridgeError
from tests.support import Bridge
from tests.test_consumption import drank, water_scene
from tests.test_wire import DeltaBridge


def sample(unit_id=2, blood=100, wounds=()):
    return {
        "unit_id": unit_id,
        "available": True,
        "blood_count": blood,
        "wounds": len(wounds),
        "wound_ids": list(wounds),
    }


def watch(**flags):
    return execution_policy(
        {"mode": "complete", "interrupt_on": {"unit_health": [{"unit_id": 2, **flags}]}}
    )


class HealthWatchTests(unittest.TestCase):
    def test_processing_reader_fields_follow_enabled_controller_predicates(self):
        policy = execution_policy(
            {
                "interrupt_on": {
                    "blood_loss": True,
                    "new_wounds": False,
                    "visible_unit_ids": [0],
                    "unit_health": [{"unit_id": 2, "new_wounds": True}],
                }
            }
        )
        self.assertEqual(
            watch_options(policy),
            {
                "progress_watch": {"blood_count": True, "visible_units": True},
                "watch_units": [2],
            },
        )
        policy = execution_policy(
            {
                "interrupt_on": {
                    "blood_loss": False,
                    "new_visible_units": False,
                    "new_visible_units_except": [0],
                    "report_types": ["COMBAT_STRIKE_DETAILS"],
                }
            }
        )
        self.assertEqual(watch_options(policy), {})
        policy["interrupt_on"].update(new_wounds=True, new_visible_units=True)
        self.assertEqual(
            watch_options(policy),
            {
                "progress_watch": {"wounds": True, "visible_units": True},
            },
        )

    def test_player_health_unknown_cannot_pass_an_enabled_watch(self):
        known = {"adventurer": {"health": {"blood_count": 100, "wounds": 0}}}
        for condition, field in (("blood_loss", "blood_count"), ("new_wounds", "wounds")):
            policy = execution_policy({"interrupt_on": {condition: True}})
            for bad in (None, False, -1, "0", 0.5):
                unknown = {"adventurer": {"health": {field: bad}}}
                for when, old, new in (("initial", unknown, known), ("current", known, unknown)):
                    with self.subTest(condition=condition, bad=bad, when=when):
                        stopped = interruption(old, new, [], policy)
                        self.assertEqual(stopped["outcome"], "needs_input")
                        self.assertEqual(stopped["details"]["facts"]["reading"], when)
            unavailable = {"adventurer": {"health": {"unavailable": {field: "offloaded"}}}}
            self.assertEqual(
                interruption(known, unavailable, [], policy)["details"]["facts"]["reason"],
                "offloaded",
            )
            self.assertIsNone(interruption(known, unavailable, [], execution_policy()))
        depleted = {"adventurer": {"health": {"blood_count": 0, "wounds": 0}}}
        stopped = interruption(
            known, depleted, [], execution_policy({"interrupt_on": {"blood_loss": True}})
        )
        self.assertEqual(stopped["outcome"], "interrupted")
        self.assertEqual(stopped["details"]["facts"]["blood_count"], [100, 0])

    def test_visibility_requires_known_complete_enumeration_for_each_needed_sample(self):
        known = {"map": {"units": [{"id": 0}], "units_available": True}}
        for bad in (
            {},
            {"units": None},
            {"units": [{"id": False}]},
            {"units": [], "units_available": False, "units_unavailable": "read failed"},
            {"units": [], "units_truncated": True},
        ):
            for when, old, new in (
                ("initial", {"map": bad}, known),
                ("current", known, {"map": bad}),
            ):
                with self.subTest(bad=bad, when=when):
                    stopped = interruption(
                        old,
                        new,
                        [],
                        execution_policy({"interrupt_on": {"new_visible_units": True}}),
                    )
                    self.assertEqual(stopped["outcome"], "needs_input")
                    self.assertEqual(stopped["details"]["facts"]["reading"], when)
        # A current-ID check does not require initial visibility. An offloaded
        # local map establishes an empty set without pretending health is known.
        explicit = execution_policy({"interrupt_on": {"visible_unit_ids": [0]}})
        self.assertEqual(interruption({}, known, [], explicit)["outcome"], "interrupted")
        self.assertIsNone(interruption(known, {"status": {"map_loaded": False}}, [], explicit))

    def test_unavailable_pending_player_watch_retains_reports_and_requires_explicit_resume(self):
        initial = water_scene("before", portions=1, opened=True)
        done = water_scene("done", portions=0, thirst=0, reports=[drank(1)])
        bridge = DeltaBridge(initial, [done])
        pending = {
            "ready": False,
            "pending_view": {
                "schema_version": 1,
                "status": {"ready_for_input": False},
                "adventurer": {"health": {"unavailable": {"blood_count": "offloaded"}}},
                "reports": [drank(1)],
            },
        }
        bridge.poll_hook = lambda _peer, req: pending if req.get("pending_reads") else None
        client = Client(
            port=1, execution={"mode": "complete", "interrupt_on": {"blood_loss": True}}
        )
        with patch.object(client, "request", side_effect=bridge):
            receipt = client.act({"type": "drink", "item_id": 10})
            full = client.dispatch_details(receipt["dispatch_id"], section="full")["value"]
            bridge.poll_hook = None
            resumed = client.act(receipt["resume"])
        self.assertEqual(receipt["outcome"], "needs_input")
        self.assertEqual(receipt["blocker"]["kind"], "watch_unavailable")
        self.assertEqual(receipt["blocker"]["facts"]["reason"], "offloaded")
        self.assertEqual(full["adventurer"], done["adventurer"])
        self.assertEqual([e["id"] for e in full["dispatch"]["events"]], [1])
        self.assertEqual(resumed["outcome"], "completed")
        self.assertEqual(resumed["inputs"], 0)
        self.assertEqual(len(bridge.inputs), 1)
        for call in bridge.wire_calls:
            if call["op"] in ("begin_dispatch", "observe", "poll", "act"):
                self.assertEqual(call["progress_watch"], {"blood_count": True})

    def test_policy_requires_explicit_distinct_targets_and_conditions(self):
        for value in (
            None,
            {},
            [2],
            [{}],
            [{"unit_id": 2}],
            [{"unit_id": True, "blood_loss": True}],
            [{"unit_id": -1, "blood_loss": True}],
            [{"unit_id": 2147483648, "blood_loss": True}],
            [{"unit_id": 2, "blood_loss": 1}],
            [{"unit_id": 2, "blood_loss": False}],
            [{"unit_id": 2, "automatic": True}],
            [{"unit_id": 2, "blood_loss": True}] * 2,
            [{"unit_id": i, "blood_loss": True} for i in range(33)],
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                execution_policy({"interrupt_on": {"unit_health": value}})
        policy = execution_policy(
            {"interrupt_on": {"unit_health": [{"unit_id": 0, "new_wounds": True}]}}
        )
        validate(policy["interrupt_on"], INTERRUPT)
        self.assertEqual(watch_options(policy), {"watch_units": [0]})
        self.assertEqual(watch_options(execution_policy()), {})

    def test_new_wound_identity_detects_replacement_without_count_growth(self):
        before = {"watched_units": [sample(wounds=[5])]}
        after = {"watched_units": [sample(wounds=[6])]}
        stopped = interruption(before, after, [], watch(new_wounds=True))
        self.assertEqual(stopped["outcome"], "interrupted")
        self.assertEqual(stopped["details"]["facts"]["new_wound_ids"], [6])
        self.assertEqual(stopped["details"]["facts"]["unit_id"], 2)
        self.assertIsNone(interruption(before, after, [], watch(blood_loss=True)))
        self.assertIsNone(
            interruption(before, {"watched_units": [sample()]}, [], watch(new_wounds=True))
        )

    def test_zero_blood_and_unavailable_fields_are_distinct(self):
        before = {"watched_units": [sample()]}
        after = {"watched_units": [sample(blood=0)]}
        stopped = interruption(before, after, [], watch(blood_loss=True))
        self.assertEqual(stopped["details"]["facts"]["blood_count"], [100, 0])
        for value in (None, False, "0", -1):
            after["watched_units"][0]["blood_count"] = value
            self.assertEqual(
                interruption(before, after, [], watch(blood_loss=True))["outcome"], "needs_input"
            )
        after = {
            "watched_units": [
                {
                    "unit_id": 2,
                    "available": True,
                    "blood_count": 100,
                    "unavailable": {"wound_ids": "enumeration exceeds bound"},
                }
            ]
        }
        self.assertIsNone(interruption(before, after, [], watch(blood_loss=True)))
        stopped = interruption(before, after, [], watch(new_wounds=True))
        self.assertEqual(stopped["details"]["facts"]["reason"], "enumeration exceeds bound")

    def test_missing_initial_and_current_samples_never_count_as_healthy(self):
        known = {"watched_units": [sample()]}
        for when, before, after in (("initial", {}, known), ("current", known, {})):
            stopped = interruption(before, after, [], watch(blood_loss=True))
            self.assertEqual(stopped["outcome"], "needs_input")
            self.assertEqual(stopped["details"]["facts"]["reading"], when)
        missing = {"watched_units": [{"unit_id": 2, "available": False, "reason": "not visible"}]}
        self.assertEqual(
            interruption(known, missing, [], watch(new_wounds=True))["details"]["facts"]["reason"],
            "not visible",
        )
        self.assertIsNone(interruption(known, missing, [], execution_policy()))

    def test_unavailable_watch_blocks_before_input_and_can_resume_with_changed_policy(self):
        initial = water_scene("initial", portions=0, thirst=0)
        initial["watched_units"] = [{"unit_id": 2, "available": False, "reason": "not visible"}]
        bridge = Bridge(initial)
        client = Client(port=1, execution=watch(blood_loss=True))
        with patch.object(client, "request", side_effect=bridge):
            result = client.act({"type": "resume"})
            resumed = client.act(result["resume"], execution={"interrupt_on": {}})
        self.assertEqual(result["outcome"], "needs_input")
        self.assertEqual(result["blocker"]["kind"], "watch_unavailable")
        self.assertEqual(result["blocker"]["facts"]["unit_id"], 2)
        self.assertEqual(result["inputs"], 0)
        self.assertEqual(resumed["outcome"], "completed")
        self.assertEqual(bridge.inputs, [])

    def test_pending_injury_stops_inputs_refreshes_details_and_resumes_without_repeating(self):
        initial = water_scene("before", portions=1, opened=True)
        initial["watched_units"] = [sample()]
        done = water_scene("after", portions=0, thirst=0, reports=[drank(1)])
        done["watched_units"] = [sample(wounds=[0])]
        bridge = DeltaBridge(initial, [done])
        pending = {
            "ready": False,
            "pending_view": {
                "schema_version": 1,
                "status": {"ready_for_input": False},
                "watched_units": deepcopy(done["watched_units"]),
                "reports": [drank(1)],
            },
        }
        bridge.poll_hook = lambda _peer, request: pending if request.get("pending_reads") else None
        client = Client(port=1, execution=watch(new_wounds=True))
        with patch.object(client, "request", side_effect=bridge):
            result = client.act({"type": "drink", "item_id": 10})
            full = client.dispatch_details(result["dispatch_id"], section="full")["value"]
            bridge.poll_hook = None
            resumed = client.act(result["resume"])
        self.assertEqual(result["outcome"], "interrupted")
        self.assertEqual(
            result["blocker"]["facts"],
            {"unit_id": 2, "condition": "new_wounds", "new_wound_ids": [0]},
        )
        self.assertEqual(full["watched_units"], done["watched_units"])
        self.assertEqual(full["adventurer"], done["adventurer"])
        self.assertEqual(resumed["outcome"], "completed")
        self.assertEqual(resumed["inputs"], 0)
        self.assertEqual(len(bridge.inputs), 1)
        self.assertLess(len(json.dumps(result)), 1700)
        for call in bridge.wire_calls:
            if call["op"] in ("begin_dispatch", "observe", "poll", "act"):
                self.assertEqual(call["watch_units"], [2])
            if call["op"] == "act":
                self.assertEqual(call["watch_expect"], initial["watched_units"])

    def test_unwatched_dispatch_adds_no_reader_or_guard_payload(self):
        bridge = Bridge(
            water_scene("before", portions=1, opened=True),
            [water_scene("after", portions=0, thirst=0, reports=[drank(1)])],
        )
        client = Client(port=1, execution={"mode": "complete"})
        with patch.object(client, "request", side_effect=bridge):
            result = client.act({"type": "drink", "item_id": 10})
        self.assertEqual(result["outcome"], "completed")
        self.assertTrue(
            all("watch_units" not in call and "watch_expect" not in call for call in bridge.calls)
        )

    def test_preflight_health_change_returns_facts_and_does_not_commit_unsent_input(self):
        initial = water_scene("before", portions=1, opened=True)
        initial["watched_units"] = [sample()]
        injured = deepcopy(initial)
        injured["watched_units"] = [sample(blood=90)]
        done = water_scene("done", portions=0, thirst=0, reports=[drank(1)])
        done["watched_units"] = deepcopy(injured["watched_units"])
        bridge = Bridge(initial, [done])
        rejected = False

        def request(call):
            nonlocal rejected
            if call["op"] == "act" and not rejected:
                rejected = True
                bridge.view = deepcopy(injured)
                raise BridgeError(
                    "Watched health changed",
                    code="watch_changed",
                    details={"view": deepcopy(injured)},
                    input_sent=False,
                )
            return bridge(call)

        client = Client(port=1, execution=watch(blood_loss=True))
        with patch.object(client, "request", side_effect=request):
            result = client.act({"type": "drink", "item_id": 10})
            self.assertEqual(bridge.inputs, [])
            self.assertNotIn(
                "pending", bridge.dispatches[result["dispatch_id"]]["workflow"]["context"]
            )
            resumed = client.act(result["resume"])
        self.assertEqual(result["outcome"], "interrupted")
        self.assertEqual(result["inputs"], 0)
        self.assertEqual(result["blocker"]["facts"]["blood_count"], [100, 90])
        self.assertEqual(resumed["outcome"], "completed")
        self.assertEqual(len(bridge.inputs), 1)
