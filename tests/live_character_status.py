"""Read-only live verification: python3 -m tests.live_character_status [--port 5001]."""

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

from dfharness.client import ASSETS, Client, lua_string, render_observation
from dfharness.rpc import run_command
from dfharness.state import flatten
from dfharness.views import character_brief


def native_fixtures(port):
    # Real Lua/DF enum bindings with isolated, synthetic character data. No
    # injured units or other test state are inserted into the running world.
    fixtures = []
    for fixture_name, reader_name in (
        ("native_ui.lua", "native_ui.lua"),
        ("wire.lua", "wire.lua"),
        ("session.lua", "session.lua"),
        ("checkpoints.lua", "checkpoints.lua"),
        ("runtime.lua", "runtime.lua"),
        ("screen.lua", "screen.lua"),
        ("hud.lua", "../tests/hud_reference.lua"),
        ("burden.lua", "burden.lua"),
        ("entry.lua", "entry.lua"),
        ("items.lua", "items.lua"),
        ("rest.lua", "rest.lua"),
        ("aim.lua", "aim.lua"),
        ("saving.lua", "saving.lua"),
        ("health.lua", "health.lua"),
        ("unit.lua", "unit.lua"),
        ("progress.lua", "progress.lua"),
        ("attack.lua", "attack.lua"),
        ("reports.lua", "reports.lua"),
        ("report_events.lua", "report_events.lua"),
        ("fastcombat.lua", "fastcombat.lua"),
        ("environment.lua", "environment.lua"),
        ("geography.lua", "geography.lua"),
        ("movement.lua", "movement.lua"),
        ("pathing.lua", "pathing.lua"),
        ("input_guard.lua", "input_guard.lua"),
        ("interactions.lua", "interactions.lua"),
        ("character_reader.lua", "character.lua"),
        ("character_profiles.lua", "character_details.lua"),
        ("character_calculations.lua", "character_calculations.lua"),
    ):
        fixture = Path(__file__).with_name(fixture_name).read_text()
        extra_readers = {
            "checkpoints.lua": ["wire.lua"],
            "interactions.lua": ["native_ui.lua"],
            "movement.lua": ["native_ui.lua"],
            "aim.lua": ["native_ui.lua"],
            "health.lua": ["wire.lua"],
            "attack.lua": ["report_events.lua"],
            "character_calculations.lua": ["burden.lua"],
            "character_profiles.lua": ["health.lua"],
        }
        arguments = [
            lua_string((ASSETS / name).read_text())
            for name in [reader_name, *extra_readers.get(fixture_name, [])]
        ]
        source = (
            "local r=assert(load("
            + lua_string(fixture)
            + "))("
            + ",".join(arguments)
            + ");print('__CHARACTER_TESTS__'..require('json').encode(r,{pretty=false}))"
        )
        output = run_command("lua", source, port=port)
        lines = [
            line[len("__CHARACTER_TESTS__") :]
            for line in output.splitlines()
            if line.startswith("__CHARACTER_TESTS__")
        ]
        assert len(lines) == 1, output
        report = json.loads(lines[0])
        if isinstance(report, dict):
            assert report["passed"] == len(report["tests"]), report
            fixtures.extend(report["tests"])
        else:
            assert isinstance(report, list) and report, report
            fixtures.extend(report)
    return fixtures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int)
    parser.add_argument(
        "--fixtures-only",
        action="store_true",
        help="Run isolated native fixtures while a human is playing",
    )
    args = parser.parse_args()
    game = Client(port=args.port)
    if args.fixtures_only:
        fixtures = native_fixtures(game.port)
        print(
            json.dumps({"passed": len(fixtures), "game_inputs": 0, "fixtures": fixtures}, indent=2)
        )
        return
    before = game.observe(view="full")
    native = game.request({"op": "observe", "ui_mode": "native"})
    for field in (before.keys() | native.keys()) - {"ui", "ui_state_id"}:
        assert native.get(field) == before.get(field), ("native execution read", field)
    if not native["ui"]["captured"]:
        assert "rows" not in native["ui"] and native["ui"]["omitted"]
        assert "ui_state_id" not in native
    result = game.status()
    assert result["available"], result
    assert result["schema_version"] == 2
    character = result["character"]
    expected_sections = {
        "identity",
        "affiliation",
        "health",
        "body",
        "conditions",
        "physiology",
        "appearance",
        "attributes",
        "skills",
        "performance_skills",
        "needs",
        "personality",
        "preferences",
        "inventory",
        "encumbrance",
        "movement",
        "relationships",
        "companions",
        "reputation",
        "career",
        "knowledge",
        "abilities",
        "combat",
        "senses",
        "activity",
        "possessions",
        "obligations",
        "history",
        "native_sheet",
    }
    assert {entry["section"] for entry in character["coverage"]["sections"]} == expected_sections
    assert character["coverage"]["unavailable_count"] == len(character["unavailable"])
    assert character["coverage"]["truncated_count"] == len(character["truncated"])
    # Known unsupported calculations are explicit. Any new native-read error
    # fails verification instead of disappearing among expected limitations.
    expected_unavailable = {
        "movement.displayed_speed",
        "encumbrance.burden",
        "combat.preferences",
        "appearance.description_text",
    }
    if character["encumbrance"]["weight_complete"] is False:
        expected_unavailable.add("encumbrance.total_weight_kg")
        assert character["encumbrance"]["unweighed_items"] or character["truncated"]
    # Validate the native aggregate scan against the independently serialized
    # item graph. A programming/read error must not pass as expected dirty data.
    if not character.get("inventory_truncated") and not any(
        i.get("contents_truncated") for i in flatten(character["inventory"])
    ):
        dirty = {
            root["id"]
            for root in character["inventory"]
            if any(i.get("weight_computed") is not True for i in flatten([root]))
        }
        assert {i.get("id") for i in character["encumbrance"]["unweighed_items"]} == dirty
        assert character["encumbrance"]["weight_complete"] is (not dirty)
    assert {entry["path"] for entry in character["unavailable"]} <= expected_unavailable, character[
        "unavailable"
    ]
    assert character["id"] == before["adventurer"]["id"]
    dawn = character["activity"]["next_dawn"]
    assert dawn["available"], dawn
    assert type(dawn["remaining_calendar_ticks"]) is int
    assert 1 <= dawn["remaining_calendar_ticks"] <= 1200
    assert 0 <= dawn["phase"] < 2400 and dawn["phase"] % 2 == 0
    for field, value in before["adventurer"]["health"].items():
        assert character["health"][field] == value, field
    assert len(character["attributes"]["physical"]) == 6
    assert isinstance(character["health"]["flags"]["on_ground"], bool)
    assert "# Inventory" in render_observation(result)
    encumbrance = character["encumbrance"]
    if encumbrance["weight_complete"]:
        assert encumbrance["unweighed_root_item_count"] == 0
        assert "Carried weight:" in render_observation(result)
        if not character.get("inventory_truncated"):
            roots = {item["id"]: item for item in character["inventory"]}
            assert all(item["weight_computed"] for item in roots.values())
            expected = (
                sum(
                    item["weight_raw"]["whole"] * 1_000_000 + item["weight_raw"]["fraction"]
                    for item in roots.values()
                )
                / 1_000_000
            )
            assert math.isclose(encumbrance["total_weight_kg"], expected)
    else:
        assert "total_weight_kg" not in encumbrance
    assert encumbrance["capacity"]["available"] and encumbrance["load_penalty"]["available"]
    burden = encumbrance["burden"]
    assert burden["source"] == "dfhack_lua_unit_burden"
    if burden["available"]:
        assert burden["label"] in ("Unburdened", "Burdened", "Overburdened")
        assert "Burden: " + burden["label"] in render_observation(result)
    else:
        assert burden["reason"] and "label" not in burden
    assert burden["compared_weight_kg"] == encumbrance["load_penalty"]["compared_weight_kg"]
    calculated = character["movement"]["effective_speed"]
    assert calculated["available"]
    assert math.isclose(calculated["value"], 1000 / calculated["movement_delay"])
    assert math.isclose(
        encumbrance["load_penalty"]["speed_reduction_percent"],
        100 * (1 - calculated["value"] / calculated["unloaded"]["value"]),
        abs_tol=1e-10,
    )
    needs = character["physiology"]["interpreted_needs"]
    assert needs["available"]
    for key, field in (
        ("hunger", "hunger_timer"),
        ("thirst", "thirst_timer"),
        ("sleep", "sleepiness_timer"),
    ):
        assert needs[key]["available"] and needs[key]["counter"] == character["health"][field]
        if "next_stage" in needs[key]:
            assert needs[key]["next_stage"]["remaining_counter"] > 0
    displayed = character["movement"].get("displayed_speed")
    if displayed:
        assert any(row["text"].strip() == displayed["text"] for row in before["ui"]["rows"])
        assert displayed["source"] == "ui_character_layer"
        assert calculated["displayed_text"] == displayed["text"], (calculated, displayed)

    # A separate process exercises CLI argument handling and the transport.
    for command in ("status", "character-status"):
        cli = subprocess.run(
            [sys.executable, str(ASSETS.parent / "dfctl"), "--port", str(game.port), command],
            check=True,
            text=True,
            capture_output=True,
        )
        cli_character = json.loads(cli.stdout)["character"]
        assert cli_character == character, command
    assert game.character_status()["character"] == character
    brief = game.brief()
    projected = character_brief(result)
    for field, value in projected["character"].items():
        if field not in {"full_report_coverage", "unavailable", "truncated"}:
            assert brief["character"].get(field) == value, ("native brief", field)
    assert "full_report_coverage" not in brief["character"]
    assert len(brief["omitted_sections"]) == 20
    assert {e["path"] for e in brief["character"]["unavailable"]} <= {
        e["path"] for e in character["unavailable"]
    }
    assert "character" not in game.game_status()
    fixtures = native_fixtures(game.port)
    after = game.observe(view="full")
    for field in (
        "action_serial",
        "world_frame",
        "year",
        "year_tick",
        "position",
        "focus",
        "open_panels",
        "modal",
    ):
        assert before["status"].get(field) == after["status"].get(field), field
    assert before["adventurer"]["health"] == after["adventurer"]["health"]
    assert before["adventurer"]["inventory"] == after["adventurer"]["inventory"]
    print(
        json.dumps(
            {
                "character": character["name"],
                "id": character["id"],
                "read_only_verified": True,
                "schema_version": result["schema_version"],
                "section_count": len(expected_sections),
                "total_weight_kg": encumbrance.get("total_weight_kg"),
                "displayed_speed": displayed,
                "capacity": encumbrance["capacity"],
                "load_penalty": encumbrance["load_penalty"],
                "burden": encumbrance["burden"],
                "calculated_speed": calculated,
                "interpreted_needs": needs,
                "lua_fixtures": fixtures,
                "unavailable": character["unavailable"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
