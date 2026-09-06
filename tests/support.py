"""A scripted bridge boundary for testing dispatch behavior without a game."""

from collections import deque
from copy import deepcopy
import json

from dfharness.rpc import DFHackError


class Bridge:
    def __init__(self, initial, views=()):
        self.view = deepcopy(initial)
        self.view.setdefault("state_id", "initial-state")
        self.views = deque(deepcopy(list(views)))
        self.calls = []
        self.dispatches = {}
        self.active = None
        self.inputs = []
        self.poll_hook = None
        self.input_hook = None

    def __call__(self, request):
        self.calls.append(deepcopy(request))
        op = request["op"]
        if op == "begin_dispatch":
            key = request["request_id"]
            signature = json.dumps(request, sort_keys=True)
            if key in self.dispatches:
                saved = self.dispatches[key]
                if saved["signature"] != signature:
                    raise DFHackError("request_id reused with different arguments")
                return {"duplicate": True, "action_id": key, "dispatch": deepcopy(saved.get("dispatch")), "view": deepcopy(self.view)}
            resume = request["action"].get("dispatch_id")
            if resume:
                prior = self.dispatches[resume]
                if prior.get("resumed_by"):
                    raise DFHackError("Dispatch was already resumed")
                workflow = deepcopy(prior["workflow"])
                last_action = prior.get("last_action_id")
                prior["resumed_by"] = key
            else:
                workflow = {"action": deepcopy(request["action"]), "context": {}}
                last_action = None
            saved = {"signature": signature, "workflow": workflow, "last_action_id": last_action}
            self.dispatches[key] = saved
            self.active = key
            return {"action_id": key, "workflow": deepcopy(workflow), "view": deepcopy(self.view), "last_action_id": last_action}
        if op == "poll":
            if self.poll_hook:
                value = self.poll_hook(self, request)
                if value is not None:
                    return value
            record = self.dispatches.get(request.get("dispatch_id"), {})
            return {"ready": self.view["status"].get("ready_for_input", True), "interrupted": record.get("interrupted", False)}
        if op == "observe":
            return deepcopy(self.view)
        if op == "act":
            parent = self.dispatches[request["parent_dispatch"]]
            if parent.get("interrupted"):
                return {"interrupted": True, "action_id": request["request_id"]}
            parent["workflow"] = deepcopy(request["workflow"])
            parent["last_action_id"] = request["request_id"]
            self.inputs.append(deepcopy(request["action"]))
            if not self.views:
                raise AssertionError("Unexpected extra input: " + str(request["action"]))
            next_view = self.views.popleft()
            if isinstance(next_view, Exception):
                raise next_view
            self.view = deepcopy(next_view)
            self.view.setdefault("state_id", "state-"+str(len(self.inputs)))
            if self.input_hook:
                self.input_hook(self, request)
            return {"action_id": request["request_id"]}
        if op == "finish_dispatch":
            saved = self.dispatches[request["action_id"]]
            saved.update(workflow=deepcopy(request["workflow"]), dispatch=deepcopy(request["dispatch"]))
            self.active = None
            return {"recorded": True}
        if op == "interrupt":
            self.dispatches[request["dispatch_id"]]["interrupted"] = True
            return {"interruption_requested": True}
        raise AssertionError("Unexpected bridge operation " + op)
