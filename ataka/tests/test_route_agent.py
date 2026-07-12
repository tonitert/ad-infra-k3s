import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path


kubernetes = types.ModuleType("kubernetes")
kubernetes.client = types.SimpleNamespace()
kubernetes.config = types.SimpleNamespace()
sys.modules.setdefault("kubernetes", kubernetes)
os.environ.setdefault("NODE_NAME", "test-node")

spec = importlib.util.spec_from_file_location(
    "ataka_route_agent",
    Path("/workspace/ataka/route-agent/route_agent.py"),
)
route_agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route_agent)


class FakeRunResult:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


class FakeNode:
    def __init__(self, pod_cidrs=None):
        self.spec = types.SimpleNamespace(pod_cidrs=pod_cidrs or [], pod_cidr=None)


class FakeCoreV1:
    def read_node(self, node_name):
        self.node_name = node_name
        return FakeNode(["10.42.0.0/24"])


class RouteAgentTests(unittest.TestCase):
    def setUp(self):
        self.original_route_cidrs = route_agent.ROUTE_CIDRS
        self.original_vpn_interface = route_agent.VPN_INTERFACE
        self.original_run = route_agent.run
        self.commands = []
        route_agent.ROUTE_CIDRS = ["10.99.0.2/32"]

    def tearDown(self):
        route_agent.ROUTE_CIDRS = self.original_route_cidrs
        route_agent.VPN_INTERFACE = self.original_vpn_interface
        route_agent.run = self.original_run

    def fake_run(self, *args, check=False):
        self.commands.append(args)
        if args[:4] == ("ip", "-4", "route", "get"):
            return FakeRunResult(stdout="10.42.0.0 dev flannel.1 src 10.42.1.0\n")
        if args[:3] == ("ip", "-4", "rule"):
            return FakeRunResult(stdout="")
        return FakeRunResult()

    def test_remote_gateway_uses_gateway_node_pod_cidr_via_flannel(self):
        route_agent.run = self.fake_run

        route_agent.install_routes(
            FakeCoreV1(),
            all_node_ips=["10.255.0.1"],
            all_gateway_ips=["10.255.0.101"],
            all_gateway_nodes=["k3s-control-plane-hel1-bcf"],
        )

        self.assertIn(
            (
                "ip",
                "-4",
                "route",
                "replace",
                "10.99.0.2/32",
                "via",
                "10.42.0.0",
                "dev",
                "flannel.1",
                "onlink",
                "table",
                "200",
            ),
            self.commands,
        )
        self.assertIn(("ip", "-4", "rule", "add", "to", "10.99.0.2/32", "table", "200"), self.commands)

    def test_gateway_node_routes_vpn_cidr_directly_to_wg0(self):
        def fake_run(*args, check=False):
            self.commands.append(args)
            if args[:4] == ("ip", "link", "show", "wg0"):
                return FakeRunResult(returncode=0)
            if args[:3] == ("ip", "-4", "rule"):
                return FakeRunResult(stdout="")
            return FakeRunResult()

        route_agent.run = fake_run

        route_agent.install_routes(
            FakeCoreV1(),
            all_node_ips=["10.255.0.101"],
            all_gateway_ips=["10.255.0.101"],
            all_gateway_nodes=["k3s-control-plane-hel1-bcf"],
        )

        self.assertIn(
            ("ip", "-4", "route", "replace", "10.99.0.2/32", "dev", "wg0", "table", "200"),
            self.commands,
        )

    def test_gateway_node_routes_vpn_cidr_to_configured_interface(self):
        route_agent.VPN_INTERFACE = "tun0"

        def fake_run(*args, check=False):
            self.commands.append(args)
            if args[:4] == ("ip", "link", "show", "tun0"):
                return FakeRunResult(returncode=0)
            if args[:3] == ("ip", "-4", "rule"):
                return FakeRunResult(stdout="")
            return FakeRunResult()

        route_agent.run = fake_run

        route_agent.install_routes(
            FakeCoreV1(),
            all_node_ips=["10.255.0.101"],
            all_gateway_ips=["10.255.0.101"],
            all_gateway_nodes=["k3s-control-plane-hel1-bcf"],
        )

        self.assertIn(
            ("ip", "-4", "route", "replace", "10.99.0.2/32", "dev", "tun0", "table", "200"),
            self.commands,
        )


if __name__ == "__main__":
    unittest.main()
