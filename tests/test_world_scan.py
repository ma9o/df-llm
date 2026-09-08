import io
import json
import unittest
from copy import deepcopy
from typing import Any
from unittest.mock import patch

from dfharness.cli import main
from dfharness.client import Client
from dfharness.world_scan import attach_stock, search


def site(id, type="Cave", name="Stone", x=0, y=0, **extra) -> dict[str, Any]:
    return {
        "id": id,
        "type": type,
        "name": name,
        "position": {"x": x, "y": y, "z": 0},
        "flags": [],
        **extra,
    }


def snapshot(sites, **extra) -> dict[str, Any]:
    return {
        "available": True,
        "complete": True,
        "format": "world_site_snapshot",
        "sites": sites,
        "total": len(sites),
        "scanned": len(sites),
        "truncated": False,
        "error_count": 0,
        **extra,
    }


class WorldScanTests(unittest.TestCase):
    def test_material_search_preserves_partial_hits_and_unknowns_without_matching_names(self):
        data = snapshot(
            [
                site(0, "Town", "Steelromance", stock={"matched": False, "complete": True}),
                site(1, "Town", "Distant", x=100, stock={"matched": True, "complete": True}),
                site(2, "Town", stock={"matched": False, "complete": False}),
                site(3, "Town", stock={"matched": True, "complete": False}),
            ],
            material="INORGANIC:STEEL",
            origin={"x": 0, "y": 0},
        )
        before = deepcopy(data)
        result = search(data, [], material="STEEL", limit=1)["results"][0]
        self.assertEqual(result["material"], "INORGANIC:STEEL")
        self.assertEqual(result["total"], 2)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["matches"][0]["id"], 3)
        self.assertFalse(result["complete"])
        self.assertEqual(result["unknown"], 2)
        self.assertEqual(data, before)
        self.assertTrue(search(data, ["Cave"], match="type", material="STEEL")["complete"])

    def test_material_can_be_combined_with_market_flags_and_known_zero_excludes_unknown_flags(self):
        data = snapshot(
            [
                site(0, flags=["HAS_MARKET"], stock={"matched": True, "complete": True}),
                site(1, stock={"matched": True, "complete": True}),
                site(2, flags_unavailable="missing", stock={"matched": False, "complete": True}),
            ],
            material="INORGANIC:STEEL",
        )
        result = search(data, ["HAS_MARKET"], match="flag", material="STEEL")["results"][0]
        self.assertEqual([row["id"] for row in result["matches"]], [0])
        self.assertTrue(result["complete"])
        self.assertEqual(result["token"], "HAS_MARKET")

    def test_world_material_scan_covers_every_site_despite_a_small_result_limit(self):
        data = snapshot([site(i, x=i) for i in range(67)], world={"epoch": "world"})
        calls = []

        def request(payload):
            calls.append(payload)
            if payload["op"] == "world_sites":
                return deepcopy(data)
            self.assertEqual(payload["world_epoch"], "world")
            self.assertEqual(payload["material"], "STEEL")
            return {
                "available": True,
                "world_epoch": "world",
                "material": "INORGANIC:STEEL",
                "sites": [
                    {"id": id, "stock": {"matched": id == 66, "complete": True}}
                    for id in payload["site_ids"]
                ],
            }

        with patch.object(Client, "request", side_effect=request):
            result = Client(port=1).world_scan(material=" STEEL ", limit=1)
        self.assertEqual([len(c["site_ids"]) for c in calls[1:]], [32, 32, 3])
        self.assertEqual(result["results"][0]["matches"][0]["id"], 66)
        self.assertTrue(result["complete"])
        self.assertNotIn("stock", data["sites"][0])

    def test_world_replacement_missing_batch_and_unavailable_material_never_claim_success(self):
        data = snapshot([site(0)], world={"epoch": "world"})
        for response in (
            {"available": True, "world_epoch": "changed"},
            {"available": True, "world_epoch": "world", "material": "INORGANIC:STEEL", "sites": []},
        ):
            with self.subTest(response=response), self.assertRaises(ValueError):
                attach_stock(data, "STEEL", lambda _payload, value=response: value)
        result = attach_stock(
            data, "typo", lambda _payload: {"available": False, "reason": "Unknown material"}
        )
        self.assertFalse(result["available"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["reason"], "Unknown material")

    def test_unknown_material_readings_report_bounded_actionable_errors(self):
        data = snapshot([site(i) for i in range(10)], world={"epoch": "world"})

        def request(payload):
            return {
                "available": True,
                "world_epoch": "world",
                "material": "INORGANIC:STEEL",
                "sites": [
                    {
                        "id": id,
                        "stock": {
                            "matched": False,
                            "complete": False,
                            "resource_pile": {
                                "complete": False,
                                "error_count": 1,
                                "errors": [{"context": "ARMOR_BODY", "reason": "Missing source"}],
                            },
                        },
                    }
                    for id in payload["site_ids"]
                ],
            }

        result = search(attach_stock(data, "STEEL", request), [], material="STEEL")
        self.assertEqual(result["material_unavailable_count"], 10)
        self.assertEqual(len(result["material_unavailable"]), 8)
        self.assertEqual(result["results"][0]["unknown"], 10)
        self.assertFalse(result["complete"])

    def test_material_validation_precedes_game_access_and_cli_accepts_material_only(self):
        client = Client(port=1)
        with patch.object(client, "request") as request:
            for material in ("", " ", False, 4, "x" * 201):
                with self.subTest(material=material), self.assertRaises(ValueError):
                    client.world_scan(material=material)
            with self.assertRaises(ValueError):
                client.world_scan(material="STEEL", catalog=True)
            request.assert_not_called()
        with (
            patch.object(Client, "world_scan", return_value={}) as scan,
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            self.assertEqual(main(["--port", "1", "world-scan", "--material", "STEEL"]), 0)
            scan.assert_called_once_with([], match="any", limit=20, catalog=False, material="STEEL")

    def test_native_flags_distinguish_market_settlements_from_hamlets_and_names(self):
        data = snapshot(
            [
                site(0, "Town", "Has_market"),
                site(1, "Town", flags=["HAS_MARKET", "SETTLED"]),
                site(2, "Town", flags=["HAS_MARKET", "RUINED", "FUTURE_FLAG", "CITY"]),
            ]
        )
        results = search(data, ["has-market", "ruined", "future_flag"], match="flag")["results"]
        self.assertEqual([[m["id"] for m in r["matches"]] for r in results], [[1, 2], [2], [2]])
        self.assertTrue(all(r["complete"] for r in results))
        self.assertEqual(search(data, ["CITY"], match="flag")["results"][0]["total"], 1)
        self.assertEqual(search(data, ["HAS_MARKET"])["results"][0]["total"], 3)
        self.assertEqual(search(data, ["HAS_MARKET"], match="type")["results"][0]["total"], 0)
        self.assertEqual(search(data, ["HAS_MARKET"], match="name")["results"][0]["total"], 1)

    def test_unreadable_or_omitted_flags_are_unknown_only_when_needed_for_matching(self):
        missing = site(0, "Town")
        del missing["flags"]
        data = snapshot([missing, site(1, "Town", flags_unavailable="bad native field")])
        result = search(data, ["HAS_MARKET"], match="flag")["results"][0]
        self.assertFalse(result["complete"])
        self.assertEqual(result["unknown"], 2)
        self.assertEqual(result["matches"], [])
        self.assertFalse(search(data, ["HAS_MARKET"])["complete"])
        self.assertTrue(search(data, ["Town"])["complete"])
        self.assertTrue(search(data, ["Cave"], match="type")["complete"])
        self.assertTrue(search(data, ["absent"], match="name")["complete"])

    def test_native_types_subtypes_aliases_and_literal_unicode_names(self):
        data = snapshot(
            [
                site(0, "Town", "The Cave [1]"),
                site(1, "MountainHalls"),
                site(2, "LairShrine", subtype="SIMPLE_BURROW"),
                site(3, "ForestRetreat", "English", native_name="Straße Áthis"),
                site(4, "FutureSiteType"),
            ]
        )
        types = search(
            data,
            ["city", "CAVE_DETAILED", "lair", "simple-burrow", "TREE_CITY", "FutureSiteType"],
            match="type",
        )
        self.assertEqual(
            [[m["id"] for m in r["matches"]] for r in types["results"]],
            [[0], [1], [2], [2], [3], [4]],
        )
        result = search(data, [" CAVE ", "STRASSE", "áTHIS", "[1]", ".*"], match="name")
        self.assertEqual(
            [[m["id"] for m in r["matches"]] for r in result["results"]], [[0], [3], [3], [0], []]
        )
        self.assertEqual(result["results"][0]["token"], "CAVE")
        self.assertEqual(search(data, ["CAVE"], match="type")["results"][0]["total"], 0)
        self.assertEqual(search(data, ["CAVE"])["results"][0]["total"], 1)

    def test_search_preserves_global_order_counts_and_zero_without_mutation(self):
        data = snapshot(
            [site(i, x=i % 7, y=i % 3) for i in reversed(range(101))], origin={"x": 0, "y": 0}
        )
        before = deepcopy(data)
        serial = search(data, ["CAVE", "Stone", "absent"], limit=5)
        self.assertEqual(data, before)
        caves = serial["results"][0]
        self.assertEqual(caves["total"], 101)
        self.assertTrue(caves["truncated"])
        self.assertTrue(caves["complete"])
        self.assertEqual([r["id"] for r in caves["matches"]], [0, 21, 42, 63, 84])
        self.assertEqual(caves["matches"][0]["distance"], 0)
        self.assertEqual(caves["matches"][0]["position"]["z"], 0)

    def test_missing_origin_sorts_ids_and_partial_scans_never_claim_complete_absence(self):
        data = snapshot([site(5, x=0), site(0, x=500)])
        result = search(data, ["CAVE"])
        self.assertEqual([r["id"] for r in result["results"][0]["matches"]], [0, 5])
        self.assertNotIn("distance", result["results"][0]["matches"][0])
        data.update(
            complete=False,
            truncated=True,
            total=40000,
            error_count=1,
            errors=[{"index": 2, "reason": "unreadable"}],
        )
        result = search(data, ["SHRINE"])
        self.assertFalse(result["complete"])
        self.assertTrue(result["truncated"])
        self.assertEqual(result["results"][0]["unknown"], 1)
        self.assertEqual(result["errors"], data["errors"])
        self.assertFalse(result["results"][0]["complete"])

    def test_subtype_failures_distinguish_unknown_from_an_absent_optional_record(self):
        data = snapshot(
            [
                site(0, "LairShrine", subtype_present=False),
                site(1, "LairShrine", subtype_present=True, subtype_unavailable="unknown enum"),
            ]
        )
        result = search(data, ["SIMPLE_BURROW", "LAIR"], match="type")
        self.assertFalse(result["complete"])
        self.assertEqual(result["results"][0]["unknown"], 1)
        self.assertFalse(result["results"][0]["complete"])
        self.assertTrue(result["results"][1]["complete"])
        self.assertEqual(result["results"][1]["total"], 2)
        self.assertTrue(search(data, ["Stone"], match="name")["complete"])

    def test_empty_world_and_unavailable_world_differ(self):
        empty = search(snapshot([]), ["CAVE"])
        unavailable = search({"available": False, "reason": "No world is loaded"}, ["CAVE"])
        self.assertEqual(
            empty["results"][0],
            {"token": "CAVE", "matches": [], "total": 0, "truncated": False, "complete": True},
        )
        self.assertFalse(unavailable["available"])
        self.assertNotIn("results", unavailable)

    def test_client_and_cli_share_one_native_read_with_no_input_or_status_queries(self):
        data = snapshot([site(0)])
        with patch.object(Client, "request", return_value=data) as request:
            expected = Client(port=1).world_scan(" CAVE ", limit=3)
            request.assert_called_once_with({"op": "world_sites"})
            request.reset_mock()
            with patch("sys.stdout", new_callable=io.StringIO) as output:
                self.assertEqual(main(["--port", "1", "world-scan", "CAVE", "--limit", "3"]), 0)
            request.assert_called_once_with({"op": "world_sites"})
            self.assertEqual(json.loads(output.getvalue()), expected)
        self.assertNotIn("sites", expected)

    def test_validation_happens_before_game_access_and_catalog_is_native(self):
        client = Client(port=1)
        with patch.object(client, "request") as request:
            for tokens, kwargs in (
                (None, {}),
                ([], {}),
                ([""], {}),
                ([" "], {}),
                ([0], {}),
                (["x"] * 33, {}),
                (["x" * 201], {}),
                ("CAVE", {"match": "regex"}),
                ("CAVE", {"limit": 0}),
                ("CAVE", {"limit": True}),
                ("CAVE", {"catalog": 1}),
                ("CAVE", {"catalog": True}),
            ):
                with self.subTest(tokens=tokens, kwargs=kwargs), self.assertRaises(ValueError):
                    client.world_scan(tokens, **kwargs)
            request.assert_not_called()
        catalog = {
            "available": True,
            "tokens": {"site": ["FutureSite"]},
            "sites": [],
            "errors": [],
            "error_count": 0,
        }
        with (
            patch.object(Client, "request", return_value=catalog) as request,
            patch("sys.stdout", new_callable=io.StringIO) as output,
        ):
            self.assertEqual(main(["--port", "1", "world-scan", "--tokens"]), 0)
        request.assert_called_once_with({"op": "world_sites", "catalog": True})
        self.assertEqual(
            json.loads(output.getvalue()), {"available": True, "tokens": {"site": ["FutureSite"]}}
        )
