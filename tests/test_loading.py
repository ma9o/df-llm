import unittest
from unittest.mock import patch

from dfharness.cli import parser
from dfharness.client import Client
from dfharness.rpc import response_timeout


class LoadingTests(unittest.TestCase):
    def test_load_uses_one_start_request_and_verifies_name_and_fresh_input_guard(self):
        client = Client(port=1, metrics_path=False)
        status = {
            "mode": "adventure",
            "map_loaded": True,
            "ready_for_input": True,
            "screen": "viewscreen_dungeonmodest",
            "save": "night",
        }
        responses = [
            {"name": "night", "phase": "selecting", "inputs": 1},
            {"load": {"name": "night", "phase": "completed", "inputs": 3}, "status": status},
            {"state_id": "fresh", "status": status},
        ]
        waits = []

        def request(_):
            waits.append(response_timeout(10))
            return responses.pop(0)

        with (
            patch.object(client, "request", side_effect=request) as send,
            patch("time.monotonic", return_value=100),
        ):
            result = client.load_game("night", timeout=120)
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(result["state_id"], "fresh")
        self.assertEqual(result["inputs"], 3)
        self.assertEqual(
            [c.args[0]["op"] for c in send.call_args_list], ["load_save", "load_status", "observe"]
        )
        self.assertEqual(waits, [120, 120, 120])

    def test_native_failure_or_another_loaded_save_never_retries(self):
        client = Client(port=1, metrics_path=False)
        for state, outcome in (
            (
                {
                    "load": {"phase": "failed", "reason": "Native button absent", "inputs": 0},
                    "status": {},
                },
                "failed",
            ),
            (
                {
                    "load": {"phase": "completed", "inputs": 3},
                    "status": {
                        "map_loaded": True,
                        "ready_for_input": True,
                        "screen": "viewscreen_dungeonmodest",
                        "save": "different",
                    },
                },
                "interrupted",
            ),
        ):
            with patch.object(client, "request", side_effect=[{}, state]) as send:
                self.assertEqual(client.load_game("night")["outcome"], outcome)
                self.assertEqual(send.call_count, 2)

    def test_aliases_and_validation(self):
        self.assertEqual(parser().parse_args(["quicksave", "night"]).command, "save-game")
        self.assertEqual(parser().parse_args(["quickload", "night"]).command, "load-game")
        client = Client(port=1, metrics_path=False)
        with patch.object(client, "request") as send:
            for name in ("../night", "current", "", [], "a\x00b"):
                with self.assertRaises(ValueError):
                    client.load_game(name)
            send.assert_not_called()

    def test_deadline_keeps_last_reading_and_does_not_poll_after_sleep_expires(self):
        client = Client(port=1, metrics_path=False)
        now = [100.0]

        def sleep(seconds):
            now[0] += seconds

        with (
            patch("time.monotonic", side_effect=lambda: now[0]),
            patch("time.sleep", side_effect=sleep),
            patch.object(
                client,
                "request",
                side_effect=[
                    {"phase": "selecting", "inputs": 1},
                    {"load": {"phase": "loading"}, "status": {"map_loaded": False}},
                ],
            ) as send,
        ):
            result = client.load_game("night", timeout=0.04)
        self.assertEqual(result["outcome"], "limit_reached")
        self.assertEqual(send.call_count, 2)
        self.assertIsNone(result["inputs"])
        self.assertEqual(result["blocker"]["facts"]["phase"], "loading")
