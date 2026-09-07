"""Controller-authored settings shared by CLI, Python and long-lived MCP clients."""

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path

from .metrics import DEFAULTS as MEASUREMENT_DEFAULTS
from .metrics import configuration as measurement_configuration
from .policy import execution_policy

DEFAULTS = {
    "execution": execution_policy(),
    "dispatch_timeout": 30,
    "result_format": "compact",
    "event_detail": "task",
    "observation_view": "concise",
    "measurement": MEASUREMENT_DEFAULTS,
}


def settings_path(path=None):
    return Path(
        path
        or os.environ.get("DFLLM_SETTINGS")
        or Path(__file__).resolve().parents[1] / ".df-llm/controller.json"
    ).expanduser()


def merge_settings(current, update):
    if not isinstance(update, dict) or update.keys() - DEFAULTS.keys():
        raise ValueError(
            "settings accepts execution, dispatch_timeout, result_format, event_detail, observation_view, measurement"
        )
    result = deepcopy(current)
    result.update(deepcopy(update))
    result["execution"] = execution_policy(current.get("execution"), update.get("execution"))
    result["measurement"] = measurement_configuration(
        current.get("measurement", MEASUREMENT_DEFAULTS), update.get("measurement", {})
    )
    seconds = result["dispatch_timeout"]
    if type(seconds) not in (int, float) or not 0 < seconds <= 300:
        raise ValueError("dispatch_timeout must be in (0, 300] seconds")
    if result["result_format"] not in ("compact", "full"):
        raise ValueError("result_format must be compact or full")
    if result["event_detail"] not in ("task", "all"):
        raise ValueError("event_detail must be task or all")
    if result["observation_view"] not in ("concise", "full"):
        raise ValueError("observation_view must be concise or full")
    return result


def read_settings(path=None):
    path = settings_path(path)
    saved = json.loads(path.read_text()) if path.exists() else {}
    return merge_settings(DEFAULTS, saved)


def write_settings(update, path=None, reset=False):
    path = settings_path(path)
    result = merge_settings(DEFAULTS if reset else read_settings(path), update)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=path.name + ".", delete=False
        ) as f:
            temporary = Path(f.name)
            f.write(json.dumps(result, indent=2) + "\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return result
