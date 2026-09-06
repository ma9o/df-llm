"""An MCP stdio server with interruptible action workers. stdout is JSON-RPC.

Implements the stable tools/lifecycle/stdio subset, without an HTTP listener.
Spec: https://modelcontextprotocol.io/specification/2025-11-25
"""

import json
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Lock

from .rpc import DispatchError


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
        "visible_unit_ids": {"type": "array", "items": COORD, "maxItems": 100},
        "report_types": {"type": "array", "items": STRING, "maxItems": 100},
    }
)
EXECUTION = obj(
    {
        "mode": {"enum": ["step", "complete"]},
        "acknowledge": {"type": "boolean"},
        "max_steps": {"type": "integer", "minimum": 1, "maximum": 64},
        "interrupt_on": INTERRUPT,
    }
)
ACTIONS = [
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
            "allow_occupied": {"type": "boolean"},
            "max_liquid_depth": {"type": "integer", "minimum": 0, "maximum": 7},
            "blocked_tiles": {"type": "array", "items": POSITION, "maxItems": 500},
        },
        ("type", "x", "y", "z"),
    ),
]


def tool(name, description, schema, read_only=True):
    return {
        "name": name,
        "description": description,
        "inputSchema": schema,
        "annotations": {
            "readOnlyHint": read_only,
            "destructiveHint": not read_only,
            "openWorldHint": False,
        },
    }


TOOLS = [
    tool(
        "df_status",
        "Read the complete supported character report and current game/input status, including health, physiology, "
        "carrying capacity, native burden state (including Overburdened), load penalty, calculated movement speed, native hunger/thirst/sleep warning stages, "
        "skills, personality, appearance, relationships, companions, knowledge, abilities, combat, possessions, "
        "reputation and obligations. Same report as df_character_status. Missing and truncated data are explicit. "
        "Use df_game_status for lightweight readiness checks. No game input or time advancement.",
        obj(),
    ),
    tool(
        "df_game_status",
        "Read only game mode, focus, detected modal, player position, active dispatch and adventure input readiness.",
        obj(),
    ),
    tool(
        "df_character_status",
        "Read the current adventurer's comprehensive character sheet without sending input or advancing game time. "
        "Returns identity, age, affiliations, health counters and condition flags, named body parts, wounds and active syndromes, "
        "physical/mental attributes, skill ratings and effective levels, physical and psychological needs, focus/stress, "
        "personality traits, values, goals, recent emotions, equipment and nested inventory, encumbrance (carried kilograms, "
        "weight by inventory mode and heaviest items), carrying capacity, native burden state/thresholds, isolated load penalty, calculated current and unloaded "
        "movement speed, displayed HUD speed when readable, gait parameters, and current action types. "
        "Native need severity labels include counters, next stages, and creature exemptions. Calculations are build-scoped "
        "and unavailable when not verified. Native warning stages do not choose risk or dispatch policy for the controller. "
        "Unavailable fields and bounded-list truncation are explicit. Returns available=false when there is no active adventurer. "
        "Also includes appearance, preferences, memories, relationships, companions, affiliations/reputation, knowledge, "
        "abilities/cooldowns, combat state, possessions/wealth/debts, and current obligations. Includes explicit section coverage. "
        "Includes a state_id guard and current game/input status, without repeating the map or report history.",
        obj(),
    ),
    tool(
        "df_observe",
        "Read UI text, an ASCII map, health/inventory, visible creatures, full conversation labels, and recent reports with speaker/activity IDs. "
        "Coordinates are zero-based. Map origin + column/row gives world coordinates; UI clicks use separate UI cells.",
        obj(
            {
                "width": {"type": "integer", "minimum": 1, "maximum": 101},
                "height": {"type": "integer", "minimum": 1, "maximum": 61},
                "center": obj({"x": COORD, "y": COORD, "z": COORD}, ("x", "y", "z")),
                "map": {"type": "boolean"},
                "radius": {"type": "integer", "minimum": 0, "maximum": 50},
            }
        ),
    ),
    tool(
        "df_act",
        "Dispatch a game action under the controller's execution policy and return its outcome, steps, events, and observation. "
        "execution.mode=complete executes the entire requested workflow; step executes one mechanical step plus delegated acknowledgements. "
        "execution.acknowledge=true delegates help/More/Okay pages. Settings apply to every action; no risk classification is inferred. "
        "pickup/equip/wield/remove/drop/stow accept item IDs and verify inventory postconditions. "
        "equip/wield replace only explicitly supplied IDs; disposition is hold (default), drop, or stow into container_id. "
        "walk_to routes within the observed local z-level; allow_occupied, max_liquid_depth, and blocked_tiles are caller constraints. "
        "No threats or equipment upgrades are selected by the harness. interrupt_on evaluates only caller-specified factual conditions. "
        "resume with dispatch_id continues the saved recipe, including after interruption or a limit, without restarting it. "
        "move is one adventure step; wait is a short in-game wait; key uses exact interface_key names. "
        "dismiss acknowledges one detected help/announcement page; inspect status.modal afterward. "
        "click_text clicks a unique visible label. select_unit clicks a visible unit by ID only in the conversation creature picker. "
        "text types printable ASCII, not Enter. "
        "Use expect=last state_id to reject stale observations. request_id deduplicates the last 128 dispatches. "
        "max_steps counts actual game inputs, including automatic responses. Compact changes/events are the default; request result_format=full for the full observation. "
        "Read dispatch.outcome: semantic completion verifies the requested postconditions. "
        "A timeout does not mean the action failed; observe or resume before retrying.",
        obj(
            {
                "action": {"oneOf": ACTIONS},
                "expect": STRING,
                "request_id": STRING,
                "execution": EXECUTION,
                "timeout": {"type": "number", "minimum": 0.1, "maximum": 300},
                "result_format": {"enum": ["compact", "full"]},
            },
            ("action",),
        ),
        False,
    ),
    tool(
        "df_items",
        "Read nearby visible ground items and nested container contents in one call, including material, quality, raw mass, wear, armor coverage and weapon definitions.",
        obj({"radius": {"type": "integer", "minimum": 0, "maximum": 50}}),
    ),
    tool(
        "df_item",
        "Inspect one item carried by the adventurer or on visible ground, including its container, inventory role and properties. Fit is checked by the game's wear menu; maker species alone does not establish fit.",
        obj({"item_id": COORD}, ("item_id",)),
    ),
    tool(
        "df_interrupt",
        "Interrupt a dispatch by its request_id. It stops further harness inputs and preserves the recipe for explicit resume; already submitted native actions are not undone. Can run while df_act is executing. df_game_status exposes the active dispatch ID and progress.",
        obj({"dispatch_id": STRING}, ("dispatch_id",)),
        False,
    ),
    tool(
        "df_inspect",
        "Read a visible world tile, terrain, liquid depth, ground items, and creatures on it.",
        obj({"x": COORD, "y": COORD, "z": COORD}, ("x", "y", "z")),
    ),
    tool(
        "df_keys",
        "List valid interface_key names from the running game, filtered by substring (e.g. A_INV, A_TALK, SELECT).",
        obj({"filter": STRING}),
    ),
    tool(
        "df_wait_ready",
        "Wait for an already submitted action/turn to finish. Does not advance game time or send inputs.",
        obj({"action_id": STRING, "timeout": {"type": "number", "minimum": 0.1, "maximum": 60}}),
    ),
]


def validate(value, schema, path="arguments"):
    """Validate just the JSON Schema vocabulary used by our tool definitions."""
    if "oneOf" in schema:
        matches = 0
        for option in schema["oneOf"]:
            try:
                validate(value, option, path)
                matches += 1
            except ValueError:
                pass
        if matches != 1:
            raise ValueError(f"{path} must match exactly one supported action schema")
    if "const" in schema and value != schema["const"]:
        raise ValueError(f"{path} must be {schema['const']}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} must be one of {schema['enum']}")
    kind = schema.get("type")
    valid = {
        "object": isinstance(value, dict),
        "string": isinstance(value, str),
        "integer": type(value) is int,
        "number": type(value) in (int, float),
        "boolean": type(value) is bool,
        "array": isinstance(value, list),
    }
    if kind and not valid.get(kind, False):
        raise ValueError(f"{path} must be a {kind}")
    if kind == "object":
        properties = schema["properties"]
        for key in schema.get("required", []):
            if key not in value:
                raise ValueError(f"Missing {path}.{key}")
        for key, item in value.items():
            if key not in properties:
                raise ValueError(f"Unknown {path}.{key}")
            validate(item, properties[key], f"{path}.{key}")
    if kind in ("integer", "number") and not schema.get(
        "minimum", float("-inf")
    ) <= value <= schema.get("maximum", float("inf")):
        raise ValueError(f"{path} is outside its allowed range")
    if kind == "string" and not schema.get("minLength", 0) <= len(value) <= schema.get(
        "maxLength", float("inf")
    ):
        raise ValueError(f"{path} has an invalid length")
    if kind == "array":
        if len(value) > schema.get("maxItems", float("inf")):
            raise ValueError(f"{path} has too many entries")
        for index, item in enumerate(value):
            validate(item, schema["items"], f"{path}[{index}]")


class Server:
    def __init__(self, client):
        self.client = client
        self.initialized = False

    def handle(self, message):
        if (
            not isinstance(message, dict)
            or message.get("jsonrpc") != "2.0"
            or not isinstance(message.get("method"), str)
        ):
            return {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "Invalid JSON-RPC request"},
            }
        if "id" not in message:
            return None  # Notifications (including initialized/cancelled) never receive replies.
        response = {"jsonrpc": "2.0", "id": message["id"]}
        method, params = message["method"], message.get("params", {})
        if not isinstance(params, dict):
            return dict(response, error={"code": -32602, "message": "params must be an object"})
        if method == "initialize":
            self.initialized = True
            version = params.get("protocolVersion")
            if version not in ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"):
                version = "2025-11-25"
            result = {
                "protocolVersion": version,
                "serverInfo": {"name": "df-llm", "version": "0.6.1"},
                "capabilities": {"tools": {"listChanged": False}},
                "instructions": "Observe first. Send one action at a time and inspect its resulting observation. "
                "Use named interface keys or unique text labels to navigate menus. "
                "The controller chooses objectives, equipment, replacements, disposition, and threat/interruption policy. "
                "Choose execution.mode=complete to delegate the entire action workflow; use step for incremental supervision. "
                "Use dispatch.resume_action to continue an unfinished recipe. df_interrupt can stop an executing dispatch. "
                "Use df_items and df_item to compare items, then dispatch pickup/equip/wield/drop/stow by ID. "
                "Use df_status (alias df_character_status) for the comprehensive character report; df_game_status is a lightweight readiness check. "
                "Choose execution.acknowledge=true to automate help/announcement acknowledgements. "
                "Read dispatch.outcome and its preserved events/prompts. Unknown choices return to you. "
                "select_unit targets a creature only in the conversation picker. "
                "Match report speaker_id and activity_id to identify direct replies. "
                "The ASCII map is a semantic terrain view; inventory and tile inspection provide details. "
                "Coordinate systems for UI clicks and world tiles are different. "
                "Do not automatically repeat an action after a timeout.",
            }
        elif method == "ping":
            result = {}
        elif not self.initialized:
            return dict(response, error={"code": -32000, "message": "Initialize the server first"})
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            definition = next((t for t in TOOLS if t["name"] == params.get("name")), None)
            if not definition:
                return dict(response, error={"code": -32602, "message": "Unknown tool"})
            try:
                arguments = params.get("arguments", {})
                validate(arguments, definition["inputSchema"])
                name = definition["name"]
                if name == "df_keys":
                    value = self.client.request({"op": "keys", **arguments})
                else:
                    method_name = {
                        "df_status": "status",
                        "df_game_status": "game_status",
                        "df_character_status": "character_status",
                        "df_observe": "observe",
                        "df_act": "act",
                        "df_inspect": "inspect",
                        "df_wait_ready": "wait_ready",
                        "df_items": "items",
                        "df_item": "item",
                        "df_interrupt": "interrupt",
                    }[name]
                    value = getattr(self.client, method_name)(**arguments)
                result = {
                    "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
                    "isError": False,
                }
            # A tool boundary must convert every application failure into an MCP result.
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
                if isinstance(exc, DispatchError):
                    error = json.dumps(
                        {
                            "error": error,
                            "dispatch_id": exc.dispatch_id,
                            "resume_action": exc.resume_action,
                        }
                    )
                result = {"content": [{"type": "text", "text": error}], "isError": True}
        else:
            return dict(response, error={"code": -32601, "message": "Method not found"})
        return dict(response, result=result)


def serve(client, source=None, target=None):
    source, target = source or sys.stdin, target or sys.stdout
    server = Server(client)
    output_lock, running_lock = Lock(), Lock()
    running = {}

    def write(response):
        if response is not None:
            with output_lock:
                target.write(json.dumps(response, ensure_ascii=False) + "\n")
                target.flush()

    def execute(message):
        try:
            write(server.handle(message))
        finally:
            with running_lock:
                running.pop(message["id"], None)

    # Game input is serialized by the bridge's active-dispatch lease. Workers
    # keep the stdio reader responsive to observation and interruption requests.
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="df-dispatch") as workers:
        while True:
            line = source.readline(1024 * 1024 + 1)
            if not line:
                return
            try:
                if len(line) > 1024 * 1024:
                    while line and not line.endswith("\n"):
                        line = source.readline(1024 * 1024)
                    raise ValueError("Request exceeds 1 MiB")
                message = json.loads(line)
                if isinstance(message, dict) and message.get("method") == "notifications/cancelled":
                    params = message.get("params", {})
                    cancelled_id = params.get("requestId") if isinstance(params, dict) else None
                    if type(cancelled_id) in (str, int):
                        with running_lock:
                            dispatch_id = running.get(cancelled_id)
                        if dispatch_id:
                            try:
                                client.interrupt(dispatch_id)
                            except Exception as exc:  # noqa: BLE001
                                # Notifications cannot receive a JSON-RPC error
                                # reply. Report the failure without losing the reader.
                                print(
                                    f"df-llm: cancellation could not interrupt {dispatch_id}: {exc}",
                                    file=sys.stderr,
                                )
                    continue
                params = message.get("params", {}) if isinstance(message, dict) else {}
                if (
                    isinstance(message, dict)
                    and message.get("method") == "tools/call"
                    and isinstance(params, dict)
                    and params.get("name") == "df_act"
                    and type(message.get("id")) in (str, int)
                    and isinstance(params.get("arguments", {}), dict)
                ):
                    message = deepcopy(message)
                    arguments = message["params"].setdefault("arguments", {})
                    dispatch_id = arguments.setdefault("request_id", str(uuid.uuid4()))
                    with running_lock:
                        running[message["id"]] = dispatch_id
                    workers.submit(execute, message)
                else:
                    write(server.handle(message))
            except (ValueError, TypeError) as exc:
                write(
                    {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
                )
