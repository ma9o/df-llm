import io
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

from dfharness.cli import main
from dfharness.client import Client
from dfharness.metrics import Recorder, active, intent, serialize
from dfharness.metrics_report import read_logs
from dfharness.metrics_tokens import encoding_path, load_encoding, prepare, tokenizer
from dfharness.program import MARKER
from dfharness.rpc import BridgeError, CommandError, DFHackError
from dfharness.settings import write_settings
from tests.support import Bridge
from tests.test_workflows import scene


class ByteEncoder:
    def encode_ordinary(self, value):
        return list(value.encode("utf-8"))


class MetricsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / "metrics.jsonl"
        env = patch.dict(
            os.environ,
            {
                "DFLLM_SETTINGS": str(self.root / "settings.json"),
                "DFLLM_METRICS": "off",
                "DFLLM_METRICS_RUN": "",
                "DFLLM_EPISODE": "",
                "DFLLM_TOKENIZER_DIR": str(self.root / "tokens"),
            },
        )
        env.start()
        self.addCleanup(env.stop)
        encoder = patch("dfharness.metrics_tokens.tokenizer", return_value=ByteEncoder())
        self.encoder = encoder.start()
        self.addCleanup(encoder.stop)

    def rows(self):
        return [json.loads(line) for line in self.path.read_text().splitlines()]

    def client(self, **kwargs):
        return Client(port=1, metrics_path=self.path, **kwargs)

    def test_disabled_does_not_tokenize_or_create_a_log(self):
        client = Client(port=1)
        self.assertIn("schema", client.actions("drop"))
        self.encoder.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_python_alias_has_one_record_and_keeps_false_zero_and_unicode(self):
        result = {"character": {"name": "Cobár ☺", "wounds": 0, "hurt": False}}
        with patch.object(Client, "request", return_value=result):
            self.assertEqual(self.client(metrics_episode="room").status(), result)
        (row,) = self.rows()
        self.assertEqual(
            (row["surface"], row["operation"], row["episode"]), ("python", "status", "room")
        )
        self.assertEqual(row["input_bytes"], len(serialize({}).encode()))
        self.assertEqual(row["output_bytes"], len(serialize(result).encode()))
        self.assertIsNone(row["output_tokens"])
        self.encoder.assert_not_called()
        self.assertNotIn("Cobár", self.path.read_text())
        self.assertEqual(row["id"], row["trace_id"])

    def test_cli_counts_actual_output_and_records_reference_calls(self):
        with patch("sys.stdout", new=io.StringIO()) as output:
            self.assertEqual(
                main(
                    [
                        "--port",
                        "1",
                        "--metrics",
                        str(self.path),
                        "--episode",
                        "combat-1",
                        "actions",
                        "strike",
                    ]
                ),
                0,
            )
        (row,) = self.rows()
        self.assertEqual(row["operation"], "actions")
        self.assertEqual(row["episode"], "combat-1")
        self.assertEqual(row["output_bytes"], len(output.getvalue().encode()))
        self.assertIsNone(row["output_tokens"])

    def test_cli_stdin_and_error_are_measured_without_payload_retention(self):
        with (
            patch("sys.stdin", new=io.StringIO('{"type":"drop","item_id":12}')),
            patch("sys.stderr", new=io.StringIO()) as errors,
            patch(
                "dfharness.client.run_dispatch",
                side_effect=BridgeError("Missing item", input_sent=False),
            ),
        ):
            code = main(["--port", "1", "--metrics", str(self.path), "act", "-"])
        self.assertEqual(code, 1)
        (row,) = self.rows()
        self.assertEqual(row["action"], "drop")
        self.assertEqual(row["intents"], [{"action": "drop", "target": {"item_id": 12}}])
        self.assertIs(row["input_sent"], False)
        self.assertEqual(row["output_bytes"], len(errors.getvalue().encode()))
        self.assertEqual(row["outcome"], "error")
        self.assertNotIn("Missing item", self.path.read_text())

    def test_cli_never_tokenizes_and_records_the_wall_interval(self):
        output = io.StringIO()
        with (
            patch("sys.stdout", output),
            patch.object(output, "flush", side_effect=self.encoder.assert_not_called) as flush,
        ):
            self.assertEqual(
                main(["--port", "1", "--metrics", str(self.path), "actions", "drop"]), 0
            )
        flush.assert_called_once_with()
        (row,) = self.rows()
        self.assertEqual(row["output_bytes"], len(output.getvalue().encode()))
        self.encoder.assert_not_called()
        wall = (
            datetime.fromisoformat(row["finished_at"]) - datetime.fromisoformat(row["at"])
        ).total_seconds() * 1000
        self.assertAlmostEqual(wall, row["duration_ms"] + row["measurement_ms"], delta=0.02)

    def test_python_invalid_action_is_measured_without_calling_the_game(self):
        client = self.client()
        with patch.object(client, "request") as request, self.assertRaises(ValueError):
            client.act({"type": "unknown"})
        request.assert_not_called()
        (row,) = self.rows()
        self.assertEqual(row["outcome"], "error")
        self.assertEqual(row["rpc_calls"], 0)

    def test_all_rpc_polls_are_correlated_without_duplicate_controller_records(self):
        bridge = Bridge(scene("start"), [scene("end")])

        def program(request):
            return SimpleNamespace(render=lambda: serialize(request))

        def command(name, source, **kwargs):
            return MARKER + serialize({"ok": True, "result": bridge(json.loads(source))})

        with (
            patch("dfharness.client.prepare_program", side_effect=program),
            patch("dfharness.client.run_command", side_effect=command),
        ):
            result = self.client().act(
                {"type": "key", "key": "A_SHORT_WAIT"}, execution={"mode": "complete"}
            )
        rows = self.rows()
        controller = [row for row in rows if row["kind"] == "interaction"]
        rpcs = [row for row in rows if row["kind"] == "rpc"]
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(len(controller), 1)
        self.assertEqual(controller[0]["rpc_calls"], len(bridge.calls))
        self.assertEqual(len(rpcs), len(bridge.calls))
        self.assertIn("poll", [row["operation"] for row in rpcs])
        self.assertTrue(all(row["parent_id"] == controller[0]["id"] for row in rpcs))
        self.assertTrue(all("input_tokens" not in row for row in rpcs))

    def test_rpc_error_keeps_partial_bytes_and_does_not_retry(self):
        with (
            patch(
                "dfharness.client.prepare_program",
                return_value=SimpleNamespace(render=lambda: "lua"),
            ),
            patch("dfharness.client.run_command", side_effect=CommandError(1, "part ☺")) as command,
            self.assertRaises(DFHackError),
        ):
            self.client().game_status()
        self.assertEqual(command.call_count, 1)
        rpc, call = self.rows()
        self.assertEqual(rpc["outcome"], "error")
        self.assertEqual(rpc["output_bytes"], len("part ☺".encode()))
        self.assertEqual(call["rpc_calls"], 1)
        self.assertIsNone(call["output_tokens"])
        self.assertIsNone(active())

    def test_sink_failure_does_not_change_results_and_tokenizer_is_never_called(self):
        self.encoder.side_effect = OSError("no encoding")
        with patch("sys.stderr", new=io.StringIO()):
            result = self.client().actions("drop")
        self.assertEqual(result["action"], "drop")
        self.assertIsNone(self.rows()[0]["output_tokens"])
        self.encoder.assert_not_called()
        recorder = Recorder(self.root)  # Directory, not a log file.
        with (
            patch("sys.stderr", new=io.StringIO()),
            recorder.interaction("python", "status", {}) as span,
        ):
            span.respond({"ok": True})
        self.assertTrue(recorder.failed)
        self.assertIsNone(active())

    def test_contexts_and_appends_remain_separate_under_concurrency(self):
        recorder = Recorder(self.path, episode="parallel")
        barrier = Barrier(4)

        def call(index):
            with recorder.interaction("python", "status", {"index": index}) as span:
                barrier.wait(timeout=5)
                with recorder.rpc("read", 4) as rpc:
                    rpc["output_bytes"] = 8
                span.respond({"index": index})

        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(call, range(4)))
        rows = self.rows()
        roots = {row["id"] for row in rows if row["kind"] == "interaction"}
        self.assertEqual(len(rows), 8)
        self.assertEqual(len(roots), 4)
        self.assertEqual({row["trace_id"] for row in rows if row["kind"] == "rpc"}, roots)

    def test_saved_episode_refreshes_existing_client_and_explicit_off_wins(self):
        client = Client(port=1)
        with patch.dict(os.environ, {"DFLLM_METRICS": ""}):
            write_settings(
                {"measurement": {"enabled": True, "path": "metrics.jsonl", "episode": "first"}}
            )
            client.actions("drop")
            write_settings({"measurement": {"episode": "second"}})
            client.actions("drop")
            Client(port=1, metrics_path=False).actions("drop")
        self.assertEqual([row["episode"] for row in self.rows()], ["first", "second"])

    def test_measurement_settings_failure_cannot_break_a_read_only_query(self):
        (self.root / "settings.json").write_text("invalid json")
        with (
            patch.object(Client, "request", return_value={"mode": "adventure"}),
            patch("sys.stderr", new=io.StringIO()),
        ):
            self.assertEqual(self.client().game_status(), {"mode": "adventure"})
        self.assertFalse(self.path.exists())

    def test_target_metadata_ignores_tactics_and_sequence_reports_only_blocked_objective(self):
        self.assertEqual(
            intent({"type": "strike", "unit_id": 0, "item_id": 42, "style": "heavy"}),
            {"action": "strike", "target": {"unit_id": 0}},
        )
        recorder = Recorder(self.path)
        with recorder.interaction("python", "act", {}) as span:
            span.action(
                {
                    "type": "sequence",
                    "actions": [{"type": "drop", "item_id": 4}, {"type": "strike", "unit_id": 9}],
                }
            )
            span.result(
                {
                    "outcome": "needs_input",
                    "blocker": {"action": {"type": "strike", "unit_id": 9, "topic": "secret"}},
                }
            )
        (row,) = self.rows()
        self.assertEqual(row["blocked_intent"], {"action": "strike", "target": {"unit_id": 9}})
        self.assertNotIn("secret", self.path.read_text())

    def test_explicit_payload_log_can_be_tokenized_offline_without_duplicate_interactions(self):
        trace = self.root / "trace.jsonl"
        result = self.client(log_path=trace).actions("drop")
        self.encoder.assert_not_called()
        rows, coverage = read_logs([self.path, trace], tokenizer="test_bytes")
        self.encoder.assert_called_once_with("test_bytes")
        self.assertEqual(len(rows), 1)
        self.assertEqual(coverage["duplicate_records"], 1)
        self.assertEqual(rows[0]["output_tokens"], len(serialize(result).encode()))
        self.assertNotIn("output", rows[0])

    def test_payload_capture_without_metrics_and_failed_trace_sink_are_passive(self):
        trace = self.root / "trace.jsonl"
        result = Client(port=1, metrics_path=False, log_path=trace).actions("drop")
        rows, _ = read_logs([trace], tokenizer="test_bytes")
        self.assertEqual(rows[0]["output_tokens"], len(serialize(result).encode()))
        with patch("sys.stderr", new=io.StringIO()):
            self.assertEqual(
                Client(port=1, metrics_path=False, log_path=self.root).actions("drop"), result
            )


class OfflineTokenizerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        env = patch.dict(os.environ, {"DFLLM_TOKENIZER_DIR": directory.name})
        env.start()
        self.addCleanup(env.stop)
        load_encoding.cache_clear()

    def test_missing_encoding_never_calls_a_network_loader(self):
        with (
            patch("tiktoken.get_encoding", side_effect=AssertionError("network loader")),
            patch("requests.get", side_effect=AssertionError("network")),
            self.assertRaisesRegex(FileNotFoundError, "prepare-tokenizer"),
        ):
            tokenizer("o200k_base")

    def test_explicit_preparation_round_trips_unicode_and_special_token_text_offline(self):
        from tiktoken_ext.openai_public import ENCODING_CONSTRUCTORS

        arguments = {
            "name": "test_bytes",
            "pat_str": "(?s:.)",
            "mergeable_ranks": {bytes([i]): i for i in range(256)},
            "special_tokens": {},
        }
        with patch.dict(ENCODING_CONSTRUCTORS, {"test_bytes": lambda: dict(arguments)}):
            info = prepare("test_bytes")
        self.assertTrue(Path(info["path"]).is_file())
        with (
            patch("requests.get", side_effect=AssertionError("network")),
            patch("tiktoken.get_encoding", side_effect=AssertionError("network loader")),
        ):
            encoding = tokenizer("test_bytes")
            value = "Cobár ☺ <|endoftext|>"
            self.assertEqual(encoding.decode(encoding.encode_ordinary(value)), value)
            self.assertEqual(len(encoding.encode_ordinary(value)), len(value.encode()))
            self.assertIs(tokenizer("test_bytes"), encoding)

    def test_corrupt_local_data_is_not_repaired_by_a_download(self):
        path = encoding_path("o200k_base")
        path.write_bytes(b"bad data")
        with (
            patch("requests.get", side_effect=AssertionError("network")),
            self.assertRaises(OSError),
        ):
            tokenizer("o200k_base")


if __name__ == "__main__":
    unittest.main()
