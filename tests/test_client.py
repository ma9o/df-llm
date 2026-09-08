import unittest
from unittest.mock import patch

from dfharness.client import Client, lua_string
from dfharness.rpc import BridgeError, DFHackError, DispatchError
from tests.support import Bridge


class ClientTests(unittest.TestCase):
    def test_known_begin_rejection_has_no_bogus_resume_handle(self):
        c = Client(port=1)
        error = BridgeError(
            "Another dispatch is active", details={"dispatch_registered": False}, input_sent=False
        )
        with (
            patch.object(c, "request", side_effect=error),
            self.assertRaises(DispatchError) as caught,
        ):
            c.act({"type": "key", "key": "A_SHORT_WAIT"})
        self.assertIsNone(caught.exception.resume_action)
        self.assertIs(caught.exception.input_sent, False)

    def test_dispatch_uses_combined_readiness_and_observation_without_an_extra_read(self):
        bridge = Bridge(
            {"status": {}, "effect_id": "before"}, [{"status": {}, "effect_id": "after"}]
        )
        c = Client(port=1, execution={"mode": "complete"})
        with patch.object(c, "request", side_effect=bridge):
            r = c.act({"type": "key", "key": "A_SHORT_WAIT"})
        self.assertEqual(r["outcome"], "completed")
        self.assertFalse(any(call["op"] == "observe" for call in bridge.calls))
        self.assertTrue(all(call.get("observe") for call in bridge.calls if call["op"] == "poll"))

    def test_lua_literals_preserve_newlines_and_delimiter_like_input(self):
        value = '\n]]; error("injected") -- ]=] \u263a'
        literal = lua_string(value)
        self.assertTrue(literal.startswith("[==[\n"))
        self.assertEqual(literal[len("[==[\n") : -len("]==]")], value)

    def test_action_is_not_retried_if_poll_connection_fails(self):
        c = Client(port=1)
        bridge = Bridge(
            {"status": {"can_move": True, "position": {"x": 1, "y": 1, "z": 0}}, "ui": {}},
            [{"status": {}, "ui": {}}],
        )

        def poll(game, request):
            if game.inputs:
                raise DFHackError("disconnect")

        bridge.poll_hook = poll
        with (
            patch.object(c, "request", side_effect=bridge),
            self.assertRaisesRegex(DFHackError, "disconnect"),
        ):
            c.act({"type": "move", "direction": "w"}, request_id="abc")
        self.assertEqual(bridge.inputs, [{"type": "move", "direction": "w"}])

    def test_action_waits_for_readiness_before_observing(self):
        c = Client(port=1)
        bridge = Bridge(
            {"status": {}, "ui": {}, "effect_id": "before"},
            [{"status": {"ready_for_input": False}, "ui": {}, "effect_id": "busy"}],
        )
        polls = 0

        def poll(game, request):
            nonlocal polls
            polls += 1
            if polls == 3:
                game.view = {"status": {"ready_for_input": True}, "ui": {}, "effect_id": "done"}

        bridge.poll_hook = poll
        with patch.object(c, "request", side_effect=bridge), patch("dfharness.dispatch.time.sleep"):
            result = c.act({"type": "key", "key": "A_SHORT_WAIT"}, request_id="abc")
        self.assertEqual(polls, 3)
        self.assertEqual(len(bridge.inputs), 1)
        self.assertEqual(result["dispatch_id"], "abc")

    def test_partial_input_failure_is_reported(self):
        c = Client(port=1)
        with (
            patch.object(
                c, "request", return_value={"ready": True, "action_error": "bad native input"}
            ),
            self.assertRaisesRegex(DFHackError, "partially executed"),
        ):
            c.wait_ready("abc")

    def test_wait_ready_uses_the_same_bounded_pending_pause(self):
        c = Client(port=1)
        with (
            patch.object(c, "request", side_effect=[{"ready": False}] * 5 + [{"ready": True}]),
            patch("dfharness.client.time.sleep") as pause,
        ):
            self.assertTrue(c.wait_ready("abc")["ready"])
        self.assertEqual(
            [call.args[0] for call in pause.call_args_list], [0.05, 0.1, 0.2, 0.25, 0.25]
        )
