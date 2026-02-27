"""
Test the stop_event path: run 2 workers, then set stop_event mid-cycle
and observe they finish the current cycle cleanly before exiting.
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
    stop_event = manager.Event()

    async with amp.Pool() as pool:
        log.info("=== Submitting 2 workers ===")

        # Fire stop_event after 2.5 s:
        # - cycle 1 completes at ~1 s
        # - cycle 2 starts at ~1 s, stop fires at ~2.5 s (mid-cycle-2)
        # - workers should finish cycle 2 (~2 s total) then exit
        async def set_stop_after(delay):
            await asyncio.sleep(delay)
            log.info("=== Setting stop_event (workers are mid-cycle) ===")
            stop_event.set()

        asyncio.create_task(set_stop_after(2.5))

        await asyncio.gather(
            pool.apply(worker, (1, stop_event, "testsession-abc")),
            pool.apply(worker, (2, stop_event, "testsession-abc")),
        )

    log.info("=== Both workers exited cleanly ===")


if __name__ == "__main__":
    asyncio.run(main())
