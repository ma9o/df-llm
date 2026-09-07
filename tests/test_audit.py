import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from dfharness.audit import audit_logs, size
from dfharness.cli import main


def row(request, result, transport=None):
    return {
        "request": request,
        "response": {"ok": True, "result": result},
        "transport": transport if transport is not None else {"rpc_calls": 1, "request_bytes": 100},
        "elapsed_ms": 20,
    }


class AuditTests(unittest.TestCase):
    def log(self, rows, extra=""):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name, "episode.jsonl")
        path.write_text("".join(json.dumps(r) + "\n" for r in rows) + extra)
        return path

    def test_counts_real_rpc_attempts_and_distinguishes_pending_reads_and_deltas(self):
        receipt = {"outcome": "completed", "inputs": 1, "said": [{"reply": "é"}]}
        rows = [
            row(
                {"op": "begin_dispatch", "request_id": "a", "action": {"type": "talk"}},
                {"view": {}},
                {"rpc_calls": 2, "request_bytes": 20000, "cache_miss": True},
            ),
            row({"op": "act", "parent_dispatch": "a"}, {"accepted": True}),
            row({"op": "poll", "dispatch_id": "a"}, {"pending_view": {"schema_version": 1}}),
            row({"op": "poll", "dispatch_id": "a"}, {"view_delta": {"change": {}}}),
            row(
                {"op": "finish_dispatch", "action_id": "a", "compact": receipt}, {"recorded": True}
            ),
        ]
        result = audit_logs([self.log(rows)])
        self.assertEqual(result["records"], 5)
        self.assertEqual(result["cache_installs"], 1)
        self.assertEqual(result["operations"]["poll.pending"]["count"], 1)
        self.assertEqual(result["operations"]["poll.delta"]["count"], 1)
        self.assertEqual(result["dispatches"]["rpc_calls"], {"median": 6, "max": 6, "total": 6})
        self.assertEqual(result["dispatches"]["input_batches"], 1)
        self.assertEqual(result["dispatches"]["receipt_bytes"]["median"], size(receipt))
        self.assertEqual(result["dispatches"]["largest_receipts"][0]["action"], "talk")
        self.assertEqual(size("é"), 4)

    def test_legacy_missing_measurements_are_not_guessed_and_duplicate_receipts_count_once(self):
        receipt = {"outcome": "completed", "inputs": 2}
        finish = row({"op": "finish_dispatch", "action_id": "a", "compact": receipt}, {}, {})
        result = audit_logs(
            [
                self.log(
                    [
                        row({"op": "begin_dispatch", "request_id": "a"}, {}, {}),
                        finish,
                        finish,
                    ]
                )
            ]
        )
        self.assertEqual(result["dispatches"]["input_batches"], 2)
        self.assertEqual(result["dispatches"]["receipts"], 1)
        self.assertIsNone(result["dispatches"]["rpc_calls"])
        self.assertEqual(result["dispatches"]["unmeasured_rpc_dispatches"], 1)
        self.assertEqual(result["operations"]["finish_dispatch"]["unmeasured"]["rpc_calls"], 2)
        self.assertIsNone(result["operations"]["finish_dispatch"]["request_bytes"])

    def test_unfinished_tail_is_marked_but_interior_corruption_rejected(self):
        result = audit_logs([self.log([row({"op": "observe"}, {})], '{"request":')])
        self.assertEqual(result["records"], 1)
        self.assertEqual(result["incomplete_final_lines"], 1)
        with self.assertRaisesRegex(ValueError, "Invalid JSONL"):
            audit_logs([self.log([], "broken\n{}\n")])
        with self.assertRaisesRegex(ValueError, "Missing request/response"):
            audit_logs([self.log([{}])])

    def test_rejected_finishes_are_not_reported_as_completed_and_errors_are_counted(self):
        record = row(
            {"op": "finish_dispatch", "action_id": "a", "compact": {"outcome": "completed"}}, {}
        )
        record["response"] = {"ok": False, "code": "stale_state", "input_sent": False}
        result = audit_logs([self.log([record])])
        self.assertEqual(result["errors"], {"stale_state": 1})
        self.assertEqual(result["dispatches"]["receipts"], 0)

    def test_cli_runs_offline_and_bounds_receipt_details(self):
        rows = [
            row(
                {
                    "op": "finish_dispatch",
                    "action_id": str(i),
                    "compact": {"outcome": "completed", "inputs": 0},
                },
                {},
            )
            for i in range(20)
        ]
        output = io.StringIO()
        with patch("dfharness.cli.Client") as client, redirect_stdout(output):
            self.assertEqual(main(["audit-log", str(self.log(rows))]), 0)
        client.assert_not_called()
        result = json.loads(output.getvalue())
        self.assertEqual(len(result["dispatches"]["largest_receipts"]), 5)
        self.assertEqual(result["dispatches"]["unmeasured_rpc_dispatches"], 20)
