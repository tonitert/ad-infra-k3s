import asyncio

from ataka.common import queue, database
from .backends import create_backend
from .jobs import Jobs


async def main():
    # initialize connections
    await queue.connect()
    await database.connect()

    backend = create_backend()
    jobs = Jobs(backend)

    try:
        poll_task = jobs.poll_and_run_jobs()
        await asyncio.gather(poll_task)
    finally:
        await backend.close()


asyncio.run(main())
