"""Read-only live verification: python3 -m tests.live_character_status [--port 5001]."""

import argparse
import json
import math
from pathlib import Path
import subprocess
import sys

from dfharness.client import ASSETS, Client, lua_string, render_observation
from dfharness.mcp import Server
from dfharness.rpc import run_command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    game = Client(port=args.port)
    before = game.observe()
    result = game.status()
    assert result["available"], result
    assert result["schema_version"] == 2
    character = result["character"]
    expected_sections = {"identity", "affiliation", "health", "body", "conditions", "physiology", "appearance",
                         "attributes", "skills", "performance_skills", "needs", "personality", "preferences",
                         "inventory", "encumbrance", "movement", "relationships", "companions", "reputation",
                         "career", "knowledge", "abilities", "combat", "senses", "activity", "possessions",
                         "obligations", "history", "native_sheet"}
    assert {entry["section"] for entry in character["coverage"]["sections"]} == expected_sections
    assert character["coverage"]["unavailable_count"] == len(character["unavailable"])
    assert character["coverage"]["truncated_count"] == len(character["truncated"])
    # Known unsupported calculations are explicit. Any new native-read error
    # fails verification instead of disappearing among expected limitations.
    expected_unavailable = {"movement.displayed_speed", "combat.preferences",
                            "appearance.description_text"}
    assert {entry["path"] for entry in character["unavailable"]} <= expected_unavailable, character["unavailable"]
    assert character["id"] == before["adventurer"]["id"]
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
            expected = sum(item["weight_raw"]["whole"] * 1_000_000 + item["weight_raw"]["fraction"]
                           for item in roots.values()) / 1_000_000
            assert math.isclose(encumbrance["total_weight_kg"], expected)
    else:
        assert "total_weight_kg" not in encumbrance
    assert encumbrance["capacity"]["available"] and encumbrance["load_penalty"]["available"]
    assert encumbrance["burden"]["available"]
    assert encumbrance["burden"]["compared_weight_kg"] == encumbrance["load_penalty"]["compared_weight_kg"]
    assert "Burden: " + encumbrance["burden"]["label"] in render_observation(result)
    calculated = character["movement"]["effective_speed"]
    assert calculated["available"]
    assert math.isclose(calculated["value"], 1000 / calculated["movement_delay"])
    assert math.isclose(encumbrance["load_penalty"]["speed_reduction_percent"],
                        100 * (1 - calculated["value"] / calculated["unloaded"]["value"]), abs_tol=1e-10)
    needs = character["physiology"]["interpreted_needs"]
    assert needs["available"]
    for key, field in (("hunger", "hunger_timer"), ("thirst", "thirst_timer"), ("sleep", "sleepiness_timer")):
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
        cli = subprocess.run([sys.executable, str(ASSETS.parent / "dfctl"), "--port", str(game.port),
                              command], check=True, text=True, capture_output=True)
        cli_character = json.loads(cli.stdout)["character"]
        assert cli_character == character, command
    assert game.character_status()["character"] == character
    assert "character" not in game.game_status()
    server = Server(game)
    server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    for tool in ("df_status", "df_character_status", "df_game_status"):
        response = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                  "params": {"name": tool, "arguments": {}}})["result"]
        assert not response["isError"], response
        value = json.loads(response["content"][0]["text"])
        if tool == "df_game_status":
            assert "character" not in value
        else:
            assert value["character"] == character, tool

    # Real Lua/DF enum bindings with isolated, synthetic character data. No
    # injured units or other test state are inserted into the running world.
    fixtures = []
    for fixture_name, reader_name in (("character_reader.lua", "character.lua"),
                                      ("character_profiles.lua", "character_details.lua"),
                                      ("character_calculations.lua", "character_calculations.lua")):
        fixture = Path(__file__).with_name(fixture_name).read_text()
        source = ("local r=assert(load(" + lua_string(fixture) + "))(" +
                  lua_string((ASSETS / reader_name).read_text()) +
                  ");print('__CHARACTER_TESTS__'..require('json').encode(r,{pretty=false}))")
        output = run_command("lua", source, port=game.port)
        lines = [line[len("__CHARACTER_TESTS__"):] for line in output.splitlines() if line.startswith("__CHARACTER_TESTS__")]
        assert len(lines) == 1, output
        report = json.loads(lines[0])
        if isinstance(report, dict):
            assert report["passed"] == len(report["tests"]), report
            fixtures.extend(report["tests"])
        else:
            assert isinstance(report, list) and report, report
            fixtures.extend(report)
    after = game.observe()
    for field in ("action_serial", "world_frame", "year", "year_tick", "position", "focus", "open_panels", "modal"):
        assert before["status"].get(field) == after["status"].get(field), field
    assert before["adventurer"]["health"] == after["adventurer"]["health"]
    assert before["adventurer"]["inventory"] == after["adventurer"]["inventory"]
    print(json.dumps({"character": character["name"], "id": character["id"], "read_only_verified": True,
                      "schema_version": result["schema_version"], "section_count": len(expected_sections),
                      "total_weight_kg": encumbrance.get("total_weight_kg"), "displayed_speed": displayed,
                      "capacity": encumbrance["capacity"], "load_penalty": encumbrance["load_penalty"], "burden": encumbrance["burden"],
                      "calculated_speed": calculated, "interpreted_needs": needs,
                      "lua_fixtures": fixtures, "unavailable": character["unavailable"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
