"""Native path execution where the game can represent the requested route rules."""

from .routing import ROUTE_FIELDS


def next_native_walk(view, target, constraints, radius, context):
    # The native interface has no excluded-tile/depth constraint fields. Keep
    # the existing observed-route adapter for these requests; never ignore them.
    if any(key in constraints for key in ROUTE_FIELDS):
        return None
    native = view.get("native_path") or {}
    evidence = view.get("input_evidence") or {}
    if context and context.get("path_evidence_for"):
        if (
            evidence.get("kind") != "walk"
            or evidence.get("available") is not True
            or evidence.get("phase") not in ("completed", "paused")
            or native.get("available") is not True
        ):
            return {
                "outcome": "needs_input",
                "reason": evidence.get("reason", "Submitted native path could not be verified"),
                "details": {
                    "blocker_kind": "native_path",
                    "facts": {"destination": target, "phase": evidence.get("phase", "unavailable")},
                },
            }
    elif native.get("available") is not True:
        return None
    if native.get("goal") != "None":
        return {
            "outcome": "needs_input",
            "reason": "Another native movement goal is active.",
            "details": {"blocker_kind": "native_path_active", "facts": native},
        }
    if context is not None:
        context["walk_adapter"] = "native_path"
    return {
        "input": {"type": "path_to", "destination": target, "arrival_radius": radius},
        "capture": {"kind": "walk"},
    }
