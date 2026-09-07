import io
import unittest
from unittest.mock import patch

from dfharness.cli import main
from dfharness.workflows import validate_action
from tests.support import Bridge
from tests.support import FullClient as Client
from tests.test_workflows import item, scene

ACTION = {"type": "empty_container", "container_id": 10}


def storage_scene(name, ids=(11, 12), *, opened=False, reported=False):
    children = [dict(item(i, container=10), type="LIQUID_MISC") for i in ids]
    container = dict(item(10), type="FLASK", capacity_volume_raw=180, contents=children)
    options = [
        {
            "id": "liquid-" + str(i),
            "kind": "DROP_ITEM",
            "operation": "empty_container",
            "container_id": 10,
            "item_id": i,
            "visible": True,
        }
        for i in ids
    ]
    view = scene(
        name,
        carried=[container],
        choices={"kind": "inventory", "context_name": "DROP", "options": options}
        if opened
        else None,
        reports=[{"id": 1, "type": "EMPTY_CONTAINER", "text": "You empty the waterskin."}]
        if reported
        else [],
    )
    view["input_guard"] = {"native_complete": True}
    return view


class StorageTests(unittest.TestCase):
    def client(self, bridge):
        client = Client(port=1, execution={"mode": "complete", "acknowledge": True})
        patched = patch.object(client, "request", side_effect=bridge)
        patched.start()
        self.addCleanup(patched.stop)
        return client

    def test_drop_liquid_cannot_silently_empty_other_contents(self):
        bridge = Bridge(storage_scene("menu", opened=True))
        receipt = self.client(bridge).act({"type": "drop", "item_id": 11}, result_format="compact")
        self.assertEqual(receipt["outcome"], "needs_input")
        self.assertEqual(receipt["blocker"]["kind"], "drop_effect")
        self.assertEqual(receipt["blocker"]["facts"]["container_id"], 10)
        self.assertEqual(bridge.inputs, [])

    def test_explicit_emptying_selects_once_and_verifies_all_contents_are_gone(self):
        bridge = Bridge(
            storage_scene("before"),
            [storage_scene("menu", opened=True), storage_scene("empty", (), reported=True)],
        )
        receipt = self.client(bridge).act(ACTION, result_format="compact")
        self.assertEqual(receipt["outcome"], "completed")
        self.assertEqual(
            receipt["values"], [{"kind": "empty_container", "container_id": 10, "items_emptied": 2}]
        )
        self.assertEqual(
            bridge.inputs,
            [
                {"type": "key", "key": "A_INV_DROP"},
                {"type": "select_option", "option_id": "liquid-11"},
            ],
        )

    def test_missing_effect_is_not_replayed_and_late_report_can_complete_resume(self):
        bridge = Bridge(storage_scene("before", opened=True), [storage_scene("empty", ())])
        client = self.client(bridge)
        first = client.act(ACTION)["dispatch"]
        self.assertEqual(first["outcome"], "no_effect")
        second = client.act(first["resume_action"])["dispatch"]
        self.assertEqual(second["outcome"], "no_effect")
        bridge.view = storage_scene("late", (), reported=True)
        self.assertEqual(client.act(second["resume_action"])["dispatch"]["outcome"], "completed")
        self.assertEqual(len(bridge.inputs), 1)

    def test_health_interruption_resumes_without_emptying_twice(self):
        after = storage_scene("hurt", (), reported=True)
        after["adventurer"]["health"]["blood_count"] -= 1
        bridge = Bridge(storage_scene("before", opened=True), [after])
        client = self.client(bridge)
        first = client.act(ACTION, execution={"interrupt_on": {"blood_loss": True}})["dispatch"]
        self.assertEqual(first["outcome"], "interrupted")
        self.assertEqual(client.act(first["resume_action"])["dispatch"]["outcome"], "completed")
        self.assertEqual(len(bridge.inputs), 1)

    def test_emptying_needs_known_capacity_complete_contents_and_a_carried_container(self):
        for field, value in (
            ("capacity_volume_raw", None),
            ("capacity_volume_raw", False),
            ("capacity_volume_raw", 0),
            ("contents_truncated", True),
            ("location", None),
        ):
            view = storage_scene("unknown")
            view["adventurer"]["inventory"][0][field] = value
            bridge = Bridge(view)
            self.assertEqual(self.client(bridge).act(ACTION)["dispatch"]["outcome"], "needs_input")
            self.assertEqual(bridge.inputs, [])

    def test_already_empty_is_idempotent(self):
        bridge = Bridge(storage_scene("empty", ()))
        result = self.client(bridge).act(ACTION)["dispatch"]
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(result["details"]["value"]["items_emptied"], 0)
        self.assertEqual(bridge.inputs, [])

    def test_added_contents_before_selection_do_not_silently_join_the_emptying(self):
        bridge = Bridge(
            storage_scene("before"), [storage_scene("extra", (11, 12, 13), opened=True)]
        )
        result = self.client(bridge).act(ACTION)["dispatch"]
        self.assertEqual(result["outcome"], "needs_input")
        self.assertEqual(result["details"]["blocker_kind"], "container_changed")
        self.assertEqual(len(bridge.inputs), 1)

    def test_refusal_truncated_choices_wrong_container_and_ordinary_drop_do_not_empty(self):
        for change in ("truncated", "wrong", "ordinary", "unknown"):
            view = storage_scene("wrong", opened=True)
            if change == "truncated":
                view["menu"]["truncated"] = True
            else:
                for choice in view["menu"]["options"]:
                    if change == "wrong":
                        choice["container_id"] = 99
                    elif change == "ordinary":
                        choice["operation"] = "drop_item"
                    else:
                        choice["details_unavailable"] = "Unknown effect"
            bridge = Bridge(view)
            self.assertEqual(self.client(bridge).act(ACTION)["dispatch"]["outcome"], "needs_input")
            self.assertEqual(bridge.inputs, [])
        bridge = Bridge(
            storage_scene("before", opened=True), [storage_scene("unchanged", reported=True)]
        )
        self.assertEqual(self.client(bridge).act(ACTION)["dispatch"]["outcome"], "no_effect")

    def test_emptying_composes_with_one_objective_value(self):
        bridge = Bridge(
            storage_scene("before", opened=True), [storage_scene("empty", (), reported=True)]
        )
        receipt = self.client(bridge).act(
            {"type": "sequence", "actions": [ACTION]}, result_format="compact"
        )
        self.assertEqual(receipt["outcome"], "completed")
        self.assertEqual(receipt["values"][0]["stage"], 0)
        self.assertEqual(len(receipt["values"]), 1)

    def test_emptying_cli_and_validation(self):
        for action in (
            {"type": "empty_container"},
            dict(ACTION, container_id=True),
            dict(ACTION, container_id=-1),
            dict(ACTION, item_id=11),
        ):
            with self.assertRaises(ValueError):
                validate_action(action)
        with (
            patch("dfharness.cli.Client") as constructor,
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            constructor.return_value.act.return_value = {}
            self.assertEqual(main(["empty-container", "10"]), 0)
            self.assertEqual(constructor.return_value.act.call_args.args[0], ACTION)


if __name__ == "__main__":
    unittest.main()
