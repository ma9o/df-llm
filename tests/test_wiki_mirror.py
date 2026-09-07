import json
import tempfile
import unittest
from pathlib import Path

from tools.mirror_wiki import NAMESPACES, mirror


def page(number, title):
    return {
        "pageid": number,
        "title": title,
        "revisions": [
            {
                "revid": number + 100,
                "timestamp": "2026-09-07T00:00:00Z",
                "slots": {"main": {"content": "Native game mechanics reference."}},
            }
        ],
    }


def siteinfo():
    return {"query": {"rightsinfo": {"text": "GFDL & MIT"}}}


class WikiMirrorTests(unittest.TestCase):
    def test_interrupted_mirror_resumes_and_completed_copy_requires_no_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = []

            def initial(params):
                calls.append(params)
                if "meta" in params:
                    return siteinfo()
                if "gapcontinue" in params:
                    raise OSError("Connection interrupted")
                return {
                    "query": {"pages": [page(1, "../Ettin")]},
                    "continue": {"gapcontinue": "Experience", "continue": "gapcontinue||"},
                }

            with self.assertRaisesRegex(OSError, "interrupted"):
                mirror(root, fetch=initial, pause=lambda _: None)
            partial = json.loads((root / "manifest.json").read_text())
            self.assertFalse(partial["complete"])
            self.assertEqual(len(partial["pages"]), 1)
            stored = root / partial["pages"]["1"]["path"]
            self.assertEqual(stored.parent, root / "articles")
            self.assertIn("oldid=101", stored.read_text())

            def resumed(params):
                calls.append(params)
                if params["gapnamespace"] == 0:
                    self.assertEqual(params["gapcontinue"], "Experience")
                    return {"query": {"pages": [page(2, "Experience")]}}
                self.assertNotIn("gapcontinue", params)
                return {"batchcomplete": True}

            result = mirror(root, fetch=resumed, pause=lambda _: None)
            self.assertTrue(result["complete"])
            self.assertEqual(len(result["pages"]), 2)
            self.assertEqual(result["finished_namespaces"], list(NAMESPACES))

            def forbidden(_):
                self.fail("A completed local mirror must not silently refresh")

            self.assertEqual(mirror(root, fetch=forbidden), result)

    def test_refresh_retains_stale_pages_until_the_new_crawl_is_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def first(params):
                if "meta" in params:
                    return siteinfo()
                return (
                    {"query": {"pages": [page(1, "Old title")]}}
                    if params["gapnamespace"] == 0
                    else {"batchcomplete": True}
                )

            result = mirror(root, fetch=first, pause=lambda _: None)
            old = root / result["pages"]["1"]["path"]

            def refreshing(params):
                if "meta" in params:
                    return siteinfo()
                if params["gapnamespace"] == 0:
                    return {"query": {"pages": [page(1, "New title")]}}
                raise OSError("Offline during refresh")

            with self.assertRaises(OSError):
                mirror(root, refresh=True, fetch=refreshing, pause=lambda _: None)
            self.assertTrue(old.exists())
            self.assertFalse(json.loads((root / "manifest.json").read_text())["complete"])
            result = mirror(root, fetch=lambda _: {"batchcomplete": True}, pause=lambda _: None)
            self.assertFalse(old.exists())
            self.assertTrue((root / result["pages"]["1"]["path"]).exists())


if __name__ == "__main__":
    unittest.main()
