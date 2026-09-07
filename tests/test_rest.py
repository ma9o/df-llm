import io
import unittest
from unittest.mock import patch

from dfharness.cli import main
from dfharness.workflows import validate_action
from tests.support import Bridge
from tests.support import FullClient as Client
from tests.test_workflows import scene


def resting(name, hours=8, sleep=True, dawn=False, opened=True, year=100, tick=100):
    v = scene(name)
    v["status"].update(year=year, year_tick=tick, can_move=not opened)
    v["rest"] = {
        "available": True,
        "sleep_hours": hours,
        "sleep_sleep": sleep,
        "sleep_until_dawn": dawn,
        "sleeping": 0,
        "sleep_interrupt": 0,
        "model": {
            "hours_min": 1,
            "hours_max": 24,
            "page_hours": 4,
            "calendar_ticks_per_hour": 50,
            "calendar_ticks_per_year": 403200,
        },
    }
    if opened:
        v["menu"] = {
            "kind": "rest",
            "no_sky": False,
            "settings": v["rest"],
            "options": [
                {
                    "id": "rest:" + name,
                    "native_type": name,
                    "selection": {"method": "native_key", "key": "SELECT"},
                }
                for name in (
                    "sleep",
                    "wait",
                    "less",
                    "more",
                    "page_less",
                    "page_more",
                    "dawn",
                    "confirm",
                    "cancel",
                )
            ],
        }
    return v


def dawn_resting(name, *, remaining=20, longitude=6, **kwargs):
    view = resting(name, **kwargs)
    view["rest"]["dawn"] = {
        "available": True,
        "remaining_calendar_ticks": remaining,
        "world_region_x": longitude,
    }
    return view


class RestTests(unittest.TestCase):
    def client(self, bridge):
        c = Client(port=1, execution={"mode": "complete", "acknowledge": True})
        p = patch.object(c, "request", side_effect=bridge)
        p.start()
        self.addCleanup(p.stop)
        return c

    def test_rest_configures_native_settings_then_resumes_without_repeating_them(self):
        b = Bridge(
            resting("initial", hours=5),
            [
                resting("wait", hours=5, sleep=False),
                resting("one-hour", hours=1, sleep=False),
                resting("done", hours=1, sleep=False, opened=False, tick=150),
            ],
        )
        c = self.client(b)
        first = c.act({"type": "rest", "hours": 1}, execution={"max_steps": 2})["dispatch"]
        self.assertEqual(first["outcome"], "limit_reached")
        final = c.act(first["resume_action"])["dispatch"]
        self.assertEqual(final["outcome"], "completed")
        self.assertEqual(final["details"]["elapsed_calendar_ticks"], 50)
        self.assertEqual(
            [a["option_id"] for a in b.inputs], ["rest:wait", "rest:page_less", "rest:confirm"]
        )
        self.assertTrue(
            all(
                r["rest_state"]
                for r in b.calls
                if r["op"] == "begin_dispatch" and r["action"]["type"] == "rest"
            )
        )

    def test_partial_duration_or_menu_closing_is_not_completion_and_never_restarts(self):
        for tick in (100, 110):
            b = Bridge(
                resting("initial", hours=1), [resting("stopped", hours=1, opened=False, tick=tick)]
            )
            c = self.client(b)
            r = c.act({"type": "sleep", "hours": 1})["dispatch"]
            self.assertEqual(r["blocker"]["kind"], "rest_incomplete")
            self.assertEqual(c.act(r["resume_action"])["dispatch"]["outcome"], "needs_input")
            self.assertEqual(len(b.inputs), 1)

    def test_native_refusal_is_a_concrete_blocker_retained_across_resume(self):
        denied = dawn_resting("denied", opened=False)
        denied["reports"] = [
            {"id": 2, "type": "CANNOT_REST", "text": "You don't feel safe enough to rest."}
        ]
        bridge = Bridge(dawn_resting("before", opened=False), [denied])
        client = self.client(bridge)
        first = client.act({"type": "sleep", "until": "dawn"}, result_format="compact")
        self.assertEqual(first["outcome"], "needs_input")
        self.assertEqual(first["blocker"]["kind"], "native_refusal")
        self.assertEqual(first["blocker"]["why"], "You don't feel safe enough to rest.")
        self.assertEqual(first["blocker"]["facts"]["type"], "CANNOT_REST")
        resumed = client.act(first["resume"], result_format="compact")
        self.assertEqual(resumed["blocker"]["facts"], first["blocker"]["facts"])
        self.assertEqual(resumed["inputs"], 0)
        self.assertEqual(len(bridge.inputs), 1)

    def test_previous_native_rest_refusal_does_not_block_a_new_dispatch(self):
        before = resting("before", hours=1, opened=False)
        before["report_cursor"] = 4
        before["reports"] = [{"id": 4, "type": "CANNOT_REST", "text": "Old refusal"}]
        opened = resting("opened", hours=1)
        opened["reports"] = before["reports"]
        bridge = Bridge(before, [opened, resting("done", hours=1, opened=False, tick=150)])
        result = self.client(bridge).act({"type": "sleep", "hours": 1})["dispatch"]
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(len(bridge.inputs), 2)

    def test_sleep_duration_handles_year_rollover_and_explicit_dawn_toggle(self):
        b = Bridge(
            resting("initial", hours=1, dawn=True, tick=403199),
            [
                resting("fixed", hours=1, tick=403199),
                resting("done", hours=1, opened=False, year=101, tick=49),
            ],
        )
        r = self.client(b).act({"type": "sleep", "hours": 1})["dispatch"]
        self.assertEqual(r["outcome"], "completed")
        self.assertEqual([a["option_id"] for a in b.inputs], ["rest:dawn", "rest:confirm"])
        self.assertEqual(r["details"]["elapsed_calendar_ticks"], 50)

    def test_wrong_duration_key_effect_never_confirms_or_repeats(self):
        b = Bridge(resting("initial", hours=8), [resting("wrong", hours=7)])
        c = self.client(b)
        r = c.act({"type": "sleep", "hours": 4})["dispatch"]
        self.assertEqual(r["outcome"], "no_effect")
        self.assertEqual(c.act(r["resume_action"])["dispatch"]["outcome"], "no_effect")
        self.assertEqual(len(b.inputs), 1)

    def test_missing_clock_or_model_blocks_before_input_and_duration_is_explicit(self):
        for missing in ("year_tick", "model"):
            v = resting("missing")
            (v["status"] if missing == "year_tick" else v["rest"]).pop(missing)
            b = Bridge(v)
            self.assertEqual(
                self.client(b).act({"type": "sleep", "hours": 8})["dispatch"]["outcome"],
                "needs_input",
            )
            self.assertFalse(b.inputs)
        for action in (
            {"type": "sleep"},
            {"type": "rest", "hours": True},
            {"type": "sleep", "hours": 25},
        ):
            with self.assertRaises(ValueError):
                validate_action(action)

    def test_dawn_configures_native_toggle_and_sleep_choice_without_replacing_hours(self):
        bridge = Bridge(
            dawn_resting("initial", hours=8, sleep=False),
            [
                dawn_resting("sleep", hours=8),
                dawn_resting("dawn", hours=8, dawn=True),
                dawn_resting("done", hours=8, dawn=True, opened=False, tick=120),
            ],
        )
        result = self.client(bridge).act(
            {"type": "sleep", "until": "dawn"}, result_format="compact"
        )
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(
            result["values"], [{"kind": "sleep", "until": "dawn", "elapsed_calendar_ticks": 20}]
        )
        self.assertEqual(
            [a["option_id"] for a in bridge.inputs], ["rest:sleep", "rest:dawn", "rest:confirm"]
        )

    def test_dawn_step_resume_reuses_native_settings_and_does_not_repeat_rest(self):
        bridge = Bridge(
            dawn_resting("initial", dawn=False, sleep=False),
            [
                dawn_resting("dawn", dawn=True, sleep=False),
                dawn_resting("done", dawn=True, sleep=False, opened=False, tick=120),
            ],
        )
        client = self.client(bridge)
        first = client.act({"type": "rest", "until": "dawn"}, execution={"max_steps": 1})[
            "dispatch"
        ]
        self.assertEqual(first["outcome"], "limit_reached")
        final = client.act(first["resume_action"])["dispatch"]
        self.assertEqual(final["outcome"], "completed")
        self.assertEqual([a["option_id"] for a in bridge.inputs], ["rest:dawn", "rest:confirm"])

    def test_native_interruption_before_dawn_retains_submission_and_compact_progress(self):
        bridge = Bridge(
            dawn_resting("initial", dawn=True),
            [dawn_resting("ambush", dawn=True, opened=False, tick=119)],
        )
        client = self.client(bridge)
        first = client.act({"type": "sleep", "until": "dawn"}, result_format="compact")
        self.assertEqual(first["blocker"]["kind"], "rest_incomplete")
        self.assertEqual(first["blocker"]["facts"]["elapsed_calendar_ticks"], 19)
        self.assertEqual(first["blocker"]["facts"]["required_calendar_ticks"], 20)
        final = client.act(first["resume"])["dispatch"]
        self.assertEqual(final["outcome"], "needs_input")
        self.assertEqual(len(bridge.inputs), 1)

    def test_dawn_health_interruption_and_late_completion_resume_without_resubmission(self):
        after = dawn_resting("hurt", dawn=True, opened=False, tick=120)
        after["adventurer"]["health"]["blood_count"] -= 1
        bridge = Bridge(dawn_resting("initial", dawn=True), [after])
        client = self.client(bridge)
        first = client.act(
            {"type": "sleep", "until": "dawn"}, execution={"interrupt_on": {"blood_loss": True}}
        )["dispatch"]
        self.assertEqual(first["outcome"], "interrupted")
        self.assertEqual(client.act(first["resume_action"])["dispatch"]["outcome"], "completed")
        self.assertEqual(len(bridge.inputs), 1)

    def test_dawn_crosses_year_boundary_and_exact_dawn_means_the_next_day(self):
        for tick, remaining, final_year, final_tick in (
            (403199, 312, 101, 311),
            (311, 1200, 100, 1511),
        ):
            bridge = Bridge(
                dawn_resting("initial", tick=tick, remaining=remaining, dawn=True),
                [dawn_resting("done", year=final_year, tick=final_tick, dawn=True, opened=False)],
            )
            result = self.client(bridge).act({"type": "sleep", "until": "dawn"})["dispatch"]
            self.assertEqual(result["outcome"], "completed")
            self.assertEqual(result["details"]["elapsed_calendar_ticks"], remaining)

    def test_sky_and_dawn_clock_unknowns_do_not_choose_an_hour_duration(self):
        for field, value in (
            ("available", False),
            ("remaining_calendar_ticks", None),
            ("remaining_calendar_ticks", False),
            ("remaining_calendar_ticks", 0),
            ("world_region_x", None),
        ):
            view = dawn_resting("unknown")
            view["rest"]["dawn"][field] = value
            bridge = Bridge(view)
            result = self.client(bridge).act({"type": "sleep", "until": "dawn"})["dispatch"]
            self.assertEqual(result["details"]["blocker_kind"], "dawn_unavailable")
            self.assertEqual(bridge.inputs, [])
        for no_sky in (True, None):
            view = dawn_resting("inside")
            view["menu"]["no_sky"] = no_sky
            bridge = Bridge(view)
            result = self.client(bridge).act({"type": "sleep", "until": "dawn"})["dispatch"]
            self.assertEqual(result["details"]["blocker_kind"], "dawn_unavailable")
            self.assertEqual(bridge.inputs, [])

    def test_dawn_longitude_change_does_not_retarget_an_already_submitted_rest(self):
        bridge = Bridge(
            dawn_resting("initial", dawn=True),
            [dawn_resting("relocated", dawn=True, opened=False, tick=120, longitude=7)],
        )
        client = self.client(bridge)
        first = client.act({"type": "sleep", "until": "dawn"})["dispatch"]
        self.assertEqual(first["details"]["blocker_kind"], "rest_location_changed")
        self.assertEqual(client.act(first["resume_action"])["dispatch"]["outcome"], "needs_input")
        self.assertEqual(len(bridge.inputs), 1)

    def test_dawn_and_hours_are_exclusive_and_cli_forwards_the_objective(self):
        for action in (
            {"type": "rest", "until": "dusk"},
            {"type": "sleep", "until": True},
            {"type": "sleep", "until": "dawn", "hours": 1},
            {"type": "sleep", "until": "dawn", "until_dawn": True},
        ):
            with self.assertRaises(ValueError):
                validate_action(action)
        with (
            patch("dfharness.cli.Client") as constructor,
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            constructor.return_value.act.return_value = {}
            self.assertEqual(main(["sleep", "--until-dawn"]), 0)
            self.assertEqual(
                constructor.return_value.act.call_args.args[0], {"type": "sleep", "until": "dawn"}
            )
