"""One dispatch engine for primitive and semantic actions, with caller-owned policy."""

from copy import deepcopy
import json
import time
import uuid

from .state import compact_result
from .workflows import SEMANTIC, next_step, validate_action


DEFAULT_EXECUTION = {"mode": "step", "acknowledge": False, "max_steps": 32, "interrupt_on": {}}


def execution_policy(defaults=None, override=None):
    policy = deepcopy(DEFAULT_EXECUTION)
    for supplied in (defaults, override):
        if supplied is None:
            continue
        if not isinstance(supplied, dict) or supplied.keys() - policy.keys():
            raise ValueError("execution accepts mode, acknowledge, max_steps, and interrupt_on only")
        policy.update(deepcopy(supplied))
    if policy["mode"] not in ("step", "complete"):
        raise ValueError("execution.mode must be step or complete")
    if type(policy["acknowledge"]) is not bool:
        raise ValueError("execution.acknowledge must be a boolean")
    if type(policy["max_steps"]) is not int or not 1 <= policy["max_steps"] <= 64:
        raise ValueError("execution.max_steps must be an integer in [1, 64]")
    rules = policy["interrupt_on"]
    if not isinstance(rules, dict) or rules.keys() - {"blood_loss", "new_wounds", "new_visible_units", "visible_unit_ids", "report_types"}:
        raise ValueError("Unknown interrupt_on condition")
    for name in ("blood_loss", "new_wounds", "new_visible_units"):
        if name in rules and type(rules[name]) is not bool:
            raise ValueError("interrupt_on."+name+" must be boolean")
    for name, item_type in (("visible_unit_ids", int), ("report_types", str)):
        values = rules.get(name, [])
        if not isinstance(values, list) or len(values) > 100 or any(type(v) is not item_type for v in values):
            raise ValueError("interrupt_on."+name+" must be a list of at most 100 values")
        if name == "visible_unit_ids" and any(v < 0 for v in values):
            raise ValueError("Visible unit IDs must be nonnegative")
    return policy


def response_for(modal, policy):
    if (policy["acknowledge"] and modal.get("dismissible") and
            (modal.get("kind"), modal.get("button")) in
            (("help", "Okay"), ("announcement", "Okay"), ("announcement", "More"))):
        return {"type": "dismiss"}
    if policy["mode"] == "complete" and modal.get("kind") == "action_prompt":
        return {"type": "action_prompt", "choice": "finish"}


def interruption_reason(before, view, events, policy):
    """Evaluate explicit factual predicates, never a built-in threat score."""
    rules = policy["interrupt_on"]
    old = (before.get("adventurer") or {}).get("health", {})
    new = (view.get("adventurer") or {}).get("health", {})
    for condition, field, compare in (("blood_loss", "blood_count", lambda a, b: b < a),
                                       ("new_wounds", "wounds", lambda a, b: b > a)):
        if rules.get(condition) and field in old and field in new and compare(old[field], new[field]):
            return "Controller interruption condition matched: " + condition
    units = {u["id"] for u in (view.get("map") or {}).get("units", [])}
    previous = {u["id"] for u in (before.get("map") or {}).get("units", [])}
    if rules.get("new_visible_units") and units - previous:
        return "Controller interruption condition matched: new_visible_units " + str(sorted(units - previous))
    if units.intersection(rules.get("visible_unit_ids", [])):
        return "Controller interruption condition matched: visible_unit_ids"
    if any(e.get("type") in rules.get("report_types", []) for e in events):
        return "Controller interruption condition matched: report_types"


def prompt_signature(view):
    return (view.get("effect_id"), json.dumps(view["status"].get("modal"), sort_keys=True))


def run_dispatch(client, action, expect=None, request_id=None, timeout=30, execution=None, result_format="compact"):
    validate_action(action)
    policy = execution_policy(client.execution, execution)
    if type(timeout) not in (int, float) or not 0 < timeout <= 300:
        raise ValueError("timeout must be in (0, 300] seconds")
    if result_format not in ("compact", "full"):
        raise ValueError("result_format must be compact or full")
    root_id = request_id or str(uuid.uuid4())
    deadline = time.monotonic() + timeout
    request = {"op": "begin_dispatch", "action": action, "request_id": root_id, "execution": policy}
    if expect is not None:
        request["expect"] = expect
    start = client.request(request)
    view = start["view"]
    before = deepcopy(view)
    if start.get("duplicate"):
        view["action"] = {"action_id": root_id, "duplicate": True}
        view["dispatch"] = start.get("dispatch") or {
            "id": root_id, "execution": policy, "outcome": "needs_input", "steps": [], "events": [], "prompts": [],
            "reason": "Earlier dispatch has no final result. Interrupt it or explicitly resume its dispatch_id.",
            "resume_action": {"type": "resume", "dispatch_id": root_id},
        }
        view["dispatch_replayed"] = True
        return view if result_format == "full" else compact_result(view, before)
    workflow = start["workflow"]
    events = {e["id"]: e for e in workflow.get("events", [])}
    cursor = workflow.setdefault("report_cursor", max((e["id"] for e in view.get("reports", [])), default=-1))
    # A resume retains history but starts a new controller decision. Reports
    # already returned by the previous dispatch must not interrupt it again.
    interruption_cursor = max(events, default=cursor)
    summary = {"id": root_id, "action": workflow["action"], "execution": policy,
               "outcome": None, "steps": [], "events": [], "prompts": deepcopy(workflow.get("prompts", []))}
    if action.get("dispatch_id"):
        summary["resumed_from"] = action["dispatch_id"]
    last_action = start.get("last_action_id")
    previous_input = None
    previous_prompt = None
    seen_prompts = set()
    mechanical_steps = 0

    def collect(observation):
        for event in observation.get("reports", []):
            if event["id"] > cursor:
                events[event["id"]] = event

    def finish(outcome, reason, next_action=None, details=None):
        collect(view)
        workflow["events"] = list(events.values())
        workflow["prompts"] = summary["prompts"]
        summary.update(outcome=outcome, reason=reason, events=list(events.values()),
                       progress={"task_index": workflow.get("context", {}).get("task_index", 0),
                                 "task_count": len(workflow.get("context", {}).get("tasks", []))})
        if outcome != "completed":
            summary["resume_action"] = {"type": "resume", "dispatch_id": root_id}
        if next_action:
            summary["next_action"] = next_action
        if details is not None:
            summary["details"] = details
        client.request({"op": "finish_dispatch", "action_id": root_id, "workflow": workflow, "dispatch": summary})
        if view["status"].get("active_dispatch", {}).get("id") == root_id:
            view["status"].pop("active_dispatch")
        view["dispatch"] = summary
        view["action"] = {"action_id": root_id}
        return view if result_format == "full" else compact_result(view, before)

    while True:
        # Poll also checks an external interruption flag. No core suspension is
        # held while the game advances or while this process waits.
        poll = {"op": "poll", "dispatch_id": root_id}
        if last_action:
            poll["action_id"] = last_action
        state = client.request(poll)
        if state.get("interrupted"):
            view = client.observe()
            return finish("interrupted", "The controller interrupted this dispatch; no further input was sent.")
        if state.get("action_error"):
            view = client.observe()
            return finish("failed", "Input may have partially executed: " + state["action_error"])
        if last_action or not state["ready"]:
            view = client.observe()
        collect(view)
        reason = interruption_reason(before, view, (e for e in events.values() if e["id"] > interruption_cursor), policy)
        if reason:
            return finish("interrupted", reason)
        if not state["ready"] or view["status"].get("ready_for_input") is False:
            if time.monotonic() >= deadline:
                return finish("limit_reached", "Dispatch timeout; already submitted game input was not cancelled or retried.")
            time.sleep(0.05)
            continue
        if previous_input:
            previous_input["state_id"] = view.get("state_id")
            previous_input["effect_observed"] = previous_input.pop("before_effect_id", None) != view.get("effect_id")
            previous_input = None
        if previous_prompt is not None and prompt_signature(view) == previous_prompt:
            return finish("no_effect", "The delegated response did not change the prompt.")
        previous_prompt = None
        ctx = workflow.get("context", {})
        explicit_primitive = workflow["action"]["type"] not in SEMANTIC | {"resume"} and not ctx.get("raw_sent")
        modal = view["status"].get("modal")
        planned = deepcopy(workflow)
        delegated = False
        if modal and not explicit_primitive:
            response = response_for(modal, policy)
            if response is None:
                return finish("needs_input", "The current prompt response was not delegated.")
            signature = prompt_signature(view)
            if signature in seen_prompts:
                return finish("no_effect", "A previously handled prompt state reappeared.")
            decision = {"input": response}
            delegated = True
        else:
            decision = next_step(planned, view)
            if "outcome" in decision:
                workflow = planned
                if (decision["outcome"] == "completed" and workflow["action"]["type"] not in SEMANTIC | {"resume"}
                        and len(summary["steps"]) == 1 and summary["steps"][0].get("effect_observed") is False):
                    return finish("no_effect", "Input was delivered without an observable state change.")
                return finish(decision["outcome"], decision["reason"], details=decision.get("details"))
            if policy["mode"] == "step" and mechanical_steps:
                return finish("in_progress", "Incremental dispatch stopped after one action step.", decision["input"])
        if len(summary["steps"]) >= policy["max_steps"]:
            return finish("limit_reached", "Dispatch max_steps reached.", decision["input"])
        if time.monotonic() >= deadline:
            return finish("limit_reached", "Dispatch timeout reached before the next input.", decision["input"])
        if delegated:
            seen_prompts.add(signature)
            previous_prompt = signature
            summary["prompts"].append({"modal": deepcopy(modal), "response": decision["input"],
                "text": deepcopy(modal.get("text")) or [r["text"].strip() for r in view.get("ui", {}).get("rows", [])]})
        else:
            mechanical_steps += 1
            if decision.get("pending"):
                planned.setdefault("context", {})["pending"] = decision["pending"]
        workflow = planned
        workflow["events"] = list(events.values())
        workflow["prompts"] = summary["prompts"]
        child_id = str(uuid.uuid4())
        previous_input = {"action_id": child_id, "action": decision["input"], "state_id": None,
                          "effect_observed": None, "before_effect_id": view.get("effect_id")}
        summary["steps"].append(previous_input)
        receipt = client.request({"op": "act", "action": decision["input"], "request_id": child_id,
                                  "expect": view["state_id"], "parent_dispatch": root_id, "workflow": workflow})
        if receipt.get("interrupted"):
            summary["steps"].pop()
            view = client.observe()
            return finish("interrupted", "The controller interrupted the dispatch before the next input.")
        last_action = receipt["action_id"]
