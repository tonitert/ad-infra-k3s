#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from pcap_generator import generate_pcaps, parse_ports


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
PATCH_TEMPLATE = SCRIPT_DIR / "tulip-rsync-source-patch.yaml"
START_IN_POD_SSHD = SCRIPT_DIR / "start-in-pod-sshd.sh"


def log(message: str) -> None:
    print(f"{datetime.now().astimezone().strftime('%Y-%m-%dT%H:%M:%S%z')} {message}", flush=True)


def require_command(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"missing required command: {name}")


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, text=True, **kwargs)


def capture(cmd: list[str]) -> str:
    return run(cmd, stdout=subprocess.PIPE).stdout


def terminate_process(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


class TulipStress:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.output_dir = args.output_dir.resolve()
        self.created_output = not self.output_dir.exists()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir = self.output_dir / ".stress-state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.port_forward_log = self.state_dir / "port-forward.log"
        self.rsync_config = self.state_dir / "rsyncd.conf"
        self.rsync_pid_file = self.state_dir / "rsyncd.pid"
        self.known_hosts = self.state_dir / "known_hosts"
        self.key_path = self.state_dir / "id_ed25519"

        self.kubectl = ["kubectl"]
        if args.kubeconfig:
            self.kubectl += ["--kubeconfig", str(args.kubeconfig)]

        self.rsync_proc: subprocess.Popen | None = None
        self.port_forward_proc: subprocess.Popen | None = None
        self.ssh_proc: subprocess.Popen | None = None
        self.generator_proc: subprocess.Popen | None = None

        self.restore_source = False
        self.old_rsync_source = ""
        self.pod_selector = ""
        self.rsync_pod = ""

    def kubectl_cmd(self, *parts: str) -> list[str]:
        return [*self.kubectl, "-n", self.args.namespace, *parts]

    def cleanup(self) -> None:
        for proc in (self.generator_proc, self.ssh_proc, self.port_forward_proc, self.rsync_proc):
            terminate_process(proc)

        if self.rsync_pod:
            log("stopping temporary in-pod sshd")
            subprocess.run(
                self.kubectl_cmd(
                    "exec",
                    f"pod/{self.rsync_pod}",
                    "-c",
                    "rsync",
                    "--",
                    "sh",
                    "-c",
                    """
if [ -f /tmp/tulip-pcap-stress-sshd.pid ]; then
  kill "$(cat /tmp/tulip-pcap-stress-sshd.pid)" >/dev/null 2>&1 || true
  rm -f /tmp/tulip-pcap-stress-sshd.pid
fi
""",
                ),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
            )

        if self.restore_source and not self.args.no_restore:
            log(f"restoring RSYNC_SOURCE to {self.old_rsync_source}")
            try:
                self.patch_rsync_source(self.old_rsync_source)
                run(self.kubectl_cmd("rollout", "status", f"deployment/{self.args.deployment}", "--timeout=120s"), stdout=subprocess.DEVNULL)
            except subprocess.CalledProcessError:
                pass

        for path in (self.rsync_config, self.rsync_pid_file, self.known_hosts, self.port_forward_log):
            path.unlink(missing_ok=True)

        if self.created_output and not self.args.keep_output:
            try:
                self.state_dir.rmdir()
                self.output_dir.rmdir()
            except OSError:
                pass

    def patch_rsync_source(self, source: str) -> None:
        patch = PATCH_TEMPLATE.read_text().replace("__RSYNC_SOURCE_JSON__", json.dumps(source))
        patch_path = self.state_dir / "rsync-source-patch.yaml"
        patch_path.write_text(patch)
        run(
            self.kubectl_cmd(
                "patch",
                f"deployment/{self.args.deployment}",
                "--type",
                "strategic",
                "--patch-file",
                str(patch_path),
            ),
            stdout=subprocess.DEVNULL,
        )
        patch_path.unlink(missing_ok=True)

    def deployment_selector(self) -> str:
        raw = capture(self.kubectl_cmd("get", f"deployment/{self.args.deployment}", "-o", "json"))
        deployment = json.loads(raw)
        labels = deployment["spec"]["selector"]["matchLabels"]
        return ",".join(f"{key}={value}" for key, value in sorted(labels.items()))

    def wait_for_rsync_pod(self) -> str:
        for _ in range(120):
            raw = capture(self.kubectl_cmd("get", "pods", "-l", self.pod_selector, "-o", "json"))
            pods = json.loads(raw).get("items", [])
            for pod in pods:
                if pod.get("metadata", {}).get("deletionTimestamp"):
                    continue
                container_names = {container.get("name") for container in pod.get("spec", {}).get("containers", [])}
                if "rsync" not in container_names:
                    continue
                statuses = {container.get("name"): container for container in pod.get("status", {}).get("containerStatuses", [])}
                if statuses.get("rsync", {}).get("ready"):
                    return pod["metadata"]["name"]
            time.sleep(1)
        raise TimeoutError("timed out waiting for a ready rsync pod")

    def wait_for_tcp(self, port: int, name: str) -> None:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    return
            except OSError:
                time.sleep(0.2)
        raise TimeoutError(f"timed out waiting for {name} on 127.0.0.1:{port}")

    def wait_for_port_forward(self) -> None:
        expected = f"Forwarding from 127.0.0.1:{self.args.ssh_local_port} -> 2222"
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.port_forward_log.exists() and expected in self.port_forward_log.read_text(errors="replace"):
                return
            if self.port_forward_proc and self.port_forward_proc.poll() is not None:
                if self.port_forward_log.exists():
                    sys.stderr.write(self.port_forward_log.read_text(errors="replace"))
                raise RuntimeError("kubectl port-forward exited early")
            time.sleep(0.2)
        if self.port_forward_log.exists():
            sys.stderr.write(self.port_forward_log.read_text(errors="replace"))
        raise TimeoutError("timed out waiting for kubectl port-forward to start")

    def ensure_key(self) -> None:
        if self.key_path.exists():
            return
        run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(self.key_path)])

    def start_in_pod_sshd(self) -> None:
        public_key = self.key_path.with_suffix(".pub").read_text().strip()
        script = START_IN_POD_SSHD.read_text()
        run(
            self.kubectl_cmd("exec", f"pod/{self.rsync_pod}", "-c", "rsync", "-i", "--", "sh", "-s", "--", public_key),
            input=script,
            stdout=subprocess.DEVNULL,
        )

    def write_rsync_config(self) -> None:
        self.rsync_config.write_text(
            "\n".join(
                [
                    f"pid file = {self.rsync_pid_file}",
                    "use chroot = no",
                    "read only = yes",
                    "list = no",
                    "hosts allow = 127.0.0.1",
                    "hosts deny = *",
                    f"[{self.args.module}]",
                    f"path = {self.output_dir}",
                    "comment = Tulip stress PCAPs",
                    "",
                ]
            )
        )

    def start_local_rsync(self) -> None:
        self.write_rsync_config()
        log(f"starting local rsync daemon on 127.0.0.1:{self.args.local_rsync_port}")
        self.rsync_proc = subprocess.Popen(
            [
                "rsync",
                "--daemon",
                "--no-detach",
                "--port",
                str(self.args.local_rsync_port),
                "--config",
                str(self.rsync_config),
            ]
        )
        self.wait_for_tcp(self.args.local_rsync_port, "local rsync")

    def start_port_forward(self) -> None:
        log(f"starting kubectl port-forward to pod/{self.rsync_pod} port 2222")
        self.port_forward_log.unlink(missing_ok=True)
        log_file = self.port_forward_log.open("w")
        self.port_forward_proc = subprocess.Popen(
            self.kubectl_cmd(
                "port-forward",
                "--address",
                "127.0.0.1",
                f"pod/{self.rsync_pod}",
                f"{self.args.ssh_local_port}:2222",
            ),
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        self.wait_for_port_forward()

    def start_reverse_tunnel(self) -> None:
        log(
            "starting SSH reverse tunnel: "
            f"cluster 127.0.0.1:{self.args.remote_rsync_port} -> local 127.0.0.1:{self.args.local_rsync_port}"
        )
        self.ssh_proc = subprocess.Popen(
            [
                "ssh",
                "-N",
                "-i",
                str(self.key_path),
                "-p",
                str(self.args.ssh_local_port),
                "-o",
                "ExitOnForwardFailure=yes",
                "-o",
                "ServerAliveInterval=15",
                "-o",
                "ServerAliveCountMax=3",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                f"UserKnownHostsFile={self.known_hosts}",
                "-R",
                f"127.0.0.1:{self.args.remote_rsync_port}:127.0.0.1:{self.args.local_rsync_port}",
                "root@127.0.0.1",
            ]
        )
        time.sleep(1)
        if self.ssh_proc.poll() is not None:
            raise RuntimeError("ssh reverse tunnel exited early")

    def start_generator(self) -> None:
        log(f"starting PCAP generator in {self.output_dir}")
        self.generator_proc = subprocess.Popen(
            [
                sys.executable,
                str(SCRIPT_DIR / "pcap_generator.py"),
                "--rps",
                str(self.args.rps),
                "--ports",
                self.args.ports,
                "--duration",
                str(self.args.duration),
                "--rotate-seconds",
                str(self.args.rotate_seconds),
                "--dst-ip",
                self.args.dst_ip,
                "--src-cidr",
                self.args.src_cidr,
                "--output-dir",
                str(self.output_dir),
            ]
        )
        self.generator_proc.wait()
        if self.generator_proc.returncode != 0:
            raise subprocess.CalledProcessError(self.generator_proc.returncode, "pcap_generator.py")

    def run(self) -> None:
        for command in ("kubectl", "rsync", "ssh", "ssh-keygen"):
            require_command(command)

        log("checking rsync deployment")
        run(self.kubectl_cmd("get", f"deployment/{self.args.deployment}"), stdout=subprocess.DEVNULL)
        self.pod_selector = self.deployment_selector()
        self.ensure_key()

        self.old_rsync_source = capture(
            self.kubectl_cmd(
                "get",
                f"deployment/{self.args.deployment}",
                "-o",
                "jsonpath={range .spec.template.spec.containers[?(@.name==\"rsync\")].env[?(@.name==\"RSYNC_SOURCE\")]}{.value}{end}",
            )
        )
        if not self.old_rsync_source:
            self.old_rsync_source = "root@168.119.122.165:/pcaps/"

        new_source = f"rsync://127.0.0.1:{self.args.remote_rsync_port}/{self.args.module}/"
        log(f"temporarily setting RSYNC_SOURCE to {new_source}")
        self.patch_rsync_source(new_source)
        self.restore_source = True
        run(self.kubectl_cmd("rollout", "status", f"deployment/{self.args.deployment}", "--timeout=180s"), stdout=subprocess.DEVNULL)

        self.rsync_pod = self.wait_for_rsync_pod()
        log(f"installing temporary tunnel public key and starting sshd in pod/{self.rsync_pod}")
        self.start_in_pod_sshd()

        self.start_local_rsync()
        self.start_port_forward()
        self.start_reverse_tunnel()
        self.start_generator()


def parse_args() -> argparse.Namespace:
    kubeconfig = os.environ.get("KUBECONFIG")
    if not kubeconfig and (REPO_ROOT / "k3s_kubeconfig.yaml").exists():
        kubeconfig = str(REPO_ROOT / "k3s_kubeconfig.yaml")

    parser = argparse.ArgumentParser(
        description="Generate synthetic HTTP PCAPs and expose them to Tulip through a temporary kubectl SSH reverse tunnel."
    )
    parser.add_argument("--rps", type=int, default=150)
    parser.add_argument("--ports", default="80,8080")
    parser.add_argument("--duration", type=int, default=0)
    parser.add_argument("--rotate-seconds", type=int, default=60)
    parser.add_argument("--dst-ip", default="10.10.3.1")
    parser.add_argument("--src-cidr", default="10.66.0.0/16")
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "pcap-stress-out")
    parser.add_argument("--namespace", default="tulip")
    parser.add_argument("--deployment", default="rsync")
    parser.add_argument("--module", default="pcaps")
    parser.add_argument("--local-rsync-port", type=int, default=18729)
    parser.add_argument("--remote-rsync-port", type=int, default=18730)
    parser.add_argument("--ssh-local-port", type=int, default=2222)
    parser.add_argument("--kubeconfig", type=Path, default=Path(kubeconfig) if kubeconfig else None)
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument("--no-restore", action="store_true")
    parser.add_argument("--keep-output", action="store_true")
    args = parser.parse_args()

    if args.rps < 1:
        parser.error("--rps must be at least 1")
    if args.duration < 0:
        parser.error("--duration must be greater than or equal to 0")
    if args.rotate_seconds < 1:
        parser.error("--rotate-seconds must be at least 1")
    for name in ("local_rsync_port", "remote_rsync_port", "ssh_local_port"):
        value = getattr(args, name)
        if value < 1 or value > 65535:
            parser.error(f"--{name.replace('_', '-')} must be in 1..65535")
    parse_ports(args.ports)
    return args


def main() -> None:
    signal.signal(signal.SIGTERM, lambda _signum, _frame: (_ for _ in ()).throw(KeyboardInterrupt()))
    args = parse_args()

    if args.generate_only:
        log(f"generating PCAPs in {args.output_dir.resolve()}")
        generate_pcaps(
            rps=args.rps,
            ports=parse_ports(args.ports),
            duration=args.duration,
            rotate_seconds=args.rotate_seconds,
            dst_ip=args.dst_ip,
            src_cidr=args.src_cidr,
            output_dir=args.output_dir.resolve(),
        )
        return

    stress = TulipStress(args)
    try:
        stress.run()
    finally:
        stress.cleanup()


if __name__ == "__main__":
    main()
