import json
import unittest
from unittest.mock import patch

from dfharness.capabilities import GROUPS, capability_report
from dfharness.client import Client
from dfharness.mcp import Server
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

    def test_capabilities_is_read_only_in_python_and_normal_mcp(self):
        client = Client(port=1, execution={"mode": "complete", "acknowledge": True})
        with patch.object(client, "request", return_value={"features": {}}) as request:
            expected = client.capabilities()
            request.assert_called_once_with({"op": "capabilities"})
            request.reset_mock()
            server = Server(client)
            server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
            r = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "df_capabilities", "arguments": {}},
                }
            )
            self.assertFalse(r["result"]["isError"])
            self.assertEqual(json.loads(r["result"]["content"][0]["text"]), expected)
            request.assert_called_once_with({"op": "capabilities"})
