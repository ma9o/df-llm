import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from . import reference
from .client import Client, render_observation
from .config import configure, doctor, launch, port_for_game
from .metrics import active
from .policy import MAX_DISPATCH_INPUTS
from .rpc import DFHackError, DispatchError, run_command


def parser():
    p = argparse.ArgumentParser(
        description="Control a running Dwarf Fortress through DFHack; adventure mode first.",
        epilog=reference.OVERVIEW,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--port", type=int, help="Override DFHACK_PORT and the game's remote-server.json"
    )
    p.add_argument("--timeout", type=float, default=10, help="RPC response timeout in seconds")
    p.add_argument("--pretty", action="store_true", help="Indent JSON for human reading")
    p.add_argument(
        "--log", type=Path, help="Append requests and observations to a JSONL episode log"
    )
    p.add_argument("--settings", type=Path, help="Controller settings file (or DFLLM_SETTINGS)")
    metrics = p.add_mutually_exclusive_group()
    metrics.add_argument(
        "--metrics",
        dest="metrics_path",
        type=Path,
        help="Append passive interaction/RPC measurements to JSONL",
    )
    metrics.add_argument(
        "--no-metrics",
        dest="metrics_path",
        action="store_const",
        const=False,
        help="Disable measurements for this process",
    )
    p.add_argument("--metrics-run", help="Label measurements for before/after comparisons")
    p.add_argument("--episode", help="Instruction identity for measurements (or DFLLM_EPISODE)")
    p.add_argument(
        "--mode", choices=["step", "complete"], help="Override saved controller dispatch mode"
    )
    p.add_argument(
        "--acknowledge",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Controller delegates help and announcement acknowledgements",
    )
    p.add_argument(
        "--max-steps", type=int, help=f"Default dispatch input limit (1..{MAX_DISPATCH_INPUTS})"
    )
    p.add_argument(
        "--interrupt-on",
        type=json.loads,
        help="Controller interruption conditions as a JSON object",
    )
    # The overview epilog groups every command; argparse's flat 75-entry list
    # would print the same names a second time.
    subs = p.add_subparsers(
        dest="command", required=True, metavar="COMMAND", help=argparse.SUPPRESS
    )
    named = {}

    def command(name, **extra):
        # Summary, contract and formatter come from the shared reference table.
        sub = subs.add_parser(name, **reference.parser_kwargs(name), **extra)
        named[name] = sub
        return sub

    command("guide")
    command("doctor")
    audit = command("audit-log")
    audit.add_argument("paths", type=Path, nargs="+")
    metrics = command("metrics")
    metrics.add_argument("paths", type=Path, nargs="*")
    metrics.add_argument(
        "--baseline",
        type=Path,
        action="append",
        help="Baseline JSONL file; repeat for multiple files",
    )
    metrics.add_argument("--run", help="Select a run label from the current files")
    metrics.add_argument(
        "--tokenizer", help="Count captured controller payloads offline with a prepared encoding"
    )
    metrics.add_argument(
        "--idle-gap",
        type=float,
        default=120,
        help="Split every episode label after this many idle seconds (default 120)",
    )
    metrics.add_argument(
        "--prepare-tokenizer",
        metavar="NAME",
        help="Explicitly prepare a local encoding; may download tokenizer data",
    )
    metrics.add_argument("--text", action="store_true", help="Show a compact latency/token table")
    setup = command("setup")
    setup.add_argument("--port", dest="setup_port", type=int, default=5001)
    launcher = command("launch")
    launcher.add_argument(
        "--direct", action="store_true", help="Launch DF directly with its installed DFHack hook"
    )
    status = command("status")
    status.add_argument(
        "--text", action="store_true", help="Render the character report as readable text"
    )
    command("game-status")
    load = command("load-game", aliases=["quickload"])
    load.add_argument("name", help="Save folder name, not a path")
    load.add_argument(
        "--seconds", type=float, default=120, help="Loading deadline, up to 300 seconds"
    )
    load.set_defaults(command="load-game")
    session = command("session")
    session.add_argument("--limit", type=int, default=20)
    brief = command("brief")
    brief.add_argument("--text", action="store_true")
    brief.add_argument("--since", help="Return changes against a previous brief read_ref")
    unit = command("unit")
    unit.add_argument("unit_id", type=int)
    unit.add_argument("--view", choices=["concise", "full"], default="concise")
    unit.add_argument("--since", help="Return exact changes against a previous concise read_ref")
    unit.add_argument("--text", action="store_true")
    settings = command("settings")
    settings.add_argument("--set", dest="settings_update", type=json.loads)
    settings.add_argument(
        "--reset", action="store_true", help="Reset to built-in settings before applying updates"
    )
    settings.add_argument("--mode", dest="setting_mode", choices=["step", "complete"])
    settings.add_argument(
        "--acknowledge",
        dest="setting_acknowledge",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    settings.add_argument("--max-steps", dest="setting_max_steps", type=int)
    settings.add_argument("--interrupt-on", dest="setting_interrupt_on", type=json.loads)
    settings.add_argument("--view", dest="setting_view", choices=["concise", "full"])
    settings.add_argument("--seconds", dest="setting_seconds", type=float)
    command("capabilities")
    action_index = command("actions")
    action_index.add_argument("name", nargs="?")
    action_index.add_argument(
        "--expand", action="store_true", help="Inline all sequence stage schemas"
    )
    details = command("dispatch-details")
    details.add_argument("dispatch_id")
    details.add_argument(
        "--section",
        choices=["events", "prompts", "steps", "summary", "full", "compact"],
        default="events",
    )
    character = command("character-status")
    character.add_argument(
        "--text", action="store_true", help="Render the character sheet as readable text"
    )
    obs = command("observe", aliases=["look"])
    obs.add_argument(
        "--view",
        choices=["concise", "full", "choices"],
        help="Scene or current choices; look defaults to concise",
    )
    obs.add_argument("--width", type=int, default=41)
    obs.add_argument("--height", type=int, default=21)
    obs.add_argument("--center", type=int, nargs=3, metavar=("X", "Y", "Z"))
    obs.add_argument("--no-map", action="store_true")
    obs.add_argument(
        "--text", action="store_true", help="Compact human/LLM-readable view instead of JSON"
    )
    obs.add_argument("--radius", type=int, default=20, help="Nearby item search radius")
    obs.add_argument(
        "--event-detail",
        choices=["task", "all"],
        help="Report projection; full observations preserve all types",
    )
    obs.add_argument(
        "--reports-after",
        type=int,
        help="Read reports newer than this native ID; -1 starts history",
    )
    obs.add_argument("--report-limit", type=int, help="Native report page size, 1..4096")
    obs.add_argument("--since", help="Return exact changes against a previous concise read_ref")
    items = command("items")
    items.add_argument("--radius", type=int, default=20)
    items.add_argument(
        "--building", dest="building_id", type=int, help="Read visible furniture storage"
    )
    items.add_argument("--type", dest="item_type", help="Filter root items by native item type")
    items.add_argument("--limit", type=int, default=100, help="Root items returned, 1..500")
    items.add_argument("--view", choices=["concise", "full"], default="concise")
    items.add_argument("--since", help="Return changes against a previous item-list read_ref")
    barter = command("barter")
    barter.add_argument("--side", choices=["take", "give"], default="take")
    barter.add_argument("--type", dest="item_type", help="Native item type, e.g. ARMOR")
    barter.add_argument("--limit", type=int, default=20)
    item = command("item")
    item.add_argument("item_id", type=int)
    interrupt = command("interrupt")
    interrupt.add_argument("dispatch_id")
    keys = command("keys")
    navigation = command("navigation")
    navigation.add_argument("--limit", type=int, default=20)
    navigation.add_argument("--view", choices=["concise", "full"], default="concise")
    navigation.add_argument("--since", help="Return changes against a previous navigation read_ref")
    shops = command("shops")
    shops.add_argument(
        "--type", dest="shop_type", help="Native type, e.g. Armorsmith or FoodImports"
    )
    shops.add_argument("--site-id", type=int)
    shops.add_argument("--limit", type=int, default=20)
    shops.add_argument(
        "--stock",
        action="store_true",
        help="Include stock counts and armor materials from native sale allotments; live stock can differ",
    )
    locate = command("locate")
    locate.add_argument("kind", choices=["figure", "artifact"])
    locate.add_argument("id", type=int)
    scan = command("world-scan")
    scan.add_argument("tokens", nargs="*", help="One or more literal search terms")
    scan.add_argument("--match", choices=["any", "type", "name", "flag"], default="any")
    scan.add_argument("--limit", type=int, default=20, help="Maximum matches per term, 1..100")
    scan.add_argument(
        "--tokens",
        dest="catalog",
        action="store_true",
        help="List the running game's native site/subtype and flag tokens",
    )
    keys.add_argument("filter", nargs="?", default="")
    inspect = command("inspect")
    for coord in ("x", "y", "z"):
        inspect.add_argument(coord, type=int)
    ready = command("wait-ready")
    ready.add_argument("--seconds", type=float, default=30)
    ready.add_argument("--action-id")
    run = command("run")
    run.add_argument("args", nargs=argparse.REMAINDER)
    actions = {}
    for name in ("drink", "eat"):
        actions[name] = command(name)
        actions[name].add_argument("item_id", type=int)
        actions[name].add_argument("--portions", type=int, default=1)
    actions["drink"].add_argument(
        "--from-container",
        action="store_true",
        help="Interpret the ID as a container; require equivalent, fully observed liquid contents",
    )
    for name in ("sleep", "rest"):
        actions[name] = command(name)
        actions[name].add_argument("hours", type=int, nargs="?")
        actions[name].add_argument("--until-dawn", dest="until", action="store_const", const="dawn")
    actions["sequence"] = command("sequence")
    actions["sequence"].add_argument("actions_json", help="JSON array, or - to read from stdin")
    actions["converse"] = command("converse")
    actions["converse"].add_argument("unit_ids", type=int, nargs="+")
    actions["converse"].add_argument(
        "--topic",
        dest="topics",
        action="append",
        help="Exact native topic type or full label; repeat for multiple topics",
    )
    actions["converse"].add_argument(
        "--topic-spec",
        dest="topics",
        action="append",
        type=json.loads,
        help="JSON {topic, tact?, subject_hf_id?}; may be mixed with --topic in request order",
    )
    actions["talk"] = command("talk")
    actions["talk"].add_argument("unit_id", type=int)
    actions["talk"].add_argument(
        "--subject-hf-id", type=int, help="Native historical-figure subject for an HF topic"
    )
    topic = actions["talk"].add_mutually_exclusive_group()
    topic.add_argument("--topic", help="Exact native topic type or full label")
    topic.add_argument("--choice-id", help="Native choice ID from observation")
    actions["talk"].add_argument("--tact", help="Explicit native tact, e.g. Persuade or Intimidate")
    actions["talk"].add_argument(
        "--completion",
        choices=["utterance", "reply"],
        help="Verified speech goal; a supplied topic defaults to reply",
    )
    actions["end-conversation"] = command("end-conversation")
    actions["open-trade"] = command("open-trade")
    actions["open-trade"].add_argument("unit_id", type=int)
    actions["open-trade"].add_argument("--shop", dest="shop_id", type=int, required=True)
    actions["close-trade"] = command("close-trade")
    actions["trade"] = command("trade")
    actions["trade"].add_argument("unit_id", type=int)
    actions["trade"].add_argument(
        "--take", type=json.loads, default=[], help="JSON list of item_id/amount pairs to receive"
    )
    actions["trade"].add_argument(
        "--give", type=json.loads, default=[], help="JSON list of item_id/amount pairs to give"
    )
    actions["trade"].add_argument("--offer-currency", type=int, default=0)
    actions["trade"].add_argument("--request-currency", type=int, default=0)
    actions["save-game"] = command("save-game", aliases=["quicksave"])
    actions["save-game"].add_argument("name")
    actions["save-game"].add_argument(
        "--overwrite", action="store_true", help="Replace the existing named checkpoint"
    )
    actions["save-game"].set_defaults(command="save-game")
    actions["combat"] = command("combat")
    actions["combat"].add_argument("unit_id", type=int)
    actions["combat"].add_argument(
        "--option-id", help="Explicit native move ID; further decisions are returned"
    )
    actions["strike"] = command("strike")
    actions["strike"].add_argument("unit_id", type=int)
    actions["strike"].add_argument("--body-part-id", type=int, required=True)
    actions["strike"].add_argument(
        "--item-id", type=int, required=True, help="Weapon item ID; -1 for a natural attack"
    )
    actions["strike"].add_argument("--attack-index", type=int, required=True)
    actions["strike"].add_argument(
        "--style", choices=["normal", "quick", "heavy", "wild", "precise"], required=True
    )
    actions["use-stairs"] = command("use-stairs")
    for name in ("x", "y", "z"):
        actions["use-stairs"].add_argument(name, type=int)
    actions["use-stairs"].add_argument("direction", choices=["up", "down"])
    actions["make-campfire"] = command("make-campfire")
    for name in ("x", "y", "z"):
        actions["make-campfire"].add_argument(name, type=int)
    actions["thaw"] = command("thaw")
    for name in ("container_id", "x", "y", "z"):
        actions["thaw"].add_argument(name, type=int)
    actions["fill-container"] = command("fill-container")
    for name in ("container_id", "x", "y", "z"):
        actions["fill-container"].add_argument(name, type=int)
    actions["fill-container"].add_argument(
        "material", help="Exact native material token, for example WATER"
    )
    actions["fill-container"].add_argument(
        "--source-state", help="Exact native source phase, for example Solid or Liquid"
    )
    actions["drink-from"] = command("drink-from")
    for name in ("x", "y", "z"):
        actions["drink-from"].add_argument(name, type=int)
    actions["drink-from"].add_argument(
        "material", help="Exact native material token, for example WATER"
    )
    actions["drink-from"].add_argument("--portions", type=int, default=1)
    actions["empty-container"] = command("empty-container")
    actions["empty-container"].add_argument("container_id", type=int)
    actions["set-posture"] = command("set-posture")
    actions["set-posture"].add_argument("posture", choices=["standing", "prone"])
    actions["set-gait"] = command("set-gait")
    actions["set-gait"].add_argument("gait")
    actions["set-sneaking"] = command("set-sneaking")
    actions["set-sneaking"].add_argument("enabled", choices=["on", "off"])
    actions["travel-to"] = command("travel-to")
    for name in ("x", "y"):
        actions["travel-to"].add_argument(name, type=int)
    actions["travel-to"].add_argument("--arrival-radius", type=int, default=0)
    actions["end-travel"] = command("end-travel")
    actions["move"] = command("move")
    actions["move"].add_argument(
        "direction", choices=["n", "s", "e", "w", "ne", "nw", "se", "sw", "up", "down"]
    )
    actions["wait"] = command("wait")
    actions["dismiss"] = command("dismiss")
    actions["resume"] = command("resume")
    actions["resume"].add_argument(
        "dispatch_id",
        nargs="?",
        help="Resume this saved workflow, including across client processes",
    )
    for name in ("pickup", "equip", "wield", "remove", "drop", "stow"):
        actions[name] = command(name)
        actions[name].add_argument("item_id", type=int)
    for name in ("equip", "wield"):
        actions[name].add_argument("--replace", type=int, nargs="*", default=[])
        actions[name].add_argument(
            "--disposition", choices=["hold", "drop", "stow"], default="hold"
        )
        actions[name].add_argument("--container-id", type=int)
        actions[name].add_argument("--body-part-id", type=int)
    actions["stow"].add_argument("container_id", type=int)
    actions["walk-to"] = command("walk-to")
    for name in ("x", "y", "z"):
        actions["walk-to"].add_argument(name, type=int)
    actions["walk-to"].add_argument(
        "--allow-occupied",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Allow routes through occupied tiles",
    )
    actions["walk-to"].add_argument("--max-liquid-depth", type=int)
    actions["walk-to"].add_argument("--blocked-tiles", type=json.loads)
    actions["walk-to"].add_argument("--arrival-radius", type=int, default=0)
    actions["walk-to"].add_argument(
        "--extend-route",
        action="store_true",
        default=None,
        help="Reveal the route by advancing through observed tiles",
    )
    for name in (
        "talk",
        "combat",
        "strike",
        "use-stairs",
        "converse",
        "make-campfire",
        "thaw",
        "fill-container",
        "drink-from",
    ):
        actions[name].add_argument(
            "--allow-occupied", action=argparse.BooleanOptionalAction, default=None
        )
        actions[name].add_argument("--max-liquid-depth", type=int)
        actions[name].add_argument("--blocked-tiles", type=json.loads)
        actions[name].add_argument("--extend-route", action="store_true", default=None)
    actions["select-option"] = command("select-option")
    actions["select-option"].add_argument("option_id")
    actions["select-interaction"] = command("select-interaction")
    actions["select-interaction"].add_argument("option_id")
    actions["respond"] = command("respond")
    actions["respond"].add_argument("choice", choices=["continue", "stop", "finish"])
    actions["select-unit"] = command("select-unit")
    actions["select-unit"].add_argument("unit_id", type=int)
    actions["key"] = command("key")
    actions["key"].add_argument("key")
    actions["click"] = command("click")
    actions["click"].add_argument("x", type=int)
    actions["click"].add_argument("y", type=int)
    actions["click"].add_argument("--button", choices=["left", "right", "middle"], default="left")
    actions["choose"] = command("choose")
    actions["choose"].add_argument("label")
    actions["text"] = command("text")
    actions["text"].add_argument("value")
    actions["act"] = command("act")
    actions["act"].add_argument("action_json")
    for action in actions.values():
        # The parser already defines each command's fields. Keep that schema
        # before adding shared execution options instead of maintaining a
        # second, easily forgotten action-field allowlist in main().
        action.set_defaults(
            action_fields=tuple(a.dest for a in action._actions if a.dest != "help")
        )
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
        action.add_argument("--seconds", type=float, help="Override saved dispatch time limit")
        action.add_argument(
            "--interrupt-on",
            dest="dispatch_interrupt_on",
            type=json.loads,
            help="Override controller interruption conditions",
        )
        action.add_argument("--result-format", choices=["compact", "full"])
        action.add_argument(
            "--after", choices=["look"], help="Include the final scene with the receipt"
        )
        action.add_argument("--since", help="Use a previous look read_ref for --after look")
        action.add_argument(
            "--event-detail",
            choices=["task", "all"],
            help="Include all reports or omit counted routine/ambient reports",
        )
        action.add_argument("--text", action="store_true", help="Return a compact text observation")
    for sub in set(subs.choices.values()):
        sub.add_argument(
            "--pretty",
            action="store_true",
            default=argparse.SUPPRESS,
            help="Indent JSON for human reading",
        )
    for name, sub in named.items():
        reference.describe_arguments(sub, name)
    return p


def main(argv=None):
    started_ns = time.perf_counter_ns()
    argv = sys.argv[1:] if argv is None else argv
    args = parser().parse_args(argv)
    defaults = {
        key: getattr(args, key)
        for key in ("mode", "acknowledge", "max_steps", "interrupt_on")
        if getattr(args, key) is not None
    }
    if args.command in (
        "guide",
        "setup",
        "doctor",
        "audit-log",
        "metrics",
        "launch",
        "run",
    ):
        return execute(args)
    try:
        client = Client(
            args.port,
            args.timeout,
            args.log,
            execution=defaults,
            settings_path=args.settings,
            metrics_path=args.metrics_path,
            metrics_run=args.metrics_run,
            metrics_episode=args.episode,
        )
        with client.metrics.interaction(
            "cli", args.command, {"argv": list(argv)}, started_ns=started_ns
        ) as span:
            span.fields["output_format"] = (
                "cli_text" if getattr(args, "text", False) else "cli_json"
            )
            return execute(args, client)
    except (DFHackError, OSError, ValueError, subprocess.SubprocessError) as exc:
        return report_error(exc)


def report_error(exc):
    error = {"ok": False, "error": str(exc)}
    if isinstance(exc, DispatchError):
        error.update(
            code=exc.code,
            dispatch_id=exc.dispatch_id,
            resume_action=exc.resume_action,
            input_sent=exc.input_sent,
            details=exc.details,
        )
    output = json.dumps(error, ensure_ascii=False, separators=(",", ":"))
    span = active()
    if span is not None:
        span.fail(exc)
        span.respond(output + "\n", text=True)
    print(output, file=sys.stderr, flush=True)
    return 1


def execute(args, client=None):
    try:
        if args.command == "guide":
            sys.stdout.write(Path(__file__).with_name("guide.md").read_text(encoding="utf-8"))
            return 0
        if args.command == "setup":
            result = configure(args.setup_port)
        elif args.command == "doctor":
            result = doctor(args.port)
        elif args.command == "audit-log":
            from .audit import audit_logs

            result = audit_logs(args.paths)
        elif args.command == "metrics":
            from .metrics_report import render, report
            from .settings import read_settings, settings_path

            if args.prepare_tokenizer:
                if args.paths or args.baseline or args.run or args.text or args.tokenizer:
                    raise ValueError("Tokenizer preparation is separate from report options")
                from .metrics_tokens import prepare

                print(json.dumps(prepare(args.prepare_tokenizer)))
                return 0
            config = read_settings(args.settings)["measurement"]
            paths = args.paths or [
                settings_path(args.settings).parent
                / Path(config["path"] or "metrics.jsonl").expanduser()
            ]
            result = report(
                paths,
                baseline=args.baseline,
                run=args.run,
                idle_gap=args.idle_gap,
                tokenizer=args.tokenizer,
            )
            if args.text:
                print(render(result))
                return 0
        elif args.command == "launch":
            result = launch(args.direct)
        elif args.command == "run":
            if not args.args:
                raise ValueError("Usage: ./dfctl run COMMAND [ARG ...]")
            sys.stdout.write(
                run_command(*args.args, port=port_for_game(args.port), timeout=args.timeout)
            )
            return 0
        else:
            assert client is not None
            if args.command == "status":
                result = client.status()
            elif args.command == "game-status":
                result = client.game_status()
            elif args.command == "load-game":
                result = client.load_game(args.name, timeout=args.seconds)
            elif args.command == "capabilities":
                result = client.capabilities()
            elif args.command == "actions":
                result = client.actions(args.name, expand=args.expand)
            elif args.command == "brief":
                result = client.brief(since=args.since)
            elif args.command == "unit":
                result = client.unit(args.unit_id, args.view, since=args.since)
            elif args.command == "settings":
                update = args.settings_update
                policy = {
                    k: getattr(args, "setting_" + k)
                    for k in ("mode", "acknowledge", "max_steps", "interrupt_on")
                    if getattr(args, "setting_" + k) is not None
                }
                if policy:
                    update = dict(update or {})
                    update["execution"] = dict(update.get("execution", {}), **policy)
                if args.setting_view is not None:
                    update = dict(update or {}, observation_view=args.setting_view)
                if args.setting_seconds is not None:
                    update = dict(update or {}, dispatch_timeout=args.setting_seconds)
                result = client.settings(update, reset=args.reset)
            elif args.command == "navigation":
                result = client.navigation(args.limit, view=args.view, since=args.since)
            elif args.command == "shops":
                result = client.shops(
                    args.shop_type, site_id=args.site_id, limit=args.limit, stock=args.stock
                )
            elif args.command == "session":
                result = client.session(args.limit)
            elif args.command == "barter":
                result = client.barter(side=args.side, item_type=args.item_type, limit=args.limit)
            elif args.command == "locate":
                result = client.locate(args.kind, args.id)
            elif args.command == "world-scan":
                result = client.world_scan(
                    args.tokens,
                    match=args.match,
                    limit=args.limit,
                    catalog=args.catalog,
                )
            elif args.command == "character-status":
                result = client.character_status()
            elif args.command in ("observe", "look"):
                center = (
                    dict(zip(("x", "y", "z"), args.center, strict=True)) if args.center else None
                )
                result = client.observe(
                    args.width,
                    args.height,
                    center,
                    not args.no_map,
                    args.radius,
                    view=args.view or ("concise" if args.command == "look" else None),
                    event_detail=args.event_detail,
                    reports_after=args.reports_after,
                    report_limit=args.report_limit,
                    since=args.since,
                )
            elif args.command == "items":
                result = client.items(
                    args.radius,
                    building_id=args.building_id,
                    item_type=args.item_type,
                    limit=args.limit,
                    view=args.view,
                    since=args.since,
                )
            elif args.command == "item":
                result = client.item(args.item_id)
            elif args.command == "interrupt":
                result = client.interrupt(args.dispatch_id)
            elif args.command == "dispatch-details":
                result = client.dispatch_details(args.dispatch_id, args.section)
            elif args.command == "keys":
                result = client.request({"op": "keys", "filter": args.filter})
            elif args.command == "inspect":
                result = client.inspect(args.x, args.y, args.z)
            elif args.command == "wait-ready":
                result = client.wait_ready(args.action_id, args.seconds)
            else:
                if args.command in ("act", "sequence"):
                    source = args.action_json if args.command == "act" else args.actions_json
                    raw = sys.stdin.read() if source == "-" else source
                    if source == "-" and active() is not None:
                        active().request["stdin"] = raw
                    value = json.loads(raw)
                    action = (
                        value if args.command == "act" else {"type": "sequence", "actions": value}
                    )
                else:
                    action = {"type": args.command.replace("-", "_")}
                    for key in args.action_fields:
                        if getattr(args, key) is not None:
                            action[key] = getattr(args, key)
                    if args.command == "choose":
                        action = {"type": "click_text", "text": args.label}
                    elif args.command == "text":
                        action = {"type": "text", "text": args.value}
                    elif args.command == "select-unit":
                        action["type"] = "select_unit"
                    elif args.command == "respond":
                        action = {"type": "action_prompt", "choice": args.choice}
                    elif args.command == "set-sneaking":
                        action["enabled"] = args.enabled == "on"
                    elif args.command == "drink" and action.pop("from_container"):
                        action["container_id"] = action.pop("item_id")
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
                    args.event_detail,
                    after=args.after,
                    since=args.since,
                )
        if getattr(args, "text", False) and isinstance(result, dict) and "status" in result:
            output = render_observation(result)
        else:
            output = json.dumps(
                result,
                ensure_ascii=False,
                indent=2 if args.pretty else None,
                separators=None if args.pretty else (",", ":"),
            )
        if active() is not None:
            active().respond(output + "\n", text=True)
        print(output, flush=True)
        return 0
    except (DFHackError, OSError, ValueError, subprocess.SubprocessError) as exc:
        return report_error(exc)
    except KeyboardInterrupt:
        if active() is not None:
            active().outcome = "interrupted"
        print(
            "Interrupted. An in-flight action may have executed; observe before retrying.",
            file=sys.stderr,
        )
        return 130
