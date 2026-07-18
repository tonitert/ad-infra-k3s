import asyncio
import os
import sys
import tempfile
import time
import types
import unittest
from enum import Enum


class DockerError(Exception):
    pass


aiodocker = types.ModuleType("aiodocker")
aiodocker.DockerError = DockerError
aiodocker.Docker = lambda *args, **kwargs: None
sys.modules.setdefault("aiodocker", aiodocker)

sqlalchemy = types.ModuleType("sqlalchemy")
sqlalchemy_future = types.ModuleType("sqlalchemy.future")
sqlalchemy_future.select = lambda *args, **kwargs: None
sqlalchemy_orm = types.ModuleType("sqlalchemy.orm")
sqlalchemy_orm.selectinload = lambda *args, **kwargs: None
sqlalchemy_orm.joinedload = lambda *args, **kwargs: None
sys.modules.setdefault("sqlalchemy", sqlalchemy)
sys.modules.setdefault("sqlalchemy.future", sqlalchemy_future)
sys.modules.setdefault("sqlalchemy.orm", sqlalchemy_orm)

database = types.ModuleType("ataka.common.database")
models = types.ModuleType("ataka.common.database.models")
models.Job = type("Job", (), {})
models.Execution = type("Execution", (), {})
models.Exploit = type("Exploit", (), {})
sys.modules.setdefault("ataka.common.database", database)
sys.modules.setdefault("ataka.common.database.models", models)


class JobAction(str, Enum):
    QUEUE = "queue"
    CANCEL = "cancel"


queue = types.ModuleType("ataka.common.queue")
queue.get_channel = None
queue.JobQueue = None
queue.JobCancelQueue = None
queue.JobAction = JobAction
queue.OutputQueue = None
queue.OutputMessage = None
sys.modules.setdefault("ataka.common.queue", queue)

from ataka.executor import backends as executor_backends
from ataka.executor import jobs as executor_jobs
from ataka.executor.localdata import LocalExecution, LocalExploit, LocalExploitStatus, LocalJob, LocalTarget
from ataka.common.job_execution_status import JobExecutionStatus


class FakeJobMessage:
    def __init__(self, action, job_id):
        self.action = action
        self.job_id = job_id


class FakeRawMessage:
    def __init__(self):
        self.acked = False
        self.rejected = False
        self.requeue = None

    async def ack(self):
        self.acked = True

    async def reject(self, requeue=False):
        self.rejected = True
        self.requeue = requeue


class FakeJobQueue:
    def __init__(self, messages):
        self.messages = messages

    @classmethod
    async def get(cls, channel):
        return channel.job_queue

    async def wait_for_raw_messages(self):
        for message in self.messages:
            yield message


class FakeCancelQueue:
    def __init__(self, messages):
        self.messages = messages

    @classmethod
    async def get(cls, channel):
        return channel.cancel_queue

    async def wait_for_messages(self):
        for message in self.messages:
            yield message


class FakeChannel:
    def __init__(self):
        self.qos = None

    async def set_qos(self, prefetch_count):
        self.qos = prefetch_count


class FakeChannelContext:
    def __init__(self, channels):
        self.channels = channels
        self.index = 0

    def __call__(self):
        context = self

        class _Context:
            async def __aenter__(self):
                channel = context.channels[context.index]
                context.index += 1
                return channel

            async def __aexit__(self, exc_type, exc, tb):
                return False

        return _Context()


class EmptyFakeJobQueue(FakeJobQueue):
    async def wait_for_raw_messages(self):
        if False:
            yield None


class EmptyFakeCancelQueue(FakeCancelQueue):
    async def wait_for_messages(self):
        if False:
            yield None


class FakeTask:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class ExecutorQueueTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_job_queue = executor_jobs.JobQueue
        self.original_cancel_queue = executor_jobs.JobCancelQueue
        self.original_job_execution = executor_jobs.JobExecution
        self.original_print_exc = executor_jobs.traceback.print_exc
        self.original_print = getattr(executor_jobs, "print", print)
        executor_jobs.JobQueue = FakeJobQueue
        executor_jobs.JobCancelQueue = FakeCancelQueue
        executor_jobs.traceback.print_exc = lambda: None
        executor_jobs.print = lambda *args, **kwargs: None

    def tearDown(self):
        executor_jobs.JobQueue = self.original_job_queue
        executor_jobs.JobCancelQueue = self.original_cancel_queue
        executor_jobs.JobExecution = self.original_job_execution
        executor_jobs.traceback.print_exc = self.original_print_exc
        executor_jobs.print = self.original_print

    async def test_poll_and_run_jobs_sets_prefetch_without_startup_error(self):
        original_get_channel = executor_jobs.get_channel
        job_channel = FakeChannel()
        cancel_channel = FakeChannel()
        job_channel.job_queue = EmptyFakeJobQueue([])
        cancel_channel.cancel_queue = EmptyFakeCancelQueue([])
        executor_jobs.get_channel = FakeChannelContext([job_channel, cancel_channel])

        try:
            scheduler = executor_jobs.Jobs(None)
            await scheduler.poll_and_run_jobs()
        finally:
            executor_jobs.get_channel = original_get_channel

        self.assertEqual(job_channel.qos, 1)

    async def test_ack_happens_after_job_finishes_terminal(self):
        raw_message = FakeRawMessage()
        channel = FakeChannel()
        channel.job_queue = FakeJobQueue([
            (FakeJobMessage(JobAction.QUEUE, 42), raw_message),
        ])

        class FinishedJobExecution:
            def __init__(self, backend, channel, job_id):
                self.job_id = job_id

            async def run(self):
                await asyncio.sleep(0)
                return True

            async def cancel(self):
                return True

        executor_jobs.JobExecution = FinishedJobExecution

        scheduler = executor_jobs.Jobs(None)
        await scheduler._poll_job_queue(channel)

        self.assertTrue(raw_message.acked)
        self.assertFalse(raw_message.rejected)

    async def test_executor_runs_jobs_concurrently_up_to_configured_limit(self):
        raw_messages = [FakeRawMessage(), FakeRawMessage()]
        channel = FakeChannel()
        channel.job_queue = FakeJobQueue([
            (FakeJobMessage(JobAction.QUEUE, 46), raw_messages[0]),
            (FakeJobMessage(JobAction.QUEUE, 47), raw_messages[1]),
        ])
        started = asyncio.Event()
        release = asyncio.Event()
        running = 0

        class ConcurrentJobExecution:
            def __init__(self, backend, channel, job_id):
                self.job_id = job_id

            async def run(self):
                nonlocal running
                running += 1
                if running == 2:
                    started.set()
                await release.wait()
                return True

            async def cancel(self):
                return True

        executor_jobs.JobExecution = ConcurrentJobExecution
        old_max_concurrent_jobs = os.environ.get("EXECUTOR_MAX_CONCURRENT_JOBS")
        os.environ["EXECUTOR_MAX_CONCURRENT_JOBS"] = "2"
        try:
            scheduler = executor_jobs.Jobs(None)
            poll_task = asyncio.create_task(scheduler._poll_job_queue(channel))
            await started.wait()
            release.set()
            await poll_task
        finally:
            if old_max_concurrent_jobs is None:
                os.environ.pop("EXECUTOR_MAX_CONCURRENT_JOBS", None)
            else:
                os.environ["EXECUTOR_MAX_CONCURRENT_JOBS"] = old_max_concurrent_jobs

        self.assertTrue(all(message.acked for message in raw_messages))

    async def test_unexpected_failure_requeues_message(self):
        raw_message = FakeRawMessage()
        channel = FakeChannel()
        channel.job_queue = FakeJobQueue([
            (FakeJobMessage(JobAction.QUEUE, 43), raw_message),
        ])

        class FailingJobExecution:
            def __init__(self, backend, channel, job_id):
                self.job_id = job_id

            async def run(self):
                raise RuntimeError("boom")

            async def cancel(self):
                return True

        executor_jobs.JobExecution = FailingJobExecution

        scheduler = executor_jobs.Jobs(None)
        await scheduler._poll_job_queue(channel)

        self.assertFalse(raw_message.acked)
        self.assertTrue(raw_message.rejected)
        self.assertTrue(raw_message.requeue)

    async def test_executor_shutdown_leaves_message_unacked(self):
        raw_message = FakeRawMessage()
        channel = FakeChannel()
        channel.job_queue = FakeJobQueue([
            (FakeJobMessage(JobAction.QUEUE, 45), raw_message),
        ])
        started = asyncio.Event()

        class SlowJobExecution:
            def __init__(self, backend, channel, job_id):
                self.job_id = job_id

            async def run(self):
                started.set()
                await asyncio.sleep(3600)

            async def cancel(self):
                return True

        executor_jobs.JobExecution = SlowJobExecution

        scheduler = executor_jobs.Jobs(None)
        poll_task = asyncio.create_task(scheduler._poll_job_queue(channel))
        await started.wait()
        poll_task.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await poll_task

        self.assertFalse(raw_message.acked)
        self.assertFalse(raw_message.rejected)

    async def test_cancel_queue_cancels_matching_running_task(self):
        channel = FakeChannel()
        channel.cancel_queue = FakeCancelQueue([
            FakeJobMessage(JobAction.CANCEL, 44),
        ])

        task = FakeTask()
        scheduler = executor_jobs.Jobs(None)
        scheduler._jobs[44] = task

        await scheduler._poll_cancel_queue(channel)

        self.assertTrue(task.cancelled)


class FakeKubernetesObject:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeKubernetesClient:
    V1Capabilities = FakeKubernetesObject
    V1Container = FakeKubernetesObject
    V1EnvVar = FakeKubernetesObject
    V1ObjectMeta = FakeKubernetesObject
    V1PersistentVolumeClaimVolumeSource = FakeKubernetesObject
    V1Pod = FakeKubernetesObject
    V1PodSpec = FakeKubernetesObject
    V1SecurityContext = FakeKubernetesObject
    V1Toleration = FakeKubernetesObject
    V1Volume = FakeKubernetesObject
    V1VolumeMount = FakeKubernetesObject


class KubernetesBackendTests(unittest.IsolatedAsyncioTestCase):
    def make_backend(self):
        settings = executor_backends.KubernetesSettings(
            namespace="ataka",
            registry_pull="ataka-registry.local",
            registry_push="ataka-registry:5000",
            buildkit_builder_name="ataka-buildkit",
            buildkit_image="moby/buildkit:buildx-stable-1",
            buildkit_replicas="1",
            buildkit_storage="20Gi",
            buildkit_driver_options="",
            service_account="ataka-executor",
            persist_claim="persists",
            shared_claim="shared",
            exploits_claim="exploits",
            image_pull_policy="IfNotPresent",
            vpn_label_key="ataka.ad.tertsonen.xyz/vpn-route",
            vpn_label_value="true",
            autoscaled_toleration_key="ataka.ad.tertsonen.xyz/autoscaled",
            autoscaled_toleration_value="true",
            autoscaled_toleration_effect="NoSchedule",
        )
        return executor_backends.KubernetesExecutorBackend(
            settings=settings,
            core_api=object(),
            client_module=FakeKubernetesClient,
        )

    def test_execution_pod_spec_uses_default_command_and_vpn_label(self):
        backend = self.make_backend()
        exploit = LocalExploit(
            id="demo",
            service="svc",
            author="alice",
            docker_name="demo-ctx",
            status=LocalExploitStatus.FINISHED,
            docker_id="ataka-registry.local/ataka-exploit/demo:abc",
        )
        execution = LocalExecution(7, exploit, LocalTarget("10.99.0.2", "x"), JobExecutionStatus.RUNNING)

        pod = backend._execution_pod_spec("ataka-exec-7", [execution], 30)
        container = pod.spec.containers[0]

        self.assertEqual(pod.metadata.labels["ataka.ad.tertsonen.xyz/vpn-route"], "true")
        self.assertNotIn("io.kompose.network/ataka-ataka", pod.metadata.labels)
        self.assertFalse(hasattr(container, "command"))
        self.assertEqual(container.image, "ataka-registry.local/ataka-exploit/demo:abc")
        self.assertEqual(container.security_context.capabilities.add, ["NET_RAW"])
        environment = [(env.name, env.value) for env in container.env]
        self.assertIn(("ATAKA_BATCH_SIZE", "1"), environment)
        self.assertIn(("ATAKA_EXECUTION_ID_0", "7"), environment)
        self.assertIn(("ATAKA_TARGET_IP_0", "10.99.0.2"), environment)
        self.assertEqual(len(pod.spec.tolerations), 1)
        self.assertEqual(pod.spec.tolerations[0].key, "ataka.ad.tertsonen.xyz/autoscaled")
        self.assertEqual(pod.spec.tolerations[0].value, "true")
        self.assertEqual(pod.spec.tolerations[0].effect, "NoSchedule")

    async def test_execution_timeout_maps_to_timeout_status(self):
        backend = self.make_backend()
        deleted = []

        async def wait_for_pod(name, timeout):
            return "Failed", "DeadlineExceeded"

        async def stream_logs(name, executions, channel):
            executions[0].stdout += "partial"

        backend._create_pod = lambda pod: None
        backend._delete_pod = lambda name: deleted.append(name)
        backend._wait_for_pod = wait_for_pod
        backend._wait_for_container_start = lambda name, timeout: asyncio.sleep(0, result=True)
        backend._stream_batch_pod_logs = stream_logs

        exploit = LocalExploit(
            id="demo",
            service="svc",
            author="alice",
            docker_name="demo-ctx",
            status=LocalExploitStatus.FINISHED,
            docker_id="ataka-registry.local/ataka-exploit/demo:abc",
        )
        execution = LocalExecution(8, exploit, LocalTarget("10.99.0.2"), JobExecutionStatus.RUNNING)

        result = (await backend._run_batch(99, [execution], asyncio.get_running_loop().time() + 5, None))[0]

        self.assertEqual(result.status, JobExecutionStatus.TIMEOUT)
        self.assertIn("<EXECUTOR TIMEOUT HAPPENED>", result.stderr)
        self.assertTrue(deleted)

    async def test_execution_that_never_starts_times_out_without_waiting_past_the_round(self):
        backend = self.make_backend()
        deleted = []

        backend._create_pod = lambda pod: None
        backend._delete_pod = lambda name: deleted.append(name)
        backend._wait_for_container_start = lambda name, timeout: asyncio.sleep(0, result=False)

        async def wait_for_pod(*args, **kwargs):
            self.fail("a pod that did not start must not be waited on past its deadline")

        backend._wait_for_pod = wait_for_pod

        exploit = LocalExploit(
            id="demo",
            service="svc",
            author="alice",
            docker_name="demo-ctx",
            status=LocalExploitStatus.FINISHED,
            docker_id="ataka-registry.local/ataka-exploit/demo:abc",
        )
        execution = LocalExecution(9, exploit, LocalTarget("10.99.0.3"), JobExecutionStatus.RUNNING)

        result = (await backend._run_batch(100, [execution], asyncio.get_running_loop().time() + 5, None))[0]

        self.assertEqual(result.status, JobExecutionStatus.TIMEOUT)
        self.assertIn("<EXECUTOR TIMEOUT HAPPENED>", result.stderr)
        self.assertTrue(deleted)

    async def test_execution_api_error_is_reported_without_failing_the_whole_job(self):
        backend = self.make_backend()
        deleted = []

        def create_pod(pod):
            raise RuntimeError("Kubernetes API unavailable")

        backend._create_pod = create_pod
        backend._delete_pod = lambda name: deleted.append(name)

        exploit = LocalExploit(
            id="demo",
            service="svc",
            author="alice",
            docker_name="demo-ctx",
            status=LocalExploitStatus.FINISHED,
            docker_id="ataka-registry.local/ataka-exploit/demo:abc",
        )
        execution = LocalExecution(10, exploit, LocalTarget("10.99.0.4"), JobExecutionStatus.RUNNING)

        result = (await backend._run_batch(101, [execution], asyncio.get_running_loop().time() + 5, None))[0]

        self.assertEqual(result.status, JobExecutionStatus.FAILED)
        self.assertIn("Kubernetes API unavailable", result.stderr)
        self.assertTrue(deleted)

    async def test_run_job_groups_targets_into_batch_pods(self):
        backend = self.make_backend()
        backend.settings.targets_per_pod = 30
        exploit = LocalExploit(
            id="demo",
            service="svc",
            author="alice",
            docker_name="demo-ctx",
            status=LocalExploitStatus.FINISHED,
            docker_id="ataka-registry.local/ataka-exploit/demo:abc",
        )
        executions = [
            LocalExecution(index, exploit, LocalTarget(f"10.99.0.{index}"), JobExecutionStatus.RUNNING)
            for index in range(1, 62)
        ]
        batches = []

        async def run_batch(job_id, batch, timeout, channel):
            batches.append(batch)
            return batch

        backend._run_batch = run_batch
        result = await backend.run_job(42, LocalJob(exploit, time.time() + 30, executions), None)

        self.assertEqual([len(batch) for batch in batches], [30, 30, 1])
        self.assertEqual(result, executions)

    def test_batch_log_markers_keep_target_output_and_statuses_separate(self):
        backend = self.make_backend()
        exploit = LocalExploit("demo", "svc", "alice", "demo-ctx", LocalExploitStatus.FINISHED)
        first = LocalExecution(11, exploit, LocalTarget("10.99.0.11"), JobExecutionStatus.RUNNING)
        second = LocalExecution(12, exploit, LocalTarget("10.99.0.12"), JobExecutionStatus.RUNNING)
        executions = {first.database_id: first, second.database_id: second}
        original_output_message = executor_backends.OutputMessage
        executor_backends.OutputMessage = lambda execution_id, stdout, output: types.SimpleNamespace(
            execution_id=execution_id, stdout=stdout, output=output
        )
        try:
            current, message = backend._process_batch_log_line("__ATAKA_BATCH_START__:11", executions, None)
            self.assertIs(current, first)
            self.assertIsNone(message)

            current, message = backend._process_batch_log_line("first target output", executions, current)
            self.assertIs(current, first)
            self.assertEqual(message.execution_id, 11)
            self.assertEqual(first.stdout, "first target output\n")

            current, message = backend._process_batch_log_line("__ATAKA_BATCH_END__:11:0", executions, current)
            self.assertIsNone(current)
            self.assertIsNone(message)
            self.assertEqual(first.status, JobExecutionStatus.FINISHED)

            current, _ = backend._process_batch_log_line("__ATAKA_BATCH_START__:12", executions, None)
            current, message = backend._process_batch_log_line("second target output", executions, current)
            self.assertEqual(message.execution_id, 12)
            backend._process_batch_log_line("__ATAKA_BATCH_END__:12:1", executions, current)
            self.assertEqual(second.status, JobExecutionStatus.FAILED)
        finally:
            executor_backends.OutputMessage = original_output_message

    async def test_concurrent_exploit_builds_initialize_buildkit_once_at_a_time(self):
        backend = self.make_backend()
        original_path = executor_backends.Path
        original_builder = backend._ensure_buildx_builder
        original_build = backend._build_with_buildx
        original_wrapper_context = backend._create_batch_wrapper_context
        active_builder_initializations = 0
        max_builder_initializations = 0

        def ensure_builder():
            nonlocal active_builder_initializations, max_builder_initializations
            active_builder_initializations += 1
            max_builder_initializations = max(max_builder_initializations, active_builder_initializations)
            time.sleep(0.02)
            active_builder_initializations -= 1

        try:
            with tempfile.TemporaryDirectory() as directory:
                executor_backends.Path = lambda value: original_path(directory)
                backend._ensure_buildx_builder = ensure_builder
                backend._build_with_buildx = lambda context_path, image_ref: "built"
                wrapper_context = original_path(directory) / "batch-wrapper.tar"
                wrapper_context.write_text("wrapper")
                backend._create_batch_wrapper_context = lambda base_image: wrapper_context
                exploits = [
                    LocalExploit("one", "svc", "alice", "one-context", LocalExploitStatus.BUILDING),
                    LocalExploit("two", "svc", "bob", "two-context", LocalExploitStatus.BUILDING),
                ]
                for exploit in exploits:
                    (original_path(directory) / exploit.docker_name).write_text("context")

                await asyncio.gather(*(backend._build_exploit(exploit) for exploit in exploits))

            self.assertEqual(max_builder_initializations, 1)
            self.assertTrue(all(exploit.status is LocalExploitStatus.FINISHED for exploit in exploits))
        finally:
            executor_backends.Path = original_path
            backend._ensure_buildx_builder = original_builder
            backend._build_with_buildx = original_build
            backend._create_batch_wrapper_context = original_wrapper_context


class BackendSelectionTests(unittest.TestCase):
    def test_dind_backend_selection(self):
        old_backend = os.environ.get("EXECUTOR_BACKEND")
        os.environ["EXECUTOR_BACKEND"] = "dind"
        os.environ.setdefault("DATA_STORE", "/data")
        try:
            backend = executor_backends.create_backend()
            self.assertIsInstance(backend, executor_backends.DockerExecutorBackend)
        finally:
            if old_backend is None:
                os.environ.pop("EXECUTOR_BACKEND", None)
            else:
                os.environ["EXECUTOR_BACKEND"] = old_backend

    def test_invalid_backend_selection_fails(self):
        old_backend = os.environ.get("EXECUTOR_BACKEND")
        os.environ["EXECUTOR_BACKEND"] = "bogus"
        try:
            with self.assertRaises(executor_backends.BackendError):
                executor_backends.create_backend()
        finally:
            if old_backend is None:
                os.environ.pop("EXECUTOR_BACKEND", None)
            else:
                os.environ["EXECUTOR_BACKEND"] = old_backend


if __name__ == "__main__":
    unittest.main()
