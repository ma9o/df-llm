"""Every command documents itself: contracts and argument help come from one table."""

import argparse
import unittest

from dfharness import reference
from dfharness.actions import ACTIONS, action_reference
from dfharness.cli import parser

ALIASES = {"look", "quickload", "quicksave"}


def subcommands():
    top = parser()
    subs = next(a for a in top._actions if isinstance(a, argparse._SubParsersAction))
    return subs.choices


class ReferenceTests(unittest.TestCase):
    def test_every_command_prints_a_contract(self):
        seen = set()
        for name, sub in subcommands().items():
            if id(sub) in seen:
                continue
            seen.add(id(sub))
            self.assertTrue(sub.description, name)
            self.assertTrue(sub.epilog, name)
            self.assertIs(sub.formatter_class, argparse.RawDescriptionHelpFormatter, name)
            self.assertIn(sub.epilog.splitlines()[0][:30], sub.format_help(), name)

    def test_every_argument_has_help(self):
        missing = []
        for name, sub in subcommands().items():
            for action in sub._actions:
                if action.dest == "help" or action.help == argparse.SUPPRESS:
                    continue
                if not action.help:
                    missing.append((name, action.dest))
        self.assertEqual(missing, [])

    def test_reference_names_match_the_cli(self):
        names = set(subcommands())
        self.assertEqual(set(reference.COMMANDS) - names, set())
        self.assertEqual(names - set(reference.COMMANDS) - ALIASES, set())
        for name, entry in reference.COMMANDS.items():
            self.assertTrue(entry["summary"].endswith("."), name)
            self.assertLessEqual(len(entry["summary"]), 100, name)
            for line in entry["details"].splitlines():
                self.assertLessEqual(len(line), 88, (name, line))

    def test_every_action_schema_shares_the_command_text(self):
        for definition in ACTIONS:
            name = definition["properties"]["type"]["const"]
            summary, details = reference.action_text(name)
            self.assertEqual(definition["description"], summary)
            self.assertTrue(details, name)
        strike = action_reference("strike")
        self.assertEqual(strike["description"], reference.COMMANDS["strike"]["summary"])
        self.assertIn("body_part_id from unit ID", strike["details"])

    def test_top_level_help_lists_policy_and_outcomes(self):
        text = parser().format_help()
        for needle in ("--mode step|complete", "needs_input", "rejected", "resume{dispatch_id}"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
