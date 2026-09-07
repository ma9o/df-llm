"""Explicit tokenizer preparation; measurement never invokes a network loader."""

import base64
import gzip
import hashlib
import json
import os
import tempfile
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path


def encoding_path(name):
    root = Path(os.environ.get("DFLLM_TOKENIZER_DIR", "~/.cache/df-llm/tokenizers")).expanduser()
    # Names are metadata, never paths. Separate artifacts across tiktoken versions.
    key = hashlib.sha256(f"{version('tiktoken')}:{name}".encode()).hexdigest()
    return root / f"{key}.json.gz"


def prepare(name):
    """The only network-capable entry point. Called by explicit CLI setup only."""
    import tiktoken
    from tiktoken_ext.openai_public import ENCODING_CONSTRUCTORS

    if name not in ENCODING_CONSTRUCTORS:
        raise ValueError(
            f"Unknown tokenizer {name!r}; choose from {', '.join(ENCODING_CONSTRUCTORS)}"
        )
    # Use the installed definitions (and their verified downloads), not a copy
    # of token patterns or a patch to the library's process-wide network code.
    arguments = ENCODING_CONSTRUCTORS[name]()
    tiktoken.Encoding(**arguments)  # Validate before replacing the local artifact.
    arguments["mergeable_ranks"] = [
        [base64.b64encode(token).decode("ascii"), rank]
        for token, rank in arguments["mergeable_ranks"].items()
    ]
    document = {
        "schema_version": 1,
        "tiktoken_version": version("tiktoken"),
        "arguments": arguments,
    }
    payload = gzip.compress(json.dumps(document, separators=(",", ":")).encode(), mtime=0)
    path = encoding_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(payload)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    load_encoding.cache_clear()
    return {
        "tokenizer": name,
        "tiktoken_version": version("tiktoken"),
        "path": str(path),
        "bytes": len(payload),
    }


@lru_cache(maxsize=8)
def load_encoding(name, path, _modified_ns):
    import tiktoken

    with gzip.open(path, "rt", encoding="utf-8") as stream:
        document = json.load(stream)
    arguments = document["arguments"]
    if (
        document["schema_version"] != 1
        or document["tiktoken_version"] != version("tiktoken")
        or arguments["name"] != name
    ):
        raise ValueError("Prepared tokenizer does not match the installed encoding/version")
    arguments["mergeable_ranks"] = {
        base64.b64decode(token, validate=True): rank for token, rank in arguments["mergeable_ranks"]
    }
    return tiktoken.Encoding(**arguments)


def tokenizer(name):
    path = encoding_path(name)
    try:
        modified = path.stat().st_mtime_ns
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"Tokenizer {name!r} is not prepared locally. Explicit setup (may download): "
            f"dfctl metrics --prepare-tokenizer {name}"
        ) from exc
    return load_encoding(name, path, modified)
