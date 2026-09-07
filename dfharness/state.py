"""Controller receipts and the small state projections used by recipes."""

from collections import Counter
from copy import deepcopy
from typing import Any

from .character_progress import compact_progress, progress_changes
from .events import project_events
from .views import pick, reading_coatings, reading_menu


def flatten(items):
    for item in items:
        yield item
        yield from flatten(item.get("contents", []))


def inventory(view):
    return {i["id"]: i for i in flatten((view.get("adventurer") or {}).get("inventory", []))}


def inventory_complete(view):
    player = view.get("adventurer") or {}
    return (
        "inventory" in player
        and not player.get("inventory_truncated", False)
        and not any(i.get("contents_truncated") for i in inventory(view).values())
    )


def all_items(view):
    return {**{i["id"]: i for i in flatten(view.get("nearby_items", []))}, **inventory(view)}


def contained_state(item):
    children = list(flatten(item.get("contents", [])))
    return {
        "ids": sorted(i["id"] for i in children),
        "records": sorted(
            [i["id"], i.get("location", {}).get("container_id"), i.get("stack_size")]
            for i in children
        ),
        "complete": not any(i.get("contents_truncated") for i in [item, *children])
        and all(type(i.get("stack_size")) is int and i["stack_size"] >= 0 for i in children),
    }


def carrying_value(view):
    """Current cached root load, never a reconstructed movement formula."""
    player = view.get("adventurer") or {}
    complete = "inventory" in player and not player.get("inventory_truncated", False)
    mass, seen = 0, set()
    for item in player.get("inventory", []):
        raw = item.get("weight_raw", {})
        whole, fraction = raw.get("whole"), raw.get("fraction")
        if item["id"] in seen:
            complete = False
            continue
        seen.add(item["id"])
        if (
            item.get("weight_computed") is not True
            or type(whole) is not int
            or whole < 0
            or type(fraction) is not int
            or not 0 <= fraction < 1000000
        ):
            complete = False
        else:
            mass += whole * 1000000 + fraction
    result = {"cached_weight_complete": complete, "source": "native_root_inventory_caches"}
    result["native_cached_weight_kg" if complete else "known_cached_weight_kg"] = mass / 1000000
    result["burden"] = deepcopy(
        player.get(
            "burden",
            {
                "available": False,
                "reason": "DFHack unit burden was not read",
            },
        )
    )
    return result


def item_value(action, view, before=None):
    value = {"kind": action["type"], "item_id": action["item_id"], "load": carrying_value(view)}
    item = all_items(view).get(action["item_id"])
    if item is None:
        value["item_available"] = False
        return value
    value.update(pick(item, ("description", "location", "mode", "body_part_id")))
    if "contents" in item or before is not None:
        contents = contained_state(item)
        value["contents"] = {
            "count": len(contents["ids"]),
            "ids": contents["ids"][:64],
            "complete": contents["complete"],
        }
        if len(contents["ids"]) > 64:
            value["contents"]["ids_omitted"] = len(contents["ids"]) - 64
        if before is not None:
            value["contents"]["intact"] = (
                contents["records"] == before["records"]
                if before["complete"] and contents["complete"]
                else None
            )
    return value


def grouped_departures(old, new, view):
    """Only group children whose continued containment is actually observed."""
    removed = set(old) - set(new)
    current = all_items(view)
    grouped, children = [], set()
    for item_id in sorted(removed):
        root = current.get(item_id)
        if not root or root.get("location", {}).get("container_id") in removed:
            continue
        ids = [i["id"] for i in flatten(root.get("contents", [])) if i["id"] in removed]
        if ids:
            grouped.append(
                {"id": item_id, "contents": sorted(ids), "location": root.get("location")}
            )
            children.update([item_id, *ids])
    return sorted(removed - children), grouped


def item_summary(item):
    out = pick(item, ("id", "description", "type", "material", "quality", "wear", "stack_size"))
    location = item.get("location", {})
    if isinstance(location, dict):
        out.update(pick(location, ("container_id", "mode", "body_part_id", "position")))
    elif "location" in item:
        out["location"] = deepcopy(location)
    out.update(pick(item, ("mode", "body_part_id")))
    if "contaminants" in item:
        out["contaminants"] = reading_coatings(item["contaminants"])
    out.update(
        pick(item, ("contaminants_unavailable", "contaminants_truncated", "contaminants_total"))
    )
    weight = item.get("weight_raw", {})
    if item.get("weight_computed") is True and {"whole", "fraction"} <= weight.keys():
        out["weight_kg"] = round(weight["whole"] + weight["fraction"] / 1000000, 6)
    elif "weight_kg" in item:
        out["weight_kg"] = item["weight_kg"]
    elif "weight_computed" in item:
        out["weight_kg"] = None
    return out


ABSENT = {"absent": True}


def field_changes(before, after, prefix=""):
    """Only changed leaves; absent, false, zero and explicit null stay distinct."""
    changed = {}
    for key in sorted(before.keys() | after.keys()):
        old, new = before.get(key, ABSENT), after.get(key, ABSENT)
        name = prefix + key
        if key in before and key in after and isinstance(old, dict) and isinstance(new, dict):
            changed.update(field_changes(old, new, name + "."))
        elif type(old) is type(new) and old == new:
            continue
        else:
            changed[name] = [deepcopy(old), deepcopy(new)]
    return changed


def state_changes(before, view, ticks):
    old, new = inventory(before), inventory(view)
    changes = {}
    available = [v.get("adventurer") is not None for v in (before, view)]
    complete = [inventory_complete(v) for v in (before, view)]
    if available[0] != available[1]:
        changes["character_available"] = available
    if not all(available):
        # Travel can offload the local adventurer. Missing that reader does not
        # mean the character lost every carried item and every health field.
        old, new = {}, {}
    elif complete[0] != complete[1]:
        changes["inventory_complete"] = complete
    added = []
    for key, item in new.items():
        if key not in old:
            summary = item_summary(item)
            if "description" in summary:
                summary.pop("type", None)
                summary.pop("material", None)
            for field, default in (("stack_size", 1), ("wear", 0), ("quality", 0)):
                if summary.get(field) == default:
                    summary.pop(field)
            if summary.get("contaminants") == []:
                summary.pop("contaminants")
            added.append(summary)
    changed = []
    for key in new.keys() & old.keys():
        fields = field_changes(item_summary(old[key]), item_summary(new[key]))
        if fields:
            changed.append({"id": key, "changed": fields})
    removed, containers = (
        grouped_departures(old, new, view) if complete[1] else (sorted(old.keys() - new.keys()), [])
    )
    items = {
        "added" if complete[0] else "observed": added,
        "removed" if complete[1] else "unobserved": removed,
        "containers_removed": containers,
        "changed": changed,
    }
    if any(items.values()):
        changes["inventory"] = {k: v for k, v in items.items() if v}
    initial, final = before.get("adventurer") or {}, view.get("adventurer") or {}
    if not all(available):
        initial, final = {}, {}
    health = field_changes(initial.get("health", {}), final.get("health", {}))
    # In the verified adventure reader, unit counters advance before the frame
    # counter during MOVE_UNIT/FINAL_PROCESSING. Interrupted receipts can catch
    # that boundary. Unknown phases retain the conservative exact-frame rule.
    phases = {
        "TAKING_INPUT": 0,
        "SUBSEQUENT_PROCESSING": 0,
        "MOVE_UNIT_PROCESSING": 1,
        "FINAL_PROCESSING": 1,
    }
    offsets = [phases.get(v.get("status", {}).get("turn_phase")) for v in (before, view)]
    counter_ticks = ticks
    if ticks is not None and offsets[0] is not None and offsets[1] is not None:
        counter_ticks += offsets[1] - offsets[0]
    for timer, need in (
        ("hunger_timer", "hunger"),
        ("thirst_timer", "thirst"),
        ("sleepiness_timer", "sleep"),
    ):
        pair = health.get(timer)
        old_need = initial.get("needs", {}).get(need, {})
        new_need = final.get("needs", {}).get(need, {})
        # Unknown needs keep their raw changes. Action effects and warning
        # transitions survive; only ordinary ticking is redundant with ticks.
        if (
            pair
            and ticks is not None
            and all(type(v) is int for v in pair)
            and pair[1] >= pair[0]
            and pair[1] - pair[0] == counter_ticks
            and "severity" in old_need
            and "severity" in new_need
        ):
            health.pop(timer)
    if health:
        changes["health"] = health
    for key in ("on_ground", "alive", "needs", "movement"):
        delta = field_changes(pick(initial, (key,)), pick(final, (key,)))
        changes.update(delta)
    if advancement := progress_changes(before, view):
        changes["progress"] = compact_progress(advancement)
    status = field_changes(
        pick(before.get("status", {}), ("map_origin", "mode", "adventurer_id", "save", "travel")),
        pick(view.get("status", {}), ("map_origin", "mode", "adventurer_id", "save", "travel")),
    )
    # Travel position and coordinate-frame transitions matter; fixed legends do not.
    status = {k: v for k, v in status.items() if not k.startswith("travel.party_needs")}
    if status:
        changes["world"] = status
    units, unit_coverage = [], []
    for v in (before, view):
        visible = v.get("map") or {}
        known_empty = v.get("status", {}).get("map_loaded") is False and "units" not in visible
        coverage = {
            "complete": known_empty
            or (
                isinstance(visible.get("units"), list)
                and visible.get("units_available") is not False
                and not visible.get("units_truncated")
            )
        }
        if not coverage["complete"]:
            coverage["reason"] = visible.get("units_unavailable") or (
                "Visible unit enumeration was truncated"
                if visible.get("units_truncated")
                else "Visible unit enumeration is unavailable"
            )
        unit_coverage.append(coverage)
        units.append(
            {
                u["id"]: {k: value for k, value in u.items() if k not in ("in_map", "glyph")}
                for u in (v.get("map") or {}).get("units", [])
                if u["id"] != v.get("status", {}).get("adventurer_id")
            }
        )
    old_units, new_units = units
    appeared = [
        pick(u, ("id", "name", "position", "race", "alive", "species", "profession"))
        for key, u in new_units.items()
        if key not in old_units
    ]
    moved, other = [], []
    for key in old_units.keys() & new_units.keys():
        fields = field_changes(old_units[key], new_units[key])
        if any(k == "position" or k.startswith("position.") for k in fields):
            moved.append({"id": key, "position": deepcopy(new_units[key].get("position"))})
            fields = {
                k: v for k, v in fields.items() if k != "position" and not k.startswith("position.")
            }
        if fields:
            other.append({"id": key, "changed": fields})
    unit_changes = {
        "appeared" if unit_coverage[0]["complete"] else "observed": appeared,
        "left" if unit_coverage[1]["complete"] else "unobserved": sorted(
            old_units.keys() - new_units.keys()
        ),
        "moved": moved,
        "changed": other,
    }
    if any(unit_changes.values()):
        changes["units"] = {k: v for k, v in unit_changes.items() if v}
    if unit_coverage[0] != unit_coverage[1]:
        changes["units_coverage"] = unit_coverage
    return changes


def speech_result(dispatch, seen_reply_ids=()):
    said, represented = [], set()
    seen = set(seen_reply_ids)
    details = [r.get("details", {}) for r in dispatch.get("results", [])]
    details.append(dispatch.get("details", {}))
    for detail in details:
        replies = [
            e
            for e in detail.get("replies", [])
            if e.get("id") not in seen and e.get("id") not in represented
        ]
        if replies:
            said.append(
                {
                    "unit": detail["unit_id"],
                    "topic": detail.get("topic"),
                    "reply": "\n".join(e["text"] for e in replies),
                }
            )
            represented.update(e["id"] for e in replies)
    return said, represented


def objective_values(dispatch, reported_stage=-1):
    """Actual recipe results, without completed-stage execution receipts."""
    composite = "results" in dispatch
    stages = dispatch.get("results", [{"stage_index": 0, "details": dispatch.get("details", {})}])
    values = []
    latest = reported_stage
    for stage in stages:
        index = stage.get("stage_index", 0)
        value = stage.get("details", {}).get("value")
        if value is not None and index > reported_stage:
            values.append({"stage": index, **deepcopy(value)} if composite else deepcopy(value))
            latest = max(latest, index)
    return values, latest


def target_condition(current, previous):
    """Keep current reassessment facts; diff other readings against this dispatch."""
    if not all(
        isinstance(sample, dict)
        and sample.get("available") is True
        and sample.get("complete") is True
        for sample in (current, previous)
    ):
        return deepcopy(current)
    always = {"available", "complete", "alive", "conscious", "prone", "projectile", "wounds"}
    # Stable impairments still matter to the next decision. Do not compact an
    # already crippled or bleeding opponent into an apparently healthy one.
    if current.get("blood_count") != current.get("blood_max"):
        always.update(("blood_count", "blood_max"))
    for key in ("grapples", "parts_with_status"):
        if current.get(key):
            always.add(key)
    for counts in current.get("functional_limbs", {}).values():
        if isinstance(counts, list) and len(counts) == 2 and counts[0] != counts[1]:
            always.add("functional_limbs")
    out = pick(current, always)
    delta = field_changes(
        {k: v for k, v in previous.items() if k not in always},
        {k: v for k, v in current.items() if k not in always},
    )
    if delta:
        out["changed"] = delta
    return out


def compact_result(
    view, before, event_detail="task", seen_reply_ids=(), event_cursor=None, reported_value_stage=-1
):
    """One outcome contract for every action; the full record is stored separately."""
    if event_detail not in ("task", "all"):
        raise ValueError("event_detail must be task or all")
    dispatch = view.get("dispatch", {})
    outcome = dispatch.get("outcome", "unknown")
    cursor = (
        max((e["id"] for e in before.get("reports", [])), default=-1)
        if event_cursor is None
        else event_cursor
    )
    said, represented = speech_result(dispatch, seen_reply_ids)
    result: dict[str, Any] = {"format": "compact", "schema_version": 3, "outcome": outcome}
    if said:
        result["said"] = said
    values, _ = objective_values(dispatch, reported_value_stage)
    if any("stage" in value for value in values):
        # A batch needs one current load, not the same character block after
        # every pickup/stow. Intermediate values remain in stage diagnostics.
        if any("load" in value for value in values):
            for value in values:
                value.pop("load", None)
            result["assessment"] = {"load": carrying_value(view)}
        # Keep each target's latest sampled condition with its stage. Earlier
        # attempts still retain their own verified effect, including new wounds.
        latest_targets = set()
        for value in reversed(values):
            if value.get("kind") == "strike" and "target" in value:
                if value["unit_id"] in latest_targets:
                    value.pop("target")
                latest_targets.add(value["unit_id"])
    if values:
        prior = before.get("target_unit") or {}
        for value in values:
            if (
                value.get("kind") == "strike"
                and "target" in value
                and value["unit_id"] == prior.get("id")
            ):
                value["target"] = target_condition(value["target"], prior.get("condition"))
        result["values"] = values
    result.update(
        dispatch_id=dispatch.get("id"),
        state_id=view.get("state_id"),
        from_state=before.get("state_id"),
        inputs=sum(
            s["action"]["type"] not in ("scroll_menu", "resume") for s in dispatch.get("steps", [])
        ),
    )
    status, initial_status = view.get("status", {}), before.get("status", {})
    ticks = None
    if all(type(s.get("world_frame")) is int for s in (status, initial_status)):
        delta = status["world_frame"] - initial_status["world_frame"]
        if (
            delta >= 0
            and status.get("save") == initial_status.get("save")
            and status.get("local_map_epoch") == initial_status.get("local_map_epoch")
        ):
            ticks = delta
    if ticks is not None:
        result["ticks"] = ticks
    if any(k in status for k in ("year", "year_tick")):
        calendar = [pick(s, ("year", "year_tick")) for s in (initial_status, status)]
        if (
            all(type(s.get(k)) is int for s in calendar for k in ("year", "year_tick"))
            and calendar[0] != calendar[1]
        ):
            if (
                calendar[0]["year"] == calendar[1]["year"]
                and calendar[1]["year_tick"] >= calendar[0]["year_tick"]
            ):
                result["calendar_ticks"] = calendar[1]["year_tick"] - calendar[0]["year_tick"]
            else:
                result["calendar"] = calendar
    if view.get("reports_more"):
        result["pending_reports"] = {
            "after": view.get("next_report_cursor"),
            "native_cursor": view.get("report_cursor"),
        }
    result["status"] = pick(status, ("position", "can_move", "ready_for_input", "open_panels"))
    if status.get("modal"):
        # This is an unresolved prompt, not a history of acknowledged help.
        result["prompt"] = deepcopy(status["modal"])
    progress = dispatch.get("progress", {})
    if "completed_stages" in progress:
        result["completed_stages"] = progress["completed_stages"]
    if outcome != "completed":
        blocker = dispatch.get("blocker", {})
        details = dispatch.get("details", {})
        result["blocker"] = {
            "kind": blocker.get("kind", details.get("blocker_kind", "controller_choice")),
            "why": dispatch.get("reason", "Completion is unverified."),
        }
        if "stage_index" in progress:
            result["blocker"]["stage"] = progress["stage_index"]
        if progress.get("current_action"):
            result["blocker"]["action"] = pick(
                progress["current_action"],
                (
                    "type",
                    "item_id",
                    "container_id",
                    "unit_id",
                    "topic",
                    "choice_id",
                    "subject_hf_id",
                    "x",
                    "y",
                    "z",
                    "direction",
                    "posture",
                    "portions",
                ),
            )
        facts = pick(
            details,
            (
                "code",
                "input_sent",
                "item_id",
                "container_id",
                "unit_id",
                "destination",
                "position",
                "expected",
                "actual",
                "completion",
                "original_map_origin",
                "current_map_origin",
                "requested_action",
                "candidates",
                "elapsed_calendar_ticks",
                "required_calendar_ticks",
                "native_interrupt",
            ),
        )
        # New recipes provide their decision facts explicitly. A renderer field
        # allowlist must not silently discard a new domain's concrete blocker.
        # Legacy flat details keep their bounded projection during migration.
        if isinstance(details.get("facts"), dict):
            facts = deepcopy(details["facts"])
        if facts:
            result["blocker"]["facts"] = facts
        if details.get("code") == "stale_state":
            result["resync_required"] = True
        if "resume_action" in dispatch:
            result["resume"] = deepcopy(dispatch["resume_action"])
        if progress.get("awaiting"):
            result["awaiting"] = deepcopy(progress["awaiting"])
    action = dispatch.get("action", {})
    needs_choices = outcome == "needs_input" or (
        outcome == "completed"
        and (
            (action.get("type") == "talk" and not (action.get("topic") or action.get("choice_id")))
            or (action.get("type") == "combat" and not action.get("option_id"))
        )
    )
    if dispatch.get("details", {}).get("facts", {}).get("matching_options") == 0:
        needs_choices = False
    if needs_choices and not status.get("modal"):
        focus = pick(progress.get("current_action", action), ("item_id", "container_id", "unit_id"))
        if dispatch.get("details", {}).get("position"):
            focus["position"] = dispatch["details"]["position"]
        for kind in ("menu", "conversation", "combat"):
            menu = view.get(kind)
            if menu and menu.get("open", True):
                result["choices"] = reading_menu(menu, focus)
                break
        if "choices" not in result and dispatch.get("details", {}).get("options"):
            result["choices"] = reading_menu({"options": dispatch["details"]["options"]}, focus)
        if view.get("input_guard", {}).get("native_complete") is not True and (
            "choices" not in result
            or result["choices"].get("selection_unavailable")
            or not result["choices"].get("options")
        ):
            result["ui_text"] = [r["text"].strip() for r in view.get("ui", {}).get("rows", [])]
    changes = state_changes(before, view, ticks)
    if changes:
        result["changes"] = changes
    force_types = dispatch.get("execution", {}).get("interrupt_on", {}).get("report_types", [])
    events, omitted = project_events(
        (
            e
            for e in dispatch.get("events", [])
            if e.get("id", -1) > cursor and e.get("id") not in represented
        ),
        event_detail,
        force_types,
        dispatch.get("task_event_ids", ()),
    )
    if events:
        result["events"] = [pick(e, ("id", "type", "speaker_id", "text")) for e in events]
    omissions = {}
    if dispatch.get("state_refreshes"):
        omissions["state_refreshes"] = len(dispatch["state_refreshes"])
    old_items, new_items = inventory(before), inventory(view)
    coating_details = 0
    for item_id in old_items.keys() & new_items.keys():
        coatings = [items[item_id].get("contaminants", []) for items in (old_items, new_items)]
        if coatings[0] != coatings[1] and any(
            "size" in c or "temperature" in c for values in coatings for c in values
        ):
            coating_details += 1
    if coating_details:
        omissions["coating_measurements"] = {"items": coating_details}
    if omitted:
        omissions["events"] = dict(omitted)
    prompts = Counter(
        p.get("modal", {}).get("kind", "unknown") for p in dispatch.get("prompts", [])
    )
    if prompts:
        omissions["prompts"] = dict(prompts)
    if omissions:
        result["omitted"] = omissions
    if view.get("dispatch_replayed"):
        result["replayed"] = True
    return result


def render_receipt(receipt):
    """Readable outcome and facts, with no inline execution-record JSON dumps."""
    lines = [f"{receipt['outcome']} | {receipt.get('inputs', 0)} inputs"]
    if "ticks" in receipt:
        lines[0] += f" | {receipt['ticks']} ticks"
    if "calendar_ticks" in receipt:
        lines[0] += f" | {receipt['calendar_ticks']} calendar ticks"
    if "calendar" in receipt:
        lines.append("Calendar: " + str(receipt["calendar"]))
    for exchange in receipt.get("said", []):
        lines.append(f"{exchange['unit']} / {exchange.get('topic')}: {exchange['reply']}")
    for value in receipt.get("values", []):
        lines.append("Result: " + "; ".join(f"{key}={field}" for key, field in value.items()))
    status = receipt.get("status", {})
    if status:
        lines.append("State: " + "; ".join(f"{k}={v}" for k, v in status.items()))
    if receipt.get("blocker"):
        blocker = receipt["blocker"]
        lines.append(f"Blocked ({blocker['kind']}): {blocker['why']}")
        for key in ("stage", "action", "facts"):
            if key in blocker:
                lines.append(f"  {key}: {blocker[key]}")
    if "completed_stages" in receipt:
        lines.append(f"Completed stages: {receipt['completed_stages']}")
    choices = receipt.get("choices", {})
    for kind, options in choices.get("options", {}).items():
        lines.append(kind + ":")
        for option in options:
            fields = [f"{k}={v}" for k, v in option.items() if k not in ("id", "hf")]
            reference = option["id"] if "id" in option else f"hf={option['hf']}"
            lines.append(f"  {reference}: " + "; ".join(fields))
    if choices.get("truncated"):
        lines.append(f"Choices truncated; native total {choices.get('total', 'unknown')}")
    for section, changes in receipt.get("changes", {}).items():
        lines.append(section + ":")
        if isinstance(changes, dict):
            for key, value in changes.items():
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    lines.extend(f"  {key}: {v}" for v in value)
                else:
                    lines.append(f"  {key}: {value}")
        else:
            lines.append(f"  {changes}")
    for event in receipt.get("events", []):
        lines.append(f"{event.get('type', 'event')}: {event.get('text', '')}")
    for kind, counts in receipt.get("omitted", {}).items():
        lines.append(f"Omitted {kind}: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    if receipt.get("prompt"):
        prompt = receipt["prompt"]
        lines.append(f"Prompt ({prompt.get('kind')}): " + str(prompt.get("text", prompt)))
    lines.extend(receipt.get("ui_text", []))
    lines.append(f"dispatch={receipt.get('dispatch_id')} state={receipt.get('state_id')}")
    if receipt.get("resume"):
        lines.append(f"Resume: {receipt['resume']['dispatch_id']}")
    return "\n".join(lines)
