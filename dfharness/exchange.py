"""Submit one explicit native offer and verify item quantities and currency."""

from collections import Counter
from copy import deepcopy

from .state import carrying_value
from .workflows import result


def validate_trade(action):
    required = {"type", "unit_id", "take", "give"}
    if required - action.keys() or action.keys() - required - {
        "offer_currency",
        "request_currency",
        "spend",
    }:
        raise ValueError(
            "trade requires unit_id, take and give, with optional offer_currency, request_currency and spend"
        )
    if action.get("spend", "cheapest") not in ("cheapest", "native"):
        raise ValueError("trade spend must be cheapest or native")
    if type(action["unit_id"]) is not int or not 0 <= action["unit_id"] <= 2147483647:
        raise ValueError("trade unit_id must be a nonnegative native ID")
    seen = set()
    for side in ("take", "give"):
        if not isinstance(action[side], list) or len(action[side]) > 32:
            raise ValueError("trade sides must be lists of at most 32 items")
        for entry in action[side]:
            if not isinstance(entry, dict) or set(entry) != {"item_id", "amount"}:
                raise ValueError("trade items require item_id and amount")
            if type(entry["item_id"]) is not int or not 0 <= entry["item_id"] <= 2147483647:
                raise ValueError("trade item_id must be a nonnegative native ID")
            if type(entry["amount"]) is not int or not 1 <= entry["amount"] <= 2147483647:
                raise ValueError("trade amount must be a positive integer")
            if entry["item_id"] in seen:
                raise ValueError("trade item IDs must be distinct across both sides")
            seen.add(entry["item_id"])
    for key in ("offer_currency", "request_currency"):
        value = action.get(key, 0)
        if type(value) is not int or not 0 <= value <= 2147483647:
            raise ValueError(key + " must be a nonnegative native currency amount")
    if not seen and not action.get("offer_currency", 0) and not action.get("request_currency", 0):
        raise ValueError("trade requires items or currency")
    if not seen and action.get("offer_currency", 0) == action.get("request_currency", 0):
        raise ValueError("A currency-only trade must request a verifiable balance change")


def unrequested_transfers(action, pending, state):
    """Non-coin items that entered or left the inventory outside the request; None when unread."""
    before, after = pending.get("held_goods"), state.get("held_goods")
    if not isinstance(before, dict) or not isinstance(after, dict):
        return None
    taken = {
        row["signature"] for row in pending["items"] if row["side"] == "take" and "signature" in row
    }
    given = {str(entry["item_id"]) for entry in action["give"]}
    return {
        "added": sorted(i for i, sig in after.items() if i not in before and sig not in taken),
        "removed": sorted(i for i in before if i not in after and i not in given),
    }


def next_trade(workflow, view):
    action, ctx = workflow["action"], workflow.setdefault("context", {})
    menu, state = view.get("menu") or {}, view.get("trade") or {}
    pending = ctx.get("trade_submitted")
    if not state.get("available"):
        return result(
            "needs_input",
            state.get(
                "reason", "Open the selected merchant's native trade before submitting an offer."
            ),
            {
                "blocker_kind": "trade_state_unavailable",
                "facts": {
                    "unit_id": action["unit_id"],
                    "open_panels": view["status"].get("open_panels"),
                },
            },
        )
    if pending:
        quantities = Counter()
        before = {row["item_id"]: row for row in pending["items"]}
        current = {row["item_id"]: row for row in state["items"]}
        verified = True
        for side, sign in (("take", 1), ("give", -1)):
            for entry in action[side]:
                old, now = before[entry["item_id"]], current.get(entry["item_id"], {})
                quantities[old["signature"]] += sign * entry["amount"]
                # A source stack must leave its original side or lose the exact quantity.
                if now.get("present") and now.get("held") == old["held"]:
                    verified &= now.get("stack_size") == old["stack_size"] - entry["amount"]
                elif now.get("present"):
                    verified &= now.get("stack_size") == entry["amount"]
                else:
                    verified &= entry["amount"] == old["stack_size"]
        for signature, change in quantities.items():
            verified &= (
                state["inventory"].get(signature) == pending["inventory"][signature] + change
            )
        currency = action.get("request_currency", 0) - action.get("offer_currency", 0)
        verified &= state["currency"]["player"] == pending["currency"]["player"] + currency
        transfers = unrequested_transfers(action, pending, state)
        if transfers is None:
            # A contained row is selected as one item; without the inventory
            # scope reading that narrower transfer stays unproven.
            verified &= not any(
                row["side"] == "take" and "container_id" in row for row in pending["items"]
            )
        else:
            verified &= not transfers["added"] and not transfers["removed"]
        # Native merchant max_currency is an amount-entry bound. Overlapping shop
        # stock and personal coins can be counted twice; it is not a ledger whose
        # delta must conserve the player's balance. Verify the player and items.
        if verified:
            return result(
                "completed",
                "Native item transfers and currency change verified.",
                {
                    "value": {
                        "kind": "trade",
                        "unit_id": action["unit_id"],
                        "take": action["take"],
                        "give": action["give"],
                        "currency_change": currency,
                        "spend": action.get("spend", "cheapest"),
                        "player_currency": state["currency"]["player"],
                        "load": carrying_value(view),
                    }
                },
            )
        facts = {
            "native_talkline": menu.get("talkline"),
            "reply": state.get("reply"),
            "reply_truncated": state.get("reply_truncated", False),
            "currency": state["currency"],
            "items": state["items"],
            "inventory_quantities": state["inventory"],
            "unrequested_transfers": transfers,
        }
        counter = state.get("counter_offer")
        requested = {k: action.get(k, 0) for k in ("offer_currency", "request_currency")}
        if menu.get("talkline") == "Haggle" and counter and counter != requested:
            return result(
                "needs_input",
                "The merchant proposed different currency amounts; choose a new offer.",
                {
                    "blocker_kind": "native_trade_counteroffer",
                    "facts": {
                        "counter_offer": counter,
                        "player_currency": state["currency"]["player"],
                    },
                },
            )
        if menu.get("talkline") != pending.get("talkline"):
            reply = facts.pop("reply")
            return result(
                "needs_input",
                reply
                or "The native trade responded without the requested transfers; choose a new offer.",
                {"blocker_kind": "native_trade_response", "facts": facts},
            )
        return result(
            "no_effect",
            "The requested transfers are unverified; the offer was not submitted again.",
            {"blocker_kind": "trade_verification", "facts": facts},
        )
    if menu.get("kind") != "barter" or menu.get("unit_id") != action["unit_id"]:
        return result(
            "needs_input",
            "The requested merchant's trade is not open.",
            {"blocker_kind": "trade_context", "facts": {"unit_id": action["unit_id"]}},
        )
    if menu.get("rebuilding"):
        return {"input": {"type": "resume"}}
    if menu.get("editing"):
        return result(
            "needs_input",
            "A native quantity or filter edit is active.",
            {"blocker_kind": "trade_edit", "facts": {"editing": True}},
        )
    if state.get("selection_unavailable"):
        return result(
            "needs_input",
            state["selection_unavailable"],
            {
                "blocker_kind": "native_trade_option_unavailable",
                "facts": {
                    "matching_options": 0,
                    "items": state["items"],
                    "currency": state["currency"],
                },
            },
        )
    ctx["trade_submitted"] = deepcopy(state)
    return {"input": dict(action, type="trade_submit")}
