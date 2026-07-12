import shutil
import subprocess
import unittest
from pathlib import Path


def helm_template(*args):
    if shutil.which("helm") is None:
        raise unittest.SkipTest("helm is not installed")

    return subprocess.check_output(
        ["helm", "template", "ataka", "argo/ataka", "--namespace", "ataka", *args],
        cwd="/workspace",
        text=True,
    )


class AtakaHelmTemplateTests(unittest.TestCase):
    def test_kubernetes_backend_is_default(self):
        rendered = helm_template()

        self.assertIn("name: EXECUTOR_BACKEND", rendered)
        self.assertIn('value: "kubernetes"', rendered)
        self.assertIn("name: ataka-registry", rendered)
        self.assertIn("nodePort: 30500", rendered)
        self.assertIn("storageClassName: longhorn", rendered)
        self.assertIn("ataka-registry.local", rendered)
        self.assertIn("name: BUILDKIT_BUILDER_NAME", rendered)
        self.assertIn("moby/buildkit:buildx-stable-1", rendered)
        self.assertNotIn("kaniko", rendered.lower())
        self.assertNotIn("ataka-builder", rendered)

    def test_executor_pod_mutation_is_admission_restricted(self):
        rendered = helm_template()

        self.assertIn("kind: ValidatingAdmissionPolicy", rendered)
        self.assertIn("system:serviceaccount:ataka:ataka-executor", rendered)
        self.assertIn('operations: ["CREATE", "UPDATE", "DELETE"]', rendered)
        self.assertIn('exploit-execution"', rendered)

    def test_executor_pod_admission_policy_can_be_disabled(self):
        rendered = helm_template("--set", "executor.podAdmissionPolicy.enabled=false")

        self.assertNotIn("kind: ValidatingAdmissionPolicy", rendered)
        self.assertNotIn("kind: ValidatingAdmissionPolicyBinding", rendered)

    def test_dind_backend_keeps_docker_daemon_without_executor_wireguard_sidecar(self):
        rendered = helm_template("--set", "executor.backend=dind")

        self.assertIn("name: dind", rendered)
        self.assertIn("value: tcp://localhost:2375", rendered)
        self.assertNotIn("name: ataka-wireguard\n", rendered)

    def test_wireguard_disabled_removes_gateway_and_route_agent(self):
        rendered = helm_template("--set", "wireguard.enabled=false")

        self.assertNotIn("ataka-wireguard-gateway", rendered)
        self.assertNotIn("ataka-route-agent", rendered)

    def test_wireguard_route_cidr_defaults_to_validation_target(self):
        rendered = helm_template()

        self.assertIn("name: WIREGUARD_ROUTE_CIDRS", rendered)
        self.assertIn('value: "10.99.0.2/32"', rendered)
        self.assertIn("name: ROUTE_CIDRS", rendered)

    def test_wireguard_route_cidrs_support_ipv6_rendering(self):
        rendered = helm_template(
            "--set",
            "wireguard.routeCidrs[0]=10.99.0.2/32",
            "--set",
            "wireguard.routeCidrs[1]=fd00::2/128",
        )

        self.assertIn('value: "10.99.0.2/32 fd00::2/128"', rendered)

    def test_openvpn_gateway_reuses_route_agent_without_ctfcode_sidecar(self):
        rendered = helm_template(
            "--set",
            "wireguard.enabled=false",
            "--set",
            "openvpn.enabled=true",
            "--set",
            "openvpn.gateway.enabled=true",
            "--set",
            "openvpn.routeCidrs[0]=10.8.0.0/24",
        )

        self.assertIn("ataka-openvpn-gateway", rendered)
        self.assertIn('value: "10.8.0.0/24"', rendered)
        self.assertIn('value: "app.kubernetes.io/name=ataka-openvpn-gateway"', rendered)
        self.assertIn('value: "tun0"', rendered)
        self.assertIn('value: "201"', rendered)
        self.assertNotIn("name: openvpn-client", rendered)
        self.assertNotIn("ataka-wireguard-gateway", rendered)

    def test_enabling_both_vpn_gateways_fails(self):
        if shutil.which("helm") is None:
            raise unittest.SkipTest("helm is not installed")

        result = subprocess.run(
            [
                "helm",
                "template",
                "ataka",
                "argo/ataka",
                "--namespace",
                "ataka",
                "--set",
                "openvpn.enabled=true",
                "--set",
                "openvpn.gateway.enabled=true",
                "--set",
                "openvpn.routeCidrs[0]=10.8.0.0/24",
            ],
            cwd="/workspace",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("Only one Ataka VPN gateway can be enabled at a time", result.stdout)

    def test_route_agent_does_not_flush_routes_or_mangle_chain(self):
        script = Path("/workspace/ataka/route-agent/route-agent.sh").read_text()

        self.assertNotIn("route flush table", script)
        self.assertNotIn(" -F ", script)
        self.assertIn("ip6tables", script)
