"""
Test the SIGTERM path: call pool.terminate() mid-cycle and observe that
worker subprocesses are killed immediately with no cleanup logged.
The parent's pool.apply() awaitables should raise an exception.
"""
import asyncio
import logging
import multiprocessing
import platform

import aiomultiprocess as amp

if platform.system() != "Windows":
    amp.set_start_method("fork")

from worker import worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(process)d] %(name)s - %(message)s",
)
log = logging.getLogger("test")


async def main():
    manager = multiprocessing.Manager()
    stop_event = manager.Event()  # never set — workers run until killed

    pool = amp.Pool()
    await pool.__aenter__()

    log.info("=== Submitting 2 workers ===")

    # Terminate the pool after 1.5 s — mid-way through cycle 2
    async def terminate_after(delay):
        await asyncio.sleep(delay)
        log.info("=== Calling pool.terminate() (workers mid-cycle) ===")
        pool.terminate()

    gather_task = asyncio.gather(
        pool.apply(worker, (1, stop_event, "testsession-xyz")),
        pool.apply(worker, (2, stop_event, "testsession-xyz")),
    )

    async def terminate_after(delay):
        await asyncio.sleep(delay)
        log.info("=== Calling pool.terminate() (workers mid-cycle) ===")
        pool.terminate()
        # aiomultiprocess does not cancel pending futures on terminate —
        # the gather would hang forever. Cancel it explicitly.
        gather_task.cancel()
        log.info("=== gather_task cancelled ===")

    asyncio.create_task(terminate_after(1.5))

    try:
        await gather_task
        log.info("=== gather returned normally (unexpected) ===")
    except asyncio.CancelledError:
        log.info("=== gather raised CancelledError (expected) ===")
    except Exception as e:
        log.info(f"=== gather raised {type(e).__name__}: {e} ===")

    log.info("=== Done — note: no 'Exiting' lines from workers ===")


if __name__ == "__main__":
    asyncio.run(main())
