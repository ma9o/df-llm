import unittest
from copy import deepcopy
from unittest.mock import patch

from dfharness.dispatch import MAX_STATE_REFRESHES
from dfharness.rpc import BridgeError, DFHackError
from tests.support import Bridge, FullClient
from tests.test_composition import PRONE, posture


class StateRefreshTests(unittest.TestCase):
    def execute(self, bridge, request, action=PRONE, **policy):
        client = FullClient(port=1, execution={"mode": "complete", "acknowledge": True, **policy})
        with patch.object(client, "request", side_effect=request):
            return client.act(action)["dispatch"]

    def reject(self, bridge):
        return BridgeError("State changed", "stale_state", {"view": deepcopy(bridge.view)}, False)

    def test_new_delegated_modal_replans_the_objective_without_replaying_input(self):
        bridge = Bridge(posture("before"), [posture("cleared"), posture("down", True)])
        attempts = 0

        def request(req):
            nonlocal attempts
            if req["op"] == "act":
                attempts += 1
                if attempts == 1:
                    bridge.view["status"]["modal"] = {
                        "kind": "announcement",
                        "button": "Okay",
                        "dismissible": True,
                    }
                    raise self.reject(bridge)
            return bridge(req)

        result = self.execute(bridge, request)
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(bridge.inputs, [{"type": "dismiss"}, {"type": "key", "key": "A_STANCE"}])
        self.assertEqual(len(result["state_refreshes"]), 1)

    def test_rejected_acknowledgement_does_not_mark_the_unsent_prompt_as_handled(self):
        initial = posture("modal")
        initial["status"]["modal"] = {"kind": "help", "button": "Okay", "dismissible": True}
        bridge = Bridge(initial, [posture("clear"), posture("down", True)])
        rejected = False

        def request(req):
            nonlocal rejected
            if req["op"] == "act" and not rejected:
                rejected = True
                raise self.reject(bridge)
            return bridge(req)

        result = self.execute(bridge, request)
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(len(result["prompts"]), 1)
        self.assertEqual(len(bridge.inputs), 2)

    def test_repeated_changes_stop_at_a_technical_bound_without_any_native_input(self):
        bridge = Bridge(posture("start"))
        attempts = 0

        def request(req):
            nonlocal attempts
            if req["op"] == "act":
                attempts += 1
                raise self.reject(bridge)
            return bridge(req)

        result = self.execute(bridge, request)
        self.assertEqual(result["outcome"], "limit_reached")
        self.assertEqual(result["details"]["blocker_kind"], "state_refresh_limit")
        self.assertEqual(attempts, MAX_STATE_REFRESHES + 1)
        self.assertFalse(bridge.inputs)
        self.assertIsNone(bridge.active)

    def test_new_reports_still_trigger_controller_interruption_before_replanning(self):
        bridge = Bridge(posture("start"))

        def request(req):
            if req["op"] == "act":
                bridge.view["reports"] = [
                    {"id": 99, "type": "COMBAT_STRIKE_DETAILS", "text": "incoming attack"}
                ]
                raise self.reject(bridge)
            return bridge(req)

        result = self.execute(
            bridge, request, interrupt_on={"report_types": ["COMBAT_STRIKE_DETAILS"]}
        )
        self.assertEqual(result["outcome"], "interrupted")
        self.assertEqual(result["events"][0]["id"], 99)
        self.assertFalse(bridge.inputs)

    def test_step_mode_and_raw_ui_actions_return_the_changed_state(self):
        for action, mode in ((PRONE, "step"), ({"type": "key", "key": "A_STANCE"}, "complete")):
            with self.subTest(action=action, mode=mode):
                bridge = Bridge(posture("start"))

                def request(req, bridge=bridge):
                    if req["op"] == "act":
                        raise self.reject(bridge)
                    return bridge(req)

                result = self.execute(bridge, request, action, mode=mode)
                self.assertEqual(result["outcome"], "needs_input")
                self.assertNotIn("state_refreshes", result)
                self.assertFalse(bridge.inputs)

    def test_transport_uncertainty_and_native_refusals_are_not_retried(self):
        for error in (
            DFHackError("lost"),
            BridgeError("uncertain", "stale_state"),
            BridgeError("refused", "unsupported", {"view": posture("start")}, False),
        ):
            with self.subTest(error=error):
                bridge = Bridge(posture("start"))
                attempts = 0

                def request(req, bridge=bridge, error=error):
                    nonlocal attempts
                    if req["op"] == "act":
                        attempts += 1
                        raise error
                    return bridge(req)

                if isinstance(error, BridgeError) and error.input_sent is False:
                    self.assertEqual(self.execute(bridge, request)["outcome"], "needs_input")
                else:
                    with self.assertRaises(DFHackError):
                        self.execute(bridge, request)
                self.assertEqual(attempts, 1)


if __name__ == "__main__":
    unittest.main()
