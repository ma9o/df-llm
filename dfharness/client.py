"""Structured observations and controller-directed dispatches through DFHack."""

import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from .config import port_for_game
from .dispatch import execution_policy, run_dispatch
from .rpc import DFHackError, DispatchError, run_command

ASSETS = Path(__file__).parent
MARKER = "__DFLLM_JSON__"


def lua_string(value):
    """A Lua literal that cannot be escaped by JSON strings or source code."""
    # Quoted JSON is not a Lua literal (notably \uXXXX escapes). Long brackets
    # are literal; the added newline prevents Lua stripping one from the input.
    equals = ""
    while "]" + equals + "]" in value:
        equals += "="
    return "[" + equals + "[\n" + value + "]" + equals + "]"


def make_program(request):
    request_json = json.dumps(request, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    character_reader = (
        "assert(load(" + lua_string((ASSETS / "character.lua").read_text()) + "))"
        if request.get("op") == "character_status"
        else "nil"
    )
    character_details = (
        "assert(load(" + lua_string((ASSETS / "character_details.lua").read_text()) + "))"
        if request.get("op") == "character_status"
        else "nil"
    )
    character_calculations = (
        "assert(load(" + lua_string((ASSETS / "character_calculations.lua").read_text()) + "))()"
        if request.get("op") == "character_status"
        else "nil"
    )
    return (
        "local glyph=assert(load(" + lua_string((ASSETS / "cp437.lua").read_text()) + "))();"
        "local request=require('json.internal'):new{strictTypes=true}:decode("
        + lua_string(request_json)
        + ");"
        "local result=assert(load("
        + lua_string((ASSETS / "bridge.lua").read_text())
        + "))(request,glyph,"
        + character_reader
        + ","
        + character_details
        + ","
        + character_calculations
        + ");"
        "print('" + MARKER + "'..require('json').encode(result,{pretty=false}))"
    )


class Client:
    def __init__(self, port=None, timeout=10.0, log_path=None, execution=None):
        self.port = port_for_game(port)
        self.timeout = timeout
        self.log_path = Path(log_path) if log_path else None
        self.log_lock = Lock()
        self.execution = execution_policy(execution)

    def request(self, request):
        started = time.monotonic()
        output = run_command("lua", make_program(request), port=self.port, timeout=self.timeout)
        lines = [line[len(MARKER) :] for line in output.splitlines() if line.startswith(MARKER)]
        if len(lines) != 1:
            raise DFHackError("DFHack returned no unique structured response: " + output[-2000:])
        envelope = json.loads(lines[0])
        if self.log_path and request.get("op") != "poll":
            with self.log_lock:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.log_path.open("a", encoding="utf-8") as log:
                    log.write(
                        json.dumps(
                            {
                                "at": datetime.now(UTC).isoformat(),
                                "request": request,
                                "response": envelope,
                                "elapsed_ms": round((time.monotonic() - started) * 1000),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
        if not envelope.get("ok"):
            raise DFHackError(envelope.get("error", "Unknown DFHack bridge error"))
        return envelope["result"]

    def status(self):
        return self.character_status()

    def game_status(self):
        return self.request({"op": "status"})

    def character_status(self):
        return self.request({"op": "character_status"})

    def observe(self, width=41, height=21, center=None, map=True, radius=20):
        request = {"op": "observe", "width": width, "height": height, "map": map}
        request["radius"] = radius
        if center is not None:
            request["center"] = center
        return self.request(request)

    def wait_ready(self, action_id=None, timeout=30):
        deadline = time.monotonic() + timeout
        while True:
            request = {"op": "poll"}
            if action_id:
                request["action_id"] = action_id
            state = self.request(request)
            if state.get("action_error"):
                raise DFHackError("Action may have partially executed: " + state["action_error"])
            if state["ready"]:
                return state
            if time.monotonic() >= deadline:
                raise DFHackError(
                    f"Timed out waiting for game input readiness (action {action_id}). "
                    "The action was not retried. Use wait-ready or observe. "
                    f"Current focus: {state['status']['focus']}; phase: {state['status'].get('turn_phase')}"
                )
            time.sleep(0.05)

    def act(
        self,
        action,
        expect=None,
        request_id=None,
        timeout=30,
        execution=None,
        result_format="compact",
    ):
        request_id = request_id or str(uuid.uuid4())
        try:
            return run_dispatch(self, action, expect, request_id, timeout, execution, result_format)
        except DFHackError as exc:
            raise DispatchError(request_id, exc) from exc

    def items(self, radius=20):
        return self.request({"op": "items", "radius": radius})

    def item(self, item_id):
        return self.request({"op": "item", "item_id": item_id})

    def interrupt(self, dispatch_id):
        return self.request({"op": "interrupt", "dispatch_id": dispatch_id})

    def inspect(self, x, y, z):
        return self.request({"op": "inspect", "x": x, "y": y, "z": z})


def render_observation(observation):
    if observation.get("format") == "character_status":
        return render_character_status(observation)
    s = observation["status"]
    lines = [
        f"# {s['df_version']} | DFHack {s['dfhack_version']} | {s['mode']}",
        f"# Focus: {', '.join(s['focus'])} | ready={s['ready_for_input']} | phase={s.get('turn_phase', '-')}",
        f"# State: {observation['state_id']}",
    ]
    if "adventurer" in observation:
        player = observation["adventurer"]
        if player:
            lines.append(
                f"# Adventurer: {player['name']} | id={player['id']} | position={player['position']}"
            )
            lines.append("# Health (raw counters): " + json.dumps(player.get("health", {})))
    if s.get("modal"):
        lines.append("# Prompt: " + json.dumps(s["modal"]))
    if observation.get("dispatch"):
        d = observation["dispatch"]
        lines.append(
            f"# Dispatch: {d['id']} | {d['outcome']} | {len(d['steps'])} steps | {d['reason']}"
        )
        for field, label in (
            ("resume_action", "Resume"),
            ("next_action", "Next input"),
            ("details", "Details"),
            ("prompts", "Handled prompts"),
            ("prompt_sequence", "Prompt order"),
        ):
            if d.get(field):
                lines.append("# " + label + ": " + json.dumps(d[field], ensure_ascii=False))
        for event in d.get("events", []):
            lines.append(
                f"E{event['id']}|speaker={event['speaker_id']} activity={event['activity_id']}|{event['text']}"
            )
    if observation.get("conversation"):
        lines.append(
            "# Conversation: " + json.dumps(observation["conversation"], ensure_ascii=False)
        )
    if observation.get("format") == "compact":
        lines.append("# Changes: " + json.dumps(observation.get("changes", {}), ensure_ascii=False))
        if observation.get("menu"):
            lines.append("# Choices: " + json.dumps(observation["menu"], ensure_ascii=False))
        lines.extend(observation.get("ui_text", []))
        return "\n".join(lines)
    if observation.get("adventurer"):
        lines.append(
            "# Inventory: "
            + json.dumps(observation["adventurer"].get("inventory", []), ensure_ascii=False)
        )
    if observation.get("nearby_items"):
        lines.append(
            "# Nearby items: " + json.dumps(observation["nearby_items"], ensure_ascii=False)
        )
    if observation.get("menu"):
        lines.append("# Menu: " + json.dumps(observation["menu"], ensure_ascii=False))
    ui = observation["ui"]
    lines.append(
        f"# UI {ui['width']}x{ui['height']}; U<y>|; x = zero-based Unicode character offset"
    )
    lines += [f"U{row['y']:02d}|{row['text']}" for row in ui["rows"]]
    if observation.get("reports"):
        lines.append(
            "# Recent reports (stable IDs; match activity_id and speaker_id for direct replies):"
        )
        lines += [
            f"R{r['id']}|speaker={r['speaker_id']} activity={r['activity_id']}|{r['text']}"
            for r in observation["reports"][-12:]
        ]
    if observation.get("map"):
        m = observation["map"]
        o = m["origin"]
        lines.append(
            f"# MAP {m['width']}x{m['height']} | origin=({o['x']},{o['y']},{o['z']}) | semantic ASCII"
        )
        lines.append(
            "# World coordinate = origin + (column, row, 0). Map cells are NOT UI click coordinates."
        )
        lines.extend(f"M{y:02d}|{row}" for y, row in enumerate(m["rows"]))
        lines.append("# Legend: " + json.dumps(m["legend"], ensure_ascii=False))
        lines.append("# Nearby: " + json.dumps(m["units"], ensure_ascii=False))
    return "\n".join(lines)


def render_character_status(observation):
    """Useful reading summary followed by every character section, without filtering."""
    s = observation["status"]
    lines = [
        f"# Character status | {s['df_version']} | DFHack {s['dfhack_version']}",
        f"# State: {observation['state_id']} | ready={s['ready_for_input']}",
    ]
    if not observation.get("available"):
        return "\n".join([*lines, observation.get("reason", "No active adventurer is available")])
    c = observation["character"]

    def dump(value):
        return json.dumps(value, ensure_ascii=False)

    lines.append(f"# {c['name']} | id={c['id']} | position={c['position']}")
    if "encumbrance" in c:
        load = c["encumbrance"]

        def kg(value):
            return f"{value:.6f}".rstrip("0").rstrip(".")

        lines.append("# Encumbrance (equipment and container contents included once)")
        if load.get("weight_complete") and "total_weight_kg" in load:
            lines.append(f"Carried weight: {kg(load['total_weight_kg'])} kg")
        else:
            subtotal = (
                kg(load["known_weight_kg"]) + " kg" if "known_weight_kg" in load else "unavailable"
            )
            lines.append(f"Carried weight: unknown; known subtotal {subtotal}")
        burden = load.get("burden", {})
        if burden.get("available"):
            lines.append(
                f"Burden: {burden['label']} ({burden['capacity_used_percent']:.2f}% of capacity)"
            )
        else:
            lines.append("Burden: unavailable — " + burden.get("reason", "Not reported"))
        for group in load.get("by_mode", []):
            amount = group.get("weight_kg", group.get("known_weight_kg", 0))
            qualifier = "" if group.get("weight_complete") else " (known subtotal)"
            lines.append(f"  {group['mode']}: {kg(amount)} kg{qualifier}")
        lines.append("Heaviest carried items (containers include their contents):")
        for item in load.get("heaviest_items", []):
            lines.append(f"  {item['id']}: {item['description']} — {kg(item['weight_kg'])} kg")
        for field, label in (("capacity", "Carrying capacity"), ("load_penalty", "Load penalty")):
            value = load.get(field, {})
            if not value.get("available"):
                summary = "unavailable — " + value.get("reason", "Not reported")
            elif field == "capacity":
                summary = (
                    f"{kg(value['weight_kg'])} kg before movement penalty (skill-adjusted load)"
                )
            else:
                summary = f"+{value['movement_cost_added']} movement cost"
                if "speed_reduction_percent" in value:
                    summary += (
                        f"; {value['speed_reduction_percent']:.2f}% lower speed from carried load"
                    )
                summary += f"; {kg(value['excess_weight_kg'])} kg over capacity after skill discounts and native rounding"
            lines.append(label + ": " + summary)
        if load.get("unweighed_items"):
            lines.append("Items with unknown weight: " + dump(load["unweighed_items"]))
        speed = c.get("movement", {}).get("displayed_speed")
        if speed is not None:
            lines.append(
                f"HUD movement: {speed['gait']} {speed['text']} (native displayed speed; not a load penalty)"
            )
        else:
            lines.append("HUD movement: unavailable in this view")
    calculated = c.get("movement", {}).get("effective_speed", {})
    if calculated.get("available"):
        lines.append(
            f"Calculated movement: {calculated['gait']} {calculated['displayed_text']} "
            f"(native speed units; unloaded {calculated['unloaded']['displayed_text']})"
        )
    needs = c.get("physiology", {}).get("interpreted_needs", {})
    if needs.get("available"):
        for key in ("hunger", "thirst", "sleep", "blood_thirst"):
            need = needs.get(key)
            if not need:
                continue
            summary = f"{key.replace('_', ' ').capitalize()}: {need['label']} (severity {need['severity']}; counter {need['counter']})"
            if "next_stage" in need:
                next_stage = need["next_stage"]
                summary += f"; next: {next_stage['label']} at {next_stage['counter']} (+{next_stage['remaining_counter']} counter units)"
            lines.append(summary)
    for group, attrs in c.get("attributes", {}).items():
        lines.append("# " + group.capitalize() + " attributes (stored / effective / maximum)")
        for a in attrs:
            lines.append(
                f"{a['name']}: {a.get('value', '?')} / {a.get('effective', '?')} / {a.get('max_value', '?')}"
            )
    if "skills" in c:
        lines.append("# Skills (native records)")
        for skill in c["skills"]:
            lines.append(
                f"{skill.get('caption', skill['name'])}: {skill.get('rating_name', skill['rating'])} "
                f"(rating {skill['rating']}, effective {skill.get('effective', '?')}); "
                f"XP {skill['experience']}/{skill.get('next_level_xp_threshold', '?')}; rust {skill.get('rusty', '?')}"
            )
    lines.append("# Game/input status: " + dump(s))
    # Do not maintain a second field allowlist that silently drops new sections,
    # healthy anatomy, item definitions, false values, or optional profiles.
    for field, value in c.items():
        lines.append("# " + field.replace("_", " ").capitalize() + ": " + dump(value))
    return "\n".join(lines)
