"""Passive controller/RPC measurements; never part of a gameplay response."""

import inspect
import json
import os
import sys
import time
import uuid
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from functools import lru_cache, wraps
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from threading import Lock

from .metrics_tokens import tokenizer

DEFAULTS = {
    "enabled": False,
    "path": None,
    "run": "default",
    "episode": None,
    "tokenizer": "o200k_base",
}


def configuration(current, update):
    if not isinstance(update, dict) or update.keys() - DEFAULTS.keys():
        raise ValueError("measurement accepts enabled, path, run, episode and tokenizer")
    result = {**DEFAULTS, **current, **update}
    if type(result["enabled"]) is not bool:
        raise ValueError("measurement.enabled must be boolean")
    if result["path"] is not None and (
        not isinstance(result["path"], str) or not result["path"] or "\0" in result["path"]
    ):
        raise ValueError("measurement.path must be a nonempty path or null")
    for key in ("run", "tokenizer", "episode"):
        value = result[key]
        if key == "episode" and value is None:
            continue
        if not isinstance(value, str) or not 0 < len(value) <= 128:
            raise ValueError(f"measurement.{key} must be a string of 1..128 characters")
    return result


def serialize(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def intent(action):
    """Bounded target metadata, never dialogue, labels, policies or payload text."""
    if not isinstance(action, dict) or not isinstance(action.get("type"), str):
        return None
    target = {
        key: action[key]
        for key in ("item_id", "container_id", "x", "y", "z")
        if type(action.get(key)) is int
    }
    # A weapon is a means; the creature is the target of a strike.
    if type(action.get("unit_id")) is int:
        target = {"unit_id": action["unit_id"]}
    elif isinstance(action.get("unit_ids"), list):
        ids = action["unit_ids"]
        if 0 < len(ids) <= 32 and all(type(unit) is int for unit in ids):
            target = {"unit_ids": sorted(set(ids))}
    return {"action": action["type"][:64], "target": target or None}


@lru_cache(maxsize=1)
def harness_version():
    try:
        return version("df-llm")
    except PackageNotFoundError:
        return "uninstalled"


def active():
    return CURRENT.get()


class Span:
    def __init__(self, recorder, surface, operation, request, started_ns=None):
        self.recorder = recorder
        self.surface, self.operation, self.request = surface, operation, request
        self.started_ns = time.perf_counter_ns() if started_ns is None else started_ns
        # CLI argument parsing and client construction can precede span construction.
        self.at = datetime.now(UTC) - timedelta(
            microseconds=(time.perf_counter_ns() - self.started_ns) / 1000
        )
        self.id = uuid.uuid4().hex
        self.depth = 0
        self.output = None
        self.output_present = False
        self.outcome = "ok"
        self.fields = {}
        self.rpc_calls = 0
        self.rpc_ms = 0.0

    def action(self, action):
        identity = intent(action)
        if identity is None:
            return
        self.fields["action"] = identity["action"]
        if identity["action"] == "resume":
            if isinstance(action.get("dispatch_id"), str):
                self.fields["resume_id"] = action["dispatch_id"]
        elif identity["action"] == "sequence":
            stages = action.get("actions")
            if isinstance(stages, list):
                self.fields["intents"] = [intent(stage) for stage in stages[:64]]
                if len(stages) > 64:
                    self.fields["intents_truncated"] = True
        else:
            self.fields["intents"] = [identity]

    def result(self, value):
        """Read only useful result metadata; never retain traces in the log."""
        if not isinstance(value, dict):
            return
        if "outcome" in value:
            self.outcome = value["outcome"]
        elif value.get("available") is False:
            self.outcome = "unavailable"
        for key in ("dispatch_id", "inputs", "ticks"):
            if key in value and isinstance(value[key], (str, int, float)):
                self.fields[key] = value[key]
        dispatch = value.get("dispatch")
        if isinstance(dispatch, dict):
            self.outcome = dispatch.get("outcome", self.outcome)
            if isinstance(dispatch.get("id"), str):
                self.fields["dispatch_id"] = dispatch["id"]
        # A failed sequence reports its active objective, not all planned stages.
        if self.fields.get("action") == "sequence":
            blocker = value.get("blocker") or {}
            current = blocker.get("action")
            if current is None and isinstance(dispatch, dict):
                current = dispatch.get("progress", {}).get("current_action")
            if identity := intent(current):
                self.fields["blocked_intent"] = identity

    def respond(self, value, *, text=False):
        if self.recorder.path is None:
            return
        try:
            self.output = value if text else serialize(value)
            self.output_present = True
        except Exception as exc:  # noqa: BLE001 -- observation must stay passive.
            self.recorder.warn("response measurement unavailable", exc)

    def fail(self, error):
        self.outcome = "error"
        self.fields["error_type"] = type(error).__name__
        for key in ("code", "dispatch_id", "input_sent"):
            value = getattr(error, key, None)
            if isinstance(value, (str, int, float, bool)):
                self.fields[key] = value


CURRENT: ContextVar[Span | None] = ContextVar("dfharness_measurement", default=None)


class Recorder:
    def __init__(self, path=None, *, run="default", episode=None, encoding="o200k_base"):
        self.path = Path(path).expanduser() if path else None
        self.run, self.encoding = run, encoding
        self.episode = episode
        self.lock = Lock()
        self.failed = False
        self.warned = set()

    def warn(self, kind, exc):
        if kind not in self.warned:
            self.warned.add(kind)
            # A closed diagnostic stream must not turn metrics into a failure.
            with suppress(OSError, ValueError):
                print(f"df-llm measurement {kind}: {exc}", file=sys.stderr)

    def write(self, row):
        if self.path is None or self.failed:
            return
        try:
            payload = (serialize(row) + "\n").encode("utf-8")
            with self.lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                try:
                    if os.write(fd, payload) != len(payload):
                        raise OSError("Incomplete measurement append")
                finally:
                    os.close(fd)
        except Exception as exc:  # noqa: BLE001 -- metrics must never change execution.
            self.failed = True
            self.warn("log unavailable", exc)

    def base(self, kind, span):
        return {
            "schema_version": 1,
            "kind": kind,
            "run": self.run,
            "episode": self.episode,
            "harness_version": harness_version(),
            "trace_id": span.id,
        }

    @contextmanager
    def interaction(self, surface, operation, request, *, started_ns=None):
        existing = active()
        if existing is not None:
            yield existing
            return
        span = Span(self, surface, operation, request, started_ns)
        context = CURRENT.set(span)
        try:
            yield span
        except BaseException as exc:
            span.fail(exc)
            raise
        finally:
            elapsed = (time.perf_counter_ns() - span.started_ns) / 1e6
            CURRENT.reset(context)
            if self.path is not None and not self.failed:
                self.finish(span, elapsed)

    def finish(self, span, duration):
        started = time.perf_counter_ns()
        try:
            request = serialize(span.request)
            row = {
                **self.base("interaction", span),
                "id": span.id,
                "at": span.at.isoformat(),
                "surface": span.surface,
                "operation": span.operation,
                "outcome": span.outcome,
                "duration_ms": round(duration, 3),
                "input_bytes": len(request.encode("utf-8")),
                "output_bytes": len(span.output.encode("utf-8")) if span.output_present else None,
                "input_tokens": None,
                "output_tokens": None,
                "tokenizer": self.encoding,
                "rpc_calls": span.rpc_calls,
                "rpc_ms": round(span.rpc_ms, 3),
                **span.fields,
            }
            try:
                encoder = tokenizer(self.encoding)
                row["input_tokens"] = len(encoder.encode_ordinary(request))
                if span.output_present:
                    row["output_tokens"] = len(encoder.encode_ordinary(span.output))
                row["tokenizer_version"] = version("tiktoken")
            except Exception as exc:  # noqa: BLE001 -- unknown counts must not block gameplay.
                row["token_error"] = type(exc).__name__
                self.warn("token counts unavailable", exc)
            row["measurement_ms"] = round((time.perf_counter_ns() - started) / 1e6, 3)
            row["finished_at"] = (
                span.at + timedelta(milliseconds=duration + row["measurement_ms"])
            ).isoformat()
            self.write(row)
        except Exception as exc:  # noqa: BLE001 -- even serialization failure is passive.
            self.warn("record unavailable", exc)

    @contextmanager
    def rpc(self, operation, input_bytes):
        parent = active()
        sample = {
            "operation": operation,
            "input_bytes": input_bytes,
            "output_bytes": None,
            "outcome": "ok",
        }
        started = time.perf_counter_ns()
        at = datetime.now(UTC).isoformat()
        try:
            yield sample
        except BaseException as exc:
            sample.update(outcome="error", error_type=type(exc).__name__)
            output = getattr(exc, "output", None)
            if isinstance(output, str):
                sample["output_bytes"] = len(output.encode("utf-8"))
            code = getattr(exc, "code", None)
            if isinstance(code, (str, int)):
                sample["code"] = code
            raise
        finally:
            duration = (time.perf_counter_ns() - started) / 1e6
            if parent is not None and self.path is not None:
                parent.rpc_calls += 1
                parent.rpc_ms += duration
                self.write(
                    {
                        **self.base("rpc", parent),
                        "id": uuid.uuid4().hex,
                        "parent_id": parent.id,
                        "at": at,
                        "duration_ms": round(duration, 3),
                        **sample,
                    }
                )


def measured(method):
    """Only the outer Python/CLI boundary becomes a controller interaction."""
    signature = inspect.signature(method)

    @wraps(method)
    def wrapped(self, *args, **kwargs):
        current = active()
        recorder = current.recorder if current else self.metrics
        with recorder.interaction(
            "python", method.__name__, {"args": args, "kwargs": kwargs}
        ) as span:
            outer = span.depth == 0
            span.depth += 1
            try:
                arguments = dict(signature.bind(self, *args, **kwargs).arguments)
                arguments.pop("self")
                if outer:
                    if span.surface == "python":
                        span.request = arguments
                    span.action(arguments.get("action"))
                result = method(self, *args, **kwargs)
                if outer:
                    span.result(result)
                    if span.surface == "python":
                        span.respond(result)
                return result
            finally:
                span.depth -= 1

    return wrapped
