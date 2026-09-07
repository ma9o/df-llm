"""Save an explicit checkpoint through native UI and verify the saved artifact."""

import re
from copy import deepcopy

from .selection import selection_input
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
    file = view.get("save_file") or {}
    menu = view.get("menu") or {}
    signature = [
        menu_signature(view),
        menu.get("mode"),
        menu.get("filename"),
        view["status"].get("open_panels"),
        bool(view.get("conversation", {}).get("open")),
        bool(view.get("combat", {}).get("open")),
    ]

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
    if ctx.get("submitted") and menu.get("kind") != "options":
        changed = file.get("world_exists") is True and (
            baseline.get("world_exists") is False
            or file.get("world_mtime") != baseline.get("world_mtime")
        )
        if changed and view["status"].get("save") == name and view["status"].get("ready_for_input"):
            return result(
                "completed",
                "Native save finished and the requested world file was written.",
                {
                    "name": name,
                    "world_mtime": file.get("world_mtime"),
                    "value": {
                        "kind": "save_game",
                        "name": name,
                        "world_file_written": True,
                        "world_mtime": file.get("world_mtime"),
                    },
                },
            )
        return blocked(
            "save_unverified",
            "The save has no verified completed file write; submission was not repeated.",
            file,
            "no_effect",
        )
    pending = ctx.pop("pending", None)
    if pending and pending["before"] == signature:
        return blocked(
            "save_no_effect",
            "The native save interface did not change; input was not repeated.",
            outcome="no_effect",
        )
    if pending and pending.get("editing") and menu.get("filename") != name:
        return blocked(
            "filename_mismatch",
            "Native filename entry did not reach the requested value.",
            {"actual": menu.get("filename")},
            "no_effect",
        )
    if menu.get("kind") == "options":
        if menu.get("selection_unavailable"):
            return blocked("save_binding", menu["selection_unavailable"])
        mode = menu.get("mode")
        if mode == "main":
            if ctx.get("submitted"):
                return blocked(
                    "save_unverified",
                    "The save returned to its menu without a verified file write.",
                    outcome="no_effect",
                )
            native = "SAVE_AND_CONTINUE"
        elif mode == "filename":
            if ctx.get("submitted"):
                return blocked(
                    "save_unverified",
                    "The game did not accept the submitted filename.",
                    outcome="no_effect",
                )
            if menu.get("filename") != name:
                return {
                    "input": {"type": "edit_text", "field": "save_name", "value": name},
                    "pending": {"before": signature, "editing": True},
                }
            native = "SUBMIT_FILENAME"
        elif mode == "overwrite":
            if menu.get("filename") != name or not action.get("overwrite", False):
                return blocked(
                    "save_exists",
                    "The game requires an undelegated overwrite choice.",
                    {"filename": menu.get("filename")},
                )
            if ctx.get("overwrite_sent"):
                return blocked(
                    "save_no_effect",
                    "The overwrite confirmation did not take effect.",
                    outcome="no_effect",
                )
            native = "OVERWRITE"
        else:
            return blocked(
                "save_mode", "The native save phase is not ready for another input.", {"mode": mode}
            )
        matches = [o for o in menu.get("options", []) if o.get("native_type") == native]
        if len(matches) != 1:
            return blocked(
                "save_choice", "The requested native save option is absent or ambiguous."
            )
        selected = selection_input(menu, matches[0], "select_option")
        if "outcome" in selected:
            return selected
        if native == "SUBMIT_FILENAME":
            ctx["submitted"] = True
        elif native == "OVERWRITE":
            ctx["submitted"] = True
            ctx["overwrite_sent"] = True
        return {"input": selected, "pending": {"before": signature}}
    if menu or view.get("conversation", {}).get("open") or view.get("combat", {}).get("open"):
        decision = close_menu(view)
        decision["pending"]["before"] = signature
        return decision
    if not view["status"].get("can_move"):
        return blocked("save_context", "Saving requires a loaded local adventure input view.")
    return {"input": {"type": "key", "key": "OPTIONS"}, "pending": {"before": signature}}
