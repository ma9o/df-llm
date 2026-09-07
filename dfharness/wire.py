"""Lossless, versioned execution deltas. This is transport, not a state projection.

Array entries use zero-based JSON indices. Replacements are explicit so null,
false, empty objects and empty arrays remain distinct from absent fields.
"""

from copy import deepcopy

from .rpc import DFHackError


def delta(before, after):
    if type(before) is not type(after):
        return {"set": deepcopy(after)}
    if isinstance(after, dict):
        fields = {}
        for key, value in after.items():
            change = delta(before[key], value) if key in before else {"set": deepcopy(value)}
            if change:
                fields[key] = change
        out = {"fields": fields} if fields else {}
        removed = sorted(before.keys() - after.keys())
        if removed:
            out["remove"] = removed
        return out
    if isinstance(after, list):
        entries = {}
        for index, value in enumerate(after):
            change = (
                delta(before[index], value) if index < len(before) else {"set": deepcopy(value)}
            )
            if change:
                entries[str(index)] = change
        # Fully changed lists (UI rows, replaced menus) are smaller as a value.
        if after and len(entries) == len(after):
            return {"set": deepcopy(after)}
        out = {"entries": entries} if entries else {}
        if len(before) != len(after):
            out["length"] = len(after)
        return out
    return {} if before == after else {"set": after}


def apply_delta(before, change):
    """Apply to a copy, rejecting incompatible shapes before a native input."""
    if not isinstance(change, dict):
        raise DFHackError("Invalid execution delta")
    if "set" in change:
        if set(change) != {"set"}:
            raise DFHackError("Invalid execution replacement")
        return deepcopy(change["set"])
    result = deepcopy(before)
    if not change:
        return result
    if isinstance(before, dict) and not change.keys() - {"fields", "remove"}:
        for key in change.get("remove", []):
            if key not in result:
                raise DFHackError("Execution delta removes an absent field")
            del result[key]
        for key, patch in change.get("fields", {}).items():
            if key not in result and "set" not in patch:
                raise DFHackError("Execution delta patches an absent field")
            result[key] = apply_delta(result.get(key), patch)
        return result
    if isinstance(before, list) and not change.keys() - {"entries", "length"}:
        length = change.get("length", len(before))
        if type(length) is not int or length < 0:
            raise DFHackError("Invalid execution array length")
        entries = change.get("entries", {})
        for index in range(len(before), length):
            if "set" not in entries.get(str(index), {}):
                raise DFHackError("Execution delta leaves an unknown array entry")
        result = result[:length] + [None] * max(0, length - len(before))
        for key, patch in entries.items():
            if not key.isdecimal() or str(int(key)) != key or not 0 <= int(key) < length:
                raise DFHackError("Invalid execution array index")
            result[int(key)] = apply_delta(result[int(key)], patch)
        return result
    raise DFHackError("Execution delta does not match its base value")


def observation(response, previous, reference):
    """Reconstruct a native snapshot only against its exact acknowledged base."""
    if "view" in response:
        return response["view"], response.get("view_ref")
    patch = response.get("view_delta")
    if not patch or reference is None or patch.get("base") != reference:
        raise DFHackError("Execution observation base mismatch; no further input was sent")
    current = response.get("view_ref")
    if (
        not isinstance(current, dict)
        or current.get("dispatch_id") != reference.get("dispatch_id")
        or current.get("revision") != reference.get("revision", 0) + 1
    ):
        raise DFHackError("Invalid execution observation revision; no further input was sent")
    return apply_delta(previous, patch["change"]), current


class Checkpoint:
    def __init__(self, workflow, revision=None):
        self.value = deepcopy(workflow)
        self.revision = revision

    def request(self, workflow):
        if self.revision is None:
            return {"workflow": workflow}
        return {"workflow_delta": {"base": self.revision, "change": delta(self.value, workflow)}}

    def accepted(self, workflow, response):
        if self.revision is not None:
            if response.get("workflow_revision") != self.revision + 1:
                raise DFHackError(
                    "Checkpoint acknowledgement missing; submitted input was not retried"
                )
            self.revision += 1
        self.value = deepcopy(workflow)
