import asyncio
import sys
import types
import unittest
from enum import Enum


class DockerError(Exception):
    pass


aiodocker = types.ModuleType("aiodocker")
aiodocker.DockerError = DockerError
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

from ataka.executor import jobs as executor_jobs


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
    pass


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

    async def test_ack_happens_after_job_finishes_terminal(self):
        raw_message = FakeRawMessage()
        channel = FakeChannel()
        channel.job_queue = FakeJobQueue([
            (FakeJobMessage(JobAction.QUEUE, 42), raw_message),
        ])

        class FinishedJobExecution:
            def __init__(self, docker, exploits, channel, job_id):
                self.job_id = job_id

            async def run(self):
                await asyncio.sleep(0)
                return True

            async def cancel(self):
                return True

        executor_jobs.JobExecution = FinishedJobExecution

        scheduler = executor_jobs.Jobs(None, None)
        await scheduler._poll_job_queue(channel)

        self.assertTrue(raw_message.acked)
        self.assertFalse(raw_message.rejected)

    async def test_unexpected_failure_requeues_message(self):
        raw_message = FakeRawMessage()
        channel = FakeChannel()
        channel.job_queue = FakeJobQueue([
            (FakeJobMessage(JobAction.QUEUE, 43), raw_message),
        ])

        class FailingJobExecution:
            def __init__(self, docker, exploits, channel, job_id):
                self.job_id = job_id

            async def run(self):
                raise RuntimeError("boom")

            async def cancel(self):
                return True

        executor_jobs.JobExecution = FailingJobExecution

        scheduler = executor_jobs.Jobs(None, None)
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
            def __init__(self, docker, exploits, channel, job_id):
                self.job_id = job_id

            async def run(self):
                started.set()
                await asyncio.sleep(3600)

            async def cancel(self):
                return True

        executor_jobs.JobExecution = SlowJobExecution

        scheduler = executor_jobs.Jobs(None, None)
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
        scheduler = executor_jobs.Jobs(None, None)
        scheduler._jobs[44] = task

        await scheduler._poll_cancel_queue(channel)

        self.assertTrue(task.cancelled)


if __name__ == "__main__":
    unittest.main()
