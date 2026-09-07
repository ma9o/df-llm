import io
import json
import unittest
from unittest.mock import patch

from dfharness.actions import ACTIONS, action_reference
from dfharness.cli import main
from dfharness.client import Client
from dfharness.workflows import validate_action


class ActionReferenceTests(unittest.TestCase):
    def test_cli_and_python_share_exact_schemas_without_game_reads(self):
        client = Client(port=1)
        with patch.object(client, "request", side_effect=AssertionError("Reference must be local")):
            expected = client.actions("strike")
        output = io.StringIO()
        with (
            patch("sys.stdout", output),
            patch(
                "dfharness.client.run_command",
                side_effect=AssertionError("Reference must be local"),
            ),
        ):
            self.assertEqual(main(["--port", "1", "actions", "strike"]), 0)
        self.assertEqual(json.loads(output.getvalue()), expected)
        validate_action(
            {
                "type": "strike",
                "unit_id": 1,
                "body_part_id": 0,
                "item_id": -1,
                "attack_index": 0,
                "style": "normal",
            },
        )

    def test_reference_is_bounded_and_preserves_schema_ownership(self):
        reference = action_reference()
        names = {r["action"] for r in reference["actions"]}
        self.assertTrue({"drop", "stow", "strike", "sequence", "converse"} <= names)
        self.assertFalse({"key", "click", "text"} & names)
        self.assertLess(len(json.dumps(reference)), 6500)
        result = action_reference("drop")
        self.assertIn("removing it first", result["description"])
        result["schema"]["oneOf"][0]["required"].clear()
        actual = next(a for a in ACTIONS if a["properties"]["type"]["const"] == "drop")
        self.assertEqual(actual["required"], ["type", "item_id"])
        with self.assertRaises(ValueError):
            action_reference("not_an_action")
