"""An MCP stdio server with interruptible action workers. stdout is JSON-RPC.

Implements the stable tools/lifecycle/stdio subset, without an HTTP listener.
Spec: https://modelcontextprotocol.io/specification/2025-11-25
"""

import json
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Lock

from .actions import ACTIONS, COORD, EXECUTION, SETTINGS, STRING, obj
from .metrics import Recorder
from .rpc import DispatchError


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
        "df_actions",
        "Read the compact action reference without contacting the game. Supply name for an action's exact schema and result semantics. Shared with CLI actions and Python Client.actions.",
        obj({"name": STRING}),
    ),
    tool(
        "df_dispatch_details",
        "Read saved events, prompts, steps or a full dispatch record without executing or replaying any action. Native session retention is 128 dispatches; unavailable/expired records are explicit.",
        obj(
            {
                "dispatch_id": STRING,
                "section": {"enum": ["events", "prompts", "steps", "summary", "full", "compact"]},
            },
            ("dispatch_id",),
        ),
    ),
    tool(
        "df_settings",
        "Read or save controller settings shared by CLI, Python and MCP. "
        "Saved settings apply on the next call; constructor and per-dispatch overrides take precedence. "
        "No game inputs. Supply update to persist execution policy, timeout or output preferences; reset starts from built-ins.",
        obj({"update": SETTINGS, "reset": {"type": "boolean"}}),
        False,
    ),
    tool(
        "df_brief",
        "Read a concise character projection: health, load/burden, movement, needs, skills and equipment. "
        "Skips omitted native profiles; coverage applies only to queried fields. "
        "df_status remains the comprehensive read-only report. Unknowns and truncation are preserved.",
        obj(),
    ),
    tool(
        "df_capabilities",
        "Read native dependency availability, execution adapter verification, action coverage and limits. "
        "New interface open flags are discovered at runtime. Presence of symbols does not prove future-version behavior. No game input.",
        obj(),
    ),
    tool(
        "df_unit",
        "Inspect one currently visible unit by ID: health, physical attributes, skills, equipment, body parts, "
        "affiliations and native opponent state. No hostility inference or threat rating; missing/truncated data are explicit.",
        obj({"unit_id": COORD, "view": {"enum": ["concise", "full"]}}, ("unit_id",)),
    ),
    tool(
        "df_navigation",
        "Read current travel coordinates, native site travel grid with legal direction masks, and character-known group/beast rumors sorted by distance. "
        "The controller chooses targets and assesses hostility/risk. No game inputs or world-map omniscience; rumor locations are leads, not verified current enemies.",
        obj({"limit": {"type": "integer", "minimum": 1, "maximum": 100}}),
    ),
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
        "Read an ASCII map, health, needs, burden, held items, visible creatures, native choices and recent reports with speaker/activity IDs. "
        "Coordinates are zero-based. Map origin + column/row gives local map coordinates. Routine output is concise; view=choices reads only current decisions. Undecoded decisions retain UI text.",
        obj(
            {
                "width": {"type": "integer", "minimum": 1, "maximum": 101},
                "height": {"type": "integer", "minimum": 1, "maximum": 61},
                "center": obj({"x": COORD, "y": COORD, "z": COORD}, ("x", "y", "z")),
                "map": {"type": "boolean"},
                "radius": {"type": "integer", "minimum": 0, "maximum": 50},
                "view": {"enum": ["concise", "full", "choices"]},
                "event_detail": {"enum": ["task", "all"]},
                "reports_after": {"type": "integer", "minimum": -1},
                "report_limit": {"type": "integer", "minimum": 1, "maximum": 4096},
            }
        ),
    ),
    tool(
        "df_act",
        "Execute a semantic objective or sequence under the controller's completion and interruption policy. "
        "The harness handles approach, native choices, prerequisites and delegated prompts. "
        "Use df_actions(name) for a focused schema and result contract. "
        "drop/stow remove worn items first; item results include load and contents integrity; strike results include target condition. "
        "Read values and said, then outcome/blocker/changes. Completion of a strike attempt does not imply a hit. "
        "Persist repeated policy with df_settings. Resume unfinished dispatches by ID; never blindly repeat an uncertain input. "
        "Raw inputs require development tools. Full traces are available through df_dispatch_details.",
        obj(
            {
                "action": {"oneOf": ACTIONS},
                "expect": STRING,
                "request_id": STRING,
                "execution": EXECUTION,
                "timeout": {"type": "number", "minimum": 0.1, "maximum": 300},
                "result_format": {"enum": ["compact", "full"]},
                "event_detail": {"enum": ["task", "all"]},
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


DEVELOPMENT_ACTIONS = {"key", "click", "click_text", "text", "select_unit"}
DEVELOPMENT_TOOLS = deepcopy(TOOLS)
TOOLS = [deepcopy(t) for t in TOOLS if t["name"] != "df_keys"]
for definition in TOOLS:
    properties = definition["inputSchema"]["properties"]
    if definition["name"] == "df_act":
        properties["action"]["oneOf"] = [
            a
            for a in properties["action"]["oneOf"]
            if a["properties"]["type"]["const"] not in DEVELOPMENT_ACTIONS
        ]
        properties["result_format"] = {"enum": ["compact"]}
    elif definition["name"] == "df_observe":
        properties["view"] = {"enum": ["concise", "choices"]}


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
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", float("inf")):
            raise ValueError(f"{path} has an invalid number of entries")
        for index, item in enumerate(value):
            validate(item, schema["items"], f"{path}[{index}]")


class Server:
    def __init__(self, client, development=False):
        self.client = client
        self.development = development
        self.tools = DEVELOPMENT_TOOLS if development else TOOLS
        self.initialized = False

    def handle(self, message, *, original=None, received_ns=None, emit=None):
        request = message if original is None else original
        method = request.get("method", "invalid") if isinstance(request, dict) else "invalid"
        params = request.get("params", {}) if isinstance(request, dict) else request
        operation = (
            params.get("name", method)
            if method == "tools/call" and isinstance(params, dict)
            else method
        )
        recorder = getattr(self.client, "metrics", None) or Recorder()
        with recorder.interaction("mcp", operation, params, started_ns=received_ns) as span:
            response = self._handle(message)
            if response is not None:
                result = response.get("result", {})
                if response.get("error") or result.get("isError"):
                    span.outcome = "error"
                    if response.get("error"):
                        span.fields["code"] = response["error"]["code"]
                content = result.get("content")
                if isinstance(content, list):
                    span.respond(
                        "\n".join(
                            block["text"] for block in content if block.get("type") == "text"
                        ),
                        text=True,
                    )
                    span.fields["output_format"] = "mcp_tool_text"
                else:
                    span.respond(response.get("error", result))
                    span.fields["output_format"] = "canonical_json"
            else:
                span.outcome = "notification"
            if emit is not None:
                emit(response)
            return response

    def _handle(self, message):
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
                "serverInfo": {"name": "df-llm", "version": "0.21.0"},
                "capabilities": {"tools": {"listChanged": False}},
                "instructions": "Observe the scene with df_observe. Use df_actions for the action reference and df_actions(name) for exact fields. "
                "The controller chooses targets, tactics and interruption predicates; the harness executes prerequisites and verifies results. "
                "Use sequence to compose actions under one policy and budget. Persist mode=complete and acknowledge with df_settings when desired. "
                "Read values and said first, then outcome, blocker and changes. Use resume by dispatch ID; never blindly repeat uncertain input. "
                "df_brief reads self, df_unit reads targets and body parts, df_item reads weapon attacks, df_status is comprehensive. "
                "df_capabilities reports runtime support. Full traces belong to df_dispatch_details. Raw input is development only.",
            }
        elif method == "ping":
            result = {}
        elif not self.initialized:
            return dict(response, error={"code": -32000, "message": "Initialize the server first"})
        elif method == "tools/list":
            result = {"tools": self.tools}
        elif method == "tools/call":
            definition = next((t for t in self.tools if t["name"] == params.get("name")), None)
            if not definition:
                return dict(response, error={"code": -32602, "message": "Unknown tool"})
            try:
                arguments = deepcopy(params.get("arguments", {}))
                validate(arguments, definition["inputSchema"])
                name = definition["name"]
                if not self.development:
                    if name == "df_observe":
                        arguments.setdefault("view", "concise")
                    elif name == "df_act":
                        arguments["result_format"] = "compact"
                if name == "df_keys":
                    value = self.client.request({"op": "keys", **arguments})
                else:
                    method_name = {
                        "df_settings": "settings",
                        "df_brief": "brief",
                        "df_actions": "actions",
                        "df_capabilities": "capabilities",
                        "df_unit": "unit",
                        "df_status": "status",
                        "df_navigation": "navigation",
                        "df_game_status": "game_status",
                        "df_character_status": "character_status",
                        "df_observe": "observe",
                        "df_act": "act",
                        "df_inspect": "inspect",
                        "df_wait_ready": "wait_ready",
                        "df_items": "items",
                        "df_item": "item",
                        "df_interrupt": "interrupt",
                        "df_dispatch_details": "dispatch_details",
                    }[name]
                    value = getattr(self.client, method_name)(**arguments)
                result = {
                    "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
                    "isError": False,
                }
            except Exception as exc:  # noqa: BLE001 -- the MCP boundary must return a tool error.
                error = str(exc)
                if isinstance(exc, DispatchError):
                    error = json.dumps(
                        {
                            "error": error,
                            "dispatch_id": exc.dispatch_id,
                            "resume_action": exc.resume_action,
                            "code": exc.code,
                            "input_sent": exc.input_sent,
                            "details": exc.details,
                        }
                    )
                result = {"content": [{"type": "text", "text": error}], "isError": True}
        else:
            return dict(response, error={"code": -32601, "message": "Method not found"})
        return dict(response, result=result)


def serve(client, source=None, target=None, development=False):
    source, target = source or sys.stdin, target or sys.stdout
    server = Server(client, development=development)
    output_lock, running_lock = Lock(), Lock()
    running = {}

    def write(response):
        if response is not None:
            with output_lock:
                target.write(json.dumps(response, ensure_ascii=False) + "\n")
                target.flush()

    def execute(message, original, received_ns):
        try:
            server.handle(message, original=original, received_ns=received_ns, emit=write)
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
            received_ns = time.perf_counter_ns()
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
                            except Exception as exc:  # noqa: BLE001 -- notifications cannot receive an error reply.
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
                    original = message
                    message = deepcopy(message)
                    arguments = message["params"].setdefault("arguments", {})
                    dispatch_id = arguments.setdefault("request_id", str(uuid.uuid4()))
                    with running_lock:
                        running[message["id"]] = dispatch_id
                    workers.submit(execute, message, original, received_ns)
                else:
                    server.handle(message, received_ns=received_ns, emit=write)
            except (ValueError, TypeError) as exc:
                write(
                    {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
                )
