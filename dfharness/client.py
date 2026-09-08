"""Structured observations and controller-directed dispatches through DFHack."""

import json
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .capabilities import capability_report
from .config import port_for_game
from .dispatch import run_dispatch
from .metrics import Recorder, active, measured
from .policy import execution_policy
from .program import ASSETS as ASSETS
from .program import MARKER, prepare_program
from .program import lua_string as lua_string
from .program import make_program as make_program
from .readings import ReadCache
from .rpc import (
    BridgeError,
    DFHackError,
    DispatchError,
    pending_pause,
    response_timeout,
    rpc_deadline,
    run_command,
)
from .settings import read_settings, settings_path, write_settings
from .views import (
    character_brief,
    choice_observation,
    concise_observation,
    reading_status,
    render_view,
    unit_brief,
)


class Client:
    def __init__(
        self,
        port=None,
        timeout=10.0,
        log_path=None,
        execution=None,
        settings_path=None,
        metrics_path=None,
        metrics_run=None,
        metrics_episode=None,
    ):
        self.port = port_for_game(port)
        self.timeout = timeout
        self.log_path = Path(log_path) if log_path else None
        self.settings_path = settings_path
        execution_policy(execution)  # Validate constructor overrides immediately.
        self.execution_override = execution
        self.metrics_path, self.metrics_run = metrics_path, metrics_run
        self.metrics_episode = metrics_episode
        self._metrics = None
        self._metrics_config = None
        self._metrics_disabled = Recorder()

    @property
    def metrics(self):
        try:
            saved = read_settings(self.settings_path)["measurement"]
        except (OSError, ValueError) as exc:
            # A query that does not need controller settings must not acquire a
            # new failure mode just because its passive recorder reads them.
            self._metrics_disabled.warn("settings unavailable", exc)
            return self._metrics_disabled
        explicit = (
            self.metrics_path if self.metrics_path is not None else os.environ.get("DFLLM_METRICS")
        )
        if explicit is False or explicit == "off":
            path = None
        elif explicit:
            path = Path(explicit).expanduser()
        elif saved["enabled"]:
            base = settings_path(self.settings_path).parent
            path = base / Path(saved["path"] or "metrics.jsonl").expanduser()
        else:
            path = None
        config = (
            path,
            self.metrics_run or os.environ.get("DFLLM_METRICS_RUN") or saved["run"],
            self.metrics_episode or os.environ.get("DFLLM_EPISODE") or saved["episode"],
            self.log_path,
        )
        if config != self._metrics_config:
            self._metrics = Recorder(
                config[0], run=config[1], episode=config[2], payload_path=config[3]
            )
            self._metrics_config = config
        return self._metrics

    @property
    def execution(self):
        return execution_policy(
            read_settings(self.settings_path)["execution"], self.execution_override
        )

    @measured
    def settings(self, update=None, reset=False):
        saved = (
            write_settings(update or {}, self.settings_path, reset)
            if update is not None or reset
            else read_settings(self.settings_path)
        )
        effective = dict(
            saved, execution=execution_policy(saved["execution"], self.execution_override)
        )
        return {
            "path": str(settings_path(self.settings_path)),
            "saved": saved,
            "effective": effective,
            "precedence": "built-in < saved < client constructor < dispatch override",
        }

    @measured
    def request(self, request):
        started = time.monotonic()
        program = prepare_program(request)
        source = program.render()
        transport = {
            "rpc_calls": 1,
            "request_bytes": len(source.encode()),
            "loader": "dfhack_reqscript_absolute",
        }
        recorder = active().recorder
        with recorder.rpc(request.get("op", "unknown"), transport["request_bytes"]) as sample:
            output = run_command(
                "lua", source, port=self.port, timeout=response_timeout(self.timeout)
            )
            sample["output_bytes"] = len(output.encode("utf-8"))
            lines = [line[len(MARKER) :] for line in output.splitlines() if line.startswith(MARKER)]
            if len(lines) != 1:
                raise DFHackError(
                    "DFHack returned no unique structured response: " + output[-2000:]
                )
            envelope = json.loads(lines[0])
            if envelope.get("ok") is False:
                sample.update(outcome="error", code=envelope.get("code", "bridge_error"))
            payload = envelope.get("result")
            if request.get("op") == "poll" and isinstance(payload, dict):
                sample["variant"] = next(
                    (
                        label
                        for field, label in (
                            ("pending_view", "pending"),
                            ("view_delta", "delta"),
                            ("view", "full"),
                        )
                        if field in payload
                    ),
                    "readiness",
                )
        if self.log_path and (request.get("op") != "poll" or request.get("observe")):
            recorder.write(
                {
                    "at": datetime.now(UTC).isoformat(),
                    "trace_id": active().id,
                    "request": request,
                    "response": envelope,
                    "transport": transport,
                    "elapsed_ms": round((time.monotonic() - started) * 1000),
                },
                path=self.log_path,
            )
        if not envelope.get("ok"):
            raise BridgeError(
                envelope.get("error", "Unknown DFHack bridge error"),
                envelope.get("code", "bridge_error"),
                envelope.get("details"),
                envelope.get("input_sent"),
            )
        return envelope["result"]

    @measured
    def status(self):
        return self.character_status()

    @measured
    def game_status(self):
        return self.request({"op": "status"})

    @measured
    def load_game(self, name, *, timeout=120):
        """Development save management: load an exact save from the native title screen."""
        if (
            not isinstance(name, str)
            or not 1 <= len(name) <= 100
            or any(c in name for c in "/\\\0")
            or name.casefold() in (".", "..", "current")
        ):
            raise ValueError("load_game requires a save folder name, not a path")
        if type(timeout) not in (int, float) or not 0 < timeout <= 300:
            raise ValueError("load_game timeout must be in (0, 300]")
        deadline = time.monotonic() + timeout
        with rpc_deadline(deadline):
            load = self.request({"op": "load_save", "name": name})
            status = {}
            polls = 0
            while True:
                result = {
                    "format": "compact",
                    "schema_version": 3,
                    "inputs": load.get("inputs"),
                    "status": reading_status(status),
                }
                if load.get("phase") == "failed":
                    return dict(
                        result,
                        outcome="failed",
                        blocker={
                            "kind": "native_load",
                            "why": load.get("reason"),
                            "facts": {"name": name},
                        },
                    )
                if (
                    status.get("map_loaded")
                    and status.get("ready_for_input")
                    and status.get("screen")
                    in ("viewscreen_dungeonmodest", "viewscreen_dwarfmodest")
                ):
                    if status.get("save") != name:
                        return dict(
                            result,
                            outcome="interrupted",
                            blocker={
                                "kind": "world_changed",
                                "why": "A different save loaded.",
                                "facts": {"requested": name, "loaded": status.get("save")},
                            },
                        )
                    after = self.observe(view="choices")
                    return dict(
                        result,
                        outcome="completed",
                        values=[{"kind": "load_game", "name": name}],
                        state_id=after["state_id"],
                        after=after,
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return dict(
                        result,
                        outcome="limit_reached",
                        blocker={
                            "kind": "load_pending",
                            "why": "Loading has not finished; read game-status before starting another load.",
                            "facts": {"name": name, "phase": load.get("phase")},
                        },
                    )
                if polls:
                    time.sleep(pending_pause(polls - 1, remaining))
                    if time.monotonic() >= deadline:
                        continue
                state = self.request({"op": "load_status"})
                load, status = state["load"], state["status"]
                polls += 1

    @measured
    def session(self, limit=20):
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError("session limit must be an integer in [1, 128]")
        return self.request({"op": "session", "limit": limit})

    @measured
    def capabilities(self):
        return capability_report(self.request({"op": "capabilities"}))

    @measured
    def actions(self, name=None, *, expand=False):
        from .actions import action_reference

        return action_reference(name, expand=expand)

    @measured
    def navigation(self, limit=20, *, view="concise", since=None):
        self._validate_view(view, since)
        request = {
            "op": "navigation",
            "limit": limit,
            "ui_mode": "native",
            "navigation_grid": view == "full",
        }
        value = self.request(request)
        if view == "full":
            return value
        return self._reading(
            dict(value, status=reading_status(value.get("status", {}))), request, value, since
        )

    @measured
    def shops(self, shop_type=None, *, site_id=None, limit=20, stock=False):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("shop limit must be an integer in [1, 100]")
        if site_id is not None and (type(site_id) is not int or not 0 <= site_id <= 2147483647):
            raise ValueError("site_id must be a nonnegative native ID")
        if shop_type is not None and (not isinstance(shop_type, str) or not shop_type.strip()):
            raise ValueError("shop_type must be a native shop type token")
        if type(stock) is not bool:
            raise ValueError("stock must be boolean")
        request = {"op": "shops", "limit": limit}
        if site_id is not None:
            request["site_id"] = site_id
        if shop_type is not None:
            request["shop_type"] = shop_type
        if stock:
            request["stock"] = True
        return self.request(request)

    @measured
    def locate(self, kind, id):
        if kind not in ("figure", "artifact") or type(id) is not int or not 0 <= id <= 2147483647:
            raise ValueError("locate requires kind=figure/artifact and a nonnegative native ID")
        return self.request({"op": "locate", "kind": kind, "id": id})

    @measured
    def barter(self, *, side="take", item_type=None, limit=20):
        if side not in ("take", "give"):
            raise ValueError("side must be take or give")
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("limit must be in [1, 500]")
        if item_type is not None and (not isinstance(item_type, str) or not item_type):
            raise ValueError("item_type must be a native token")
        request = {"op": "barter", "side": side, "limit": limit}
        if item_type is not None:
            request["item_type"] = item_type
        return self.request(request)

    @measured
    def world_scan(self, tokens=None, *, match="any", limit=20, catalog=False, material=None):
        from .world_scan import attach_stock, search, validate

        if type(catalog) is not bool:
            raise ValueError("catalog must be boolean")
        if catalog:
            if tokens or material is not None:
                raise ValueError("Choose a token catalog or a search, not both")
            snapshot = self.request({"op": "world_sites", "catalog": True})
            return {
                k: v for k, v in snapshot.items() if k not in ("sites", "errors", "error_count")
            }
        tokens = [tokens] if isinstance(tokens, str) else tokens
        tokens = validate(tokens, match, limit, material)
        snapshot = self.request({"op": "world_sites"})
        if material is not None:
            snapshot = attach_stock(snapshot, material, self.request)
        return search(snapshot, tokens, match, limit, material)

    @measured
    def character_status(self):
        return self.request({"op": "character_status"})

    @measured
    def brief(self, *, since=None):
        self._validate_since(since, "concise")
        request = {"op": "character_brief", "ui_mode": "native"}
        value = self.request(request)
        return self._reading(character_brief(value), request, value, since)

    @measured
    def unit(self, unit_id, view="concise", since=None):
        if view not in ("concise", "full"):
            raise ValueError("view must be concise or full")
        self._validate_since(since, view)
        result = self.request(
            {"op": "unit", "unit_id": unit_id, "unit_view": view, "ui_mode": "native"}
        )
        if view == "full":
            return result
        return self._reading(unit_brief(result), {"op": "unit", "unit_id": unit_id}, result, since)

    @staticmethod
    def _validate_view(view, since):
        if view not in ("concise", "full"):
            raise ValueError("view must be concise or full")
        Client._validate_since(since, view)

    @staticmethod
    def _validate_since(since, view):
        if since is not None and (
            view != "concise" or not isinstance(since, str) or not 1 <= len(since) <= 100
        ):
            raise ValueError("since requires a read_ref string and view=concise")

    def _reading(self, value, query, native, since):
        epoch = native.get("status", {}).get("world_epoch")
        if epoch is None:
            return dict(
                value,
                read_cache={"available": False, "reason": "Native world identity is unavailable"},
            )
        scope = {
            "port": self.port,
            "world_epoch": epoch,
            "query": query,
        }
        cache = ReadCache(settings_path(self.settings_path).parent / "readings.sqlite3")
        return cache.project(value, scope, since)

    def _after_scene(self, value, event_detail, force_types, since):
        # Match an ordinary default look query, independently of execution-only readers.
        request = {
            "op": "observe",
            "width": 41,
            "height": 21,
            "map": True,
            "ui_mode": "native",
            "scope": "scene",
            "receipt_state": True,
            "navigation_grid": False,
            "radius": 20,
        }
        scene = dict(value)
        scene.pop("target_unit", None)
        if "scene_reports" in value:
            for key in (
                "reports",
                "report_cursor",
                "reports_more",
                "reports_truncated",
                "reports_total",
                "report_scope",
                "report_cursor_reset",
                "reports_after",
                "next_report_cursor",
            ):
                scene.pop(key, None)
            scene.update(value["scene_reports"])
        if "scene_nearby_items" in value:
            scene["nearby_items"] = value["scene_nearby_items"]
        return self._reading(
            concise_observation(scene, event_detail, force_types),
            dict(request, event_detail=event_detail, force_types=force_types),
            value,
            since,
        )

    @measured
    def observe(
        self,
        width=41,
        height=21,
        center=None,
        map=True,
        radius=20,
        view=None,
        target_unit_id=None,
        conversation_activity=None,
        event_detail=None,
        reports_after=None,
        report_limit=None,
        since=None,
    ):
        settings = read_settings(self.settings_path)
        view = view or settings["observation_view"]
        event_detail = settings["event_detail"] if event_detail is None else event_detail
        if event_detail not in ("task", "all"):
            raise ValueError("event_detail must be task or all")
        if view not in ("concise", "full", "choices"):
            raise ValueError("view must be concise, full or choices")
        self._validate_since(since, view)
        request = {"op": "observe", "width": width, "height": height, "map": map}
        if view != "full":
            request["ui_mode"] = "native"
        if view == "choices":
            request["scope"] = "choices"
        elif view == "concise":
            request["scope"] = "scene"
            request["receipt_state"] = True
            request["navigation_grid"] = False
        request["radius"] = radius
        if center is not None:
            request["center"] = center
        if target_unit_id is not None:
            request["target_unit_id"] = target_unit_id
        if conversation_activity is not None:
            request["conversation_activity"] = conversation_activity
        if reports_after is not None:
            if type(reports_after) is not int or reports_after < -1:
                raise ValueError("reports_after must be an integer >= -1")
            request["reports_after"] = reports_after
        if report_limit is not None:
            if type(report_limit) is not int or not 1 <= report_limit <= 4096:
                raise ValueError("report_limit must be an integer in [1, 4096]")
            request["report_limit"] = report_limit
        value = self.request(request)
        if view == "choices":
            return choice_observation(value)
        if view == "full":
            return value
        force_types = self.execution["interrupt_on"].get("report_types", [])
        return self._reading(
            concise_observation(value, event_detail, force_types),
            dict(request, event_detail=event_detail, force_types=force_types),
            value,
            since,
        )

    @measured
    def wait_ready(self, action_id=None, timeout=30):
        deadline = time.monotonic() + timeout
        pending_polls = 0
        while True:
            request = {"op": "poll"}
            if action_id:
                request["action_id"] = action_id
            state = self.request(request)
            if state.get("action_error"):
                raise DFHackError("Action may have partially executed: " + state["action_error"])
            if state["ready"]:
                return state
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DFHackError(
                    f"Timed out waiting for game input readiness (action {action_id}). "
                    "The action was not retried. Use wait-ready or observe. "
                    f"Current focus: {state['status']['focus']}; phase: {state['status'].get('turn_phase')}"
                )
            time.sleep(pending_pause(pending_polls, remaining))
            pending_polls += 1

    @measured
    def act(
        self,
        action,
        expect=None,
        request_id=None,
        timeout=None,
        execution=None,
        result_format=None,
        event_detail=None,
        *,
        after=None,
        since=None,
    ):
        if after not in (None, "look") or (since is not None and after is None):
            raise ValueError("after must be look; since requires after=look")
        self._validate_since(since, "concise")
        settings = read_settings(self.settings_path)
        timeout = settings["dispatch_timeout"] if timeout is None else timeout
        result_format = settings["result_format"] if result_format is None else result_format
        event_detail = settings["event_detail"] if event_detail is None else event_detail
        request_id = request_id or str(uuid.uuid4())
        try:
            return run_dispatch(
                self,
                action,
                expect,
                request_id,
                timeout,
                execution,
                result_format,
                event_detail,
                after=after,
                since=since,
            )
        except DFHackError as exc:
            raise DispatchError(request_id, exc) from exc

    @measured
    def items(
        self, radius=20, *, building_id=None, item_type=None, limit=100, view="concise", since=None
    ):
        self._validate_view(view, since)
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("item limit must be an integer in [1, 500]")
        request = {"op": "items", "limit": limit, "item_view": view}
        if item_type is not None:
            if not isinstance(item_type, str) or not item_type.strip():
                raise ValueError("item_type must be a native item type token")
            request["item_type"] = item_type
        if building_id is not None:
            if type(building_id) is not int or not 0 <= building_id <= 2147483647:
                raise ValueError("building_id must be a nonnegative native ID")
            request["building_id"] = building_id
        else:
            request["radius"] = radius
        value = self.request(request)
        return value if view == "full" else self._reading(value, request, value, since)

    @measured
    def item(self, item_id):
        return self.request({"op": "item", "item_id": item_id})

    @measured
    def interrupt(self, dispatch_id):
        return self.request({"op": "interrupt", "dispatch_id": dispatch_id})

    @measured
    def dispatch_details(self, dispatch_id, section="events"):
        if section not in ("events", "prompts", "steps", "summary", "full", "compact"):
            raise ValueError("Unknown dispatch detail section")
        return self.request(
            {"op": "dispatch_details", "dispatch_id": dispatch_id, "section": section}
        )

    @measured
    def inspect(self, x, y, z):
        return self.request({"op": "inspect", "x": x, "y": y, "z": z})


def render_observation(observation):
    if observation.get("format") == "compact" and observation.get("schema_version") in (2, 3):
        from .state import render_receipt

        return render_receipt(observation)
    if observation.get("format") == "character_status":
        return render_character_status(observation)
    if observation.get("format") in (
        "character_brief",
        "concise_observation",
        "choice_observation",
        "unit_status",
    ):
        return render_view(observation)
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
        count = d.get("native_input_count", len(d.get("steps", [])))
        lines.append(
            f"# Dispatch: {d['id']} | {d['outcome']} | {count} native inputs | {d['reason']}"
        )
        for field, label in (
            ("resume_action", "Resume"),
            ("next_action", "Next input"),
            ("details", "Details"),
            ("progress", "Progress"),
            ("blocker", "Blocker"),
            ("results", "Verified stages"),
            ("replies", "Replies"),
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
    if observation.get("combat"):
        lines.append("# Combat: " + json.dumps(observation["combat"], ensure_ascii=False))
    if observation.get("format") == "compact":
        if observation.get("current"):
            lines.append("# Current: " + json.dumps(observation["current"], ensure_ascii=False))
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
            if "native_cached_weight_kg" in load:
                lines.append(
                    f"Native cached load: {kg(load['native_cached_weight_kg'])} kg; contents not fully verified"
                )
        burden = load.get("burden", {})
        if burden.get("available"):
            summary = "Burden: " + burden["label"]
            if "capacity_used_percent" in burden:
                summary += f" ({burden['capacity_used_percent']:.2f}% of capacity)"
            lines.append(summary)
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
