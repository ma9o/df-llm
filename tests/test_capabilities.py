import io
import json
import unittest
from unittest.mock import patch

from dfharness.capabilities import GROUPS, capability_report
from dfharness.cli import main
from dfharness.client import Client
from dfharness.workflows import SEMANTIC


class CapabilityTests(unittest.TestCase):
    def test_all_semantic_recipes_have_an_explicit_completion_contract(self):
        self.assertEqual({name for names, _, _ in GROUPS for name in names}, SEMANTIC)

    def test_missing_runtime_dependencies_never_claim_available(self):
        r = capability_report({"features": {"core": {"dependencies_present": True}}})
        sequence = next(g for g in r["actions"] if "sequence" in g["names"])
        self.assertTrue(sequence["dependencies_present"])
        inventory = next(g for g in r["actions"] if "pickup" in g["names"])
        self.assertFalse(inventory["dependencies_present"])
        self.assertIn("inventory", inventory["missing_features"])
        combat = next(g for g in r["actions"] if "combat" in g["names"])
        self.assertTrue(combat["partial"])

    def test_capabilities_is_read_only_in_cli_and_python(self):
        client = Client(port=1, execution={"mode": "complete", "acknowledge": True})
        with patch.object(Client, "request", return_value={"features": {}}) as request:
            expected = client.capabilities()
            request.assert_called_once_with({"op": "capabilities"})
            request.reset_mock()
            with patch("sys.stdout", new_callable=io.StringIO) as output:
                self.assertEqual(main(["--port", "1", "capabilities"]), 0)
            self.assertEqual(json.loads(output.getvalue()), expected)
            request.assert_called_once_with({"op": "capabilities"})
