import unittest
from copy import deepcopy
from unittest.mock import patch

from dfharness.environment import fill_state, water_state
from tests.support import Bridge
from tests.support import FullClient as Client
from tests.test_workflows import item, scene

TARGET = {"x": 2, "y": 1, "z": 0}


def water(ice=True, quantity=3, temperature=9994, item_id=11):
    return dict(
        item(item_id, container=10),
        type="GLOB" if ice else "LIQUID_MISC",
        stack_size=quantity,
        material_ref={"token": "WATER", "type": 6, "index": 0},
        temperature={"whole": temperature},
    )


def environment_scene(name, contents=None, options=None, fire=False):
    container = dict(item(10), type="FLASK", contents=[water()] if contents is None else contents)
    choices = (
        {"kind": "inventory", "context": 8, "options": options} if options is not None else None
    )
    v = scene(name, carried=[container], choices=choices)
    v["map"]["landmarks"] = [{"position": TARGET, "material": "CAMPFIRE"}] if fire else []
    return v


def heating(target=TARGET, item_id=10):
    return {
        "id": "heat",
        "operation": "heat_item",
        "item_id": item_id,
        "target_position": target,
        "visible": True,
        "kind": "NONE",
    }


FILL = {"type": "fill_container", "container_id": 10, "material": "WATER", **TARGET}


def filling(name, quantity=2, *, options=True, phase="Solid"):
    contents = (
        [dict(water(phase == "Solid", quantity=quantity), volume_raw=quantity * 60)]
        if quantity
        else []
    )
    option = {
        "id": "fill",
        "operation": "fill_container",
        "container_id": 10,
        "target_position": TARGET,
        "material_ref": {"token": "WATER", "state": phase},
        "visible": True,
    }
    v = environment_scene(name, contents=contents, options=[option] if options else None)
    v["adventurer"]["inventory"][0]["capacity_volume_raw"] = 180
    return v


class EnvironmentTests(unittest.TestCase):
    def test_filling_verifies_native_fullness_despite_a_phase_or_item_id_change(self):
        before, done = filling("before"), filling("done", 3, options=False, phase="Liquid")
        done["adventurer"]["inventory"][0]["contents"][0]["id"] = 99
        b = Bridge(before, [done])
        r = self.client(b).act(FILL)["dispatch"]
        self.assertEqual(r["outcome"], "completed")
        self.assertEqual(r["details"]["contents_volume_raw"], 180)
        self.assertEqual(r["details"]["item_ids"], [99])
        self.assertEqual(b.inputs, [{"type": "select_option", "option_id": "fill"}])

    def test_partial_filling_resumes_until_full_without_restarting_completed_portions(self):
        b = Bridge(
            filling("empty", 0),
            [filling("one", 1), filling("two", 2), filling("full", 3, options=False)],
        )
        c = self.client(b)
        first = c.act(FILL, execution={"max_steps": 1})["dispatch"]
        self.assertEqual(first["outcome"], "limit_reached")
        final = c.act(first["resume_action"])["dispatch"]
        self.assertEqual(final["outcome"], "completed")
        self.assertEqual(len(b.inputs), 3)

    def test_filling_never_treats_no_progress_as_full_or_repeats_the_selection(self):
        b = Bridge(filling("before"), [filling("unchanged", options=False)])
        c = self.client(b)
        first = c.act(FILL)["dispatch"]
        self.assertEqual(first["outcome"], "needs_input")
        self.assertEqual(c.act(first["resume_action"])["dispatch"]["outcome"], "needs_input")
        self.assertEqual(len(b.inputs), 1)

    def test_filling_rejects_unknown_capacity_volume_mixed_contents_and_truncation(self):
        for field, value in (
            ("capacity_volume_raw", None),
            ("capacity_volume_raw", 0),
            ("capacity_volume_raw", False),
            ("contents_truncated", True),
        ):
            v = filling("unknown")
            v["adventurer"]["inventory"][0][field] = value
            self.assertIsNone(fill_state(v, 10, "WATER"))
        for field, value in (
            ("volume_raw", None),
            ("volume_raw", False),
            ("material_ref", {"token": "BLOOD"}),
        ):
            v = filling("unknown")
            v["adventurer"]["inventory"][0]["contents"][0][field] = value
            b = Bridge(v)
            self.assertEqual(self.client(b).act(FILL)["dispatch"]["outcome"], "needs_input")
            self.assertEqual(b.inputs, [])

    def test_filling_uses_explicit_source_phase_and_never_chooses_between_ambiguous_sources(self):
        before = filling("choices")
        other = deepcopy(before["menu"]["options"][0])
        other.update(id="liquid", material_ref={"token": "WATER", "state": "Liquid"})
        before["menu"]["options"].append(other)
        b = Bridge(before, [filling("done", 3, options=False)])
        r = self.client(b).act(dict(FILL, source_state="Solid"))["dispatch"]
        self.assertEqual(r["outcome"], "completed")
        self.assertEqual(b.inputs[0]["option_id"], "fill")
        # An already-open environment list does not silently choose a phase.
        b = Bridge(environment_scene("start", contents=[]), [before])
        b.view["adventurer"]["inventory"][0]["capacity_volume_raw"] = 180
        r = self.client(b).act(FILL)["dispatch"]
        self.assertEqual(r["outcome"], "needs_input")
        self.assertEqual(b.inputs, [{"type": "key", "key": "A_INTERACT"}])

    def client(self, bridge):
        c = Client(port=1, execution={"mode": "complete", "acknowledge": True})
        p = patch.object(c, "request", side_effect=bridge)
        p.start()
        self.addCleanup(p.stop)
        return c

    def test_thaw_verifies_native_phase_change_and_new_liquid_item_id(self):
        initial = environment_scene("heat", options=[heating()])
        done = environment_scene("melted", contents=[water(False, item_id=12)])
        b = Bridge(initial, [done])
        r = self.client(b).act({"type": "thaw", "container_id": 10, **TARGET})["dispatch"]
        self.assertEqual(r["outcome"], "completed")
        self.assertEqual(r["details"]["liquid_item_ids"], [12])
        self.assertEqual(len(b.inputs), 1)

    def test_heating_progress_can_resume_without_restarting_completed_inputs(self):
        initial = environment_scene("cold", options=[heating()])
        warmer = environment_scene(
            "warming", contents=[water(temperature=9998)], options=[heating()]
        )
        done = environment_scene("melted", contents=[water(False, item_id=12)])
        b = Bridge(initial, [warmer, done])
        c = self.client(b)
        r = c.act({"type": "thaw", "container_id": 10, **TARGET}, execution={"max_steps": 1})[
            "dispatch"
        ]
        self.assertEqual(r["outcome"], "limit_reached")
        final = c.act(r["resume_action"])["dispatch"]
        self.assertEqual(final["outcome"], "completed")
        self.assertEqual(len(b.inputs), 2)

    def test_unchanged_temperature_and_changed_quantity_never_prove_thawing(self):
        initial = environment_scene("cold", options=[heating()])
        for contents in ([water()], [water(False, quantity=2)]):
            b = Bridge(initial, [environment_scene("unverified", contents=contents)])
            c = self.client(b)
            r = c.act({"type": "thaw", "container_id": 10, **TARGET})["dispatch"]
            self.assertEqual(r["outcome"], "needs_input")
            self.assertEqual(c.act(r["resume_action"])["dispatch"]["outcome"], "needs_input")
            self.assertEqual(len(b.inputs), 1)

    def test_target_and_container_are_both_required_to_match_the_native_option(self):
        initial = environment_scene(
            "menu", options=[heating(item_id=99), heating(target={**TARGET, "x": 3})]
        )
        b = Bridge(environment_scene("start"), [initial])
        r = self.client(b).act({"type": "thaw", "container_id": 10, **TARGET})["dispatch"]
        self.assertEqual(r["outcome"], "needs_input")
        self.assertEqual(b.inputs, [{"type": "key", "key": "A_INTERACT"}])

    def test_truncated_or_unknown_materials_never_look_like_an_empty_or_liquid_container(self):
        for field in ("inventory_truncated", "contents_truncated", "material_ref"):
            v = environment_scene("unknown")
            if field == "inventory_truncated":
                v["adventurer"][field] = True
            elif field == "contents_truncated":
                v["adventurer"]["inventory"][0][field] = True
            else:
                v["adventurer"]["inventory"][0]["contents"][0].pop(field)
            self.assertIsNone(water_state(v, 10))
            b = Bridge(v)
            r = self.client(b).act({"type": "thaw", "container_id": 10, **TARGET})["dispatch"]
            self.assertEqual(r["outcome"], "needs_input")
            self.assertEqual(b.inputs, [])

    def test_campfire_requires_observed_material_at_the_requested_coordinate(self):
        option = {
            "id": "fire",
            "operation": "make_campfire",
            "target_position": TARGET,
            "visible": True,
        }
        initial = environment_scene("make", options=[option])
        for present in (True, False):
            final = environment_scene("result", fire=present)
            b = Bridge(initial, [final])
            r = self.client(b).act({"type": "make_campfire", **TARGET})["dispatch"]
            self.assertEqual(r["outcome"], "completed" if present else "needs_input")
            self.assertEqual(len(b.inputs), 1)

    def test_already_liquid_and_already_built_are_idempotent(self):
        for action in (
            {"type": "thaw", "container_id": 10, **TARGET},
            {"type": "make_campfire", **TARGET},
        ):
            b = Bridge(environment_scene("done", contents=[water(False)], fire=True))
            self.assertEqual(self.client(b).act(action)["dispatch"]["outcome"], "completed")
            self.assertEqual(b.inputs, [])

    def test_interruption_after_heating_retains_the_requested_effect_for_resume(self):
        initial = environment_scene("heat", options=[heating()])
        final = environment_scene("melted", contents=[water(False, item_id=12)])
        hurt = deepcopy(final)
        hurt["adventurer"]["health"]["blood_count"] -= 1
        b = Bridge(initial, [hurt])
        c = self.client(b)
        r = c.act(
            {"type": "thaw", "container_id": 10, **TARGET},
            execution={"interrupt_on": {"blood_loss": True}},
        )["dispatch"]
        self.assertEqual(r["outcome"], "interrupted")
        self.assertEqual(c.act(r["resume_action"])["dispatch"]["outcome"], "completed")
        self.assertEqual(len(b.inputs), 1)
