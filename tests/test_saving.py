import unittest
from unittest.mock import patch

from dfharness.rpc import response_timeout
from dfharness.workflows import validate_action
from tests.support import Bridge
from tests.support import FullClient as Client
from tests.test_workflows import scene


def save_scene(mode=None, name="", *, exists=False, modified=None, saved="old"):
    view = scene(mode or "local")
    view["status"].update(
        save=saved, open_panels=["main.options"] if mode else [], can_move=not mode
    )
    view["save_file"] = {
        "available": True,
        "name": "night",
        "directory_exists": exists,
        "world_exists": modified is not None,
    }
    if modified is not None:
        view["save_file"]["world_mtime"] = str(modified)
    if mode:
        native = {
            "main": "SAVE_AND_CONTINUE",
            "filename": "SUBMIT_FILENAME",
            "overwrite": "OVERWRITE",
        }[mode]
        view["menu"] = {
            "kind": "options",
            "context": "MAIN_ADVENTURE",
            "mode": mode,
            "filename": name,
            "options": [{"id": native, "index": 0, "native_type": native, "visible": True}],
        }
    return view


class SavingTests(unittest.TestCase):
    def test_save_uses_its_dispatch_budget_and_returns_the_verified_file(self):
        bridge = Bridge(save_scene(), [save_scene(exists=True, modified=2, saved="night")])
        waits = []

        def request(payload):
            waits.append(response_timeout(10))
            return bridge(payload)

        client = Client(port=1, timeout=10, execution={"mode": "complete"})
        with (
            patch.object(client, "request", side_effect=request),
            patch("time.monotonic", return_value=100),
        ):
            result = client.act(
                {"type": "save_game", "name": "night"}, timeout=90, result_format="compact"
            )
        self.assertTrue(waits and all(wait == 90 for wait in waits))
        self.assertEqual(response_timeout(10), 10)
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(
            result["values"],
            [
                {
                    "kind": "save_game",
                    "name": "night",
                    "world_file_written": True,
                    "world_mtime": "2",
                }
            ],
        )
        self.assertEqual(len(bridge.inputs), 1)

    def client(self, bridge):
        client = Client(port=1, execution={"mode": "complete"})
        mock = patch.object(client, "request", side_effect=bridge)
        mock.start()
        self.addCleanup(mock.stop)
        return client

    def test_named_save_uses_one_native_quicksave_request(self):
        bridge = Bridge(save_scene(), [save_scene(exists=True, modified=2, saved="night")])
        result = self.client(bridge).act({"type": "save_game", "name": "night"})
        self.assertEqual(result["dispatch"]["outcome"], "completed")
        self.assertEqual(
            bridge.inputs, [{"type": "save_native", "name": "night", "overwrite": False}]
        )
        self.assertTrue(
            all(call["save_name"] == "night" for call in bridge.calls if call["op"] == "poll")
        )

    def test_existing_save_requires_explicit_overwrite_before_any_input(self):
        bridge = Bridge(save_scene(exists=True, modified=1))
        result = self.client(bridge).act({"type": "save_game", "name": "night"})
        self.assertEqual(result["dispatch"]["details"]["blocker_kind"], "save_exists")
        self.assertEqual(bridge.inputs, [])

    def test_delegated_overwrite_verifies_changed_file_timestamp(self):
        bridge = Bridge(
            save_scene(exists=True, modified=1),
            [save_scene(exists=True, modified=2, saved="night")],
        )
        result = self.client(bridge).act({"type": "save_game", "name": "night", "overwrite": True})
        self.assertEqual(result["dispatch"]["outcome"], "completed")
        self.assertEqual(
            bridge.inputs, [{"type": "save_native", "name": "night", "overwrite": True}]
        )

    def test_save_name_change_without_a_new_write_is_not_success_or_retried(self):
        bridge = Bridge(
            save_scene(exists=True, modified=1),
            [save_scene(exists=True, modified=1, saved="night")],
        )
        client = self.client(bridge)
        result = client.act({"type": "save_game", "name": "night", "overwrite": True})
        self.assertEqual(result["dispatch"]["outcome"], "no_effect")
        resumed = client.act(result["dispatch"]["resume_action"])
        self.assertEqual(resumed["dispatch"]["outcome"], "no_effect")
        self.assertEqual(len(bridge.inputs), 1)
        bridge.view = save_scene(exists=True, modified=2, saved="night")
        self.assertEqual(
            client.act(resumed["dispatch"]["resume_action"])["dispatch"]["outcome"], "completed"
        )
        self.assertEqual(len(bridge.inputs), 1)

    def test_an_unfinished_filename_or_overwrite_choice_is_preserved(self):
        for mode in ("filename", "overwrite"):
            bridge = Bridge(save_scene(mode, "other"))
            result = self.client(bridge).act({"type": "save_game", "name": "night"})
            self.assertEqual(result["dispatch"]["outcome"], "needs_input")
            self.assertFalse(bridge.inputs)

    def test_unavailable_native_filesystem_is_not_an_empty_save_directory(self):
        view = save_scene()
        view["save_file"] = {
            "available": False,
            "name": "night",
            "reason": "missing native data root",
        }
        bridge = Bridge(view)
        result = self.client(bridge).act({"type": "save_game", "name": "night"})
        self.assertEqual(result["dispatch"]["details"]["blocker_kind"], "save_verification")
        self.assertEqual(bridge.inputs, [])

    def test_names_are_not_paths_or_reserved_native_working_folders(self):
        for name in (
            "",
            "current",
            "CURRENT",
            "autosave 1",
            "autosave 2",
            "autosave 3",
            "../elsewhere",
            "a/b",
            "a\\b",
            ".",
            "x" * 41,
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_action({"type": "save_game", "name": name})
        validate_action({"type": "save_game", "name": "night-2026_09 07"})
