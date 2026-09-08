import io
import unittest
from unittest.mock import patch

from dfharness.cli import main
from dfharness.client import Client
from dfharness.composition import observation_args
from dfharness.metrics import intent
from dfharness.metrics_episodes import role
from dfharness.views import reading_menu
from dfharness.workflows import validate_action
from tests.support import Bridge
from tests.test_workflows import scene

OPEN = {"type": "open_trade", "unit_id": 2, "shop_id": 8}


def catalog(name, *, shop=7, rebuilding=False, **extra):
    return scene(
        name,
        choices={
            "kind": "barter",
            "available": True,
            "unit_id": 2,
            "zone": {"id": shop, "type": "Shop" if shop == 8 else "Home"},
            "personal": False,
            "demand_only": False,
            "editing": False,
            "rebuilding": rebuilding,
            "options": [],
            "draft": {"take": [], "give": []},
            "currency": {
                "offer": 0,
                "request": 0,
                "player_available": 100,
                "merchant_available": 0,
            },
            "goods": {"take": {"count": 138 if shop == 8 else 0, "counts": {}}},
            **extra,
        },
    )


class BarterTests(unittest.TestCase):
    def client(self, bridge):
        client = Client(port=1, execution={"mode": "complete", "acknowledge": True})
        mocked = patch.object(client, "request", side_effect=bridge)
        mocked.start()
        self.addCleanup(mocked.stop)
        return client

    def test_native_catalog_rebuild_is_verified_before_completion(self):
        bridge = Bridge(
            catalog("home"), [catalog("pending", shop=8, rebuilding=True), catalog("shop", shop=8)]
        )
        result = self.client(bridge).act(OPEN)
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(result["values"][0]["goods"]["count"], 138)
        self.assertEqual(bridge.inputs, [dict(OPEN, type="trade_shop"), {"type": "resume"}])

    def test_failed_catalog_selection_does_not_repeat_or_claim_completion(self):
        bridge = Bridge(catalog("home"), [catalog("unchanged")])
        result = self.client(bridge).act(OPEN)
        self.assertEqual(result["outcome"], "no_effect")
        resumed = self.client(bridge).act(result["resume"])
        self.assertEqual(resumed["outcome"], "no_effect")
        self.assertEqual(len(bridge.inputs), 1)

    def test_no_inputs_when_pending_offer_or_different_merchant_is_present(self):
        for kwargs in (
            {"editing": True},
            {"draft": {"take": [9]}},
            {"personal": True},
            {"unit_id": 9},
        ):
            with self.subTest(kwargs=kwargs):
                bridge = Bridge(catalog("busy", **kwargs))
                result = self.client(bridge).act(OPEN)
                self.assertEqual(result["outcome"], "needs_input")
                self.assertEqual(bridge.inputs, [])

    def test_close_requires_native_panel_disappearance(self):
        bridge = Bridge(catalog("shop", shop=8), [scene("closed")])
        self.assertEqual(self.client(bridge).act({"type": "close_trade"})["outcome"], "completed")
        self.assertEqual(bridge.inputs, [{"type": "key", "key": "LEAVESCREEN"}])

    def test_filters_use_the_same_native_query_on_python_and_cli(self):
        expected = {"op": "barter", "side": "take", "item_type": "ARMOR", "limit": 2}
        with patch.object(Client, "request", return_value={}) as send:
            Client(port=1).barter(item_type="ARMOR", limit=2)
            send.assert_called_once_with(expected)
            send.reset_mock()
            with patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(
                    main(["--port", "1", "barter", "--type", "ARMOR", "--limit", "2"]), 0
                )
            send.assert_called_once_with(expected)

    def test_invalid_targets_and_queries_are_rejected_before_io(self):
        for action in (
            dict(OPEN, shop_id=True),
            dict(OPEN, unit_id=-1),
            {"type": "open_trade", "unit_id": 2},
        ):
            with self.assertRaises(ValueError):
                validate_action(action)
        client = Client(port=1)
        with patch.object(client, "request") as send:
            for kwargs in ({"side": "other"}, {"limit": True}, {"limit": 501}, {"item_type": ""}):
                with self.assertRaises(ValueError):
                    client.barter(**kwargs)
            send.assert_not_called()

    def test_item_dispatches_request_explicit_furniture_targets_without_expanding_shop(self):
        args = observation_args(
            {
                "action": {
                    "type": "equip",
                    "item_id": 0,
                    "replace": [4, 7],
                    "disposition": "stow",
                    "container_id": 9,
                },
                "context": {},
            }
        )
        self.assertEqual(args["target_item_ids"], [0, 4, 7, 9])
        self.assertNotIn("target_item_ids", observation_args({"action": OPEN, "context": {}}))

    def test_concise_menu_exposes_catalog_identity_and_metrics_keep_shop_targets(self):
        reading = reading_menu(catalog("home")["menu"])
        self.assertEqual(reading["zone"], {"id": 7, "type": "Home"})
        self.assertEqual(reading["goods"]["take"]["count"], 0)
        self.assertNotIn("options", reading)
        self.assertEqual(intent(OPEN)["target"], {"unit_id": 2, "shop_id": 8})
        self.assertEqual(role({"operation": "barter"}), "read")
