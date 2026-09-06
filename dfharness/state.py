"""Small, stable state projections shared by dispatch and action recipes."""

from copy import deepcopy
import json


def flatten(items):
    for item in items:
        yield item
        yield from flatten(item.get("contents", []))


def inventory(view):
    return {i["id"]: i for i in flatten((view.get("adventurer") or {}).get("inventory", []))}


def all_items(view):
    return {**{i["id"]: i for i in flatten(view.get("nearby_items", []))}, **inventory(view)}


def item_summary(item):
    return {k: deepcopy(item[k]) for k in ("id", "description", "type", "quality", "material",
            "wear", "weight_raw", "weight_computed", "mode", "body_part_id", "location", "stack_size") if k in item}


def compact_result(view, before):
    old, new = inventory(before), inventory(view)
    result = {k: deepcopy(view[k]) for k in ("state_id", "effect_id", "status", "dispatch",
              "dispatch_replayed", "action") if k in view}
    result["format"] = "compact"
    if "dispatch" in result:
        # Preserve exact messages and encounter order without returning the
        # same Inventory help paragraph once for every menu in a recipe.
        unique, encounters, indices = [], [], {}
        for prompt in result["dispatch"].get("prompts", []):
            prompt["modal"].pop("text", None)  # Already in prompt.text.
            key = json.dumps(prompt, sort_keys=True, ensure_ascii=False)
            if key not in indices:
                indices[key] = len(unique)
                unique.append(prompt)
            encounters.append(indices[key])
        result["dispatch"]["prompts"] = unique
        result["dispatch"]["prompt_sequence"] = encounters
    result["changes"] = {
        "inventory_added": [item_summary(i) for key, i in new.items() if key not in old],
        "inventory_removed": [item_summary(i) for key, i in old.items() if key not in new],
        "inventory_changed": [{"before": item_summary(old[key]), "after": item_summary(i)}
                              for key, i in new.items() if key in old and item_summary(old[key]) != item_summary(i)],
    }
    for field, initial, final in (
        ("position", before.get("status", {}).get("position"), view.get("status", {}).get("position")),
        ("health", (before.get("adventurer") or {}).get("health"), (view.get("adventurer") or {}).get("health")),
    ):
        if initial != final:
            result["changes"][field] = {"before": initial, "after": final}
    old_units = {u["id"]: u for u in (before.get("map") or {}).get("units", [])
                 if u["id"] != before.get("status", {}).get("adventurer_id")}
    new_units = {u["id"]: u for u in (view.get("map") or {}).get("units", [])
                 if u["id"] != view.get("status", {}).get("adventurer_id")}
    result["changes"].update(
        visible_units_added=[deepcopy(u) for i, u in new_units.items() if i not in old_units],
        visible_units_removed=[deepcopy(u) for i, u in old_units.items() if i not in new_units],
        visible_units_changed=[{"before": deepcopy(old_units[i]), "after": deepcopy(u)}
                               for i, u in new_units.items() if i in old_units and old_units[i] != u],
    )
    # Return choices whenever a controller decision is needed; the full UI/map
    # remain available through observe, independently of execution policy.
    if view.get("menu"):
        result["menu"] = {k: deepcopy(v) for k, v in view["menu"].items() if k != "options"}
        result["menu"]["options"] = [{k: o[k] for k in ("id", "item_id", "container_id", "kind", "label", "visible") if k in o}
                                     for o in view["menu"].get("options", [])]
    if view.get("conversation"):
        result["conversation"] = deepcopy(view["conversation"])
    if view.get("status", {}).get("modal") or view.get("dispatch", {}).get("outcome") in ("needs_input", "failed", "no_effect"):
        result["ui_text"] = [r["text"].strip() for r in view.get("ui", {}).get("rows", [])]
    return result
