import unittest
from copy import deepcopy
from unittest.mock import patch

from dfharness.client import Client
from dfharness.refusals import REPORTS, native_refusal
from tests.support import Bridge
from tests.test_dispatch import OKAY
from tests.test_movement import movement
from tests.test_workflows import item, menu, scene


class RefusalTests(unittest.TestCase):
    def client(self, bridge):
        client = Client(port=1, execution={"mode": "complete", "acknowledge": True})
        patcher = patch.object(client, "request", side_effect=bridge)
        patcher.start()
        self.addCleanup(patcher.stop)
        return client

    def test_supported_types_are_scoped_to_an_input_and_not_its_preexisting_reports(self):
        for action, types in REPORTS.items():
            for kind in types:
                workflow = {"action": {"type": action}, "context": {"refusal_after": -1}}
                event = {"id": 0, "type": kind, "text": "Native refusal in any language."}
                found = native_refusal(workflow, scene("a"), [event])
                self.assertEqual(found["reason"], event["text"])
                self.assertEqual(found["facts"]["report_id"], 0)
                workflow["context"]["refusal_after"] = 0
                self.assertIsNone(native_refusal(workflow, scene("a"), [event]))
                workflow["context"] = {}
                self.assertIsNone(native_refusal(workflow, scene("a"), [event]))

    def test_posture_refusal_survives_acknowledgement_and_resume_without_replay(self):
        before = movement("before")
        before["adventurer"]["on_ground"] = True
        denied = deepcopy(before)
        denied.update(state_id="denied", effect_id="denied", report_cursor=12)
        denied["reports"] = [{"id": 12, "type": "CANNOT_STAND", "text": "Somebody is in the way."}]
        modal = deepcopy(denied)
        modal["status"]["modal"] = OKAY
        modal.update(state_id="modal", effect_id="modal")
        bridge = Bridge(before, [modal, denied])
        client = self.client(bridge)
        first = client.act({"type": "set_posture", "posture": "standing"})
        self.assertEqual(first["outcome"], "needs_input")
        self.assertEqual(
            first["blocker"],
            {
                "kind": "native_refusal",
                "why": "Somebody is in the way.",
                "facts": {"type": "CANNOT_STAND", "report_id": 12},
            },
        )
        again = client.act(first["resume"])
        self.assertEqual(again["blocker"], first["blocker"])
        self.assertEqual(again["inputs"], 0)
        self.assertEqual(len(bridge.inputs), 2)
        # A new objective is allowed after the controller changes circumstances.
        stood = deepcopy(denied)
        stood["adventurer"]["on_ground"] = False
        bridge.views.append(stood)
        self.assertEqual(
            client.act({"type": "set_posture", "posture": "standing"})["outcome"], "completed"
        )

    def test_pickup_refusal_does_not_replay_a_consumed_selection_on_resume(self):
        held, ground = [item(8, "Weapon"), item(9, "Hauled")], [item(2, ground=True)]
        offered = scene("menu", held, ground, choices=menu("ENVIRONMENT_PICK_UP_GROUND_ITEM", [2]))
        denied = scene(
            "denied",
            held,
            ground,
            reports=[
                {"id": 1, "type": "NO_GRASP_FOR_PICKUP", "text": "No free grasp."},
            ],
        )
        bridge = Bridge(offered, [denied])
        client = self.client(bridge)
        first = client.act({"type": "pickup", "item_id": 2})
        self.assertEqual(first["blocker"]["facts"]["held_item_ids"], [8, 9])
        self.assertEqual(client.act(first["resume"])["inputs"], 0)
        self.assertEqual(len(bridge.inputs), 1)

    def test_refusals_cannot_override_completion_other_stages_or_injury_interruptions(self):
        before = movement("before")
        before["adventurer"]["on_ground"] = True
        stood = deepcopy(before)
        stood["adventurer"]["on_ground"] = False
        stood["reports"] = [{"id": 1, "type": "CANNOT_STAND", "text": "Other timing."}]
        bridge = Bridge(before, [stood, stood])
        result = self.client(bridge).act(
            {
                "type": "sequence",
                "actions": [
                    {"type": "set_posture", "posture": "standing"},
                    {"type": "set_sneaking", "enabled": True},
                ],
            }
        )
        self.assertEqual(result["completed_stages"], 1)
        self.assertEqual(result["outcome"], "no_effect")
        self.assertNotEqual(result["blocker"]["kind"], "native_refusal")
        stood["adventurer"]["health"]["wounds"] = 1
        bridge = Bridge(before, [stood])
        result = self.client(bridge).act(
            {"type": "set_posture", "posture": "standing"},
            execution={"interrupt_on": {"new_wounds": True}},
        )
        self.assertEqual(result["outcome"], "interrupted")
