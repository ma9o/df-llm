import unittest
from copy import deepcopy
from unittest.mock import patch

from dfharness.character_progress import progress_changes
from dfharness.client import Client
from tests.support import Bridge
from tests.test_workflows import scene


def sample(*, rating=1, xp=590, total=1090):
    v = scene(str(total))
    v["status"]["world_epoch"] = "same-world"
    v["adventurer"]["progress"] = {
        "unit_id": 1,
        "soul_id": 0,
        "soul_available": True,
        "skills": [
            {
                "id": 41,
                "name": "HAMMER",
                "rating": rating,
                "rating_name": "Novice" if rating == 1 else "Adequate",
                "experience": xp,
                "total_experience": total,
                "next_level_xp_threshold": 600 if rating == 1 else 700,
            }
        ],
        "attributes": {"physical": [{"id": 0, "name": "STRENGTH", "value": 1000}], "mental": []},
        "unavailable": [],
        "truncated": [],
    }
    return v


class CharacterProgressTests(unittest.TestCase):
    def test_native_total_handles_a_rank_rollover_without_negative_xp(self):
        self.assertEqual(
            progress_changes(sample(), sample(rating=2, xp=0, total=1100)),
            {"skills": {"HAMMER": {"xp": 10, "level": "Adequate", "progress": [0, 700]}}},
        )

    def test_new_skill_uses_native_absent_record_semantics_only_with_complete_baseline(self):
        old, new = sample(), sample()
        old["adventurer"]["progress"]["skills"] = []
        self.assertEqual(progress_changes(old, new)["skills"]["HAMMER"]["xp"], 1090)
        old["adventurer"]["progress"]["truncated"] = [
            {"path": "skills", "total": 301, "limit": 300}
        ]
        delta = progress_changes(old, new)
        self.assertNotIn("skills", delta)
        self.assertEqual(delta["unavailable"]["before"], ["skills"])

    def test_absent_failed_changed_souls_and_worlds_do_not_invent_training_gains(self):
        for mutation in (
            lambda v: v["adventurer"].pop("progress"),
            lambda v: v["adventurer"]["progress"].update(soul_available=False),
            lambda v: v["adventurer"]["progress"].update(soul_id=1),
            lambda v: v["adventurer"]["progress"].pop("soul_id"),
            lambda v: v["adventurer"]["progress"].update(unit_id=2),
            lambda v: v["adventurer"]["progress"].pop("unit_id"),
            lambda v: v["status"].update(world_epoch="new-world"),
        ):
            old, new = sample(), sample(total=1200)
            mutation(new)
            self.assertEqual(set(progress_changes(old, new)), {"unavailable"})
        self.assertEqual(progress_changes(scene("a"), scene("b")), {})

    def test_unchanged_progress_is_omitted_and_stored_attribute_zero_is_preserved(self):
        old, new = sample(), sample()
        self.assertEqual(progress_changes(old, new), {})
        new["adventurer"]["progress"]["attributes"]["physical"][0]["value"] = 0
        self.assertEqual(
            progress_changes(old, new), {"attributes": {"physical.STRENGTH": [1000, 0]}}
        )

    def test_failed_xp_read_is_unknown_and_negative_native_changes_are_preserved(self):
        old, new = sample(), sample(total=1000, xp=500)
        self.assertEqual(progress_changes(old, new)["skills"]["HAMMER"]["xp"], -90)
        new["adventurer"]["progress"]["skills"][0].pop("total_experience")
        self.assertEqual(progress_changes(old, new), {"unavailable": {"skills": [41]}})

    def test_resumed_receipts_report_only_the_new_interval_without_extra_character_queries(self):
        old, halfway, done = (
            sample(),
            sample(rating=2, xp=0, total=1100),
            sample(rating=2, xp=10, total=1110),
        )
        for position, view in enumerate((old, halfway, done), start=1):
            view["status"]["position"]["x"] = position
        bridge = Bridge(old, [halfway, done])
        client = Client(port=1, execution={"mode": "complete", "max_steps": 1})
        with patch.object(client, "request", side_effect=bridge):
            first = client.act({"type": "walk_to", "x": 3, "y": 1, "z": 0})
            second = client.act(first["resume"])
        self.assertEqual(first["outcome"], "limit_reached")
        self.assertEqual(second["outcome"], "completed")
        for r in (first, second):
            self.assertEqual(r["changes"]["progress"]["skills"]["HAMMER"]["xp"], 10)
        reads = [r for r in bridge.calls if r["op"] in ("poll", "observe", "begin_dispatch")]
        self.assertTrue(all(r["character_progress"] for r in reads))
        self.assertFalse(any(r["op"].startswith("character_") for r in bridge.calls))
        self.assertEqual(len(bridge.inputs), 2)

    def test_diff_does_not_modify_saved_observations(self):
        old, new = sample(), sample(rating=2, xp=0, total=1100)
        original = deepcopy((old, new))
        progress_changes(old, new)
        self.assertEqual((old, new), original)
