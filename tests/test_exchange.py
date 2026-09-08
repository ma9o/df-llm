import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from dfharness.client import Client
from dfharness.workflows import validate_action
from tests.support import Bridge
from tests.test_workflows import scene

ACTION = {
    "type": "trade",
    "unit_id": 2,
    "take": [{"item_id": 10, "amount": 2}],
    "give": [],
    "offer_currency": 5,
}


def trade_state(name, *, stack=5, held=False, quantity=0, player=100, merchant=30, reply="Greet"):
    value = scene(name)
    value["menu"] = {
        "kind": "barter",
        "available": True,
        "unit_id": 2,
        "talkline": reply,
        "options": [],
    }
    value["trade"] = {
        "available": True,
        "unit_id": 2,
        "trader_id": 1,
        "talkline": reply,
        "currency": {"player": player, "merchant": merchant},
        "inventory": {"gem": quantity},
        "items": [
            {
                "item_id": 10,
                "side": "take",
                "signature": "gem",
                "stack_size": stack,
                "present": True,
                "held": held,
            }
        ],
    }
    return value


class ExchangeTests(unittest.TestCase):
    def client(self, bridge):
        client = Client(port=1, execution={"mode": "complete"}, metrics_path=False)
        patched = patch.object(client, "request", side_effect=bridge)
        patched.start()
        self.addCleanup(patched.stop)
        return client

    def test_partial_stack_requires_both_source_and_destination_and_currency(self):
        after = trade_state("bought", stack=3, quantity=2, player=95, merchant=35, reply="Trade")
        bridge = Bridge(trade_state("before"), [after])
        result = self.client(bridge).act(ACTION)
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(result["values"][0]["kind"], "trade")
        self.assertEqual(bridge.inputs, [dict(ACTION, type="trade_submit")])
        watch = [c["trade_watch"] for c in bridge.calls if c.get("trade_watch", {}).get("verify")]
        self.assertEqual(watch[0]["signatures"], ["gem"])

    def test_trade_acknowledgement_alone_does_not_prove_transfer(self):
        bridge = Bridge(trade_state("before"), [trade_state("responded", reply="Trade")])
        client = self.client(bridge)
        first = client.act(ACTION)
        self.assertEqual(first["outcome"], "needs_input")
        self.assertEqual(first["blocker"]["kind"], "native_trade_response")
        again = client.act(first["resume"])
        self.assertEqual(again["outcome"], "needs_input")
        self.assertEqual(len(bridge.inputs), 1)

    def test_unverified_offer_can_verify_late_without_resubmitting(self):
        bridge = Bridge(trade_state("before"), [trade_state("unchanged")])
        client = self.client(bridge)
        first = client.act(ACTION)
        self.assertEqual(first["outcome"], "no_effect")
        bridge.view = trade_state("late", stack=3, quantity=2, player=95, merchant=35)
        self.assertEqual(client.act(first["resume"])["outcome"], "completed")
        self.assertEqual(len(bridge.inputs), 1)

    def test_source_quantity_or_currency_mismatch_cannot_complete(self):
        for changes in ({"stack": 4}, {"quantity": 1}, {"player": 96}):
            args = {"stack": 3, "quantity": 2, "player": 95, "merchant": 35}
            args.update(changes)
            bridge = Bridge(trade_state("before"), [trade_state("wrong", **args)])
            self.assertEqual(self.client(bridge).act(ACTION)["outcome"], "no_effect")

    def test_merchant_entry_bound_is_not_a_currency_ledger(self):
        after = trade_state("bought", stack=3, quantity=2, player=95, merchant=40, reply="Trade")
        result = self.client(Bridge(trade_state("before"), [after])).act(ACTION)
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(result["values"][0]["player_currency"], 95)

    def test_repeated_haggle_reports_native_counteroffer_even_when_talkline_is_unchanged(self):
        after = trade_state("counter", reply="Haggle")
        after["trade"]["counter_offer"] = {"offer_currency": 9, "request_currency": 0}
        bridge = Bridge(trade_state("before", reply="Haggle"), [after])
        result = self.client(bridge).act(ACTION)
        self.assertEqual(result["blocker"]["facts"]["counter_offer"]["offer_currency"], 9)
        self.assertEqual(len(bridge.inputs), 1)
        self.assertNotIn(
            "choices", result
        )  # A catalog with no native choices is not a choice list.
        self.assertLess(len(json.dumps(result).encode()), 1400)

    def test_empty_missing_and_broader_scope_are_rejected_without_input(self):
        value = trade_state("before")
        value["trade"]["selection_unavailable"] = "Nonempty container includes its contents"
        bridge = Bridge(value)
        result = self.client(bridge).act(ACTION)
        self.assertEqual(result["outcome"], "needs_input")
        self.assertNotIn("choices", result)
        self.assertFalse(bridge.inputs)
        for action in (
            dict(ACTION, give=ACTION["take"]),
            dict(ACTION, offer_currency=-1),
            dict(ACTION, take=[{"item_id": 10, "amount": 0}]),
            {"type": "trade", "unit_id": 2, "take": [], "give": []},
        ):
            with self.subTest(action=action), self.assertRaises(ValueError):
                validate_action(action)

    def test_trade_is_composable_and_completed_value_is_not_repeated_on_resume(self):
        after = trade_state("bought", stack=3, quantity=2, player=95, merchant=35)
        closed = deepcopy(after)
        closed["menu"] = None
        bridge = Bridge(trade_state("before"), [after, closed])
        client = self.client(bridge)
        first = client.act(
            {"type": "sequence", "actions": [ACTION, {"type": "close_trade"}]},
            execution={"max_steps": 1},
        )
        self.assertEqual(first["outcome"], "limit_reached")
        self.assertEqual(first["values"][0]["kind"], "trade")
        last = client.act(first["resume"])
        self.assertEqual(last["outcome"], "completed")
        self.assertNotIn("values", last)
