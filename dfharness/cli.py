import argparse
import json
import subprocess
import sys
from pathlib import Path

from .client import Client, render_observation
from .config import configure, doctor, launch, port_for_game
from .rpc import DFHackError, DispatchError, run_command


def parser():
    p = argparse.ArgumentParser(
        description="Control a running Dwarf Fortress through DFHack; adventure mode first."
    )
    p.add_argument(
        "--port", type=int, help="Override DFHACK_PORT and the game's remote-server.json"
    )
    p.add_argument("--timeout", type=float, default=10, help="RPC response timeout in seconds")
    p.add_argument(
        "--log", type=Path, help="Append requests and observations to a JSONL episode log"
    )
    p.add_argument(
        "--mode",
        choices=["step", "complete"],
        default="step",
        help="Controller's default dispatch mode",
    )
    p.add_argument(
        "--acknowledge",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Controller delegates help and announcement acknowledgements",
    )
    p.add_argument("--max-steps", type=int, default=32, help="Default dispatch input limit (1..64)")
    p.add_argument(
        "--interrupt-on",
        type=json.loads,
        default={},
        help="Controller interruption conditions as a JSON object",
    )
    subs = p.add_subparsers(dest="command", required=True)
    subs.add_parser("doctor", help="Find CrossOver, DFHack, saves, and the RPC connection")
    setup = subs.add_parser(
        "setup", help="Set the game's local RPC port; restart DFHack after changing it"
    )
    setup.add_argument("--port", dest="setup_port", type=int, default=5001)
    launcher = subs.add_parser("launch", help="Ask Steam in CrossOver to launch DFHack")
    launcher.add_argument(
        "--direct", action="store_true", help="Launch DF directly with its installed DFHack hook"
    )
    status = subs.add_parser(
        "status", help="Read all supported character state and current game/input status"
    )
    status.add_argument(
        "--text", action="store_true", help="Render the character report as readable text"
    )
    subs.add_parser("game-status", help="Read only the mode, screen, turn readiness, and version")
    character = subs.add_parser(
        "character-status",
        help="Read comprehensive character health, attributes, skills, needs, personality, and equipment",
    )
    character.add_argument(
        "--text", action="store_true", help="Render the character sheet as readable text"
    )
    obs = subs.add_parser(
        "observe", help="Read UI text, a local ASCII map, and structured adventure state"
    )
    obs.add_argument("--width", type=int, default=41)
    obs.add_argument("--height", type=int, default=21)
    obs.add_argument("--center", type=int, nargs=3, metavar=("X", "Y", "Z"))
    obs.add_argument("--no-map", action="store_true")
    obs.add_argument(
        "--text", action="store_true", help="Compact human/LLM-readable view instead of JSON"
    )
    obs.add_argument("--radius", type=int, default=20, help="Nearby item search radius")
    items = subs.add_parser(
        "items", help="Read visible nearby items and container contents in one call"
    )
    items.add_argument("--radius", type=int, default=20)
    item = subs.add_parser("item", help="Inspect one carried or visible ground item by ID")
    item.add_argument("item_id", type=int)
    interrupt = subs.add_parser(
        "interrupt", help="Request that a running dispatch stop before further inputs"
    )
    interrupt.add_argument("dispatch_id")
    keys = subs.add_parser("keys", help="List valid DF interface keys, optionally filtered")
    keys.add_argument("filter", nargs="?", default="")
    inspect = subs.add_parser("inspect", help="Read a world tile and the items/creatures on it")
    for coord in ("x", "y", "z"):
        inspect.add_argument(coord, type=int)
    ready = subs.add_parser(
        "wait-ready", help="Wait without advancing the game until it can accept input"
    )
    ready.add_argument("--seconds", type=float, default=30)
    ready.add_argument("--action-id")
    run = subs.add_parser("run", help="Run an explicit DFHack command (advanced escape hatch)")
    run.add_argument("args", nargs=argparse.REMAINDER)
    subs.add_parser("native-ascii", help="Run the original experimental classic-render capture")
    subs.add_parser("mcp", help="Serve structured tools to any MCP client over stdio")
    actions = {}
    actions["move"] = subs.add_parser("move", help="Move one adventure step and observe the result")
    actions["move"].add_argument(
        "direction", choices=["n", "s", "e", "w", "ne", "nw", "se", "sw", "up", "down"]
    )
    actions["wait"] = subs.add_parser("wait", help="Take one short in-game wait action")
    actions["dismiss"] = subs.add_parser(
        "dismiss", help="Acknowledge one detected help or announcement page"
    )
    actions["resume"] = subs.add_parser(
        "resume", help="Apply dispatch policy to the current state without repeating prior input"
    )
    actions["resume"].add_argument(
        "dispatch_id",
        nargs="?",
        help="Resume this saved workflow, including across client processes",
    )
    for name in ("pickup", "equip", "wield", "remove", "drop", "stow"):
        actions[name] = subs.add_parser(
            name, help=f"Dispatch {name} by item ID and verify its inventory result"
        )
        actions[name].add_argument("item_id", type=int)
    for name in ("equip", "wield"):
        actions[name].add_argument("--replace", type=int, nargs="*", default=[])
        actions[name].add_argument(
            "--disposition", choices=["hold", "drop", "stow"], default="hold"
        )
        actions[name].add_argument("--container-id", type=int)
        actions[name].add_argument("--body-part-id", type=int)
    actions["stow"].add_argument("container_id", type=int)
    actions["walk-to"] = subs.add_parser(
        "walk-to", help="Walk to a tile in the currently observed local area"
    )
    for name in ("x", "y", "z"):
        actions["walk-to"].add_argument(name, type=int)
    actions["walk-to"].add_argument(
        "--allow-occupied", action="store_true", help="Allow routes through occupied tiles"
    )
    actions["walk-to"].add_argument("--max-liquid-depth", type=int, default=7)
    actions["walk-to"].add_argument("--blocked-tiles", type=json.loads, default=[])
    actions["select-option"] = subs.add_parser(
        "select-option", help="Select a currently visible structured menu option"
    )
    actions["select-option"].add_argument("option_id")
    actions["respond"] = subs.add_parser(
        "respond", help="Respond to the current Continue/Stop/Finish prompt"
    )
    actions["respond"].add_argument("choice", choices=["continue", "stop", "finish"])
    actions["select-unit"] = subs.add_parser(
        "select-unit", help="Select a visible creature in the conversation picker"
    )
    actions["select-unit"].add_argument("unit_id", type=int)
    actions["key"] = subs.add_parser("key", help="Send one named DF interface key and observe")
    actions["key"].add_argument("key")
    actions["click"] = subs.add_parser("click", help="Click a zero-based UI character cell")
    actions["click"].add_argument("x", type=int)
    actions["click"].add_argument("y", type=int)
    actions["click"].add_argument("--button", choices=["left", "right", "middle"], default="left")
    actions["choose"] = subs.add_parser(
        "choose", help="Click a unique visible label in the text UI"
    )
    actions["choose"].add_argument("label")
    actions["text"] = subs.add_parser(
        "text", help="Type printable ASCII into the focused text field"
    )
    actions["text"].add_argument("value")
    actions["act"] = subs.add_parser("act", help="Send an action JSON object; use - to read stdin")
    actions["act"].add_argument("action_json")
    for action in actions.values():
        action.add_argument("--expect", help="Reject input if this observation state_id is stale")
        action.add_argument("--request-id", help="Deduplicate an action within this game session")
        action.add_argument(
            "--mode",
            dest="dispatch_mode",
            choices=["step", "complete"],
            help="Override dispatch completion mode",
        )
        action.add_argument(
            "--acknowledge",
            dest="dispatch_acknowledge",
            action=argparse.BooleanOptionalAction,
            default=None,
            help="Override automatic help/announcement acknowledgements",
        )
        action.add_argument(
            "--max-steps", dest="dispatch_max_steps", type=int, help="Override dispatch input limit"
        )
        action.add_argument(
            "--seconds",
            type=float,
            default=30,
            help="Dispatch time limit, including automatic responses",
        )
        action.add_argument(
            "--interrupt-on",
            dest="dispatch_interrupt_on",
            type=json.loads,
            help="Override controller interruption conditions",
        )
        action.add_argument("--result-format", choices=["compact", "full"], default="compact")
        action.add_argument("--text", action="store_true", help="Return a compact text observation")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    defaults = {
        "mode": args.mode,
        "acknowledge": args.acknowledge,
        "max_steps": args.max_steps,
        "interrupt_on": args.interrupt_on,
    }
    try:
        if args.command == "setup":
            result = configure(args.setup_port)
        elif args.command == "doctor":
            result = doctor(args.port)
        elif args.command == "launch":
            result = launch(args.direct)
        elif args.command == "mcp":
            from .mcp import serve

            serve(Client(args.port, args.timeout, args.log, execution=defaults))
            return 0
        elif args.command == "native-ascii":
            import os

            env = dict(os.environ, DFHACK_PORT=str(port_for_game(args.port)))
            return subprocess.run(
                [str(Path(__file__).resolve().parents[1] / "df-ascii")], env=env
            ).returncode
        elif args.command == "run":
            if not args.args:
                raise ValueError("Usage: ./dfctl run COMMAND [ARG ...]")
            sys.stdout.write(
                run_command(*args.args, port=port_for_game(args.port), timeout=args.timeout)
            )
            return 0
        else:
            client = Client(args.port, args.timeout, args.log, execution=defaults)
            if args.command == "status":
                result = client.status()
            elif args.command == "game-status":
                result = client.game_status()
            elif args.command == "character-status":
                result = client.character_status()
            elif args.command == "observe":
                center = (
                    dict(zip(("x", "y", "z"), args.center, strict=True)) if args.center else None
                )
                result = client.observe(
                    args.width, args.height, center, not args.no_map, args.radius
                )
            elif args.command == "items":
                result = client.items(args.radius)
            elif args.command == "item":
                result = client.item(args.item_id)
            elif args.command == "interrupt":
                result = client.interrupt(args.dispatch_id)
            elif args.command == "keys":
                result = client.request({"op": "keys", "filter": args.filter})
            elif args.command == "inspect":
                result = client.inspect(args.x, args.y, args.z)
            elif args.command == "wait-ready":
                result = client.wait_ready(args.action_id, args.seconds)
            else:
                if args.command == "act":
                    raw = sys.stdin.read() if args.action_json == "-" else args.action_json
                    action = json.loads(raw)
                else:
                    action = {"type": args.command.replace("-", "_")}
                    for key in (
                        "direction",
                        "key",
                        "x",
                        "y",
                        "z",
                        "button",
                        "unit_id",
                        "item_id",
                        "option_id",
                        "dispatch_id",
                        "replace",
                        "disposition",
                        "container_id",
                        "body_part_id",
                        "allow_occupied",
                        "max_liquid_depth",
                        "blocked_tiles",
                    ):
                        if hasattr(args, key) and getattr(args, key) is not None:
                            action[key] = getattr(args, key)
                    if args.command == "choose":
                        action = {"type": "click_text", "text": args.label}
                    elif args.command == "text":
                        action["text"] = args.value
                    elif args.command == "select-unit":
                        action["type"] = "select_unit"
                    elif args.command == "respond":
                        action = {"type": "action_prompt", "choice": args.choice}
                execution = {
                    key: getattr(args, "dispatch_" + key)
                    for key in ("mode", "acknowledge", "max_steps", "interrupt_on")
                    if getattr(args, "dispatch_" + key) is not None
                }
                result = client.act(
                    action,
                    args.expect,
                    args.request_id,
                    args.seconds,
                    execution,
                    args.result_format,
                )
        if getattr(args, "text", False) and isinstance(result, dict) and "status" in result:
            print(render_observation(result))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (DFHackError, OSError, ValueError, subprocess.SubprocessError) as exc:
        error = {"ok": False, "error": str(exc)}
        if isinstance(exc, DispatchError):
            error.update(dispatch_id=exc.dispatch_id, resume_action=exc.resume_action)
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(
            "Interrupted. An in-flight action may have executed; observe before retrying.",
            file=sys.stderr,
        )
        return 130
