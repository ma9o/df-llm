"""Find the game in a CrossOver bottle and configure its loopback RPC port."""

import json
import os
import socket
import subprocess
from pathlib import Path

from .rpc import Connection, DFHackError

WINE = Path("/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine")


def installations():
    if os.environ.get("DF_PATH"):
        return [Path(os.environ["DF_PATH"]).expanduser().resolve()]
    bottles = Path.home() / "Library/Application Support/CrossOver/Bottles"
    roots = list(
        bottles.glob("*/drive_c/Program Files (x86)/Steam/steamapps/common/Dwarf Fortress")
    )
    roots += list(bottles.glob("*/drive_c/Program Files/Steam/steamapps/common/Dwarf Fortress"))
    roots += [
        Path.home() / p
        for p in (
            ".local/share/Steam/steamapps/common/Dwarf Fortress",
            ".steam/steam/steamapps/common/Dwarf Fortress",
            "Library/Application Support/Steam/steamapps/common/Dwarf Fortress",
        )
    ]
    return sorted({p.resolve() for p in roots if p.is_dir()})


def game_path():
    paths = installations()
    if len(paths) > 1:
        raise DFHackError(
            "Multiple installations found; set DF_PATH to the intended game directory"
        )
    return paths[0] if paths else None


def remote_config(path):
    return path / "dfhack-config/remote-server.json"


def port_for_game(explicit=None):
    if explicit is not None:
        return explicit
    if os.environ.get("DFHACK_PORT"):
        return int(os.environ["DFHACK_PORT"])
    path = game_path()
    if path and remote_config(path).exists():
        return int(json.loads(remote_config(path).read_text()).get("port", 5000))
    return 5000


def probe(port):
    try:
        with Connection(port, timeout=0.7):
            return {"port": port, "dfhack": True}
    except DFHackError as exc:
        return {"port": port, "dfhack": False, "error": str(exc)}


def configure(port=5001):
    path = game_path()
    if path is None or not path.is_dir():
        raise DFHackError("Game directory not found. Set DF_PATH to the Dwarf Fortress directory")
    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    target = remote_config(path)
    old_text = target.read_text() if target.exists() else None
    config = json.loads(old_text) if old_text else {}
    if config.get("port", 5000) != port:
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError as exc:
                raise DFHackError(f"Port {port} is already occupied; choose another port") from exc
    config.update(port=port, allow_remote=False)
    new_text = json.dumps(config, indent=2) + "\n"
    if new_text != old_text:
        target.parent.mkdir(parents=True, exist_ok=True)
        if old_text is not None:
            backup = target.with_suffix(".json.df-llm-backup")
            if not backup.exists():
                backup.write_text(old_text)
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(new_text)
        temporary.replace(target)
    return {
        "config": str(target),
        "port": port,
        "allow_remote": False,
        "note": "Restart DFHack if it was already running when the port changed.",
    }


def launch(direct=False):
    path = game_path()
    if path is None or "drive_c" not in path.parts or not WINE.exists():
        raise DFHackError("Automatic launch requires a discovered CrossOver installation")
    bottle = path.parts[path.parts.index("drive_c") - 1]
    command = [str(WINE), "--bottle", bottle, "--no-wait"]
    if direct:
        if not (path / "dfhooks_dfhack.ini").exists():
            raise DFHackError(
                "Launch DFHack through Steam once to install its hook before using --direct"
            )
        command += ["--workdir", str(path), str(path / "Dwarf Fortress.exe")]
    else:
        command += ["--start", "steam://rungameid/2346660"]
    # A Wine child can retain pipes after its launcher exits. Do not wait on
    # captured stdout/stderr for a long-running GUI application.
    subprocess.Popen(
        command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
    )
    return {
        "bottle": bottle,
        "requested": "DF executable" if direct else "DFHack via Steam",
        "game_path": str(path),
        "next": "./dfctl status",
    }


def discover_saves(roots):
    records = {}
    for root in roots:
        if not root.is_dir():
            continue
        for folder in root.iterdir():
            if not folder.is_dir() or folder.name == "current":
                continue
            markers = [name for name in ("world.sav", "world.dat") if (folder / name).is_file()]
            if markers:
                records[str(folder.resolve())] = {
                    "name": folder.name,
                    "path": str(folder.resolve()),
                    "markers": markers,
                }
    return sorted(records.values(), key=lambda r: (r["name"], r["path"]))


def doctor(explicit_port=None):
    path = game_path()
    port = port_for_game(explicit_port)
    result = {
        "game_path": str(path) if path else None,
        "crossover": WINE.exists(),
        "connection": probe(port),
    }
    if path:
        result["dfhack_installed"] = (path / "hack").exists() or (
            path.parent / "DFHack/hack"
        ).exists()
        save_roots = [path / "save", path / "data/save"]
        if "drive_c" in path.parts:
            drive = Path(*path.parts[: path.parts.index("drive_c") + 1])
            save_roots += list(
                (drive / "users").glob("*/AppData/Roaming/Bay 12 Games/Dwarf Fortress/save")
            )
        result["save_roots"] = [str(root) for root in save_roots if root.is_dir()]
        result["save_records"] = discover_saves(save_roots)
        result["saves"] = sorted({r["name"] for r in result["save_records"]})
    if not result["connection"]["dfhack"]:
        result["next"] = "./dfctl setup --port 5001; ./dfctl launch; ./dfctl status"
    return result
