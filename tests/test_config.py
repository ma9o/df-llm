import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dfharness.config import discover_saves


class SaveDiscoveryTests(unittest.TestCase):
    def test_numeric_and_named_saves_are_discovered_without_including_working_files(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for folder, marker in (
                ("1", "world.sav"),
                ("overnight-recovery", "world.sav"),
                ("region1", "world.dat"),
                ("current", "world.sav"),
                ("region-not-a-save", "notes.txt"),
            ):
                (root / folder).mkdir()
                (root / folder / marker).write_bytes(b"test")
            records = discover_saves([root, root, root / "missing"])
            self.assertEqual([r["name"] for r in records], ["1", "overnight-recovery", "region1"])
            self.assertTrue(all(Path(r["path"]).is_absolute() for r in records))
