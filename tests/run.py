"""Run offline tests without reading live controller policy or writing play metrics."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def main():
    with (
        tempfile.TemporaryDirectory(prefix="df-llm-tests-") as directory,
        patch.dict(
            os.environ,
            {
                "DFLLM_SETTINGS": str(Path(directory) / "controller.json"),
                "DFLLM_METRICS": "off",
                "DFLLM_METRICS_RUN": "offline-tests",
                "DFLLM_EPISODE": "",
            },
        ),
    ):
        unittest.main(module=None, argv=[sys.argv[0], *(sys.argv[1:] or ["discover", "-v"])])


if __name__ == "__main__":
    main()
