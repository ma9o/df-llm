"""Shared action schemas and a local, compact controller reference."""

from copy import deepcopy

from .policy import MAX_DISPATCH_INPUTS, MAX_WATCHED_UNITS, UNIT_HEALTH_FLAGS
from .workflows import SEMANTIC

ACTION_HELP = {
    "drop": "Drop the specified item, removing it first if worn. Container contents stay inside. Returns location, contents integrity, cached load and burden from unit state.",
    "stow": "Place the item in container_id, removing it first if worn. Returns destination, contents integrity, cached load and burden from unit state.",
    "equip": "Wear item_id; only replace listed item IDs and apply the requested disposition. Returns equipment location and resulting load.",
    "wield": "Hold item_id as a weapon; replacements and their disposition must be explicit. Returns equipment location and resulting load.",
    "pickup": "Approach and acquire item_id with its contents. Returns location, contents integrity and resulting load.",
    "remove": "Remove item_id into a hand. Returns location and resulting load; does not select other equipment to discard.",
    "strike": "Attempt one aimed melee strike using the chosen body_part_id, item_id, attack_index and style. Native attempt/recovery verification is separate from damage. Returns target condition. Obtain body-part IDs with unit; weapon attack indices with item.",
    "combat": "Open the target's native combat choices. This is discovery/navigation; use strike to execute a complete aimed attack.",
    "sequence": "Execute explicit semantic actions in order under one completion policy, interruption policy and budget. Resume preserves completed stages. Item prerequisites are handled inside their stages.",
    "converse": "Visit explicit unit_ids, ask explicit topics and collect replies. A topic may include tact and subject_hf_id. Return only when completed or an undelegated choice is needed.",
    "save_game": "Save and continue under the specified name. Verifies the named world.sav was written and the game is ready again. Existing folders require overwrite=true; current and native autosave names are reserved.",
}


def obj(properties=None, required=()):
    return {
        "type": "object",
        "properties": properties or {},
        "required": list(required),
        "additionalProperties": False,
    }


STRING = {"type": "string"}
COORD = {"type": "integer", "minimum": 0}
POSITION = obj({"x": COORD, "y": COORD, "z": COORD}, ("x", "y", "z"))
INTERRUPT = obj(
    {
        "blood_loss": {"type": "boolean"},
        "new_wounds": {"type": "boolean"},
        "new_visible_units": {"type": "boolean"},
        "new_visible_units_except": {"type": "array", "items": COORD, "maxItems": 100},
        "visible_unit_ids": {"type": "array", "items": COORD, "maxItems": 100},
        "report_types": {"type": "array", "items": STRING, "maxItems": 100},
        "unit_health": {
            "type": "array",
            "maxItems": MAX_WATCHED_UNITS,
            "items": obj(
                {"unit_id": COORD, **{flag: {"type": "boolean"} for flag in UNIT_HEALTH_FLAGS}},
                ("unit_id",),
            ),
        },
    }
)
EXECUTION = obj(
    {
        "mode": {"enum": ["step", "complete"]},
        "acknowledge": {"type": "boolean"},
        "max_steps": {"type": "integer", "minimum": 1, "maximum": MAX_DISPATCH_INPUTS},
        "interrupt_on": INTERRUPT,
    }
)
ROUTE = {
    "extend_route": {"type": "boolean"},
    "allow_occupied": {"type": "boolean"},
    "max_liquid_depth": {"type": "integer", "minimum": 0, "maximum": 7},
    "blocked_tiles": {"type": "array", "items": POSITION, "maxItems": 500},
}
SETTINGS = obj(
    {
        "execution": EXECUTION,
        "dispatch_timeout": {"type": "number", "minimum": 0.1, "maximum": 300},
        "result_format": {"enum": ["compact", "full"]},
        "event_detail": {"enum": ["task", "all"]},
        "observation_view": {"enum": ["concise", "full"]},
        "measurement": obj(
            {
                "enabled": {"type": "boolean"},
                "path": {"type": ["string", "null"]},
                "run": {"type": "string", "minLength": 1, "maxLength": 128},
                "episode": {"type": ["string", "null"], "minLength": 1, "maxLength": 128},
                "tokenizer": {"type": "string", "minLength": 1, "maxLength": 128},
            }
        ),
    }
)
ACTIONS = [
    *[
        obj(
            {"type": {"const": name}, "hours": {"type": "integer", "minimum": 1, "maximum": 24}},
            ("type", "hours"),
        )
        for name in ("sleep", "rest")
    ],
    *[
        obj({"type": {"const": name}, "until": {"const": "dawn"}}, ("type", "until"))
        for name in ("sleep", "rest")
    ],
    obj(
        {
            "type": {"const": "drink"},
            "container_id": COORD,
            "portions": {"type": "integer", "minimum": 1, "maximum": 32},
        },
        ("type", "container_id"),
    ),
    obj(
        {
            "type": {"const": "drink_from"},
            "x": COORD,
            "y": COORD,
            "z": COORD,
            "material": STRING,
            "portions": {"type": "integer", "minimum": 1, "maximum": 32},
            **ROUTE,
        },
        ("type", "x", "y", "z", "material"),
    ),
    obj(
        {
            "type": {"const": "eat"},
            "item_id": COORD,
            "portions": {"type": "integer", "minimum": 1, "maximum": 32},
        },
        ("type", "item_id"),
    ),
    obj(
        {
            "type": {"const": "drink"},
            "item_id": COORD,
            "portions": {"type": "integer", "minimum": 1, "maximum": 32},
        },
        ("type", "item_id"),
    ),
    obj(
        {
            "type": {"const": "talk"},
            "unit_id": COORD,
            "topic": STRING,
            "tact": STRING,
            "choice_id": STRING,
            "subject_hf_id": COORD,
            "completion": {"enum": ["utterance", "reply"]},
            **ROUTE,
        },
        ("type", "unit_id"),
    ),
    obj({"type": {"const": "end_conversation"}}, ("type",)),
    obj({"type": {"const": "empty_container"}, "container_id": COORD}, ("type", "container_id")),
    obj(
        {
            "type": {"const": "save_game"},
            "name": {"type": "string", "minLength": 1, "maxLength": 40},
            "overwrite": {"type": "boolean"},
        },
        ("type", "name"),
    ),
    obj({"type": {"const": "end_travel"}}, ("type",)),
    obj(
        {
            "type": {"const": "thaw"},
            "container_id": COORD,
            "x": COORD,
            "y": COORD,
            "z": COORD,
            **ROUTE,
        },
        ("type", "container_id", "x", "y", "z"),
    ),
    obj(
        {"type": {"const": "make_campfire"}, "x": COORD, "y": COORD, "z": COORD, **ROUTE},
        ("type", "x", "y", "z"),
    ),
    obj(
        {
            "type": {"const": "fill_container"},
            "container_id": COORD,
            "x": COORD,
            "y": COORD,
            "z": COORD,
            "material": STRING,
            "source_state": STRING,
            **ROUTE,
        },
        ("type", "container_id", "x", "y", "z", "material"),
    ),
    obj(
        {"type": {"const": "combat"}, "unit_id": COORD, "option_id": STRING, **ROUTE},
        ("type", "unit_id"),
    ),
    obj(
        {
            "type": {"const": "strike"},
            "unit_id": COORD,
            "body_part_id": COORD,
            "item_id": {"type": "integer", "minimum": -1, "maximum": 2147483647},
            "attack_index": COORD,
            "style": {"enum": ["normal", "quick", "heavy", "wild", "precise"]},
            **ROUTE,
        },
        ("type", "unit_id", "body_part_id", "item_id", "attack_index", "style"),
    ),
    obj(
        {
            "type": {"const": "use_stairs"},
            "x": COORD,
            "y": COORD,
            "z": COORD,
            "direction": {"enum": ["up", "down"]},
            **ROUTE,
        },
        ("type", "x", "y", "z", "direction"),
    ),
    obj({"type": {"const": "select_interaction"}, "option_id": STRING}, ("type", "option_id")),
    obj(
        {"type": {"const": "set_posture"}, "posture": {"enum": ["standing", "prone"]}},
        ("type", "posture"),
    ),
    obj({"type": {"const": "set_gait"}, "gait": STRING}, ("type", "gait")),
    obj({"type": {"const": "set_sneaking"}, "enabled": {"type": "boolean"}}, ("type", "enabled")),
    obj(
        {
            "type": {"const": "travel_to"},
            "x": COORD,
            "y": COORD,
            "arrival_radius": {"type": "integer", "minimum": 0, "maximum": 48},
        },
        ("type", "x", "y"),
    ),
    obj(
        {
            "type": {"const": "move"},
            "direction": {"enum": ["n", "s", "e", "w", "ne", "nw", "se", "sw", "up", "down"]},
        },
        ("type", "direction"),
    ),
    obj({"type": {"const": "wait"}}, ("type",)),
    obj({"type": {"const": "dismiss"}}, ("type",)),
    obj({"type": {"const": "resume"}, "dispatch_id": STRING}, ("type",)),
    obj({"type": {"const": "select_option"}, "option_id": STRING}, ("type", "option_id")),
    obj(
        {"type": {"const": "action_prompt"}, "choice": {"enum": ["continue", "stop", "finish"]}},
        ("type", "choice"),
    ),
    obj({"type": {"const": "key"}, "key": STRING}, ("type", "key")),
    obj({"type": {"const": "select_unit"}, "unit_id": COORD}, ("type", "unit_id")),
    obj(
        {
            "type": {"const": "click"},
            "x": COORD,
            "y": COORD,
            "button": {"enum": ["left", "right", "middle"]},
        },
        ("type", "x", "y"),
    ),
    obj({"type": {"const": "click_text"}, "text": STRING}, ("type", "text")),
    obj(
        {"type": {"const": "text"}, "text": {"type": "string", "minLength": 1, "maxLength": 200}},
        ("type", "text"),
    ),
]
for name in ("pickup", "remove", "drop"):
    ACTIONS.append(obj({"type": {"const": name}, "item_id": COORD}, ("type", "item_id")))
for name in ("equip", "wield"):
    ACTIONS.append(
        obj(
            {
                "type": {"const": name},
                "item_id": COORD,
                "replace": {"type": "array", "items": COORD, "maxItems": 16},
                "disposition": {"enum": ["hold", "drop", "stow"]},
                "container_id": COORD,
                "body_part_id": COORD,
            },
            ("type", "item_id"),
        )
    )
ACTIONS += [
    obj(
        {"type": {"const": "stow"}, "item_id": COORD, "container_id": COORD},
        ("type", "item_id", "container_id"),
    ),
    obj(
        {
            "type": {"const": "walk_to"},
            "x": COORD,
            "y": COORD,
            "z": COORD,
            "arrival_radius": {"type": "integer", "minimum": 0, "maximum": 48},
            **ROUTE,
        },
        ("type", "x", "y", "z"),
    ),
]
ACTIONS.append(
    obj(
        {
            "type": {"const": "converse"},
            "unit_ids": {"type": "array", "items": COORD, "minItems": 1, "maxItems": 32},
            "topics": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "items": {
                    "anyOf": [
                        STRING,
                        obj({"topic": STRING, "tact": STRING, "subject_hf_id": COORD}, ("topic",)),
                    ]
                },
            },
            **ROUTE,
        },
        ("type", "unit_ids", "topics"),
    )
)


# Deliberately flat: semantic stages (including converse), no nested sequences
# or raw input batches that could masquerade as a verified gameplay objective.
ACTIONS.append(
    obj(
        {
            "type": {"const": "sequence"},
            "actions": {
                "type": "array",
                "minItems": 1,
                "maxItems": 64,
                "items": {
                    "oneOf": [a for a in ACTIONS if a["properties"]["type"]["const"] in SEMANTIC]
                },
            },
        },
        ("type", "actions"),
    )
)

# Action-specific semantics travel with the same schemas used by MCP.
for definition in ACTIONS:
    if note := ACTION_HELP.get(definition["properties"]["type"]["const"]):
        definition["description"] = note


def action_reference(name=None):
    """No game connection or separate copy of the action field schema."""
    allowed = SEMANTIC | {"resume", "wait", "move", "select_option", "select_interaction"}
    selected = [a for a in ACTIONS if a["properties"]["type"]["const"] in allowed]
    if name is not None:
        variants = [a for a in selected if a["properties"]["type"]["const"] == name]
        if not variants:
            raise ValueError("Unknown controller action: " + name)
        return {
            "action": name,
            "description": ACTION_HELP.get(name, "See schema and runtime capabilities."),
            "schema": {"oneOf": deepcopy(variants)},
            "execution": "Use saved settings or override mode=complete/step, acknowledge and interrupt_on. Availability: capabilities.",
        }
    rows = []
    for action in selected:
        properties = action["properties"]
        name = properties["type"]["const"]
        required = [k for k in action["required"] if k != "type"]
        optional = [k for k in properties if k not in action["required"]]
        rows.append(
            {"action": name, "required": required, **({"optional": optional} if optional else {})}
        )
    return {
        "format": "action_reference",
        "actions": rows,
        "usage": "act accepts one action or sequence. actions NAME returns its exact schema. Routine play needs no source reads.",
        "queries": "look: scene; brief: self; unit ID: target/body parts; item ID: weapon attacks; status: comprehensive character; capabilities: runtime support",
        "policy": "Persist mode=complete and acknowledge with settings; supply interruption conditions. Controller selects targets and tactics; harness executes prerequisites.",
        "receipts": "Read values and said first, then outcome, blocker and changes. Resume unfinished dispatches by ID; never blindly repeat an uncertain input.",
    }
