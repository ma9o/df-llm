import unittest
from unittest.mock import patch

from dfharness.client import Client, lua_string
from dfharness.rpc import DFHackError
from tests.support import Bridge


class ClientTests(unittest.TestCase):
    def test_lua_literals_preserve_newlines_and_delimiter_like_input(self):
        value = '\n]]; error("injected") -- ]=] \u263a'
        literal = lua_string(value)
        self.assertTrue(literal.startswith("[==[\n"))
        self.assertEqual(literal[len("[==[\n"):-len("]==]")], value)

    def test_action_is_not_retried_if_poll_connection_fails(self):
        c = Client(port=1)
        bridge = Bridge({"status": {}, "ui": {}}, [{"status": {}, "ui": {}}])
        def poll(game, request):
            if game.inputs:
                raise DFHackError("disconnect")
        bridge.poll_hook = poll
        with patch.object(c, "request", side_effect=bridge):
            with self.assertRaisesRegex(DFHackError, "disconnect"):
                c.act({"type": "move", "direction": "w"}, request_id="abc")
        self.assertEqual(bridge.inputs, [{"type": "move", "direction": "w"}])

    def test_action_waits_for_readiness_before_observing(self):
        c = Client(port=1)
        bridge = Bridge({"status": {}, "ui": {}, "effect_id": "before"},
                        [{"status": {"ready_for_input": False}, "ui": {}, "effect_id": "busy"}])
        polls = 0
        def poll(game, request):
            nonlocal polls
            polls += 1
            if polls == 3:
                game.view = {"status": {"ready_for_input": True}, "ui": {}, "effect_id": "done"}
        bridge.poll_hook = poll
        with patch.object(c, "request", side_effect=bridge), patch("dfharness.dispatch.time.sleep"):
            result = c.act({"type": "wait"}, request_id="abc")
        self.assertEqual(polls, 3)
        self.assertEqual(len(bridge.inputs), 1)
        self.assertEqual(result["action"]["action_id"], "abc")

    def test_partial_input_failure_is_reported(self):
        c = Client(port=1)
        with patch.object(c, "request", return_value={"ready": True, "action_error": "bad native input"}):
            with self.assertRaisesRegex(DFHackError, "partially executed"):
                c.wait_ready("abc")
