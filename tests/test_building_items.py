import io
import unittest
from unittest.mock import patch

from dfharness.cli import main
from dfharness.client import Client


class BuildingItemsTests(unittest.TestCase):
    def test_python_and_cli_filter_at_the_native_reader(self):
        request = {
            "op": "items",
            "building_id": 0,
            "item_type": "ARMOR",
            "limit": 2,
            "item_view": "concise",
        }
        with patch.object(Client, "request", return_value={}) as send:
            Client(port=1).items(building_id=0, item_type="ARMOR", limit=2)
            send.assert_called_once_with(request)
            send.reset_mock()
            with patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(
                    main(
                        [
                            "--port",
                            "1",
                            "items",
                            "--building",
                            "0",
                            "--type",
                            "ARMOR",
                            "--limit",
                            "2",
                        ]
                    ),
                    0,
                )
            send.assert_called_once_with(request)

    def test_invalid_storage_queries_never_reach_the_game(self):
        client = Client(port=1)
        with patch.object(client, "request") as send:
            for kwargs in (
                {"building_id": True},
                {"building_id": -1},
                {"building_id": 0, "limit": False},
                {"building_id": 0, "limit": 501},
                {"building_id": 0, "item_type": 1},
                {"building_id": 0, "item_type": ""},
                {"view": "unknown"},
                {"view": "full", "since": "r1:example"},
            ):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    client.items(**kwargs)
            send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
