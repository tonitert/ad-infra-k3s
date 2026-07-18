import importlib.util
import sys
import types
import unittest
from pathlib import Path


class FakeResponse:
    def __init__(self, payload=None, text=""):
        self.payload = payload
        self.text = text

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def load_config():
    pwn = types.ModuleType("pwn")
    pwn.remote = lambda *args, **kwargs: None
    requests = types.ModuleType("requests")
    requests.get = lambda *args, **kwargs: None
    requests.exceptions = types.SimpleNamespace(RequestException=RuntimeError)
    previous = sys.modules.get("pwn")
    previous_requests = sys.modules.get("requests")
    sys.modules["pwn"] = pwn
    sys.modules["requests"] = requests
    try:
        spec = importlib.util.spec_from_file_location(
            "enowars10_test", Path("ataka/ctfconfig/enowars10.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            sys.modules.pop("pwn", None)
        else:
            sys.modules["pwn"] = previous
        if previous_requests is None:
            sys.modules.pop("requests", None)
        else:
            sys.modules["requests"] = previous_requests


class Enowars10ConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def test_team_and_event_constants(self):
        self.assertEqual(self.config.TEAM_ID, 15)
        self.assertEqual(self.config.OWN_HOST, "10.1.15.1")
        self.assertEqual(self.config.START_TIME, 1784376000)
        self.assertEqual(self.config.ROUND_TIME, 60)
        self.assertEqual(self.config.ATTACK_INFO_URL, "https://10.enowars.com/scoreboard/attack.json")
        self.assertFalse(self.config.LIVE_SELF_TEST)
        self.assertEqual(self.config.ADDITIONAL_SERVICES, {"test"})

    def test_attack_info_services_and_extra_are_preserved(self):
        self.config.ADDITIONAL_SERVICES = set()
        payload = {
            "availableTeams": ["10.1.52.1"],
            "services": {
                "service_1": {
                    "10.1.52.1": {"7": [["user73"], ["user5"]]},
                    "10.1.15.1": {"7": [["own-user"]]},
                }
            },
        }
        self.config.requests.get = lambda url, timeout: FakeResponse(payload)

        targets = self.config.get_targets()

        self.assertEqual(list(targets), ["service_1"])
        self.assertEqual(
            targets["service_1"],
            [
                {"ip": "10.1.52.1", "extra": '{"7":[["user73"],["user5"]]}'},
                {"ip": "10.1.15.1", "extra": '{"7":[["own-user"]]}'},
            ],
        )

    def test_additional_test_service_uses_team_ips(self):
        def get(url, timeout):
            if url == self.config.ATTACK_INFO_URL:
                return FakeResponse({"services": {}})
            self.assertEqual(url, self.config.OPPONENT_IPS_URL)
            return FakeResponse(text="10.1.52.1\n10.1.15.1\n10.1.42.1\n")

        self.config.requests.get = get

        targets = self.config.get_targets()

        self.assertEqual(
            targets,
            {
                "test": [
                    {"ip": "10.1.15.1", "extra": "[]"},
                    {"ip": "10.1.42.1", "extra": "[]"},
                    {"ip": "10.1.52.1", "extra": "[]"},
                ]
            },
        )

    def test_additional_test_service_survives_attack_info_failure(self):
        class FailingResponse(FakeResponse):
            def raise_for_status(self):
                raise RuntimeError("not found")

        def get(url, timeout):
            if url == self.config.ATTACK_INFO_URL:
                return FailingResponse()
            return FakeResponse(text="10.1.52.1\n10.1.15.1\n")

        self.config.requests.get = get

        self.assertEqual(
            self.config.get_targets(),
            {
                "test": [
                    {"ip": "10.1.15.1", "extra": "[]"},
                    {"ip": "10.1.52.1", "extra": "[]"},
                ]
            },
        )

    def test_fallback_targets_use_documented_opponent_ip_endpoint(self):
        def get(url, timeout):
            self.assertEqual(url, self.config.OPPONENT_IPS_URL)
            return FakeResponse(text="10.1.52.1\n10.1.15.1\n10.1.42.1\n")

        self.config.requests.get = get

        targets = self.config.get_fallback_targets({"without-attack-info"})

        self.assertEqual(
            targets,
            {
                "without-attack-info": [
                    {"ip": "10.1.15.1", "extra": "[]"},
                    {"ip": "10.1.42.1", "extra": "[]"},
                    {"ip": "10.1.52.1", "extra": "[]"},
                ]
            },
        )

    def test_submission_failure_returns_one_status_per_flag(self):
        class FailingRemote:
            def recvuntil(self, *args, **kwargs):
                return b""

            def sendline(self, *args, **kwargs):
                pass

            def recvline(self, *args, **kwargs):
                raise TimeoutError("test timeout")

            def close(self):
                pass

        self.config.remote = lambda *args, **kwargs: FailingRemote()

        statuses = self.config.submit_flags(["ENO" + "A" * 48, "ENO" + "B" * 48])

        self.assertEqual(statuses, [self.config.FlagStatus.ERROR, self.config.FlagStatus.ERROR])
