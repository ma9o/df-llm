import io
import json
import unittest
from unittest.mock import patch

from dfharness.cli import main
from dfharness.client import Client


class ShopTests(unittest.TestCase):
    def test_cli_and_python_use_one_filtered_native_read(self):
        value = {"available": True, "entries": [], "matched": 0}
        request = {"op": "shops", "shop_type": "Armorsmith", "site_id": 0, "limit": 3}
        with patch.object(Client, "request", return_value=value) as send:
            self.assertEqual(Client(port=1).shops("Armorsmith", site_id=0, limit=3), value)
            send.assert_called_once_with(request)
            send.reset_mock()
            with patch("sys.stdout", new_callable=io.StringIO) as output:
                self.assertEqual(
                    main(
                        [
                            "--port",
                            "1",
                            "shops",
                            "--type",
                            "Armorsmith",
                            "--site-id",
                            "0",
                            "--limit",
                            "3",
                        ]
                    ),
                    0,
                )
            send.assert_called_once_with(request)
            self.assertEqual(json.loads(output.getvalue()), value)

    def test_invalid_arguments_never_access_the_game(self):
        client = Client(port=1)
        with patch.object(client, "request") as send:
            for kwargs in (
                {"limit": True},
                {"limit": 0},
                {"site_id": -1},
                {"site_id": False},
                {"shop_type": ""},
                {"shop_type": 1},
            ):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    client.shops(**kwargs)
            send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
