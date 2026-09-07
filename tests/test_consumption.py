import unittest
from unittest.mock import patch

from dfharness.workflows import validate_action
from tests.support import Bridge
from tests.support import FullClient as Client
from tests.test_workflows import item, menu, scene


def water_scene(name, portions=2, thirst=100000, opened=False, reports=()):
    liquid = dict(item(10), type="LIQUID_MISC", stack_size=portions)
    v = scene(
        name,
        carried=[liquid] if portions else [],
        choices=menu("EAT_DRINK_ITEM", [10]) if opened else None,
        reports=reports,
    )
    v["adventurer"]["health"]["thirst_timer"] = thirst
    return v


def drank(number):
    return {"id": number, "type": "DRINK_ITEM", "text": "You drink water."}


def pooled_water_scene(name, ids, thirst=100000, opened=False, reports=()):
    liquids = [
        dict(
            item(i, container=20),
            type="LIQUID_MISC",
            subtype=-1,
            wear=0,
            contaminants=[],
            material_ref={"token": "WATER"},
            stack_size=1,
        )
        for i in ids
    ]
    v = water_scene(name, thirst=thirst, reports=reports)
    v["adventurer"]["inventory"] = [dict(item(20), contents=liquids)]
    v["menu"] = menu("EAT_DRINK_ITEM", ids) if opened else None
    v["status"]["can_move"] = not opened
    return v


class ConsumptionTests(unittest.TestCase):
    def test_equivalent_liquid_stacks_share_portion_progress_across_resume(self):
        b = Bridge(
            pooled_water_scene("initial", [10, 11], opened=True),
            [
                pooled_water_scene("first-drunk", [11], 50000, reports=[drank(1)]),
                pooled_water_scene("menu", [11], 50000, opened=True, reports=[drank(1)]),
                pooled_water_scene("done", [], 0, reports=[drank(1), drank(2)]),
            ],
        )
        c = self.client(b)
        first = c.act(
            {"type": "drink", "container_id": 20, "portions": 2}, execution={"max_steps": 1}
        )["dispatch"]
        self.assertEqual(first["outcome"], "limit_reached")
        self.assertEqual(first["progress"]["portions_consumed"], 1)
        done = c.act(first["resume_action"])["dispatch"]
        self.assertEqual(done["outcome"], "completed")
        self.assertEqual([r["item_id"] for r in done["details"]["consumption"]], [10, 11])
        self.assertEqual(sum(a["type"] == "select_option" for a in b.inputs), 2)

    def test_pooling_requires_matching_known_contents_including_coatings(self):
        for changed in (
            {"material_ref": {"token": "CREATURE_MAT:DWARF:BLOOD"}},
            {"contaminants": [{"material": "CREATURE_MAT:SPIDER:VENOM"}]},
            {"contaminants_unavailable": "Unreadable material"},
        ):
            initial = pooled_water_scene("initial", [10, 11])
            initial["adventurer"]["inventory"][0]["contents"][1].update(changed)
            b = Bridge(initial)
            r = self.client(b).act({"type": "drink", "container_id": 20})["dispatch"]
            self.assertEqual(r["blocker"]["kind"], "source_ambiguous")
            self.assertEqual([i["item_id"] for i in r["details"]["candidates"]], [10, 11])
            self.assertFalse(b.inputs)

    def test_pinned_pool_never_adopts_a_replacement_or_changed_source(self):
        for replaced in (True, False):
            after = pooled_water_scene(
                "first-drunk", [99 if replaced else 11], 50000, reports=[drank(1)]
            )
            if not replaced:
                after["adventurer"]["inventory"][0]["contents"][0]["contaminants"] = [
                    {"material": "CREATURE_MAT:SPIDER:VENOM"}
                ]
            b = Bridge(pooled_water_scene("initial", [10, 11], opened=True), [after])
            c = self.client(b)
            r = c.act({"type": "drink", "container_id": 20, "portions": 2})["dispatch"]
            self.assertEqual(r["outcome"], "needs_input")
            self.assertEqual(r["progress"]["portions_consumed"], 1)
            self.assertEqual(c.act(r["resume_action"])["dispatch"]["outcome"], "needs_input")
            self.assertEqual(len(b.inputs), 1)

    def test_drink_container_resolves_the_unique_liquid_and_verifies_its_last_portion(self):
        initial = water_scene("contained", portions=1, opened=True)
        liquid = initial["adventurer"]["inventory"][0]
        liquid["location"]["container_id"] = 20
        initial["adventurer"]["inventory"] = [dict(item(20), contents=[liquid])]
        done = water_scene("drank", portions=0, thirst=0, reports=[drank(1)])
        done["adventurer"]["inventory"] = [dict(item(20), contents=[])]
        b = Bridge(initial, [done])
        r = self.client(b).act({"type": "drink", "container_id": 20})["dispatch"]
        self.assertEqual(r["outcome"], "completed")
        self.assertEqual(r["details"]["item_id"], 10)

    def test_ambiguous_liquids_or_frozen_contents_need_a_controller_choice(self):
        for kinds in (["GLOB"], ["LIQUID_MISC", "DRINK"]):
            initial = water_scene("container")
            initial["adventurer"]["inventory"] = [
                dict(item(20), contents=[dict(item(10 + i), type=k) for i, k in enumerate(kinds)])
            ]
            b = Bridge(initial)
            r = self.client(b).act({"type": "drink", "container_id": 20})["dispatch"]
            self.assertEqual(r["outcome"], "needs_input")
            self.assertEqual(b.inputs, [])

    def test_resume_never_switches_to_a_replacement_liquid_implicitly(self):
        initial = water_scene("contained", portions=2, opened=True)
        liquid = initial["adventurer"]["inventory"][0]
        liquid["location"]["container_id"] = 20
        initial["adventurer"]["inventory"] = [dict(item(20), contents=[liquid])]
        done = water_scene("unexpected", portions=0, thirst=0, reports=[drank(1)])
        replacement = dict(item(99, container=20), type="LIQUID_MISC", stack_size=1)
        done["adventurer"]["inventory"] = [dict(item(20), contents=[replacement])]
        b = Bridge(initial, [done])
        c = self.client(b)
        r = c.act({"type": "drink", "container_id": 20})["dispatch"]
        self.assertEqual(r["outcome"], "no_effect")
        self.assertEqual(c.act(r["resume_action"])["dispatch"]["outcome"], "no_effect")
        self.assertEqual(len(b.inputs), 1)

    def test_needs_reset_can_be_followed_by_passive_ticks_during_the_same_consumption(self):
        initial = water_scene("already-hydrated", portions=1, thirst=0, opened=True)
        initial["status"]["world_frame"] = 10
        done = water_scene("drank", portions=0, thirst=1, reports=[drank(1)])
        done["status"]["world_frame"] = 11
        b = Bridge(initial, [done])
        r = self.client(b).act({"type": "drink", "item_id": 10})["dispatch"]
        self.assertEqual(r["outcome"], "completed")

    def test_food_uses_native_consumption_and_verifies_hunger_including_zero(self):
        for hunger in (90000, 0):
            initial = water_scene("food", portions=1, opened=True)
            initial["adventurer"]["inventory"][0]["type"] = "MEAT"
            initial["adventurer"]["health"]["hunger_timer"] = hunger
            done = water_scene("eaten", portions=0, reports=[{"id": 1, "type": "EAT_ITEM"}])
            done["adventurer"]["health"]["hunger_timer"] = 0
            b = Bridge(initial, [done])
            r = self.client(b).act({"type": "eat", "item_id": 10})["dispatch"]
            self.assertEqual(r["outcome"], "completed")
            self.assertEqual(r["details"]["consumption"][0]["hunger_after"], 0)
            self.assertEqual(len(b.inputs), 1)

    def test_other_consumption_report_and_truncated_nested_inventory_are_not_proof(self):
        for nested_truncated in (False, True):
            initial = water_scene("menu", portions=1, opened=True)
            done = water_scene(
                "unknown",
                portions=0,
                thirst=0,
                reports=[{"id": 1, "type": "DRINK_ITEM" if nested_truncated else "EAT_ITEM"}],
            )
            if nested_truncated:
                done["adventurer"]["inventory"] = [dict(item(20), contents_truncated=True)]
            b = Bridge(initial, [done])
            c = self.client(b)
            r = c.act({"type": "drink", "item_id": 10})["dispatch"]
            self.assertEqual(r["outcome"], "no_effect")
            self.assertEqual(c.act(r["resume_action"])["dispatch"]["outcome"], "no_effect")
            self.assertEqual(len(b.inputs), 1)

    def client(self, bridge):
        c = Client(port=1, execution={"mode": "complete", "acknowledge": True})
        p = patch.object(c, "request", side_effect=bridge)
        p.start()
        self.addCleanup(p.stop)
        return c

    def test_two_portions_verify_quantity_reports_and_thirst_with_shared_resume(self):
        b = Bridge(
            water_scene("start"),
            [
                water_scene("menu", opened=True),
                water_scene("one-drunk", 1, 50000, reports=[drank(1)]),
                water_scene("menu-again", 1, 50000, opened=True, reports=[drank(1)]),
                water_scene("done", 0, 0, reports=[drank(1), drank(2)]),
            ],
        )
        c = self.client(b)
        d = c.act({"type": "drink", "item_id": 10, "portions": 2}, execution={"max_steps": 2})[
            "dispatch"
        ]
        self.assertEqual(d["outcome"], "limit_reached")
        self.assertEqual(d["progress"]["portions_consumed"], 1)
        done = c.act(d["resume_action"])["dispatch"]
        self.assertEqual(done["outcome"], "completed")
        self.assertEqual(done["details"]["portions_consumed"], 2)
        self.assertEqual(done["details"]["consumption"][-1]["thirst_after"], 0)
        self.assertEqual(sum(a["type"] == "select_option" for a in b.inputs), 2)

    def test_lick_or_unverified_consumption_does_not_complete_or_repeat(self):
        for portions, thirst, reports in (
            (2, 100001, []),
            (1, 100001, [drank(1)]),
            (2, 50000, [drank(1)]),
        ):
            with self.subTest(portions=portions, thirst=thirst):
                b = Bridge(
                    water_scene("menu", opened=True),
                    [water_scene("failed", portions, thirst, reports=reports)],
                )
                c = self.client(b)
                d = c.act({"type": "drink", "item_id": 10})["dispatch"]
                self.assertEqual(d["outcome"], "no_effect")
                self.assertEqual(c.act(d["resume_action"])["dispatch"]["outcome"], "no_effect")
                self.assertEqual(len(b.inputs), 1)

    def test_frozen_contents_and_container_are_not_liquid_drink_targets(self):
        for kind in ("GLOB", "FLASK"):
            v = water_scene("frozen")
            v["adventurer"]["inventory"][0]["type"] = kind
            b = Bridge(v)
            d = self.client(b).act({"type": "drink", "item_id": 10})["dispatch"]
            self.assertEqual(d["blocker"]["kind"], "source_not_liquid")
            self.assertFalse(b.inputs)

    def test_drink_composes_and_preserves_caller_portion_count(self):
        b = Bridge(
            water_scene("menu", 1, opened=True), [water_scene("done", 0, 50000, reports=[drank(1)])]
        )
        d = self.client(b).act({"type": "sequence", "actions": [{"type": "drink", "item_id": 10}]})[
            "dispatch"
        ]
        self.assertEqual(d["outcome"], "completed")
        self.assertEqual(d["results"][0]["details"]["portions_consumed"], 1)
        for action in (
            {"type": "drink", "item_id": 10, "portions": 0},
            {"type": "drink", "item_id": True},
            {"type": "drink", "item_id": 10, "portions": 33},
        ):
            with self.assertRaises(ValueError):
                validate_action(action)
