import json
import sqlite3
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import patch

from dfharness.client import Client
from dfharness.readings import MAX_READS, ReadCache, apply_read, encoded, read_value
from dfharness.rpc import DFHackError
from tests.test_workflows import scene


class ReadingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "readings.sqlite3"
        self.cache = ReadCache(self.path)
        self.scope = {"query": "scene", "world_epoch": "a"}
        self.value: dict[str, Any] = {
            "state_id": "n2:a",
            "health": {"blood": 100, "pain": 0},
            "map": {"rows": ["." * 41] * 21},
            "units": [],
            "warning": False,
        }

    def test_exact_delta_survives_new_cli_client_and_preserves_warning_changes(self):
        before = self.cache.project(self.value, self.scope)
        after = deepcopy(self.value)
        after.update(state_id="n2:b", warning=True, units=[{"id": 0, "alive": False}])
        after["health"] = {"blood": 0, "unavailable": {"pain": "unreadable"}}
        result = ReadCache(self.path).project(after, self.scope, before["read_ref"])
        self.assertEqual(result["format"], "reading_delta")
        self.assertEqual(read_value(apply_read(before, result)), after)
        self.assertEqual(before["health"]["blood"], 100)
        self.assertNotIn("map", result["change"]["fields"])
        self.assertLess(len(encoded(result)), len(encoded(after)) / 2)

    def test_unchanged_read_is_small_and_cannot_apply_to_a_wrong_or_modified_base(self):
        before = self.cache.project(self.value, self.scope)
        result = self.cache.project(self.value, self.scope, before["read_ref"])
        self.assertEqual(result["change"], {})
        self.assertLess(len(encoded(result)), 200)
        self.assertEqual(apply_read(before, result), before)
        damaged = deepcopy(before)
        damaged["warning"] = None
        with self.assertRaises(DFHackError):
            apply_read(damaged, result)
        damaged = deepcopy(result)
        damaged["change"] = {"fields": {"warning": {"set": None}}}
        with self.assertRaises(DFHackError):
            apply_read(before, damaged)

    def test_query_world_scope_expiry_and_large_changes_return_explicit_full_resync(self):
        before = self.cache.project(self.value, self.scope)
        for scope in (
            {"query": "other", "world_epoch": "a"},
            {"query": "scene", "world_epoch": "b"},
        ):
            result = self.cache.project(self.value, scope, before["read_ref"])
            self.assertEqual(read_value(result), self.value)
            self.assertIn("resync", result["read_cache"])
        for index in range(MAX_READS + 1):
            self.cache.project(dict(self.value, state_id=str(index)), self.scope)
        result = self.cache.project(self.value, self.scope, before["read_ref"])
        self.assertIn("resync", result["read_cache"])
        self.assertEqual(apply_read(before, result), result)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM readings").fetchone()[0], MAX_READS)
        result = self.cache.project({"state_id": "gone"}, self.scope, before["read_ref"])
        self.assertEqual(read_value(result), {"state_id": "gone"})

    def test_corrupt_or_unwritable_cache_never_changes_a_successful_observation(self):
        self.path.write_text("broken database")
        result = self.cache.project(self.value, self.scope, "missing")
        self.assertEqual(read_value(result), self.value)
        self.assertFalse(result["read_cache"]["available"])
        self.assertNotIn("read_ref", result)
        self.path.unlink()
        before = self.cache.project(self.value, self.scope)
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE readings SET body=?", (json.dumps({"wrong": 0}),))
        result = self.cache.project(self.value, self.scope, before["read_ref"])
        self.assertIn("content check", result["read_cache"]["resync"])

    def test_observe_uses_one_native_read_and_rejects_invalid_since_before_rpc(self):
        client = Client(
            port=1, settings_path=Path(self.directory.name) / "settings.json", metrics_path=False
        )
        native = scene("ready")
        with patch.object(client, "request", return_value=native) as request:
            before = client.observe()
            request.assert_called_once()
            request.reset_mock()
            after = client.observe(since=before["read_ref"])
            request.assert_called_once()
            self.assertNotIn("since", request.call_args.args[0])
            self.assertEqual(apply_read(before, after), before)
            request.reset_mock()
            for since, view in (
                (0, "concise"),
                ("", "concise"),
                ("ref", "full"),
                ("ref", "choices"),
            ):
                with self.assertRaises(ValueError):
                    client.observe(since=since, view=view)
            request.assert_not_called()
