"""Save an explicit checkpoint through native UI and verify the saved artifact."""

import re
from copy import deepcopy

from .workflows import close_menu, menu_signature, result


def validate_save(action):
    name = action.get("name")
    if (
        action.keys() - {"type", "name", "overwrite"}
        or not isinstance(name, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,39}", name)
        or name.casefold() in {"current", "autosave 1", "autosave 2", "autosave 3"}
    ):
        raise ValueError(
            "save_game.name must be 1..40 letters/digits/spaces/underscores/hyphens; native working/autosave folders are reserved"
        )
    if type(action.get("overwrite", False)) is not bool:
        raise ValueError("save_game.overwrite must be boolean")


def next_save(workflow, view):
    action, ctx = workflow["action"], workflow.setdefault("context", {})
    name = action["name"]
    file, menu = view.get("save_file") or {}, view.get("menu") or {}

    def blocked(kind, why, facts=None, outcome="needs_input"):
        return result(
            outcome, why, {"blocker_kind": kind, "facts": {"name": name, **(facts or {})}}
        )

    if file.get("available") is not True or file.get("name") != name:
        return blocked("save_verification", "Native save-file evidence is unavailable.", file)
    baseline = ctx.setdefault("baseline", deepcopy(file))
    if baseline.get("directory_exists") and not action.get("overwrite", False):
        return blocked(
            "save_exists", "The requested save folder exists; overwrite was not delegated."
        )
    if ctx.get("submitted"):
        changed = file.get("world_exists") is True and (
            baseline.get("world_exists") is False
            or file.get("world_mtime") != baseline.get("world_mtime")
        )
        if (
            changed
            and view["status"].get("save") == name
            and view["status"].get("ready_for_input")
            and menu.get("kind") != "options"
        ):
            return result(
                "completed",
                "Native quicksave finished and the requested world file was written.",
                {
                    "value": {
                        "kind": "save_game",
                        "name": name,
                        "world_file_written": True,
                        "world_mtime": file.get("world_mtime"),
                    }
                },
            )
        return blocked(
            "save_unverified",
            "The save has no verified completed file write; submission was not repeated.",
            file,
            "no_effect",
        )
    pending = ctx.get("closing")
    signature = [menu_signature(view), menu.get("mode"), view["status"].get("open_panels")]
    if pending == signature:
        return blocked(
            "save_no_effect",
            "The prerequisite interface did not close; input was not repeated.",
            outcome="no_effect",
        )
    if menu or view.get("conversation", {}).get("open") or view.get("combat", {}).get("open"):
        if menu.get("kind") == "options" and menu.get("mode") != "main":
            return blocked(
                "save_context",
                "An unfinished native options operation is active.",
                {"mode": menu.get("mode")},
            )
        decision = close_menu(view)
        ctx["closing"] = signature
        return decision
    if not view["status"].get("can_move"):
        return blocked("save_context", "Quicksave requires the loaded local adventure input view.")
    ctx["submitted"] = True
    return {
        "input": {"type": "save_native", "name": name, "overwrite": action.get("overwrite", False)}
    }
