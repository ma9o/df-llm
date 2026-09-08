"""Open a controller-selected shop catalog, without proposing a transaction."""

from .interactions import next_interaction
from .workflows import result


def validate_barter(action):
    if action["type"] == "close_trade":
        if set(action) != {"type"}:
            raise ValueError("close_trade accepts no targets")
        return
    if set(action) != {"type", "unit_id", "shop_id"} or any(
        type(action[k]) is not int or not 0 <= action[k] <= 2147483647
        for k in ("unit_id", "shop_id")
    ):
        raise ValueError("open_trade requires a merchant unit_id and a loaded Shop zone shop_id")


def next_barter(workflow, view):
    action, ctx = workflow["action"], workflow.setdefault("context", {})
    menu = view.get("menu") or {}
    opened = menu.get("kind") == "barter"
    if action["type"] == "close_trade":
        if not opened:
            if "barter" in view["status"].get("open_panels", []):
                return result("needs_input", "The native trade reader is unavailable.")
            return result("completed", "The trade interface is closed.")
        if ctx.get("pending"):
            return result("no_effect", "The native trade interface did not close.")
        return {"input": {"type": "key", "key": "LEAVESCREEN"}, "pending": {"kind": "close_trade"}}
    if not opened:
        if ctx.get("catalog_submitted"):
            return result("no_effect", "The requested shop catalog did not remain open.")
        if "barter" in view["status"].get("open_panels", []):
            return result("needs_input", "The native trade reader is unavailable.")
        decision = next_interaction(
            {
                "action": {"type": "talk", "unit_id": action["unit_id"], "topic": "Trade"},
                "context": ctx,
            },
            view,
        )
        if decision.get("outcome") == "completed":
            return result("needs_input", "The merchant's reply did not open a native trade.")
        return decision
    if not menu.get("available"):
        return result(
            "needs_input", menu.get("selection_unavailable", "Trade state is unavailable.")
        )
    if menu.get("unit_id") != action["unit_id"] or menu.get("personal") or menu.get("demand_only"):
        return result("needs_input", "A different merchant or trade mode is already open.")
    if menu.get("rebuilding"):
        return {"input": {"type": "resume"}, "pending": {"kind": "catalog_rebuild"}}
    zone = menu.get("zone") or {}
    if zone.get("id") == action["shop_id"] and zone.get("type") == "Shop":
        return result(
            "completed",
            "DF rebuilt the requested shop's trade catalog.",
            {
                "value": {
                    "kind": "open_trade",
                    "unit_id": action["unit_id"],
                    "shop_id": action["shop_id"],
                    "goods": menu["goods"]["take"],
                    "currency": menu["currency"],
                }
            },
        )
    if ctx.get("catalog_submitted"):
        return result("no_effect", "DF did not retain the requested shop catalog.")
    if (
        menu.get("editing")
        or any(menu.get("draft", {}).values())
        or any(menu.get("currency", {}).get(k) for k in ("offer", "request"))
    ):
        return result(
            "needs_input", "Finish the active trade edit or pending offer before changing catalogs."
        )
    ctx["catalog_submitted"] = True
    return {
        "input": {"type": "trade_shop", "unit_id": action["unit_id"], "shop_id": action["shop_id"]},
        "pending": {"kind": "catalog_rebuild"},
    }
