import asyncio
import hashlib
import io
import math
import os
import re
import shlex
import subprocess
import tarfile
import tempfile
import time
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from aiodocker import Docker, DockerError

from ataka.common.job_execution_status import JobExecutionStatus
from ataka.common.queue import OutputMessage, OutputQueue

from .exploits import Exploits
from .localdata import LocalExecution, LocalExploit, LocalExploitStatus, LocalJob


class BackendError(Exception):
    pass


def _k8s_name(value: str, max_length: int = 63) -> str:
    value = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    if not value:
        value = "exploit"
    return value[:max_length].strip("-")


def _seconds_until(timestamp: float) -> int:
    return max(1, math.floor(timestamp - time.time()))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ExecutorBackend(ABC):
    name: str

    @abstractmethod
    async def ensure_exploit(self, exploit) -> LocalExploit:
        pass

    @abstractmethod
    async def run_job(self, job_id: int, job: LocalJob, channel) -> list[LocalExecution]:
        pass

    @abstractmethod
    async def cancel_job(self, job_id: int):
        pass

    async def close(self):
        pass


class DockerExecutorBackend(ExecutorBackend):
    name = "dind"

    def __init__(self, docker: Docker):
        self._docker = docker
        self._exploits = Exploits(docker)
        self._data_store = os.environ["DATA_STORE"]
        self._containers = {}

    async def ensure_exploit(self, exploit) -> LocalExploit:
        return await self._exploits.ensure_exploit(exploit)

    async def run_job(self, job_id: int, job: LocalJob, channel) -> list[LocalExecution]:
        exploit = job.exploit
        persist_dir = f"/data/persist/{exploit.docker_name}"
        host_persist_dir = f"{self._data_store}/persist/{exploit.docker_name}"
        host_shared_dir = f"{self._data_store}/shared/exploits"

        try:
            os.makedirs(persist_dir, exist_ok=True)
            container_ref = await self._docker.containers.create_or_replace(
                name=f"ataka-exploit-{exploit.docker_name}",
                config={
                    "Image": exploit.docker_id,
                    "Cmd": ["sleep", str(_seconds_until(job.timeout))],
                    "AttachStdin": False,
                    "AttachStdout": False,
                    "AttachStderr": False,
                    "Tty": False,
                    "OpenStdin": False,
                    "StopSignal": "SIGKILL",
                    "HostConfig": {
                        "Mounts": [
                            {
                                "Type": "bind",
                                "Source": host_persist_dir,
                                "Target": "/persist",
                            },
                            {
                                "Type": "bind",
                                "Source": host_shared_dir,
                                "Target": "/shared",
                            },
                        ],
                        "CapAdd": ["NET_RAW"],
                        "CpusetCpus": os.environ.get("EXPLOIT_CPUSET", ""),
                    },
                },
            )
            self._containers[job_id] = container_ref
            await container_ref.start()
        except DockerError as exception:
            print(f"Got docker error for exploit {exploit.id} (service {exploit.service}) by {exploit.author}")
            print(traceback.format_exception(exception))
            for execution in job.executions:
                execution.status = JobExecutionStatus.FAILED
                execution.stderr = str(exception)
            raise

        try:
            execute_tasks = [self._docker_execute(container_ref, execution, channel) for execution in job.executions]
            print(f"Starting {len(execute_tasks)} tasks for exploit {exploit.id} (service {exploit.service}) by {exploit.author}")
            return await asyncio.gather(*execute_tasks)
        finally:
            await self.cancel_job(job_id)

    async def cancel_job(self, job_id: int):
        container_ref = self._containers.pop(job_id, None)
        if container_ref is None:
            return

        try:
            await container_ref.kill()
        except DockerError:
            pass

        try:
            await container_ref.delete(force=True)
        except DockerError:
            pass

    async def _docker_execute(self, container_ref, execution: LocalExecution, channel) -> LocalExecution:
        async def exec_in_container_and_poll_output():
            try:
                exec_ref = await container_ref.exec(
                    cmd=execution.exploit.docker_cmd,
                    workdir="/exploit",
                    tty=False,
                    environment={
                        "ATAKA_CENTRAL_EXECUTION": "TRUE",
                        "TARGET_IP": execution.target.ip,
                        "TARGET_EXTRA": execution.target.extra,
                        "ATAKA_EXPLOIT_ID": execution.exploit.id,
                    },
                )
                async with exec_ref.start(detach=False) as stream:
                    while True:
                        message = await stream.read_out()
                        if message is None:
                            break

                        yield message[0], message[1].decode()
            except DockerError as e:
                print(
                    f"DOCKER EXECUTION ERROR for {execution.exploit.id} (service {execution.exploit.service}) "
                    f"by {execution.exploit.author} against target {execution.target.ip}\n"
                    f"{e.message}"
                )
                msg = f"DOCKER EXECUTION ERROR: {e.message}"
                execution.status = JobExecutionStatus.FAILED
                execution.stderr += msg
                yield 2, msg

        output_queue = await OutputQueue.get(channel)

        async for (stream, output) in exec_in_container_and_poll_output():
            if stream == 1:
                execution.stdout += output
            elif stream == 2:
                execution.stderr += output

            await output_queue.send_message(OutputMessage(execution.database_id, stream == 1, output))

        if execution.status in [JobExecutionStatus.QUEUED, JobExecutionStatus.RUNNING]:
            execution.status = JobExecutionStatus.FINISHED
        return execution

    async def close(self):
        await self._docker.close()


@dataclass
class KubernetesSettings:
    namespace: str
    registry_pull: str
    registry_push: str
    buildkit_builder_name: str
    buildkit_image: str
    buildkit_replicas: str
    buildkit_storage: str
    buildkit_driver_options: str
    service_account: str
    persist_claim: str
    shared_claim: str
    exploits_claim: str
    image_pull_policy: str
    vpn_label_key: str
    vpn_label_value: str
    autoscaled_toleration_key: str
    autoscaled_toleration_value: str
    autoscaled_toleration_effect: str
    targets_per_pod: int = 30

    @classmethod
    def from_env(cls):
        namespace_path = Path("/var/run/secrets/kubernetes.io/serviceaccount/namespace")
        namespace = os.environ.get("POD_NAMESPACE")
        if not namespace and namespace_path.exists():
            namespace = namespace_path.read_text().strip()
        return cls(
            namespace=namespace or "ataka",
            registry_pull=os.environ.get("EXPLOIT_REGISTRY_PULL", "ataka-registry.local"),
            registry_push=os.environ.get("EXPLOIT_REGISTRY_PUSH", "ataka-registry:5000"),
            buildkit_builder_name=os.environ.get("BUILDKIT_BUILDER_NAME", "ataka-buildkit"),
            buildkit_image=os.environ.get("BUILDKIT_IMAGE", "moby/buildkit:buildx-stable-1"),
            buildkit_replicas=os.environ.get("BUILDKIT_REPLICAS", "1"),
            buildkit_storage=os.environ.get("BUILDKIT_STORAGE", ""),
            buildkit_driver_options=os.environ.get("BUILDKIT_DRIVER_OPTIONS", ""),
            service_account=os.environ.get("EXECUTOR_SERVICE_ACCOUNT", "ataka-executor"),
            persist_claim=os.environ.get("PERSIST_CLAIM", "persists"),
            shared_claim=os.environ.get("SHARED_CLAIM", "shared"),
            exploits_claim=os.environ.get("EXPLOITS_CLAIM", "exploits"),
            image_pull_policy=os.environ.get("EXPLOIT_IMAGE_PULL_POLICY", "IfNotPresent"),
            vpn_label_key=os.environ.get("VPN_ROUTE_LABEL_KEY", "ataka.ad.tertsonen.xyz/vpn-route"),
            vpn_label_value=os.environ.get("VPN_ROUTE_LABEL_VALUE", "true"),
            autoscaled_toleration_key=os.environ.get("AUTOSCALED_TOLERATION_KEY", ""),
            autoscaled_toleration_value=os.environ.get("AUTOSCALED_TOLERATION_VALUE", ""),
            autoscaled_toleration_effect=os.environ.get("AUTOSCALED_TOLERATION_EFFECT", "NoSchedule"),
            targets_per_pod=max(1, int(os.environ.get("EXECUTOR_TARGETS_PER_POD", "30"))),
        )


class KubernetesExecutorBackend(ExecutorBackend):
    name = "kubernetes"

    def __init__(self, settings: Optional[KubernetesSettings] = None, core_api=None, client_module=None):
        self.settings = settings or KubernetesSettings.from_env()
        self._exploits = {}
        self._pods_by_job = {}
        self._buildkit_lock = asyncio.Lock()

        if core_api is None:
            from kubernetes import client, config

            try:
                config.load_incluster_config()
            except config.ConfigException:
                config.load_kube_config()
            self._client = client
            self._core = client.CoreV1Api()
        elif client_module is not None:
            self._client = client_module
            self._core = core_api
        else:
            from kubernetes import client

            self._client = client
            self._core = core_api

    async def ensure_exploit(self, exploit) -> LocalExploit:
        if exploit.id not in self._exploits:
            local = LocalExploit(
                id=exploit.id,
                service=exploit.exploit_history.service,
                author=exploit.author,
                docker_name=exploit.docker_name,
                status=LocalExploitStatus.BUILDING,
            )
            self._exploits[exploit.id] = local
            await self._build_exploit(local)

        local = self._exploits[exploit.id]
        while local.status == LocalExploitStatus.BUILDING:
            await asyncio.sleep(1)
        return local

    async def run_job(self, job_id: int, job: LocalJob, channel) -> list[LocalExecution]:
        batches = [
            job.executions[index:index + self.settings.targets_per_pod]
            for index in range(0, len(job.executions), self.settings.targets_per_pod)
        ]
        print(
            f"Starting {len(batches)} Kubernetes exploit pods for {len(job.executions)} targets "
            f"of {job.exploit.id} (service {job.exploit.service})"
        )
        results = await asyncio.gather(
            *(self._run_batch(job_id, batch, job.timeout, channel) for batch in batches)
        )
        return [execution for batch in results for execution in batch]

    async def cancel_job(self, job_id: int):
        pod_names = list(self._pods_by_job.pop(job_id, set()))
        for name in pod_names:
            await asyncio.to_thread(self._delete_pod, name)

    async def _build_exploit(self, exploit: LocalExploit):
        context_path = Path("/data/exploits") / exploit.docker_name
        if not context_path.exists():
            exploit.status = LocalExploitStatus.ERROR
            exploit.build_output = f"FileNotFoundError: {context_path}"
            return

        digest = _sha256_file(context_path)[:24]
        repo = f"ataka-exploit/{_k8s_name(exploit.docker_name, 48)}"
        pull_ref = f"{self.settings.registry_pull}/{repo}:{digest}"
        push_ref = f"{self.settings.registry_push}/{repo}:{digest}"
        batch_pull_ref = f"{pull_ref}-batch"
        batch_push_ref = f"{push_ref}-batch"

        try:
            async with self._buildkit_lock:
                await asyncio.to_thread(self._ensure_buildx_builder)
            output = await asyncio.to_thread(self._build_with_buildx, context_path, push_ref)
            wrapper_context = self._create_batch_wrapper_context(push_ref)
            try:
                output += await asyncio.to_thread(self._build_with_buildx, wrapper_context, batch_push_ref)
            finally:
                wrapper_context.unlink(missing_ok=True)
            exploit.build_output = output
            exploit.docker_id = batch_pull_ref
            exploit.docker_cmd = None
            exploit.status = LocalExploitStatus.FINISHED
        except Exception as exc:
            exploit.status = LocalExploitStatus.ERROR
            exploit.build_output += f"\nKUBERNETES BUILD ERROR: {exc}"

    def _ensure_buildx_builder(self):
        kubeconfig = self._write_incluster_kubeconfig()
        buildkit_config = self._write_buildkit_config()
        env = self._buildx_env(kubeconfig)

        inspect = subprocess.run(
            ["docker", "buildx", "inspect", self.settings.buildkit_builder_name],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if inspect.returncode == 0:
            return

        driver_options = [
            f"namespace={self.settings.namespace}",
            f"image={self.settings.buildkit_image}",
            f"replicas={self.settings.buildkit_replicas}",
            f"serviceaccount={self.settings.service_account}",
            "loadbalance=random",
        ]
        if self.settings.buildkit_storage:
            driver_options.append(f"persistent-volume-claim.requests.storage={self.settings.buildkit_storage}")
        if self.settings.buildkit_driver_options:
            driver_options.extend(shlex.split(self.settings.buildkit_driver_options))

        command = [
            "docker",
            "buildx",
            "create",
            "--bootstrap",
            f"--name={self.settings.buildkit_builder_name}",
            "--driver=kubernetes",
            f"--driver-opt={','.join(driver_options)}",
            "--buildkitd-config",
            buildkit_config,
        ]
        created = subprocess.run(command, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if created.returncode != 0:
            raise BackendError(created.stdout)

    def _build_with_buildx(self, context_path: Path, image_ref: str) -> str:
        kubeconfig = self._write_incluster_kubeconfig()
        env = self._buildx_env(kubeconfig)
        command = [
            "docker",
            "buildx",
            "build",
            f"--builder={self.settings.buildkit_builder_name}",
            "--progress=plain",
            "-t",
            image_ref,
            "--output=type=image,push=true,registry.insecure=true",
            "-",
        ]
        with context_path.open("rb") as context:
            result = subprocess.run(
                command,
                env=env,
                stdin=context,
                text=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        output = result.stdout.decode(errors="replace")
        if result.returncode != 0:
            raise BackendError(output)
        return output

    def _create_batch_wrapper_context(self, base_image: str) -> Path:
        runner = Path(__file__).with_name("batch_runner.sh").read_bytes()
        dockerfile = (
            f"FROM {base_image}\n"
            "COPY --chmod=0755 batch-runner.sh /usr/local/bin/ataka-batch-runner\n"
            "ENTRYPOINT [\"/bin/sh\", \"/usr/local/bin/ataka-batch-runner\"]\n"
        ).encode()
        context = tempfile.NamedTemporaryFile(prefix="ataka-batch-", suffix=".tar", delete=False)
        try:
            with tarfile.open(fileobj=context, mode="w") as archive:
                for name, content in (("Dockerfile", dockerfile), ("batch-runner.sh", runner)):
                    info = tarfile.TarInfo(name)
                    info.size = len(content)
                    archive.addfile(info, io.BytesIO(content))
        finally:
            context.close()
        return Path(context.name)

    def _buildx_env(self, kubeconfig: str) -> dict[str, str]:
        env = os.environ.copy()
        env["KUBECONFIG"] = kubeconfig
        env.setdefault("DOCKER_CONFIG", "/tmp/.docker")
        return env

    def _write_incluster_kubeconfig(self) -> str:
        service_account_dir = Path("/var/run/secrets/kubernetes.io/serviceaccount")
        token_path = service_account_dir / "token"
        ca_path = service_account_dir / "ca.crt"
        if not token_path.exists() or not ca_path.exists():
            return os.environ.get("KUBECONFIG", "")

        kubeconfig = Path(tempfile.gettempdir()) / "ataka-buildx-kubeconfig"
        kubeconfig.write_text(
            "\n".join(
                [
                    "apiVersion: v1",
                    "kind: Config",
                    "clusters:",
                    "- name: incluster",
                    "  cluster:",
                    "    server: https://kubernetes.default.svc",
                    f"    certificate-authority: {ca_path}",
                    "users:",
                    "- name: ataka-executor",
                    "  user:",
                    f"    token: {token_path.read_text().strip()}",
                    "contexts:",
                    "- name: incluster",
                    "  context:",
                    "    cluster: incluster",
                    "    user: ataka-executor",
                    f"    namespace: {self.settings.namespace}",
                    "current-context: incluster",
                    "",
                ]
            )
        )
        return str(kubeconfig)

    def _write_buildkit_config(self) -> str:
        config_path = Path(tempfile.gettempdir()) / "ataka-buildkitd.toml"
        config_path.write_text(
            "\n".join(
                [
                    f'[registry."{self.settings.registry_push}"]',
                    "  http = true",
                    "  insecure = true",
                    "",
                ]
            )
        )
        return str(config_path)

    def _execution_pod_spec(self, pod_name: str, executions: list[LocalExecution], timeout_seconds: int):
        if not executions:
            raise ValueError("an execution pod must contain at least one target")
        exploit = executions[0].exploit
        client = self._client
        labels = {
            "app.kubernetes.io/name": "ataka-exploit-execution",
            "ataka.ad.tertsonen.xyz/component": "exploit-execution",
            "ataka.ad.tertsonen.xyz/exploit-id": _k8s_name(exploit.id, 48),
            self.settings.vpn_label_key: self.settings.vpn_label_value,
        }
        environment = [
            client.V1EnvVar(name="ATAKA_CENTRAL_EXECUTION", value="TRUE"),
            client.V1EnvVar(name="ATAKA_BATCH_SIZE", value=str(len(executions))),
            client.V1EnvVar(name="ATAKA_EXPLOIT_ID", value=exploit.id),
        ]
        for index, execution in enumerate(executions):
            environment.extend(
                [
                    client.V1EnvVar(name=f"ATAKA_EXECUTION_ID_{index}", value=str(execution.database_id)),
                    client.V1EnvVar(name=f"ATAKA_TARGET_IP_{index}", value=execution.target.ip),
                    client.V1EnvVar(name=f"ATAKA_TARGET_EXTRA_{index}", value=execution.target.extra or ""),
                ]
            )
        tolerations = []
        if self.settings.autoscaled_toleration_key:
            tolerations.append(
                client.V1Toleration(
                    key=self.settings.autoscaled_toleration_key,
                    operator="Equal",
                    value=self.settings.autoscaled_toleration_value,
                    effect=self.settings.autoscaled_toleration_effect,
                )
            )
        return client.V1Pod(
            metadata=client.V1ObjectMeta(name=pod_name, labels=labels),
            spec=client.V1PodSpec(
                restart_policy="Never",
                service_account_name=self.settings.service_account,
                active_deadline_seconds=timeout_seconds,
                tolerations=tolerations,
                containers=[
                    client.V1Container(
                        name="exploit",
                        image=exploit.docker_id,
                        image_pull_policy=self.settings.image_pull_policy,
                        working_dir="/exploit",
                        env=environment,
                        security_context=client.V1SecurityContext(
                            capabilities=client.V1Capabilities(add=["NET_RAW"])
                        ),
                        volume_mounts=[
                            client.V1VolumeMount(
                                name="persists",
                                mount_path="/persist",
                                sub_path=exploit.docker_name,
                            ),
                            client.V1VolumeMount(name="shared", mount_path="/shared", sub_path="exploits"),
                        ],
                    )
                ],
                volumes=[
                    client.V1Volume(
                        name="persists",
                        persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                            claim_name=self.settings.persist_claim
                        ),
                    ),
                    client.V1Volume(
                        name="shared",
                        persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                            claim_name=self.settings.shared_claim
                        ),
                    ),
                ],
            ),
        )

    async def _run_batch(self, job_id: int, executions: list[LocalExecution], timeout: float, channel) -> list[LocalExecution]:
        suffix = hashlib.sha256(
            f"{job_id}-{executions[0].database_id}-{time.time_ns()}".encode()
        ).hexdigest()[:10]
        pod_name = _k8s_name(f"ataka-exec-{executions[0].database_id}-{suffix}", 63)
        timeout_seconds = _seconds_until(timeout)
        pod = self._execution_pod_spec(pod_name, executions, timeout_seconds)
        self._pods_by_job.setdefault(job_id, set()).add(pod_name)
        output_task = None

        try:
            await asyncio.to_thread(self._create_pod, pod)
            if not await self._wait_for_container_start(pod_name, timeout=timeout_seconds):
                for execution in executions:
                    execution.status = JobExecutionStatus.TIMEOUT
                    execution.stderr += "<EXECUTOR TIMEOUT HAPPENED>"
                return executions

            output_task = asyncio.create_task(self._stream_batch_pod_logs(pod_name, executions, channel))
            phase, reason = await self._wait_for_pod(pod_name, _seconds_until(timeout))
            await output_task

            for execution in executions:
                if execution.status != JobExecutionStatus.RUNNING:
                    continue
                if phase == "Succeeded":
                    execution.status = JobExecutionStatus.FAILED
                    execution.stderr += "<EXECUTOR ERROR: batch runner returned no result>"
                elif reason == "DeadlineExceeded":
                    execution.status = JobExecutionStatus.TIMEOUT
                    execution.stderr += "<EXECUTOR TIMEOUT HAPPENED>"
                else:
                    execution.status = JobExecutionStatus.FAILED
                    execution.stderr += f"Exploit pod finished with phase={phase} reason={reason}"
            return executions
        except asyncio.CancelledError:
            for execution in executions:
                execution.status = JobExecutionStatus.CANCELLED
                execution.stderr += "<EXECUTOR CANCELLED>"
            raise
        except Exception as exc:
            for execution in executions:
                execution.status = JobExecutionStatus.FAILED
                execution.stderr += f"<EXECUTOR ERROR: {exc}>"
            return executions
        finally:
            self._pods_by_job.get(job_id, set()).discard(pod_name)
            await asyncio.to_thread(self._delete_pod, pod_name)
            if output_task is not None and not output_task.done():
                try:
                    await asyncio.wait_for(output_task, timeout=5)
                except asyncio.TimeoutError:
                    output_task.cancel()
                    await asyncio.gather(output_task, return_exceptions=True)

    async def _stream_batch_pod_logs(self, pod_name: str, executions: list[LocalExecution], channel):
        output_queue = await OutputQueue.get(channel)
        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        execution_by_id = {execution.database_id: execution for execution in executions}
        current_execution = None
        partial_line = ""

        def read_logs():
            try:
                response = self._core.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=self.settings.namespace,
                    container="exploit",
                    follow=True,
                    _preload_content=False,
                )
                for chunk in response.stream():
                    if not chunk:
                        continue
                    loop.call_soon_threadsafe(queue.put_nowait, chunk.decode(errors="replace"))
            except Exception as exc:
                loop.call_soon_threadsafe(queue.put_nowait, f"<EXECUTOR LOG ERROR: {exc}>")
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        reader = asyncio.create_task(asyncio.to_thread(read_logs))
        try:
            while True:
                output = await queue.get()
                if output is None:
                    break
                partial_line += output
                while "\n" in partial_line:
                    line, partial_line = partial_line.split("\n", 1)
                    current_execution, output_message = self._process_batch_log_line(
                        line, execution_by_id, current_execution
                    )
                    if output_message is not None:
                        await output_queue.send_message(output_message)
            if partial_line and current_execution is not None:
                current_execution.stdout += partial_line
                await output_queue.send_message(
                    OutputMessage(current_execution.database_id, True, partial_line)
                )
        finally:
            await reader

    @staticmethod
    def _process_batch_log_line(line, execution_by_id, current_execution):
        start = re.fullmatch(r"__ATAKA_BATCH_START__:(\d+)", line.rstrip("\r"))
        end = re.fullmatch(r"__ATAKA_BATCH_END__:(\d+):(\d+)", line.rstrip("\r"))
        if start:
            return execution_by_id.get(int(start.group(1))), None
        if end:
            execution = execution_by_id.get(int(end.group(1)))
            if execution is not None:
                execution.status = (
                    JobExecutionStatus.FINISHED if end.group(2) == "0" else JobExecutionStatus.FAILED
                )
            return None, None
        if current_execution is None:
            return None, None
        output = f"{line}\n"
        current_execution.stdout += output
        return current_execution, OutputMessage(current_execution.database_id, True, output)

    async def _wait_for_pod(self, pod_name: str, timeout: int) -> tuple[str, str]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            pod = await asyncio.to_thread(
                self._core.read_namespaced_pod_status,
                name=pod_name,
                namespace=self.settings.namespace,
            )
            phase = pod.status.phase
            if phase in ("Succeeded", "Failed"):
                return phase, pod.status.reason or ""
            await asyncio.sleep(1)
        return "Failed", "DeadlineExceeded"

    async def _wait_for_container_start(self, pod_name: str, timeout: int) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                pod = await asyncio.to_thread(
                    self._core.read_namespaced_pod_status,
                    name=pod_name,
                    namespace=self.settings.namespace,
                )
                if pod.status.phase in ("Running", "Succeeded", "Failed"):
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
        return False

    def _create_pod(self, pod):
        try:
            self._core.delete_namespaced_pod(
                name=pod.metadata.name,
                namespace=self.settings.namespace,
                grace_period_seconds=0,
            )
        except Exception:
            pass
        self._core.create_namespaced_pod(namespace=self.settings.namespace, body=pod)

    def _delete_pod(self, name: str):
        try:
            self._core.delete_namespaced_pod(
                name=name,
                namespace=self.settings.namespace,
                grace_period_seconds=0,
            )
        except Exception:
            pass

    def _read_pod_log(self, name: str) -> str:
        try:
            return self._core.read_namespaced_pod_log(name=name, namespace=self.settings.namespace)
        except Exception as exc:
            return f"<EXECUTOR LOG ERROR: {exc}>"


def create_backend() -> ExecutorBackend:
    backend = os.environ.get("EXECUTOR_BACKEND", "kubernetes").lower()
    if backend == "kubernetes":
        return KubernetesExecutorBackend()
    if backend in ("dind", "docker"):
        return DockerExecutorBackend(Docker())
    raise BackendError(f"Unsupported EXECUTOR_BACKEND={backend!r}; expected 'kubernetes' or 'dind'")
