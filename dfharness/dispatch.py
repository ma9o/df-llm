"""One dispatch engine for primitive and semantic actions, with caller-owned policy."""

import json
import time
import uuid
from copy import deepcopy
from typing import Any

from .composition import active_workflow, observation_args, progress
from .policy import execution_policy, interruption, watch_options
from .refusals import native_refusal
from .rpc import BridgeError, DFHackError, pending_pause, rpc_deadline
from .state import compact_result, objective_values, speech_result
from .wire import Checkpoint, observation
from .workflows import SEMANTIC, next_step, validate_action

MAX_STATE_REFRESHES = 3


def response_for(modal, policy):
    if (
        policy["acknowledge"]
        and modal.get("dismissible")
        and (modal.get("kind"), modal.get("button"))
        in (("help", "Okay"), ("announcement", "Okay"), ("announcement", "More"))
    ):
        return {"type": "dismiss"}
    if policy["mode"] == "complete" and modal.get("kind") == "action_prompt":
        return {"type": "action_prompt", "choice": "finish"}
    if policy["mode"] == "complete" and modal.get("kind") == "waiting_prompt":
        return {"type": "action_prompt", "choice": "continue"}
    return None


def prompt_signature(view):
    return (view.get("effect_id"), json.dumps(view["status"].get("modal"), sort_keys=True))


def run_dispatch(
    client,
    action,
    expect=None,
    request_id=None,
    timeout=30,
    execution=None,
    result_format="compact",
    event_detail="task",
    *,
    after=None,
    since=None,
):
    validate_action(action)
    policy = execution_policy(client.execution, execution)
    if type(timeout) not in (int, float) or not 0 < timeout <= 300:
        raise ValueError("timeout must be in (0, 300] seconds")
    if result_format not in ("compact", "full"):
        raise ValueError("result_format must be compact or full")
    if event_detail not in ("task", "all"):
        raise ValueError("event_detail must be task or all")
    root_id = request_id or str(uuid.uuid4())
    deadline = time.monotonic() + timeout

    def send(payload):
        with rpc_deadline(deadline):
            return client.request(payload)

    def read_options(current):
        leaf = active_workflow(current)
        raw_ui = leaf and leaf["action"]["type"] in {
            "key",
            "click",
            "click_text",
            "text",
            "select_unit",
            "resume",
        }
        return {
            **observation_args(current),
            **({"receipt_state": True, "scene_reports": True} if after else {}),
            **watch_options(policy),
            "character_progress": True,
            "navigation_grid": result_format == "full"
            or bool(leaf and leaf["action"]["type"] == "travel_to"),
            "ui_mode": "full" if raw_ui or result_format == "full" else "native",
        }

    read_args = read_options({"action": action, "context": {}})
    request = {
        "op": "begin_dispatch",
        "action": action,
        "request_id": root_id,
        "execution": policy,
        "report_limit": 1,
        "result_format": result_format,
        **read_args,
    }
    if expect is not None:
        request["expect"] = expect
    try:
        start = send(request)
    except BridgeError as exc:
        if exc.code != "stale_state" or exc.input_sent is not False or "view" not in exc.details:
            raise
        view = exc.details["view"]
        view["dispatch"] = {
            "id": root_id,
            "action": action,
            "execution": policy,
            "outcome": "rejected",
            "reason": str(exc),
            "steps": [],
            "events": [],
            "prompts": [],
            "details": {
                "code": exc.code,
                "input_sent": False,
                "expected": exc.details.get("expected"),
                "actual": view["state_id"],
            },
        }
        # No lease/checkpoint was created, so there is nothing to interrupt or resume.
        result = view if result_format == "full" else compact_result(view, view, event_detail)
        if after:
            result["after"] = client._after_scene(
                view, event_detail, policy["interrupt_on"].get("report_types", []), since
            )
        return result
    if start.get("duplicate") and result_format == "compact" and start.get("compact"):
        result = dict(start["compact"], replayed=True)
        if after:
            result["after"] = client.observe(view="concise", event_detail=event_detail, since=since)
        return result
    view = start["view"]
    before = deepcopy(view)
    if start.get("duplicate"):
        if start.get("receipt_view"):
            view = start["receipt_view"]
        view["action"] = {"action_id": root_id, "duplicate": True}
        view["dispatch"] = (
            start.get("dispatch")
            or view.get("dispatch")
            or {
                "id": root_id,
                "execution": policy,
                "outcome": "needs_input",
                "steps": [],
                "events": [],
                "prompts": [],
                "reason": "Earlier dispatch has no final result. Interrupt it or explicitly resume its dispatch_id.",
                "resume_action": {"type": "resume", "dispatch_id": root_id},
            }
        )
        view["dispatch_replayed"] = True
        result = view if result_format == "full" else compact_result(view, before, event_detail)
        if after:
            result["after"] = client.observe(view="concise", event_detail=event_detail, since=since)
        return result
    workflow = start["workflow"]
    saved = Checkpoint(workflow, start.get("workflow_revision"))
    view_ref = start.get("view_ref")
    reusable_state = start if "ready" in start else None
    events = {e["id"]: e for e in workflow.get("events", [])}
    task_event_ids = set(workflow.get("task_event_ids", []))
    observed_progress = {}
    cursor = workflow.setdefault(
        "report_cursor",
        view.get("report_cursor", max((e["id"] for e in view.get("reports", [])), default=-1)),
    )
    # A resume retains history but starts a new controller decision. Reports
    # already returned by the previous dispatch must not interrupt it again.
    interruption_cursor = max(events, default=cursor)
    # Native goal watchers retain the instant that paused a command, including
    # transient changes that have vanished by the next RPC. Consume it once;
    # explicit resume is a new controller decision, just like the event cursor.
    consumed_native_watch = workflow.get("consumed_native_watch")
    receipt_cursor = workflow.get("reported_event_cursor", cursor)
    summary: dict[str, Any] = {
        "id": root_id,
        "action": workflow["action"],
        "execution": policy,
        "outcome": None,
        "steps": [],
        "events": [],
        "prompts": deepcopy(workflow.get("prompts", [])),
    }
    if action.get("dispatch_id"):
        summary["resumed_from"] = action["dispatch_id"]
    last_action = start.get("last_action_id")
    previous_input = None
    previous_prompt = None
    seen_prompts = set()
    mechanical_steps = 0
    pending_read = False
    pending_polls = 0
    state_refreshes = 0

    def observe():
        nonlocal view_ref
        view_ref = None
        return send(
            {
                "op": "observe",
                "reports_after": max(events, default=cursor),
                **read_options(workflow),
            }
        )

    def collect(observation):
        for event in observation.get("reports", []):
            if event["id"] > cursor:
                events[event["id"]] = event

    def finish(outcome, reason, next_action=None, details: dict[str, Any] | None = None):
        nonlocal view, view_ref, pending_read
        if pending_read or (
            after and (read_args.get("route_target") or read_args.get("target_unit_id"))
        ):
            # Observers can stop execution on a narrow processing sample. Final
            # records need a complete snapshot, retained by the same wire peer.
            # A standalone observe would discard its revision and send the
            # entire snapshot back again in finish_dispatch.
            final_poll = {
                "op": "poll",
                "dispatch_id": root_id,
                "observe": True,
                "pending_reads": False,
                "reports_after": max(events, default=cursor),
                **read_options(workflow),
                **(
                    {"map_fixed": True, "map": True, "width": 41, "height": 21, "radius": 20}
                    if after
                    else {}
                ),
                **({"action_id": last_action} if last_action else {}),
                **({"view_ref": view_ref} if view_ref is not None else {}),
            }
            final_state = send(final_poll)
            if "pending_view" in final_state:
                raise DFHackError("Final observation is still partial; no further input was sent")
            if "view" in final_state or "view_delta" in final_state:
                view, view_ref = observation(final_state, view, view_ref)
            else:
                view = observe()
            pending_read = False
            if final_state.get("world_changed"):
                outcome = "interrupted"
                reason = "World changed; observe and start a new dispatch. Old progress cannot be resumed."
                details = {"blocker_kind": "world_changed"}
                next_action = None
        world_changed = (details or {}).get("blocker_kind") == "world_changed"
        if not world_changed:
            collect(view)
        if outcome in ("no_effect", "needs_input") and not world_changed:
            leaf = active_workflow(workflow)
            refusal = native_refusal(leaf, view, events.values()) if leaf else None
            if refusal:
                details = deepcopy(details or {})
                details["verification_reason"] = reason
                details["blocker_kind"] = "native_refusal"
                details["facts"] = {**details.get("facts", {}), **refusal["facts"]}
                reason, outcome = refusal["reason"], "needs_input"
                # A resume can still verify a late postcondition, but must not
                # replay the refused input when a recipe has consumed pending.
                leaf.setdefault("context", {})["native_refusal"] = deepcopy(refusal)
        workflow["events"] = list(events.values())
        workflow["task_event_ids"] = sorted(task_event_ids)
        workflow["prompts"] = summary["prompts"]
        summary.update(
            outcome=outcome,
            reason=reason,
            events=list(events.values()),
            progress=progress(workflow),
        )
        summary["progress"].update(observed_progress)
        if task_event_ids:
            summary["task_event_ids"] = sorted(task_event_ids)
        if "results" in workflow.get("context", {}):
            summary["results"] = deepcopy(workflow["context"]["results"])
        if outcome != "completed" and not world_changed:
            summary["resume_action"] = {"type": "resume", "dispatch_id": root_id}
        if next_action:
            summary["next_action"] = next_action
        if details is not None:
            summary["details"] = details
        if outcome != "completed":
            summary["blocker"] = {
                "kind": (details or {}).get("blocker_kind")
                or {
                    "limit_reached": "execution_limit",
                    "interrupted": "interrupted",
                    "in_progress": "incremental_boundary",
                    "no_effect": "verification",
                    "failed": "execution_failure",
                }.get(outcome, "controller_choice"),
                "reason": reason,
            }
            if "stage_index" in summary["progress"]:
                summary["blocker"]["stage_index"] = summary["progress"]["stage_index"]
        if view["status"].get("active_dispatch", {}).get("id") == root_id:
            view["status"].pop("active_dispatch")
        view["dispatch"] = summary
        view["action"] = {"action_id": root_id}
        seen_replies = workflow.get("reported_reply_ids", [])
        reported_value_stage = workflow.get("reported_value_stage", -1)
        compact = compact_result(
            view,
            view if world_changed else before,
            event_detail,
            seen_replies,
            receipt_cursor,
            reported_value_stage,
        )
        if after:
            final_scene = client._after_scene(
                view, event_detail, policy["interrupt_on"].get("report_types", []), since
            )
            compact["after"] = final_scene
            # Avoid persisting a second observation inside the native full snapshot.
        value_stage = objective_values(summary, reported_value_stage)[1]
        if value_stage >= 0:
            workflow["reported_value_stage"] = value_stage
        workflow["reported_event_cursor"] = max(events, default=cursor)
        if consumed_native_watch is not None:
            workflow["consumed_native_watch"] = consumed_native_watch
        workflow["reported_reply_ids"] = sorted(
            set(seen_replies) | speech_result(summary, seen_replies)[1]
        )
        receipt = {
            "op": "finish_dispatch",
            "action_id": root_id,
            **saved.request(workflow),
            "dispatch": summary,
            "compact": compact,
            **({"view_ref": view_ref} if view_ref is not None else {"view": view}),
        }
        if saved.revision is not None:
            receipt["dispatch_from_workflow"] = True
            receipt["dispatch"] = {
                k: v
                for k, v in summary.items()
                if k not in ("action", "events", "prompts", "results")
            }
        stored = send(receipt)
        saved.accepted(workflow, stored)
        return (
            dict(view, after=compact["after"])
            if after and result_format == "full"
            else view
            if result_format == "full"
            else compact
        )

    while True:
        # Poll also checks an external interruption flag. No core suspension is
        # held while the game advances or while this process waits.
        needed = read_options(workflow)
        if reusable_state is not None and read_args == needed:
            state = reusable_state
            observed = view
        else:
            poll = {
                "op": "poll",
                "dispatch_id": root_id,
                "observe": True,
                "reports_after": max(events, default=cursor),
                "pending_reads": result_format != "full",
                **needed,
            }
            if last_action:
                poll["action_id"] = last_action
            if view_ref is not None:
                poll["view_ref"] = view_ref
            state = send(poll)
            # Read readiness, events and observation in the same native request.
            # Older diagnostic peers can still return an ordinary full view.
            if "pending_view" in state:
                observed = state["pending_view"]
                if (
                    state.get("ready") is not False
                    or not poll["pending_reads"]
                    or needed["ui_mode"] == "full"
                    or not isinstance(observed, dict)
                    or observed.get("schema_version") != 1
                    or not isinstance(observed.get("status"), dict)
                    or any(k in state for k in ("view", "view_delta", "view_ref"))
                ):
                    raise DFHackError("Invalid pending observation; no further input was sent")
                pending_read = True
            elif "view" in state or "view_delta" in state:
                view, view_ref = observation(state, view, view_ref)
                observed = view
                pending_read = False
            else:
                view = observe()
                observed = view
                pending_read = False
            read_args = needed
        reusable_state = None
        if previous_input is not None and state.get("presentation") is not None:
            previous_input["presentation"] = deepcopy(state["presentation"])
        if state.get("world_changed"):
            return finish(
                "interrupted",
                "World changed; observe and start a new dispatch. Old progress cannot be resumed.",
                details={"blocker_kind": "world_changed"},
            )
        if state.get("interrupted"):
            return finish(
                "interrupted",
                "The controller interrupted this dispatch; no further input was sent.",
            )
        if state.get("action_error"):
            return finish("failed", "Input may have partially executed: " + state["action_error"])
        collect(observed)
        native_watch = (observed.get("input_evidence") or {}).get("watch_view")
        native_watch_id = needed.get("input_evidence_for")
        if native_watch and native_watch_id and native_watch_id != consumed_native_watch:
            consumed_native_watch = native_watch_id
            workflow["consumed_native_watch"] = native_watch_id
            stopped = interruption(before, native_watch, native_watch.get("reports", []), policy)
            if stopped:
                return finish(**stopped)
        stopped = interruption(
            before, observed, (e for e in events.values() if e["id"] > interruption_cursor), policy
        )
        if stopped:
            return finish(**stopped)
        if observed.get("report_cursor_reset"):
            return finish(
                "needs_input",
                "The native report cursor reset; start a new dispatch after reviewing the current state.",
                details={"blocker_kind": "report_cursor_reset"},
            )
        if observed.get("reports_more"):
            if time.monotonic() >= deadline:
                return finish(
                    "limit_reached",
                    "Report collection reached the dispatch timeout; resume to collect the remaining page.",
                )
            continue
        if not state["ready"] or observed["status"].get("ready_for_input") is False:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return finish(
                    "limit_reached",
                    "Dispatch timeout; already submitted game input was not cancelled or retried.",
                )
            time.sleep(pending_pause(pending_polls, remaining))
            pending_polls += 1
            continue
        pending_polls = 0
        if previous_input:
            previous_input["state_id"] = view.get("state_id")
            previous_input["effect_observed"] = previous_input.pop(
                "before_effect_id", None
            ) != view.get("effect_id")
            previous_input = None
        if previous_prompt is not None and prompt_signature(view) == previous_prompt:
            return finish("no_effect", "The delegated response did not change the prompt.")
        previous_prompt = None
        ctx = workflow.get("context", {})
        explicit_primitive = workflow["action"]["type"] not in SEMANTIC | {
            "resume"
        } and not ctx.get("raw_sent")
        modal = view["status"].get("modal")
        checkpoint = deepcopy(workflow)
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
            # Include reports retained across intermediate prompts and stage
            # boundaries, so reply verification does not depend on the UI tail.
            reports = {e["id"]: e for e in view.get("reports", [])}
            reports.update(events)
            decision = next_step(planned, dict(view, reports=list(reports.values())))
            refusal = (active_workflow(workflow) or {}).get("context", {}).get("native_refusal")
            if refusal and "input" in decision:
                return finish(
                    "needs_input",
                    refusal["reason"],
                    details={"blocker_kind": "native_refusal", "facts": refusal["facts"]},
                )
            task_event_ids.update(decision.get("task_event_ids", []))
            # Observation facts remain useful when an input limit prevents
            # committing the planned mechanics. Never commit an unsent step's
            # pending marker just to report the listener's observed condition.
            observed_progress = decision.get("progress", {})
            if decision.get("advanced"):
                workflow = planned
                # Planning another stage does not change the game. Reuse this
                # exact snapshot if it contains that stage's required readers.
                # Every subsequent native input still checks the lease/guard.
                if view_ref is not None:
                    reusable_state = state
                continue
            if "outcome" in decision:
                # Keep the pre-verification checkpoint on an ineffective input.
                # A recipe may inspect/pop its pending marker while checking;
                # explicit resume must recheck that input, not send it again.
                workflow = checkpoint if decision["outcome"] == "no_effect" else planned
                if (
                    decision["outcome"] == "completed"
                    and workflow["action"]["type"] not in SEMANTIC | {"resume"}
                    and len(summary["steps"]) == 1
                    and summary["steps"][0].get("effect_observed") is False
                ):
                    return finish(
                        "no_effect", "Input was delivered without an observable state change."
                    )
                return finish(
                    decision["outcome"], decision["reason"], details=decision.get("details")
                )
            if policy["mode"] == "step" and mechanical_steps:
                return finish(
                    "in_progress",
                    "Incremental dispatch stopped after one action step.",
                    decision["input"],
                )
        if len(summary["steps"]) >= policy["max_steps"]:
            return finish("limit_reached", "Dispatch max_steps reached.", decision["input"])
        if time.monotonic() >= deadline:
            return finish(
                "limit_reached",
                "Dispatch timeout reached before the next input.",
                decision["input"],
            )
        if delegated:
            seen_prompts.add(signature)
            previous_prompt = signature
            summary["prompts"].append(
                {
                    "modal": deepcopy(modal),
                    "response": decision["input"],
                    "text": deepcopy(modal.get("text"))
                    or [r["text"].strip() for r in view.get("ui", {}).get("rows", [])],
                }
            )
        else:
            mechanical_steps += 1
            active_workflow(planned).setdefault("context", {})["refusal_after"] = max(
                max(events, default=cursor), view.get("report_cursor", cursor)
            )
            if decision.get("pending"):
                active_workflow(planned).setdefault("context", {})["pending"] = decision["pending"]
        workflow = planned
        workflow["events"] = list(events.values())
        workflow["prompts"] = summary["prompts"]
        child_id = str(uuid.uuid4())
        if decision.get("capture"):
            evidence_key = (
                "path_evidence_for"
                if decision["capture"]["kind"] == "walk"
                else "input_evidence_for"
            )
            active_workflow(workflow).setdefault("context", {})[evidence_key] = child_id
        previous_input = {
            "action_id": child_id,
            "action": decision["input"],
            "state_id": None,
            "effect_observed": None,
            "before_effect_id": view.get("effect_id"),
        }
        summary["steps"].append(previous_input)
        try:
            receipt = send(
                {
                    "op": "act",
                    "action": decision["input"],
                    "request_id": child_id,
                    "expect": (
                        view.get("ui_state_id", view["state_id"])
                        if decision["input"]["type"]
                        in ("click", "click_text", "text", "select_unit")
                        or (
                            decision["input"]["type"] == "key"
                            and active_workflow(workflow)["action"]["type"] == "key"
                        )
                        else view["state_id"]
                    ),
                    "parent_dispatch": root_id,
                    **({"fastcombat": True} if policy["mode"] == "complete" else {}),
                    "ui_mode": read_args["ui_mode"],
                    **({"capture": decision["capture"]} if decision.get("capture") else {}),
                    **(
                        {
                            "path_execution": policy,
                            "path_timeout_ms": max(1, (deadline - time.monotonic()) * 1000),
                        }
                        if decision["input"]["type"] == "path_to"
                        else {}
                    ),
                    **watch_options(policy),
                    **({"watch_expect": view["watched_units"]} if "watched_units" in view else {}),
                    **saved.request(workflow),
                }
            )
        except BridgeError as exc:
            if exc.input_sent is not False or "view" not in exc.details:
                raise
            # The rejected child never ran. Restore its planning changes before
            # deciding whether to replan the same objective or return control.
            workflow = checkpoint
            summary["steps"].pop()
            previous_input = None
            if delegated:
                summary["prompts"].pop()
                seen_prompts.discard(signature)
                previous_prompt = None
            else:
                mechanical_steps -= 1
            view = exc.details["view"]
            view_ref = exc.details.get("view_ref")
            if before["status"].get("world_epoch") is not None and before["status"][
                "world_epoch"
            ] != view["status"].get("world_epoch"):
                return finish(
                    "interrupted",
                    "World changed before input; observe and start a new dispatch.",
                    details={"blocker_kind": "world_changed", "input_sent": False},
                )
            # A fresh rejected-input observation can reveal a requested stop
            # condition. Evaluate it with the same predicates as an ordinary
            # poll, while keeping the last accepted workflow checkpoint.
            collect(view)
            if stopped := interruption(
                before, view, (e for e in events.values() if e["id"] > interruption_cursor), policy
            ):
                return finish(**stopped)
            if (
                exc.code == "stale_state"
                and policy["mode"] == "complete"
                and workflow["action"]["type"]
                in SEMANTIC | {"move", "wait", "select_option", "select_interaction"}
            ):
                if state_refreshes >= MAX_STATE_REFRESHES:
                    return finish(
                        "limit_reached",
                        "Native state kept changing before input; refresh limit reached.",
                        details={
                            "blocker_kind": "state_refresh_limit",
                            "input_sent": False,
                            "facts": {
                                "state_refreshes": state_refreshes,
                                "limit": MAX_STATE_REFRESHES,
                            },
                        },
                    )
                state_refreshes += 1
                summary.setdefault("state_refreshes", []).append(
                    {"expected": exc.details.get("expected"), "actual": view["state_id"]}
                )
                # Poll again to check cancellation, reports, readiness and all
                # controller predicates. Replan from fresh state, never resend
                # the old native selection or retain its unsent pending marker.
                continue
            return finish(
                "needs_input",
                str(exc),
                details={
                    "code": exc.code,
                    "input_sent": False,
                    "expected": exc.details.get("expected"),
                    "actual": exc.details.get("actual", view["state_id"]),
                },
            )
        if receipt.get("interrupted"):
            workflow = checkpoint
            summary["steps"].pop()
            if delegated:
                summary["prompts"].pop()
            view = observe()
            return finish(
                "interrupted", "The controller interrupted the dispatch before the next input."
            )
        saved.accepted(workflow, receipt)
        for field in ("input_key", "ui_adjustment"):
            if field in receipt:
                previous_input[field] = receipt[field]
        last_action = receipt["action_id"]
