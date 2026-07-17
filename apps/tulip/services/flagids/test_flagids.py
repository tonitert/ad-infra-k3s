import importlib.util
import sys
import types
import unittest
from pathlib import Path


def load_flagids_module():
    psycopg_pool = types.ModuleType("psycopg_pool")
    psycopg_pool.ConnectionPool = object
    requests = types.ModuleType("requests")
    previous_psycopg = sys.modules.get("psycopg_pool")
    previous_requests = sys.modules.get("requests")
    sys.modules["psycopg_pool"] = psycopg_pool
    sys.modules["requests"] = requests
    try:
        spec = importlib.util.spec_from_file_location(
            "tulip_flagids_test", Path("apps/tulip/services/flagids/flagids.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if previous_psycopg is None:
            sys.modules.pop("psycopg_pool", None)
        else:
            sys.modules["psycopg_pool"] = previous_psycopg
        if previous_requests is None:
            sys.modules.pop("requests", None)
        else:
            sys.modules["requests"] = previous_requests


class FlagIdScraperTests(unittest.TestCase):
    def setUp(self):
        self.module = load_flagids_module()

    def test_team_key_parser_uses_the_configured_team_id(self):
        parser = self.module.load_parser("team_key")
        self.assertEqual(
            parser({"teams": {"42": [["flag-id"]], "43": [["other-id"]]}}, {"TEAM_ID": "42"}),
            ["flag-id"],
        )

    def test_scrape_schedule_stays_aligned_to_rounds(self):
        self.assertEqual(self.module.seconds_until_next_scrape(0, 0, 60), 5)
        self.assertEqual(self.module.seconds_until_next_scrape(5, 0, 60), 60)
        self.assertEqual(self.module.seconds_until_next_scrape(65, 0, 60), 60)
        self.assertEqual(self.module.seconds_until_next_scrape(3600, 0, 60), 5)
