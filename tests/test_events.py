import unittest
from copy import deepcopy
from unittest.mock import patch

from dfharness.client import Client
from dfharness.events import project_events
from dfharness.views import concise_observation
from tests.support import Bridge
from tests.test_workflows import scene


class EventTests(unittest.TestCase):
    def test_projection_keeps_unknown_and_requested_types_and_counts_ambient(self):
        events = [{"id": 0, "type": "REGULAR_CONVERSATION"}, {"id": 1, "type": "NEW_GAME_TYPE"}]
        shown, omitted = project_events(events)
        self.assertEqual(shown, events[1:])
        self.assertEqual(omitted, {"REGULAR_CONVERSATION": 1})
        self.assertEqual(project_events(events, force_types=["REGULAR_CONVERSATION"])[0], events)
        self.assertEqual(project_events(events, "all")[0], events)
        same_type = [{"id": i, "type": "REGULAR_CONVERSATION"} for i in (0, 1)]
        shown, omitted = project_events(same_type, force_ids=[0])
        self.assertEqual(shown, same_type[:1])
        self.assertEqual(omitted, {"REGULAR_CONVERSATION": 1})

    def test_concise_observation_preserves_needs_and_native_omission_metadata(self):
        v = scene("needs", reports=[{"id": 0, "type": "REGULAR_CONVERSATION"}])
        v["reports_truncated"] = 100
        v["reports_more"] = True
        v["next_report_cursor"] = 0
        v["adventurer"]["needs"] = {"thirst": {"severity": 3, "label": "Very thirsty"}}
        r = concise_observation(v)
        self.assertEqual(r["reports_omitted"], 101)
        self.assertEqual(r["report_cursor"], 0)
        self.assertEqual(r["next_report_cursor"], 0)
        self.assertTrue(r["reports_more"])
        self.assertEqual(r["adventurer"]["needs"], v["adventurer"]["needs"])

    def test_dispatch_drains_report_pages_before_another_input(self):
        initial = scene("start", reports=[{"id": 0}])
        first = scene("first", reports=[{"id": 1, "type": "COMBAT"}])
        first.update(reports_more=True, next_report_cursor=1, report_cursor=2)
        final = scene("last", reports=[{"id": 2, "type": "COMBAT"}])
        bridge = Bridge(initial, [first])
        page_seen = False

        def request(req):
            nonlocal page_seen
            if req["op"] == "poll" and req.get("observe") and bridge.inputs:
                if page_seen:
                    self.assertEqual(req["reports_after"], 1)
                    bridge.view = deepcopy(final)
                page_seen = True
            return bridge(req)

        with patch.object(Client, "request", side_effect=request):
            result = Client(port=1, execution={"mode": "complete"}).act({"type": "wait"})
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual([e["id"] for e in result["events"]], [1, 2])
        self.assertEqual(len(bridge.inputs), 1)

    def test_reports_that_arrive_before_resume_are_returned_exactly_once(self):
        initial = scene("start", reports=[{"id": 0}])
        bridge = Bridge(
            initial,
            [
                scene("moved", x=2, reports=[{"id": 1, "type": "COMBAT"}]),
                scene("finished", x=3, reports=[{"id": 2, "type": "COMBAT"}]),
            ],
        )
        client = Client(port=1)
        with patch.object(client, "request", side_effect=bridge):
            first = client.act({"type": "walk_to", "x": 3, "y": 1, "z": 0})
            self.assertEqual([e["id"] for e in first["events"]], [1])
            bridge.view["reports"].append({"id": 2, "type": "COMBAT"})
            final = client.act(first["resume"], execution={"mode": "complete"})
        self.assertEqual([e["id"] for e in final["events"]], [2])
