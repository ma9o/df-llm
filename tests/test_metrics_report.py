import io
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from dfharness.cli import main
from dfharness.metrics_episodes import episodes
from dfharness.metrics_report import read_logs, render, report


def sample(
    name,
    at,
    *,
    operation="act",
    action="strike",
    target=7,
    outcome="completed",
    duration=1000,
    output_tokens=300,
    episode=None,
    **extra,
):
    row = {
        "schema_version": 1,
        "kind": "interaction",
        "id": name,
        "trace_id": name,
        "run": "test",
        "at": (datetime(2026, 9, 7, tzinfo=UTC) + timedelta(milliseconds=at)).isoformat(),
        "surface": "python",
        "operation": operation,
        "outcome": outcome,
        "duration_ms": duration,
        "measurement_ms": 0,
        "input_tokens": 20,
        "output_tokens": output_tokens,
        "tokenizer": "o200k_base",
        "episode": episode,
        "dispatch_id": name,
        "rpc_calls": 0,
        "rpc_ms": 0,
    }
    if action:
        row.update(action=action, intents=[{"action": action, "target": {"unit_id": target}}])
    row.update(extra)
    return row


def read(name, at, operation="brief", **kwargs):
    return sample(name, at, operation=operation, action=None, duration=100, **kwargs)


class EpisodeTests(unittest.TestCase):
    def test_three_minutes_are_attributed_to_gaps_and_followup_reads_not_just_receipt_size(self):
        rows = [
            sample("strike1", 0),
            read("brief", 30_000, output_tokens=100),
            read("unit", 60_000, "df_unit", output_tokens=120),
            read("item", 90_000, "item", output_tokens=130),
            sample("strike2", 179_000),
        ]
        result = episodes(rows)
        self.assertEqual(result["count"], 1)
        episode = result["items"][0]
        self.assertEqual((episode["calls"], episode["dispatch_count"]), (5, 2))
        self.assertEqual(episode["wall_ms"], 180_000)
        self.assertEqual(episode["harness_ms"], 2300)
        self.assertEqual(episode["gap_ms"], 177700)
        self.assertEqual(episode["followup_reads"]["reads_per_dispatch"], 3)
        window = episode["followup_reads"]["windows"][0]
        self.assertEqual(window["receipt_output_tokens"]["o200k_base"]["known_total"], 300)
        self.assertEqual(window["read_output_tokens"]["o200k_base"]["known_total"], 350)

    def test_explicit_labels_cross_idle_gaps_and_runs_do_not_mix(self):
        rows = [
            sample("a", 0, episode="fight"),
            sample("b", 999_000, episode="fight"),
            sample("c", 10, episode="fight", run="another-controller"),
            read("d", 5000),
            read("e", 130_000),
        ]
        result = episodes(list(reversed(rows)), idle_gap=60)
        self.assertEqual(result["count"], 4)
        fight = result["items"][0]
        self.assertEqual(fight["calls"], 2)
        self.assertEqual(fight["wall_ms"], 1_000_000)
        self.assertEqual(fight["grouping"], "explicit")

    def test_overlap_and_tokenizer_work_are_not_counted_twice_or_called_deliberation(self):
        rows = [
            sample("a", 0, duration=5000, measurement_ms=2000),
            read("poll", 1000, "game-status", output_tokens=20),
            read("after-reply", 6000, duration_ms=2000),
            sample("b", 9000),
        ]
        item = episodes(rows)["items"][0]
        self.assertEqual(item["wall_ms"], 10_000)
        self.assertEqual(item["harness_ms"], 9000)
        self.assertEqual(item["gap_ms"], 1000)
        self.assertEqual(item["followup_reads"]["reads"], 1)

    def test_reads_during_any_overlapping_dispatch_are_not_followups(self):
        rows = [
            sample("long", 0, duration=10000),
            sample("short", 1000),
            read("poll", 2500),
            sample("last", 12000),
        ]
        item = episodes(rows)["items"][0]
        self.assertEqual(item["followup_reads"]["overlapping_dispatch_windows"], 1)
        self.assertEqual(item["followup_reads"]["reads"], 0)

    def test_trailing_reads_and_reference_calls_remain_separate(self):
        rows = [
            sample("a", 0),
            read("reference", 2000, "df_actions"),
            read("capabilities", 3000, "capabilities"),
            read("tail", 4000, "brief"),
        ]
        item = episodes(rows)["items"][0]
        self.assertEqual(item["reference_calls"], {"df_actions": 1, "capabilities": 1})
        self.assertIsNone(item["followup_reads"]["reads_per_dispatch"])
        self.assertEqual(item["followup_reads"]["trailing_reads"], 1)

    def test_missing_timestamp_is_reported_and_rpc_rows_are_not_episode_time(self):
        row = sample("unknown", 0)
        del row["at"]
        result = episodes([row, sample("good", 1000)])
        self.assertEqual(result["untimed_calls"], 1)
        self.assertEqual(result["totals"]["calls"], 1)
        self.assertEqual(result["count"], 1)

    def test_same_target_reissue_inside_sequence_is_a_bounce(self):
        rows = [
            sample("blocked", 0, outcome="needs_input"),
            read("reference", 5000, "actions"),
            sample(
                "batch",
                8000,
                action="sequence",
                intents=[
                    {"action": "drop", "target": {"item_id": 1}},
                    {"action": "strike", "target": {"unit_id": 7}},
                ],
            ),
        ]
        bounces = episodes(rows)["items"][0]["bounces"]
        self.assertEqual(bounces["reissued"], 1)
        self.assertEqual(bounces["rate"], 1)
        self.assertEqual(
            bounces["links"], [{"from": "blocked", "to": "batch", "outcome": "needs_input"}]
        )

    def test_failed_sequence_uses_its_blocked_target_not_completed_stages(self):
        blocked = sample(
            "batch",
            0,
            action="sequence",
            outcome="needs_input",
            intents=[
                {"action": "drop", "target": {"item_id": 1}},
                {"action": "strike", "target": {"unit_id": 7}},
            ],
            blocked_intent={"action": "strike", "target": {"unit_id": 7}},
        )
        rows = [blocked, sample("different-target", 2000, target=8), sample("retry", 4000)]
        bounce = episodes(rows)["items"][0]["bounces"]
        self.assertEqual(bounce["reissued"], 1)
        self.assertEqual(bounce["links"][0]["to"], "retry")

    def test_different_targets_completed_repeats_and_other_episodes_are_not_bounces(self):
        rows = [
            sample("a", 0, outcome="needs_input", episode="one"),
            sample("b", 3000, target=8, episode="one"),
            sample("c", 5000, target=8, episode="one"),
            sample("d", 6000, episode="two"),
        ]
        result = episodes(rows)
        self.assertEqual(result["bounces"]["assessed"], 1)
        self.assertEqual(result["bounces"]["reissued"], 0)

    def test_explicit_resumes_and_idempotent_redelivery_are_separate_from_bounces(self):
        for later, counter in (
            (sample("resume", 2000, action="resume", resume_id="a"), "resumed"),
            (sample("redelivery", 2000, dispatch_id="a"), "redelivered"),
        ):
            with self.subTest(counter=counter):
                item = episodes([sample("a", 0, outcome="bounded"), later])["items"][0]
                self.assertEqual(item["bounces"][counter], 1)
                self.assertEqual(item["bounces"]["reissued"], 0)

    def test_legacy_targets_unknown_followups_and_open_tails_are_not_verified_zero(self):
        row = sample("a", 0, outcome="needs_input")
        del row["intents"]
        bounce = episodes([row, sample("b", 2000)])["bounces"]
        self.assertEqual(bounce["unknown_target"], 1)
        self.assertIsNone(bounce["rate"])
        known = sample("known", 0, outcome="needs_input")
        legacy = sample("old", 2000)
        del legacy["intents"]
        bounce = episodes([known, legacy])["bounces"]
        self.assertEqual(bounce["unknown_followup"], 1)
        self.assertIsNone(bounce["rate"])
        bounce = episodes([known])["bounces"]
        self.assertEqual(bounce["no_later_dispatch"], 1)

    def test_tokenizers_and_unmeasured_counts_are_not_merged(self):
        rows = [
            sample("a", 0, output_tokens=0),
            read("b", 2000, output_tokens=None),
            read("c", 3000, output_tokens=10, tokenizer="cl100k_base"),
        ]
        groups = episodes(rows)["items"][0]["output_tokens"]
        self.assertEqual(groups["o200k_base"], {"known_total": 0, "measured": 1, "unmeasured": 1})
        self.assertEqual(groups["cl100k_base"]["known_total"], 10)


class ReportTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def log(self, name, rows):
        path = self.root / name
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return path

    def test_empty_log_is_valid_but_unknown_rates_stay_null(self):
        result = report([self.log("empty", [])])
        self.assertEqual(result["episodes"]["count"], 0)
        self.assertIsNone(result["episodes"]["bounces"]["rate"])
        self.assertIn("Episodes: 0", render(result))

    def test_partial_final_line_and_duplicate_records_are_counted(self):
        row = sample("a", 0)
        path = self.log("partial", [row, row])
        with path.open("a") as stream:
            stream.write('{"schema_version":1,')
        rows, reading = read_logs([path])
        self.assertEqual(rows, [row])
        self.assertEqual(reading, {"incomplete_final_lines": 1, "duplicate_records": 1})

    def test_corruption_conflicting_ids_negative_counts_and_boolean_counts_are_rejected(self):
        for value in (-1, float("nan"), True):
            path = self.log("bad", [sample("a", 0, output_tokens=value)])
            with self.assertRaises(ValueError):
                read_logs([path])
        path = self.log("conflict", [sample("a", 0), sample("a", 1)])
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            read_logs([path])
        path.write_text("broken\n")
        with self.assertRaisesRegex(ValueError, "Invalid measurement JSONL"):
            read_logs([path])

    def test_run_filter_and_rpc_children_do_not_add_wall_time_or_llm_tokens(self):
        rpc = sample("rpc", 0, kind="rpc", trace_id="a", duration=9000, operation="observe")
        path = self.log("all", [sample("a", 0), rpc, sample("other", 3000, run="other")])
        result = report([path], run="test")
        self.assertEqual(result["interactions"]["count"], 1)
        self.assertEqual(result["episodes"]["totals"]["wall_ms"], 1000)
        self.assertEqual(result["tokens"]["o200k_base"]["output_tokens"]["total"], 300)
        self.assertEqual(result["rpc_traces_without_completed_interaction"], 0)

    def test_comparison_includes_episode_cost_and_thin_receipt_followup_tradeoff(self):
        before = self.log("before", [sample("a", 0, output_tokens=600), sample("b", 2000)])
        after = self.log(
            "after",
            [
                sample("c", 0, output_tokens=100),
                read("unit", 10000),
                read("item", 20000),
                sample("d", 40000),
            ],
        )
        result = report([after], baseline=[before])
        change = result["comparison"]["episodes"]
        self.assertEqual(change["followup_reads_per_dispatch"], {"baseline": 0, "current": 2})
        self.assertGreater(change["means"]["wall_ms"]["delta"], 0)
        text = render(result)
        self.assertIn("receipt=100, reads=600", text)
        self.assertIn("Episode comparison", text)
        self.assertIn("not proven thinking time", text)

    def test_zero_baseline_and_changed_tokenizers_do_not_produce_fake_percentages(self):
        before = self.log("before", [sample("a", 0, output_tokens=0, duration=0)])
        after = self.log("after", [sample("b", 0, output_tokens=5)])
        result = report([after], baseline=[before])
        change = next(iter(result["comparison"]["operations"].values()))
        self.assertIsNone(change["duration_ms"]["percent"])
        self.assertIsNone(change["output_tokens"]["percent"])
        after = self.log("other-tokenizer", [sample("b", 0, tokenizer="cl100k_base")])
        self.assertEqual(report([after], baseline=[before])["comparison"]["operations"], {})

    def test_cli_report_is_offline_and_idle_gap_is_validated(self):
        path = self.log("current", [sample("a", 0), sample("b", 3000)])
        with (
            patch("dfharness.cli.Client", side_effect=AssertionError("game connection")),
            patch("sys.stdout", new=io.StringIO()) as output,
        ):
            self.assertEqual(main(["metrics", str(path), "--idle-gap", "1", "--text"]), 0)
        self.assertIn("Episodes: 2", output.getvalue())
        for gap in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                report([path], idle_gap=gap)


if __name__ == "__main__":
    unittest.main()
