"""Controller policy validation and factual interruption predicates."""

from copy import deepcopy

DEFAULT_EXECUTION = {"mode": "step", "acknowledge": False, "max_steps": 32, "interrupt_on": {}}
MAX_DISPATCH_INPUTS = 1024
UNIT_HEALTH_FLAGS = ("blood_loss", "new_wounds")
MAX_WATCHED_UNITS = 32


def execution_policy(defaults=None, override=None):
    policy = deepcopy(DEFAULT_EXECUTION)
    for supplied in (defaults, override):
        if supplied is None:
            continue
        if not isinstance(supplied, dict) or supplied.keys() - policy.keys():
            raise ValueError(
                "execution accepts mode, acknowledge, max_steps, and interrupt_on only"
            )
        policy.update(deepcopy(supplied))
    if policy["mode"] not in ("step", "complete"):
        raise ValueError("execution.mode must be step or complete")
    if type(policy["acknowledge"]) is not bool:
        raise ValueError("execution.acknowledge must be a boolean")
    if type(policy["max_steps"]) is not int or not 1 <= policy["max_steps"] <= MAX_DISPATCH_INPUTS:
        raise ValueError(f"execution.max_steps must be an integer in [1, {MAX_DISPATCH_INPUTS}]")
    rules = policy["interrupt_on"]
    supported_rules = {
        "blood_loss",
        "new_wounds",
        "new_visible_units",
        "new_visible_units_except",
        "visible_unit_ids",
        "report_types",
        "unit_health",
    }
    if not isinstance(rules, dict):
        raise ValueError("interrupt_on must be an object")
    if unknown := rules.keys() - supported_rules:
        raise ValueError(
            "Unknown interrupt_on condition: "
            + ", ".join(sorted(unknown))
            + "; supported: "
            + ", ".join(sorted(supported_rules))
        )
    for name in ("blood_loss", "new_wounds", "new_visible_units"):
        if name in rules and type(rules[name]) is not bool:
            raise ValueError("interrupt_on." + name + " must be boolean")
    for name, item_type in (
        ("visible_unit_ids", int),
        ("new_visible_units_except", int),
        ("report_types", str),
    ):
        values = rules.get(name, [])
        if (
            not isinstance(values, list)
            or len(values) > 100
            or any(type(v) is not item_type for v in values)
        ):
            raise ValueError("interrupt_on." + name + " must be a list of at most 100 values")
        if item_type is int and any(v < 0 for v in values):
            raise ValueError("Visible unit IDs must be nonnegative")
    watches = rules.get("unit_health", [])
    if not isinstance(watches, list) or len(watches) > MAX_WATCHED_UNITS:
        raise ValueError(
            f"interrupt_on.unit_health must be a list of at most {MAX_WATCHED_UNITS} rules"
        )
    seen = set()
    for watch in watches:
        if not isinstance(watch, dict) or watch.keys() - {"unit_id", *UNIT_HEALTH_FLAGS}:
            raise ValueError("Each unit_health rule accepts unit_id, blood_loss and new_wounds")
        unit_id = watch.get("unit_id")
        if type(unit_id) is not int or not 0 <= unit_id <= 2147483647 or unit_id in seen:
            raise ValueError("unit_health requires distinct nonnegative native unit IDs")
        if any(type(watch.get(flag, False)) is not bool for flag in UNIT_HEALTH_FLAGS):
            raise ValueError("unit_health conditions must be boolean")
        if not any(watch.get(flag) for flag in UNIT_HEALTH_FLAGS):
            raise ValueError("Each unit_health rule must enable at least one condition")
        seen.add(unit_id)
    return policy


def watch_options(policy):
    rules = policy["interrupt_on"]
    ids = [watch["unit_id"] for watch in rules.get("unit_health", [])]
    out = {"watch_units": ids} if ids else {}
    fields = {}
    for condition, field in (("blood_loss", "blood_count"), ("new_wounds", "wounds")):
        if rules.get(condition):
            fields[field] = True
    if rules.get("new_visible_units") or rules.get("visible_unit_ids"):
        fields["visible_units"] = True
    if fields:
        out["progress_watch"] = fields
    return out


def stop(message, *, unavailable=False, **facts):
    return {
        "outcome": "needs_input" if unavailable else "interrupted",
        "reason": message,
        "details": {
            "blocker_kind": "watch_unavailable" if unavailable else "interrupted",
            "facts": facts,
        },
    }


def unit_health_interruption(before, view, watches):
    previous = {u["unit_id"]: u for u in before.get("watched_units", [])}
    current = {u["unit_id"]: u for u in view.get("watched_units", [])}
    offloaded = (view.get("status") or {}).get("map_loaded") is False
    for watch in watches:
        unit_id = watch["unit_id"]
        old, new = previous.get(unit_id, {}), current.get(unit_id, {})
        for condition, field in (("blood_loss", "blood_count"), ("new_wounds", "wound_ids")):
            if not watch.get(condition):
                continue
            if offloaded and new.get("available") is not True and old.get("available") is True:
                continue  # Deferred until the local map reloads; the baseline stays.
            for when, sample in (("initial", old), ("current", new)):
                value = sample.get(field)
                known = sample.get("available") is True and (
                    type(value) is int and value >= 0
                    if field == "blood_count"
                    else isinstance(value, list) and all(type(v) is int and v >= 0 for v in value)
                )
                if not known:
                    return stop(
                        "The requested unit health watch cannot be evaluated; no further input was sent.",
                        unavailable=True,
                        unit_id=unit_id,
                        condition=condition,
                        reading=when,
                        reason=sample.get("reason")
                        or sample.get("unavailable", {}).get(field)
                        or "Requested native health sample is missing or invalid",
                    )
            if condition == "blood_loss" and new[field] < old[field]:
                return stop(
                    "Controller interruption condition matched: unit_health.blood_loss",
                    unit_id=unit_id,
                    condition=condition,
                    blood_count=[old[field], new[field]],
                )
            if condition == "new_wounds" and (added := set(new[field]) - set(old[field])):
                return stop(
                    "Controller interruption condition matched: unit_health.new_wounds",
                    unit_id=unit_id,
                    condition=condition,
                    new_wound_ids=sorted(added),
                )
    return None


def interruption(before, view, events, policy):
    """Evaluate explicit factual predicates, never a built-in threat score."""
    rules = policy["interrupt_on"]
    old = (before.get("adventurer") or {}).get("health", {})
    new = (view.get("adventurer") or {}).get("health", {})
    # A native rest, sleep or travel offloads the local map, and no unit can be
    # read until it reloads. The watch is deferred, never passed: the next
    # loaded observation is compared with the same pre-offload baseline.
    offloaded = (view.get("status") or {}).get("map_loaded") is False
    for condition, field, compare in (
        ("blood_loss", "blood_count", lambda a, b: b < a),
        ("new_wounds", "wounds", lambda a, b: b > a),
    ):
        if not rules.get(condition):
            continue
        if offloaded and type(new.get(field)) is not int and type(old.get(field)) is int:
            continue
        for when, sample in (("initial", old), ("current", new)):
            value = sample.get(field)
            if type(value) is not int or value < 0:
                return stop(
                    "The requested player health watch cannot be evaluated; no further input was sent.",
                    unavailable=True,
                    condition=condition,
                    reading=when,
                    reason=sample.get("unavailable", {}).get(field)
                    or "Requested native health sample is missing or invalid",
                )
        if compare(old[field], new[field]):
            return stop(
                "Controller interruption condition matched: " + condition,
                condition=condition,
                **{field: [old[field], new[field]]},
            )
    if watched := unit_health_interruption(before, view, rules.get("unit_health", [])):
        return watched
    visibility = rules.get("new_visible_units") or rules.get("visible_unit_ids")
    if visibility:
        samples = [("current", view)]
        if rules.get("new_visible_units"):
            samples.insert(0, ("initial", before))
        for when, observation in samples:
            visible = observation.get("map") or {}
            units = visible.get("units")
            # Offloaded local maps have no locally visible units. An absent
            # map in any other state does not establish an empty visible set.
            offloaded = observation.get("status", {}).get("map_loaded") is False
            if units is None and offloaded:
                continue
            known = (
                isinstance(units, list)
                and visible.get("units_available") is not False
                and not visible.get("units_truncated")
                and all(
                    isinstance(u, dict) and type(u.get("id")) is int and u["id"] >= 0 for u in units
                )
            )
            if not known:
                return stop(
                    "Visible unit enumeration is unavailable or truncated; the controller's interruption conditions cannot be fully evaluated.",
                    unavailable=True,
                    condition="visibility",
                    reading=when,
                    reason=visible.get("units_unavailable")
                    or (
                        "Visible unit enumeration was truncated"
                        if visible.get("units_truncated")
                        else "Requested visible unit sample is missing or invalid"
                    ),
                )
    units = {u["id"] for u in (view.get("map") or {}).get("units", [])}
    previous = {u["id"] for u in (before.get("map") or {}).get("units", [])}
    # Local reloads put the player back into the visible-unit list. That is not
    # another newly encountered creature. Explicit visible_unit_ids still means
    # precisely the controller's named IDs, including the player if requested.
    actor_id = view.get("status", {}).get("adventurer_id")
    new_units = units - previous - set(rules.get("new_visible_units_except", [])) - {actor_id}
    if rules.get("new_visible_units") and new_units:
        return stop(
            "Controller interruption condition matched: new_visible_units "
            + str(sorted(new_units)),
            condition="new_visible_units",
            unit_ids=sorted(new_units),
        )
    if units.intersection(rules.get("visible_unit_ids", [])):
        return stop(
            "Controller interruption condition matched: visible_unit_ids",
            condition="visible_unit_ids",
            unit_ids=sorted(units.intersection(rules["visible_unit_ids"])),
        )
    if any(e.get("type") in rules.get("report_types", []) for e in events):
        return stop(
            "Controller interruption condition matched: report_types", condition="report_types"
        )
    return None
