"""Small RPC requests using DFHack's mtime loader for explicit package paths."""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

ASSETS = Path(__file__).parent
MARKER = "__DFLLM_JSON__"


def lua_string(value):
    """A literal preserving newlines, Unicode and delimiter-like input."""
    equals = ""
    while "]" + equals + "]" in value:
        equals += "="
    return "[" + equals + "[\n" + value + "]" + equals + "]"


def script_path():
    """The package parent, as seen by DFHack (CrossOver exposes macOS as Z:)."""
    if explicit := os.environ.get("DFLLM_SCRIPT_PATH"):
        return explicit
    path = ASSETS.resolve().parent.as_posix()
    return "Z:" + path if sys.platform == "darwin" else path


@dataclass(frozen=True)
class Program:
    root: str
    request: str

    def render(self):
        return (
            "local root=" + lua_string(self.root) + ";root=root:gsub('\\\\','/'):gsub('/+$','');"
            "assert(root:sub(1,1)=='/' or root:match('^%a:/'),"
            "'DFLLM_SCRIPT_PATH must be absolute');assert(dfhack.filesystem.isdir(root),"
            "'DF-LLM script path unavailable; set DFLLM_SCRIPT_PATH to the package parent');"
            "local package_path=root..'/dfharness/';"
            "local function norm(p) p=p:gsub('\\\\','/');"
            "return dfhack.getOSType()=='windows' and p:lower() or p end;"
            "local path=dfhack.findScript(package_path..'entry');"
            "assert(path and norm(path)==norm(package_path..'entry.lua'),"
            "'DF-LLM package entry unavailable');"
            "dfhack.reqscript(package_path..'entry').request("
            + lua_string(self.request)
            + ",package_path)"
        )


def prepare_program(request):
    return Program(
        script_path(),
        json.dumps(request, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
    )


def make_program(request):
    """Render a request for direct Lua diagnosis using the same script loader."""
    return prepare_program(request).render()
