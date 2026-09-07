import json
import unittest
from unittest.mock import patch

from dfharness.client import Client
from dfharness.program import MARKER, prepare_program, script_path
from dfharness.rpc import DFHackError, rpc_deadline


def envelope(value):
    return MARKER + json.dumps(value) + "\n"


class ProgramTests(unittest.TestCase):
    def test_transport_wait_uses_dispatch_deadline_and_resets_after_failure(self):
        with (
            patch("dfharness.client.run_command", side_effect=DFHackError("lost response")) as rpc,
            patch("time.monotonic", return_value=100),
        ):
            client = Client(port=1, timeout=10)
            with self.assertRaises(DFHackError), rpc_deadline(190):
                client.request({"op": "act"})
            self.assertEqual(rpc.call_args.kwargs["timeout"], 90)
            with self.assertRaises(DFHackError):
                client.request({"op": "status"})
            self.assertEqual(rpc.call_args.kwargs["timeout"], 10)
            self.assertEqual(rpc.call_count, 2)

    def test_every_request_uses_the_native_loader_without_shipping_source(self):
        for op in ("status", "observe", "character_status", "character_brief", "act"):
            program = prepare_program({"op": op})
            self.assertIn("dfhack.reqscript('dfharness/entry')", program.render())
            self.assertNotIn("df_llm_programs", program.render())
            self.assertLess(len(program.render()), 1000)
        first = prepare_program({"op": "poll", "dispatch_id": "first"})
        second = prepare_program({"op": "poll", "dispatch_id": "second"})
        self.assertNotEqual(first.render(), second.render())

    def test_explicit_game_visible_path_and_cross_platform_mapping(self):
        with patch.dict("os.environ", {"DFLLM_SCRIPT_PATH": "Z:/my shared/scripts"}):
            self.assertEqual(script_path(), "Z:/my shared/scripts")
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("dfharness.program.sys.platform", "darwin"),
        ):
            self.assertTrue(script_path().startswith("Z:/"))
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("dfharness.program.sys.platform", "linux"),
        ):
            self.assertTrue(script_path().startswith("/"))

    def test_a_successful_request_is_one_rpc_even_when_starting_cold(self):
        with patch(
            "dfharness.client.run_command",
            return_value=envelope({"ok": True, "result": {"accepted": True}}),
        ) as rpc:
            self.assertEqual(
                Client(port=1).request({"op": "act", "action": {"type": "wait"}}),
                {"accepted": True},
            )
            self.assertEqual(rpc.call_count, 1)

    def test_transport_failures_and_game_rejections_never_retry(self):
        for response in (
            DFHackError("connection lost"),
            "missing structured response",
            envelope({"ok": False, "code": "stale_state", "input_sent": False}),
            envelope({"ok": False, "code": "bridge_cache_miss", "input_sent": False}),
        ):
            with (
                self.subTest(response=response),
                patch("dfharness.client.run_command", side_effect=[response]) as rpc,
            ):
                with self.assertRaises(DFHackError):
                    Client(port=1).request({"op": "act", "action": {"type": "wait"}})
                self.assertEqual(rpc.call_count, 1)
