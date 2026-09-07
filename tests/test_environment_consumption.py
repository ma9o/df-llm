import io
import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from dfharness.cli import main
from dfharness.workflows import validate_action
from tests.support import Bridge
from tests.support import FullClient as Client
from tests.test_workflows import scene

SOURCE = {"x": 2, "y": 1, "z": 0}
ACTION = {"type": "drink_from", **SOURCE, "material": "WATER"}


def option(key="water", *, position=SOURCE, material="WATER", phase="Liquid"):
    return {
        "id": key,
        "kind": "NONE",
        "operation": "ingest_material",
        "native_class": "adventure_environment_ingest_materialst",
        "player_position": {"x": 1, "y": 1, "z": 0},
        "target_position": position,
        "material_ref": {"token": material, "state": phase},
        "visible": True,
    }


def source_scene(name, *, options=None, thirst=100, reports=(), frame=0, x=1):
    menu = (
        {"kind": "inventory", "context_name": "EAT_DRINK", "options": options}
        if options is not None
        else None
    )
    view = scene(name, choices=menu, x=x, reports=reports)
    view["status"].update(world_frame=frame, local_map_epoch="local-1")
    view["adventurer"]["health"]["thirst_timer"] = thirst
    view["input_guard"] = {"native_complete": True}
    return view


def report(number=1, kind="DRINK_ITEM"):
    return {"id": number, "type": kind, "text": "Native consumption report"}


class EnvironmentalConsumptionTests(unittest.TestCase):
    def client(self, bridge):
        client = Client(port=1, execution={"mode": "complete", "acknowledge": True})
        patched = patch.object(client, "request", side_effect=bridge)
        patched.start()
        self.addCleanup(patched.stop)
        return client

    def test_direct_source_opens_native_menu_and_returns_verified_portion_once(self):
        bridge = Bridge(
            source_scene("start"),
            [
                source_scene("menu", options=[option()]),
                source_scene("drank", thirst=0, reports=[report()], frame=1),
            ],
        )
        receipt = self.client(bridge).act(ACTION, result_format="compact")
        self.assertEqual(receipt["outcome"], "completed")
        self.assertEqual(
            bridge.inputs,
            [
                {"type": "key", "key": "A_INV_EATDRINK"},
                {"type": "select_option", "option_id": "water"},
            ],
        )
        self.assertEqual(
            receipt["values"],
            [
                {
                    "kind": "drink_from",
                    "position": SOURCE,
                    "material": "WATER",
                    "source_state": "Liquid",
                    "portions_consumed": 1,
                }
            ],
        )
        self.assertNotIn("choices", receipt)
        self.assertLess(len(json.dumps(receipt)), 1400)

    def test_frozen_source_stops_without_selecting_and_shows_only_that_tiles_choice(self):
        options = [
            option("other-tile", position={**SOURCE, "x": 3}),
            option("snow", phase="Powder"),
        ]
        bridge = Bridge(source_scene("snow", options=options))
        receipt = self.client(bridge).act(ACTION, result_format="compact")
        self.assertEqual(receipt["outcome"], "needs_input")
        self.assertEqual(bridge.inputs, [])
        self.assertEqual(receipt["choices"]["omitted_options"], 1)
        self.assertEqual(receipt["choices"]["options"]["NONE"][0]["id"], "snow")
        self.assertEqual(receipt["blocker"]["facts"]["source_state"], "Liquid")

    def test_wrong_material_duplicate_sources_and_incomplete_source_data_do_not_select(self):
        damaged = option()
        damaged["details_unavailable"] = "Failed native material read"
        different = option("different-class")
        different["native_class"] = "unverified_ingestion_class"
        for options in ([option(material="MILK")], [option(), different], [damaged]):
            with self.subTest(options=options):
                bridge = Bridge(source_scene("blocked", options=options))
                self.assertEqual(
                    self.client(bridge).act(ACTION)["dispatch"]["outcome"], "needs_input"
                )
                self.assertEqual(bridge.inputs, [])

    def test_native_water_material_aliases_do_not_require_an_extra_controller_choice(self):
        first, second = option("snow-water"), option("ice-water")
        first["material_ref"]["index"] = -1
        second["material_ref"]["index"] = 0
        bridge = Bridge(
            source_scene("before", options=[first, second]),
            [source_scene("drank", thirst=0, reports=[report()], frame=1)],
        )
        result = self.client(bridge).act(ACTION)["dispatch"]
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(bridge.inputs, [{"type": "select_option", "option_id": "snow-water"}])

    def test_missing_or_partial_effect_is_never_replayed_on_resume(self):
        for thirst, reports in (
            (0, []),
            (101, [report()]),
            (0, [report(kind="CONSUME_FAILURE")]),
            (0, [report(), report(2)]),
        ):
            with self.subTest(thirst=thirst, reports=reports):
                bridge = Bridge(
                    source_scene("before", options=[option()]),
                    [source_scene("unverified", thirst=thirst, reports=reports, frame=1)],
                )
                client = self.client(bridge)
                first = client.act(ACTION)["dispatch"]
                self.assertEqual(first["outcome"], "no_effect")
                self.assertEqual(
                    client.act(first["resume_action"])["dispatch"]["outcome"], "no_effect"
                )
                self.assertEqual(len(bridge.inputs), 1)

    def test_late_effect_resume_completes_without_resubmitting_the_drink(self):
        bridge = Bridge(
            source_scene("before", options=[option()]),
            [source_scene("not-yet", thirst=101, frame=1)],
        )
        client = self.client(bridge)
        first = client.act(ACTION)["dispatch"]
        self.assertEqual(first["outcome"], "no_effect")
        bridge.view = source_scene("late", thirst=0, reports=[report()], frame=2)
        self.assertEqual(client.act(first["resume_action"])["dispatch"]["outcome"], "completed")
        self.assertEqual(len(bridge.inputs), 1)

    def test_fullness_warning_does_not_erase_verified_drinking(self):
        warning = report(2, "CONSUME_FAILURE")
        warning["text"] = "You are starting to feel full."
        bridge = Bridge(
            source_scene("before", options=[option()]),
            [source_scene("drank", thirst=1, reports=[report(), warning], frame=1)],
        )
        client = self.client(bridge)
        receipt = client.act(ACTION, result_format="compact")
        self.assertEqual(receipt["outcome"], "completed")
        self.assertEqual(receipt["values"][0]["portions_consumed"], 1)
        self.assertIn(warning, receipt["events"])
        self.assertEqual(len(bridge.inputs), 1)

    def test_multiple_portions_resume_from_observed_consumption(self):
        bridge = Bridge(
            source_scene("before", options=[option()]),
            [source_scene("one", thirst=0, reports=[report()], frame=1)],
        )
        client = self.client(bridge)
        first = client.act(dict(ACTION, portions=2), execution={"max_steps": 1})["dispatch"]
        self.assertEqual(first["outcome"], "limit_reached")
        self.assertEqual(first["progress"]["portions_consumed"], 1)
        bridge.views.extend(
            [
                source_scene("again", options=[option()], thirst=0, reports=[report()], frame=1),
                source_scene("two", thirst=0, reports=[report(), report(2)], frame=2),
            ]
        )
        final = client.act(first["resume_action"])["dispatch"]
        self.assertEqual(final["outcome"], "completed")
        self.assertEqual(final["details"]["value"]["portions_consumed"], 2)
        self.assertEqual(len(bridge.inputs), 3)

    def test_health_interruption_preserves_the_consumed_portion(self):
        after = source_scene("hurt", thirst=0, reports=[report()], frame=1)
        after["adventurer"]["health"]["blood_count"] -= 1
        bridge = Bridge(source_scene("before", options=[option()]), [after])
        client = self.client(bridge)
        first = client.act(ACTION, execution={"interrupt_on": {"blood_loss": True}})["dispatch"]
        self.assertEqual(first["outcome"], "interrupted")
        self.assertEqual(client.act(first["resume_action"])["dispatch"]["outcome"], "completed")
        self.assertEqual(len(bridge.inputs), 1)

    def test_unknown_counter_and_truncated_choice_list_block_before_consumption(self):
        for counter in (None, False, -1):
            bridge = Bridge(source_scene("unknown", options=[option()], thirst=counter))
            self.assertEqual(self.client(bridge).act(ACTION)["dispatch"]["outcome"], "needs_input")
            self.assertEqual(bridge.inputs, [])
        view = source_scene("partial", options=[option()])
        view["menu"]["truncated"] = True
        bridge = Bridge(view)
        self.assertEqual(self.client(bridge).act(ACTION)["dispatch"]["outcome"], "needs_input")
        self.assertEqual(bridge.inputs, [])

    def test_reset_then_ticking_is_verified_but_map_epoch_change_does_not_prove_reset(self):
        before = source_scene("before", options=[option()], thirst=1, frame=10)
        after = source_scene("after", thirst=2, frame=13, reports=[report()])
        bridge = Bridge(before, [after])
        self.assertEqual(self.client(bridge).act(ACTION)["dispatch"]["outcome"], "completed")
        changed = deepcopy(after)
        changed["status"]["local_map_epoch"] = "different-map"
        bridge = Bridge(before, [changed])
        self.assertEqual(self.client(bridge).act(ACTION)["dispatch"]["outcome"], "no_effect")

    def test_route_rebase_keeps_the_original_source_tile(self):
        before = source_scene("before")
        before["status"]["map_origin"] = {"x": 100, "y": 0, "z": 0}
        rebased = source_scene("rebase")
        rebased["status"]["map_origin"] = {"x": 101, "y": 0, "z": 0}
        opened = source_scene("menu", options=[option(position=SOURCE)])
        opened["status"]["map_origin"] = rebased["status"]["map_origin"]
        done = source_scene("drank", thirst=0, reports=[report()], frame=1)
        done["status"]["map_origin"] = rebased["status"]["map_origin"]
        bridge = Bridge(before, [rebased, opened, done])
        receipt = self.client(bridge).act(dict(ACTION, x=3))["dispatch"]
        self.assertEqual(receipt["outcome"], "completed")
        self.assertEqual(receipt["details"]["value"]["position"], SOURCE)
        self.assertTrue(
            any(
                call.get("route_target") == {"absolute": {"x": 103, "y": 1, "z": 0}}
                for call in bridge.calls
            )
        )

    def test_validation_and_cli_preserve_source_portions_and_route_policy(self):
        for changes in (
            {"material": ""},
            {"x": -1},
            {"portions": False},
            {"portions": 33},
            {"source_state": "Powder"},
            {"container_id": 1},
        ):
            with self.assertRaises(ValueError):
                validate_action(dict(ACTION, **changes))
        with (
            patch("dfharness.cli.Client") as constructor,
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            constructor.return_value.act.return_value = {}
            self.assertEqual(
                main(
                    [
                        "drink-from",
                        "2",
                        "1",
                        "0",
                        "WATER",
                        "--portions",
                        "3",
                        "--max-liquid-depth",
                        "0",
                    ]
                ),
                0,
            )
            action = constructor.return_value.act.call_args.args[0]
        self.assertEqual(action["type"], "drink_from")
        self.assertEqual(action["material"], "WATER")
        self.assertEqual(action["portions"], 3)
        self.assertEqual(action["max_liquid_depth"], 0)


if __name__ == "__main__":
    unittest.main()
