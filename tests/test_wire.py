import json
import random
import unittest
from copy import deepcopy
from unittest.mock import patch

from dfharness.client import Client
from dfharness.rpc import DFHackError
from dfharness.wire import apply_delta, delta, observation
from tests.support import Bridge
from tests.test_consumption import drank, water_scene


class DeltaBridge(Bridge):
    """Wire peer around the independent scripted gameplay boundary."""

    def __init__(self, *args):
        super().__init__(*args)
        self.wire_calls = []
        self.responses = []
        self.bad_revision = False

    def __call__(self, request):
        self.wire_calls.append(deepcopy(request))
        req = deepcopy(request)
        op = req["op"]
        record = self.dispatches.get(req.get("parent_dispatch") or req.get("action_id"))
        if "workflow_delta" in req:
            assert record is not None
            d = req.pop("workflow_delta")
            if d["base"] != record["workflow_revision"]:
                raise DFHackError("Checkpoint base mismatch")
            req["workflow"] = apply_delta(record["workflow"], d["change"])
        if "view_ref" in req and op == "finish_dispatch":
            assert record is not None
            ref = req.pop("view_ref")
            if ref != record["view_ref"]:
                raise DFHackError("Final observation mismatch")
            req["view"] = deepcopy(record["snapshot"])
            req["view"]["status"].pop("active_dispatch", None)
        if req.pop("dispatch_from_workflow", False):
            for key in ("action", "events", "prompts"):
                req["dispatch"][key] = deepcopy(req["workflow"][key])
            if "results" in req["workflow"].get("context", {}):
                req["dispatch"]["results"] = deepcopy(req["workflow"]["context"]["results"])
            req["view"]["dispatch"] = deepcopy(req["dispatch"])
            req["view"]["action"] = {"action_id": req["action_id"]}
        response = super().__call__(req)
        if op == "begin_dispatch" and not response.get("duplicate"):
            record = self.dispatches[req["request_id"]]
            record["workflow_revision"] = response["workflow_revision"] = 0
            response["ready"] = self.view["status"].get("ready_for_input", True)
            record["snapshot"] = deepcopy(response["view"])
            record["view_ref"] = response["view_ref"] = {
                "dispatch_id": req["request_id"],
                "revision": 1,
            }
        elif op == "poll" and "view" in response:
            record = self.dispatches[req["dispatch_id"]]
            current = response.pop("view")
            previous_ref = record["view_ref"]
            if req.get("view_ref") == previous_ref:
                response["view_delta"] = {
                    "base": previous_ref,
                    "change": delta(record["snapshot"], current),
                }
            else:
                response["view"] = current
            record["snapshot"] = deepcopy(current)
            record["view_ref"] = response["view_ref"] = dict(
                previous_ref, revision=previous_ref["revision"] + 1
            )
            if self.bad_revision:
                response["view_ref"] = dict(response["view_ref"], revision=0)
        elif op in ("act", "finish_dispatch") and not response.get("interrupted"):
            assert record is not None
            record["workflow_revision"] += 1
            response["workflow_revision"] = record["workflow_revision"]
        self.responses.append(deepcopy(response))
        return response


class WireTests(unittest.TestCase):
    def test_pending_pages_preserve_full_delta_base_inventory_and_collected_reports(self):
        initial = water_scene("menu", portions=1, opened=True)
        done = water_scene("done", portions=0, thirst=0)
        b = DeltaBridge(initial, [done])
        polls = 0

        def pending(peer, request):
            nonlocal polls
            polls += 1
            if polls > 2:
                return None
            self.assertTrue(request["pending_reads"])
            self.assertEqual(request["view_ref"]["revision"], 1)
            return {
                "ready": False,
                "pending_view": {
                    "schema_version": 1,
                    "status": {"ready_for_input": False},
                    "reports": [drank(1)]
                    if polls == 1
                    else [{"id": 2, "type": "REGULAR_CONVERSATION", "text": "Hello"}],
                    "reports_more": polls == 1,
                },
            }

        b.poll_hook = pending
        c = Client(port=1, execution={"mode": "complete"})
        with patch.object(c, "request", side_effect=b), patch("dfharness.dispatch.time.sleep"):
            result = c.act({"type": "drink", "item_id": 10})
            saved = c.dispatch_details(result["dispatch_id"], section="full")["value"]
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(saved["adventurer"]["inventory"], [])
        self.assertEqual(saved["map"], done["map"])
        self.assertEqual([r["id"] for r in saved["dispatch"]["events"]], [1, 2])
        self.assertEqual(len(b.inputs), 1)
        self.assertFalse(any(r["op"] == "observe" for r in b.wire_calls))
        self.assertEqual(
            next(r for r in b.wire_calls if r["op"] == "finish_dispatch")["view_ref"]["revision"], 2
        )

    def test_interruption_on_a_pending_sample_refreshes_the_final_diagnostic_view(self):
        initial = water_scene("before", portions=1, opened=True)
        done = water_scene("blood-loss", portions=0, thirst=0, reports=[drank(1)])
        done["adventurer"]["health"]["blood_count"] = 900
        b = DeltaBridge(initial, [done])
        pending = {
            "ready": False,
            "pending_view": {
                "schema_version": 1,
                "status": {"ready_for_input": False},
                "adventurer": {"health": {"blood_count": 900, "wounds": 0}},
                "reports": [drank(1)],
            },
        }
        b.poll_hook = lambda _peer, request: pending if request.get("pending_reads") else None
        c = Client(port=1, execution={"mode": "complete", "interrupt_on": {"blood_loss": True}})
        with patch.object(c, "request", side_effect=b):
            result = c.act({"type": "drink", "item_id": 10})
            saved = c.dispatch_details(result["dispatch_id"], section="full")["value"]
            b.poll_hook = None
            resumed = c.act(result["resume"])
        self.assertEqual(result["outcome"], "interrupted")
        self.assertEqual(result["changes"]["health"]["blood_count"], [1000, 900])
        self.assertEqual(saved["adventurer"], done["adventurer"])
        self.assertEqual(saved["map"], done["map"])
        self.assertEqual(saved["dispatch"]["events"], [drank(1)])
        self.assertEqual(resumed["outcome"], "completed")
        self.assertEqual(resumed["inputs"], 0)
        self.assertFalse(any(r["op"] == "observe" for r in b.wire_calls))
        final = next(r for r in b.wire_calls if r["op"] == "finish_dispatch")
        self.assertNotIn("view", final)
        self.assertEqual(final["view_ref"]["revision"], 2)
        self.assertEqual(len(b.inputs), 1)

    def test_final_refresh_rejects_a_partial_snapshot_and_revokes_progress_on_world_change(self):
        for changed in (False, True):
            initial = water_scene("before", portions=1, opened=True)
            done = water_scene("done", portions=0, thirst=0)
            b = DeltaBridge(initial, [done])
            pending = {
                "ready": False,
                "pending_view": {
                    "schema_version": 1,
                    "status": {"ready_for_input": False},
                    "adventurer": {"health": {"blood_count": 900, "wounds": 0}},
                },
            }

            def poll(_peer, request, changed=changed, pending=pending, done=done):
                if request.get("pending_reads") or not changed:
                    return pending
                return {"ready": True, "world_changed": True, "view": deepcopy(done)}

            b.poll_hook = poll
            c = Client(port=1, execution={"mode": "complete", "interrupt_on": {"blood_loss": True}})
            with patch.object(c, "request", side_effect=b):
                if changed:
                    r = c.act({"type": "drink", "item_id": 10})
                    self.assertEqual(r["blocker"]["kind"], "world_changed")
                    self.assertNotIn("resume", r)
                else:
                    with self.assertRaisesRegex(DFHackError, "Final observation is still partial"):
                        c.act({"type": "drink", "item_id": 10})
            self.assertEqual(len(b.inputs), 1)

    def test_invalid_or_ready_pending_samples_never_drive_a_second_input(self):
        for bad in (
            {"ready": True},
            {"view_ref": {"revision": 2}},
            {"pending_view": {"schema_version": 2, "status": {}}},
        ):
            b = DeltaBridge(water_scene("start"), [water_scene("menu", opened=True)])
            b.poll_hook = lambda _peer, _request, bad=bad: {
                "ready": False,
                "pending_view": {"schema_version": 1, "status": {}},
                **bad,
            }
            c = Client(port=1, execution={"mode": "complete"})
            with (
                patch.object(c, "request", side_effect=b),
                self.assertRaisesRegex(DFHackError, "Invalid pending"),
            ):
                c.act({"type": "drink", "item_id": 10})
            self.assertEqual(len(b.inputs), 1)

    def test_semantic_execution_defers_ui_but_raw_inputs_and_full_diagnostics_capture_it(self):
        for action, result_format, expected in (
            ({"type": "wait"}, "compact", "native"),
            ({"type": "wait"}, "full", "full"),
            ({"type": "key", "key": "A_SHORT_WAIT"}, "compact", "full"),
        ):
            with self.subTest(action=action, result_format=result_format):
                b = DeltaBridge(water_scene("before"), [water_scene("after")])
                c = Client(port=1, execution={"mode": "complete"})
                with patch.object(c, "request", side_effect=b):
                    c.act(action, result_format=result_format)
                reads = [r for r in b.wire_calls if r["op"] in ("begin_dispatch", "poll", "act")]
                self.assertTrue(reads)
                self.assertTrue(all(r["ui_mode"] == expected for r in reads))

    def test_world_reload_stops_without_mixing_histories_or_offering_stale_resume(self):
        old = water_scene("old")
        new = water_scene("new", reports=[dict(drank(99), text="Other world's report")])
        old["status"]["world_epoch"] = "old"
        new["status"]["world_epoch"] = "new"
        b = DeltaBridge(old, [new])
        b.poll_hook = lambda peer, _req: {
            "ready": True,
            "world_changed": True,
            "interrupted": True,
            "view": deepcopy(peer.view),
        }
        c = Client(port=1, execution={"mode": "complete"})
        with patch.object(c, "request", side_effect=b):
            result = c.act({"type": "drink", "item_id": 10})
            full = c.dispatch_details(result["dispatch_id"], section="full")
        self.assertEqual(len(b.inputs), 1)
        self.assertEqual(result["blocker"]["kind"], "world_changed")
        self.assertNotIn("resume", result)
        self.assertNotIn("changes", result)
        self.assertEqual(full["value"]["dispatch"]["events"], [])

    def test_compact_duplicate_requires_neither_a_new_observation_nor_a_lease(self):
        c = Client(port=1)
        saved = {"outcome": "completed", "dispatch_id": "old", "inputs": 1}
        with patch.object(
            c, "request", return_value={"duplicate": True, "compact": saved}
        ) as request:
            self.assertEqual(c.act({"type": "wait"}, request_id="old"), dict(saved, replayed=True))
        self.assertEqual(request.call_count, 1)

    def test_random_json_round_trips_and_does_not_mutate_its_base(self):
        rng = random.Random(3)

        def value(depth):
            if not depth or rng.randrange(3) == 0:
                return rng.choice([None, False, True, 0, 1, 3.5, "", "hello"])
            if rng.randrange(2):
                return [value(depth - 1) for _ in range(rng.randrange(4))]
            return {key: value(depth - 1) for key in rng.sample(["a", "b", "c"], rng.randrange(4))}

        for _ in range(500):
            before, after = value(4), value(4)
            original = deepcopy(before)
            actual = apply_delta(before, json.loads(json.dumps(delta(before, after))))
            self.assertEqual(type(actual), type(after))
            self.assertEqual(actual, after)
            self.assertEqual(before, original)

    def test_one_item_field_changes_without_sending_other_inventory_fields(self):
        initial = {
            "inventory": [{"id": i, "description": "armor " * 500, "count": 5} for i in range(30)]
        }
        final = deepcopy(initial)
        final["inventory"][29]["count"] = 4
        change = delta(initial, final)
        self.assertLess(len(json.dumps(change)), 150)
        self.assertEqual(apply_delta(initial, change), final)

    def test_observation_mismatch_and_unknown_shapes_fail_before_input(self):
        ref = {"dispatch_id": "a", "revision": 1}
        for response in (
            {"view_delta": {"base": dict(ref, dispatch_id="b"), "change": {}}},
            {"view_delta": {"base": ref, "change": {}}, "view_ref": dict(ref, revision=3)},
        ):
            with self.assertRaises(DFHackError):
                observation(response, {}, ref)
        for before, change in (({}, {"entries": {}}), ([], {"length": 2}), ({}, {"remove": ["x"]})):
            with self.assertRaises(DFHackError):
                apply_delta(before, change)

    def test_dispatch_resume_reconstructs_state_and_retains_full_details_without_uploading_views(
        self,
    ):
        b = DeltaBridge(
            water_scene("start"),
            [
                water_scene("menu", opened=True),
                water_scene("one", 1, 50000, reports=[drank(1)]),
                water_scene("menu2", 1, 50000, opened=True, reports=[drank(1)]),
                water_scene("done", 0, 0, reports=[drank(1), drank(2)]),
            ],
        )
        c = Client(port=1, execution={"mode": "complete"})
        with patch.object(c, "request", side_effect=b):
            first = c.act(
                {"type": "drink", "item_id": 10, "portions": 2}, execution={"max_steps": 2}
            )
            final = c.act(first["resume"], result_format="full")
            stored = c.dispatch_details(final["dispatch"]["id"], section="full")
        self.assertEqual(first["outcome"], "limit_reached")
        self.assertEqual(final["dispatch"]["outcome"], "completed")
        self.assertEqual(final["adventurer"]["inventory"], [])
        self.assertEqual(final["dispatch"]["events"], [drank(1), drank(2)])
        self.assertEqual(stored["value"], final)
        finish = [r for r in b.wire_calls if r["op"] == "finish_dispatch"]
        self.assertTrue(all("view" not in r and "workflow" not in r for r in finish))
        self.assertTrue(all("events" not in r["dispatch"] for r in finish))
        self.assertEqual(len(b.inputs), 4)

    def test_bad_poll_revision_never_sends_another_input(self):
        b = DeltaBridge(water_scene("start"), [water_scene("menu", opened=True)])
        b.bad_revision = True
        c = Client(port=1)
        with patch.object(c, "request", side_effect=b), self.assertRaises(DFHackError):
            c.act({"type": "drink", "item_id": 10})
        self.assertEqual(len(b.inputs), 1)

    def test_verified_stages_reuse_the_snapshot_until_the_next_native_input(self):
        initial = water_scene("idle")
        initial["adventurer"]["movement"] = {"available": True, "sneaking": False}
        b = DeltaBridge(initial)
        c = Client(port=1, execution={"mode": "complete"})
        with patch.object(c, "request", side_effect=b):
            r = c.act(
                {"type": "sequence", "actions": [{"type": "set_sneaking", "enabled": False}] * 20}
            )
        self.assertEqual(r["outcome"], "completed")
        self.assertEqual(r["completed_stages"], 20)
        self.assertEqual([r["op"] for r in b.wire_calls], ["begin_dispatch", "finish_dispatch"])
        self.assertEqual(b.inputs, [])
