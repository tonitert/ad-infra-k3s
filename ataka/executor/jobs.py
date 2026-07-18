import asyncio
import os
import time
import traceback
from datetime import datetime
from typing import Optional

from sqlalchemy.future import select
from sqlalchemy.orm import selectinload, joinedload

from ataka.common import database
from ataka.common.database.models import Job, Execution, Exploit
from ataka.common.queue import get_channel, JobQueue, JobCancelQueue, JobAction
from .localdata import *


class BuildError(Exception):
    pass


TERMINAL_STATUSES = {
    JobExecutionStatus.FINISHED,
    JobExecutionStatus.FAILED,
    JobExecutionStatus.TIMEOUT,
    JobExecutionStatus.CANCELLED,
}


class Jobs:
    def __init__(self, backend):
        self._backend = backend
        self._jobs = {}
        self._job_executions = {}
        self._cancel_requested = set()

    async def poll_and_run_jobs(self):
        async with get_channel() as job_channel, get_channel() as cancel_channel:
            prefetch_count = int(os.environ.get("EXECUTOR_MAX_CONCURRENT_JOBS", "1"))
            await job_channel.set_qos(prefetch_count=prefetch_count)

            await asyncio.gather(
                self._poll_job_queue(job_channel),
                self._poll_cancel_queue(cancel_channel),
            )

    async def _poll_job_queue(self, channel):
        job_queue = await JobQueue.get(channel)
        max_concurrent_jobs = int(os.environ.get("EXECUTOR_MAX_CONCURRENT_JOBS", "1"))
        if max_concurrent_jobs < 1:
            raise ValueError("EXECUTOR_MAX_CONCURRENT_JOBS must be at least 1")
        semaphore = asyncio.Semaphore(max_concurrent_jobs)
        tasks = set()

        def release_task(task):
            tasks.discard(task)
            semaphore.release()

        try:
            async for job_message, raw_message in job_queue.wait_for_raw_messages():
                if job_message.action != JobAction.QUEUE:
                    await raw_message.ack()
                    continue

                await semaphore.acquire()
                job_execution = JobExecution(self._backend, channel, job_message.job_id)
                task = asyncio.create_task(self._run_job_message(job_message, raw_message, job_execution))
                self._jobs[job_message.job_id] = task
                self._job_executions[job_message.job_id] = job_execution
                tasks.add(task)
                task.add_done_callback(release_task)
        except BaseException:
            for task in tuple(tasks):
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        else:
            await asyncio.gather(*tasks)

    async def _run_job_message(self, job_message, raw_message, job_execution):
        try:
            terminal = await job_execution.run()
        except asyncio.CancelledError:
            if job_message.job_id not in self._cancel_requested:
                raise
            terminal = await job_execution.cancel()
        except Exception:
            print(f"Unexpected executor failure for job {job_message.job_id}")
            traceback.print_exc()
            await raw_message.reject(requeue=True)
        else:
            if terminal:
                await raw_message.ack()
            else:
                await raw_message.reject(requeue=True)
        finally:
            self._cancel_requested.discard(job_message.job_id)
            if self._jobs.get(job_message.job_id) is asyncio.current_task():
                self._jobs.pop(job_message.job_id, None)
                self._job_executions.pop(job_message.job_id, None)

    async def _poll_cancel_queue(self, channel):
        cancel_queue = await JobCancelQueue.get(channel)

        async for job_message in cancel_queue.wait_for_messages():
            if job_message.action != JobAction.CANCEL:
                continue

            print(f"DEBUG: CURRENTLY RUNNING {len(self._jobs)}")
            task = self._jobs.get(job_message.job_id)
            if task is not None:
                self._cancel_requested.add(job_message.job_id)
                task.cancel()


class JobExecution:
    def __init__(self, backend, channel, job_id: int):
        self.id = job_id
        self._backend = backend
        self._channel = channel

    async def run(self):
        job = await self.fetch_job_from_database()
        if job is None:
            return True

        exploit = job.exploit

        try:
            results = await self._backend.run_job(self.id, job, self._channel)
        except Exception as exception:
            for e in job.executions:
                e.status = JobExecutionStatus.FAILED
                e.stderr = str(exception)
            await self.submit_to_database(job.executions)
            raise exception

        try:
            await self.submit_to_database(results)
            return True
        except asyncio.CancelledError:
            return await self.cancel()

    async def fetch_job_from_database(self) -> Optional[LocalJob]:
        async with database.get_session() as session:
            get_job = select(Job).where(Job.id == self.id).options(
                joinedload(Job.exploit).joinedload(Exploit.exploit_history), joinedload(Job.executions).joinedload(Execution.target)
            )
            job = (await session.execute(get_job)).unique().scalar_one()
            executions = job.executions

            if job.status in TERMINAL_STATUSES:
                return None

            time_left = job.timeout.timestamp() - time.time()
            if time_left < 0:
                job.status = JobExecutionStatus.TIMEOUT
                for e in executions:
                    e.status = JobExecutionStatus.TIMEOUT
                    e.stderr = "<EXECUTOR TIMEOUT HAPPENED>"
                await session.commit()
                return None

            local_exploit = await self._backend.ensure_exploit(job.exploit)

            job.timeout = datetime.fromtimestamp(time.time() + time_left)
            if local_exploit.status is not LocalExploitStatus.FINISHED:
                print(f"Got build error for exploit {local_exploit.id} (service {local_exploit.service}) by {local_exploit.author}")
                print(f"   {local_exploit.build_output}")
                job.status = JobExecutionStatus.FAILED
                for e in executions:
                    e.status = JobExecutionStatus.FAILED
                    e.stderr = local_exploit.build_output
                await session.commit()
                return None

            job.status = JobExecutionStatus.RUNNING
            local_executions = []
            for e in executions:
                e.status = JobExecutionStatus.RUNNING
                local_executions += [
                    LocalExecution(e.id, local_exploit, LocalTarget(e.target.ip, e.target.extra), JobExecutionStatus.RUNNING)]

            await session.commit()

            # Convert data to local for usage without database
            return LocalJob(local_exploit, job.timeout.timestamp(), local_executions)

    async def cancel(self):
        await self._backend.cancel_job(self.id)
        async with database.get_session() as session:
            get_job = select(Job).where(Job.id == self.id).options(selectinload(Job.executions))
            job = (await session.execute(get_job)).scalar_one()
            job.status = JobExecutionStatus.CANCELLED

            for execution in job.executions:
                if execution.status not in TERMINAL_STATUSES:
                    execution.status = JobExecutionStatus.CANCELLED
                    execution.stderr = (execution.stderr or "") + "<EXECUTOR CANCELLED>"

            await session.commit()
        return True

    async def submit_to_database(self, results: [LocalExecution]):
        local_executions = {e.database_id: e for e in results}
        status = JobExecutionStatus.FAILED if any([e.status == JobExecutionStatus.FAILED for e in results]) \
            else JobExecutionStatus.CANCELLED if any([e.status == JobExecutionStatus.CANCELLED for e in results]) \
            else JobExecutionStatus.TIMEOUT if any([e.status == JobExecutionStatus.TIMEOUT for e in results]) \
            else JobExecutionStatus.FINISHED

        # submit results to database
        async with database.get_session() as session:
            get_job = select(Job).where(Job.id == self.id)
            job = (await session.execute(get_job)).scalar_one()
            if job.status == JobExecutionStatus.CANCELLED:
                return
            job.status = status

            get_executions = select(Execution).where(Execution.job_id == self.id) \
                .options(selectinload(Execution.target))
            executions = (await session.execute(get_executions)).scalars()

            for execution in executions:
                local_execution = local_executions[execution.id]
                execution.status = local_execution.status
                execution.stdout = local_execution.stdout
                execution.stderr = local_execution.stderr

            await session.commit()
