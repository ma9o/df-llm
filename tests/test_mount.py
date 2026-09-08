import unittest
from unittest.mock import patch

from dfharness.client import Client
from dfharness.workflows import validate_action
from tests.support import Bridge
from tests.test_workflows import scene


def riding(name, *, rider=False, mount_id=-1, adjacent=True, visible=True, queued=(), owner=-1):
    value = scene(name)
    value["status"]["position"] = {"x": 5, "y": 5, "z": 0}
    value["mount"] = {
        "available": True,
        "adventurer_id": 1,
        "rider": rider,
        "mount_id": mount_id,
        "leading_id": -1,
        "queued": list(queued),
        "animal": {
            "id": 7,
            "position": {"x": 6 if adjacent else 20, "y": 5, "z": 0},
            "alive": True,
            "visible": visible,
            "tame": True,
            "pet": owner == 1,
            "mount_capable": True,
            "ridden": rider,
            "owner_id": owner,
            "adjacent": adjacent,
        },
    }
    return value


class MountTests(unittest.TestCase):
    def client(self, bridge):
        client = Client(port=1, execution={"mode": "complete"}, metrics_path=False)
        patched = patch.object(client, "request", side_effect=bridge)
        patched.start()
        self.addCleanup(patched.stop)
        return client

    def test_mount_sends_one_native_command_waits_for_the_queued_action_and_verifies(self):
        queued = riding("queued", queued=["Mount"])
        done = riding("done", rider=True, mount_id=7, queued=["Mount"])
        bridge = Bridge(riding("before"), [queued, done])
        result = self.client(bridge).act({"type": "mount", "unit_id": 7})
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(result["values"][0]["mount_id"], 7)
        self.assertEqual(
            bridge.inputs,
            [{"type": "mount_command", "command": "mount", "unit_id": 7}, {"type": "wait"}],
        )

    def test_unobserved_result_is_reported_without_resending(self):
        bridge = Bridge(riding("before"), [riding("same")])
        result = self.client(bridge).act({"type": "mount", "unit_id": 7})
        self.assertEqual(result["outcome"], "no_effect")
        self.assertEqual(result["blocker"]["kind"], "mount_verification")
        self.assertEqual(len(bridge.inputs), 1)

    def test_unseen_animal_and_bad_targets_are_blockers_before_input(self):
        bridge = Bridge(riding("hidden", visible=False))
        result = self.client(bridge).act({"type": "claim_pet", "unit_id": 7})
        self.assertEqual(result["outcome"], "needs_input")
        self.assertFalse(bridge.inputs)
        for bad in (
            {"type": "mount"},
            {"type": "dismount", "unit_id": 7},
            {"type": "pack", "item_id": 3},
            {"type": "unpack", "item_id": 3, "unit_id": -1},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_action(bad)
        validate_action({"type": "pack", "item_id": 3, "unit_id": 7})

    def test_claim_and_dismount_verify_from_relationships_and_flags(self):
        owned = riding("owned", owner=1)
        result = self.client(Bridge(riding("before"), [owned])).act(
            {"type": "claim_pet", "unit_id": 7}
        )
        self.assertEqual(result["outcome"], "completed")
        off = riding("off", rider=False)
        bridge = Bridge(riding("on", rider=True, mount_id=7), [off])
        self.assertEqual(self.client(bridge).act({"type": "dismount"})["outcome"], "completed")
        self.assertEqual(bridge.inputs, [{"type": "mount_command", "command": "dismount"}])
