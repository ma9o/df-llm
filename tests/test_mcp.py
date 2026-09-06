import io
import json
import unittest
from threading import Event
from unittest.mock import patch

from dfharness.mcp import Server, serve
from dfharness.rpc import DispatchError


class FakeGame:
    def __init__(self):
        self.calls = []

    def status(self):
        self.calls.append("status")
        return {"mode": "adventure", "ready_for_input": True}

    def act(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": {"mode": "adventure"}}


class McpTests(unittest.TestCase):
    def setUp(self):
        self.game = FakeGame()
        self.server = Server(self.game)
        self.init = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-11-25"},
        }
        self.server.handle(self.init)

    def call(self, name, args):
        return self.server.handle(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": name, "arguments": args},
            }
        )

    def test_stdio_lifecycle_notifications_and_tool_call(self):
        messages = [
            self.init,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "df_status"}},
        ]
        out = io.StringIO()
        serve(self.game, io.StringIO("\n".join(json.dumps(m) for m in messages)), out)
        replies = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual([r["id"] for r in replies], [1, 2, 3])
        self.assertEqual(len(replies[1]["result"]["tools"]), 11)
        self.assertEqual(self.game.calls, ["status"])

    def test_invalid_mutation_arguments_never_reach_the_game(self):
        for action in (
            {"type": "move", "direction": "north"},
            {"type": "click", "x": True, "y": 4},
            {"type": "click", "x": -1, "y": 4},
            {"type": "select_unit", "unit_id": True},
            {"type": "select_unit", "unit_id": -1},
            {"type": "select_unit"},
            {"type": "dismiss", "key": "OPTION3"},
            {"type": "wait", "lua": "evil()"},
        ):
            with self.subTest(action=action):
                result = self.call("df_act", {"action": action})
                self.assertTrue(result["result"]["isError"])
        self.assertEqual(self.game.calls, [])

    def test_valid_action_and_unknown_tool(self):
        self.assertFalse(
            self.call("df_act", {"action": {"type": "move", "direction": "w"}})["result"]["isError"]
        )
        self.assertEqual(len(self.game.calls), 1)
        self.assertEqual(self.call("run_lua", {})["error"]["code"], -32602)

    def test_conversation_actions_preserve_state_guard_and_request_id(self):
        for action in ({"type": "select_unit", "unit_id": 4232}, {"type": "dismiss"}):
            args = {
                "action": action,
                "expect": "observed-state",
                "request_id": "one-intended-action",
            }
            result = self.call("df_act", args)
            self.assertFalse(result["result"]["isError"])
            self.assertEqual(self.game.calls[-1], args)

    def test_execution_policy_reaches_dispatch_and_invalid_policies_do_not(self):
        args = {
            "action": {"type": "resume"},
            "execution": {"mode": "complete", "acknowledge": True},
            "timeout": 20,
        }
        self.assertFalse(self.call("df_act", args)["result"]["isError"])
        self.assertEqual(self.game.calls, [args])
        for policy in ({"mode": "safe"}, {"risk": "low"}, {"max_steps": 65}, {"acknowledge": 1}):
            self.assertTrue(
                self.call("df_act", {"action": {"type": "wait"}, "execution": policy})["result"][
                    "isError"
                ]
            )
        self.assertEqual(self.game.calls, [args])

    def test_parse_error_does_not_break_next_request(self):
        out = io.StringIO()
        serve(self.game, io.StringIO("not json\n" + json.dumps(self.init) + "\n"), out)
        replies = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(replies[0]["error"]["code"], -32700)
        self.assertEqual(replies[1]["id"], 1)

    def test_stdio_can_interrupt_or_cancel_while_action_is_running(self):
        for notification in (False, True):
            with self.subTest(notification=notification):
                started, interrupted = Event(), Event()

                class RunningGame(FakeGame):
                    def __init__(self, started_event, interrupted_event):
                        super().__init__()
                        self.started_event = started_event
                        self.interrupted_event = interrupted_event

                    def act(self, **kwargs):
                        self.dispatch_id = kwargs["request_id"]
                        self.started_event.set()
                        if not self.interrupted_event.wait(2):
                            raise AssertionError("The stdio reader blocked behind the action")
                        return {"dispatch": {"outcome": "interrupted", "id": self.dispatch_id}}

                    def interrupt(self, dispatch_id):
                        if not self.started_event.wait(2):
                            raise AssertionError("Action worker did not start")
                        if dispatch_id != self.dispatch_id:
                            raise AssertionError("Cancellation targeted another dispatch")
                        self.interrupted_event.set()
                        return {"interruption_requested": True}

                game = RunningGame(started, interrupted)
                call = {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "df_act",
                        "arguments": {"action": {"type": "wait"}, "request_id": "running-action"},
                    },
                }
                stop = (
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/cancelled",
                        "params": {"requestId": 3},
                    }
                    if notification
                    else {
                        "jsonrpc": "2.0",
                        "id": 4,
                        "method": "tools/call",
                        "params": {
                            "name": "df_interrupt",
                            "arguments": {"dispatch_id": "running-action"},
                        },
                    }
                )
                messages = [self.init, call, stop, {"jsonrpc": "2.0", "id": 5, "method": "ping"}]
                out = io.StringIO()
                serve(game, io.StringIO("\n".join(json.dumps(m) for m in messages)), out)
                replies = {r["id"]: r for r in map(json.loads, out.getvalue().splitlines())}
                self.assertFalse(replies[3]["result"]["isError"])
                result = json.loads(replies[3]["result"]["content"][0]["text"])
                self.assertEqual(result["dispatch"]["outcome"], "interrupted")
                self.assertEqual(replies[5]["result"], {})
                self.assertEqual(len(replies), 3 if notification else 4)

    def test_dispatch_error_returns_identity_and_recovery_action(self):
        def fail(**kwargs):
            raise DispatchError("recoverable-id", "Lost reply")

        with patch.object(self.game, "act", side_effect=fail):
            response = self.call("df_act", {"action": {"type": "wait"}})["result"]
        self.assertTrue(response["isError"])
        error = json.loads(response["content"][0]["text"])
        self.assertEqual(error["dispatch_id"], "recoverable-id")
        self.assertEqual(
            error["resume_action"], {"type": "resume", "dispatch_id": "recoverable-id"}
        )

    def test_semantic_action_schema_preserves_controller_choices(self):
        args = {
            "action": {
                "type": "equip",
                "item_id": 3,
                "replace": [2],
                "disposition": "stow",
                "container_id": 99,
            },
            "execution": {
                "mode": "complete",
                "interrupt_on": {"blood_loss": True, "visible_unit_ids": [20]},
            },
            "result_format": "compact",
            "request_id": "equipment-action",
        }
        self.assertFalse(self.call("df_act", args)["result"]["isError"])
        self.assertEqual(self.game.calls, [args])
        bad = {"action": {"type": "equip", "item_id": 3, "replace": [True]}}
        self.assertTrue(self.call("df_act", bad)["result"]["isError"])
        self.assertEqual(self.game.calls, [args])
