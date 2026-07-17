import importlib.util
import unittest
from pathlib import Path


def load_parser():
    spec = importlib.util.spec_from_file_location(
        "enowars_parser_test", Path("apps/tulip/services/flagids/parsers/enowars.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EnowarsParserTests(unittest.TestCase):
    def test_extracts_only_our_address_key(self):
        payload = {
            "availableTeams": ["10.1.15.1", "10.1.52.1"],
            "services": {
                "service_1": {
                    "10.1.15.1": {"7": [["own-flag-id"], ["own-flag-id-2"]]},
                    "10.1.52.1": {"7": [["other-team-id"]]},
                }
            },
        }

        self.assertEqual(
            load_parser().extract_flagids(payload, {"TEAM_ADDRESS": "10.1.15.1"}),
            ["own-flag-id", "own-flag-id-2"],
        )
