"""Changes in native skill XP and stored attributes, separate from health ticking."""

from copy import deepcopy


def compact_progress(changes):
    """Routine XP is one delta per skill; rank changes retain their new progress."""
    out = deepcopy({k: v for k, v in changes.items() if k != "skills"})
    xp, levels, records = {}, {}, {}
    for name, change in changes.get("skills", {}).items():
        if "xp" in change:
            xp[name] = change["xp"]
        if "level" in change:
            levels[name] = {k: deepcopy(change[k]) for k in ("level", "progress") if k in change}
        if "record" in change:
            records[name] = change["record"]
    out.update({k: v for k, v in (("xp", xp), ("levels", levels), ("records", records)) if v})
    return out


def _issues(sample, field):
    return [
        entry["path"]
        for kind in ("unavailable", "truncated")
        for entry in sample.get(kind, [])
        if entry.get("path", "").startswith(field)
    ]


def _skills(sample):
    values = sample.get("skills")
    return (
        {s["id"]: s for s in values if type(s.get("id")) is int} if isinstance(values, list) else {}
    )


def progress_changes(before, after):
    old, new = [(v.get("adventurer") or {}).get("progress") for v in (before, after)]
    if old is None and new is None:
        return {}
    if not isinstance(old, dict) or not isinstance(new, dict):
        return {"unavailable": {"reason": "A character progression sample is unavailable"}}
    samples = (old, new)
    epochs = [v.get("status", {}).get("world_epoch") for v in (before, after)]
    if (
        epochs[0] != epochs[1]
        or any(type(s.get("unit_id")) is not int for s in samples)
        or old["unit_id"] != new["unit_id"]
    ):
        return {"unavailable": {"reason": "Character or world changed; XP was not compared"}}
    if (
        any(
            s.get("soul_available") is not True or type(s.get("soul_id")) is not int
            for s in samples
        )
        or old["soul_id"] != new["soul_id"]
    ):
        return {
            "unavailable": {"reason": "Current soul changed or is unavailable; XP was not compared"}
        }

    out, unavailable = {}, {}
    for when, sample in zip(("before", "after"), samples, strict=True):
        paths = sorted(
            {
                entry["path"]
                for kind in ("unavailable", "truncated")
                for entry in sample.get(kind, [])
                if "path" in entry
            }
        )
        if not isinstance(sample.get("skills"), list):
            paths.append("skills")
        if paths:
            unavailable[when] = paths

    previous, current = _skills(old), _skills(new)
    complete = [isinstance(s.get("skills"), list) and not _issues(s, "skills") for s in samples]
    skills = {}
    for key in sorted(previous.keys() | current.keys()):
        left, right = previous.get(key), current.get(key)
        # DFHack getExperience returns zero for an absent stored skill. That
        # baseline is valid only after a complete enumeration of the same soul.
        if (left is None and not complete[0]) or (right is None and not complete[1]):
            continue
        old_xp = left.get("total_experience") if left else 0
        new_xp = right.get("total_experience") if right else 0
        if type(old_xp) is not int or type(new_xp) is not int:
            unavailable.setdefault("skills", []).append(key)
            continue
        changed = {"xp": new_xp - old_xp} if old_xp != new_xp else {}
        if right is None:
            changed["record"] = "removed"
        elif left is None or left.get("rating") != right.get("rating"):
            changed["level"] = right.get("rating_name", right.get("rating"))
        if changed:
            if right and all(
                type(right.get(k)) is int for k in ("experience", "next_level_xp_threshold")
            ):
                changed["progress"] = [right["experience"], right["next_level_xp_threshold"]]
            skills[(right or left).get("name", str(key))] = changed
    if skills:
        out["skills"] = skills

    attributes = {}
    for group in ("physical", "mental"):
        values = [s.get("attributes", {}).get(group) for s in samples]
        if any(not isinstance(v, list) for v in values):
            unavailable.setdefault("attributes", []).append(group)
            continue
        earlier = {a["id"]: a for a in values[0] if type(a.get("id")) is int}
        for attr in values[1]:
            prior = earlier.get(attr.get("id"), {})
            left, right = prior.get("value"), attr.get("value")
            if type(left) is int and type(right) is int and left != right:
                attributes[group + "." + attr.get("name", str(attr.get("id")))] = [left, right]
    if attributes:
        out["attributes"] = attributes
    if unavailable:
        out["unavailable"] = unavailable
    return out
