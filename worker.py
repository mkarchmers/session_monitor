"""Subprocess worker used by app_pool.py."""

import asyncio
import logging
import os


async def _sub_task(sub_id: int, tag: str, sid: str, log: logging.Logger) -> str:
    """One of 5 concurrent sub-tasks per worker cycle. Takes ~1 second."""
    log.info(f"[{sid}] {tag}/sub-{sub_id} starting")
    await asyncio.sleep(1)
    log.info(f"[{sid}] {tag}/sub-{sub_id} done")
    return f"sub-{sub_id}-result"


async def worker(task_id: int, stop_event, session_id: str = "") -> None:
    """Async worker: each loop runs 5 concurrent coroutines (each 1 s).

    Termination behaviour:
    - stop_event set: checked *between* cycles; the current cycle's 5
      coroutines always run to completion (asyncio.gather is not cancelled).
    - pool.terminate() / SIGTERM: the subprocess is killed immediately;
      all coroutines vanish with no cleanup or exception propagation back
      to the caller in the parent process.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(process)d] %(name)s - %(message)s",
        force=True,
    )
    tag = f"worker-{task_id}"
    sid = session_id[:8]
    log = logging.getLogger(tag)
    log.info(f"[{sid}] Started (pid={os.getpid()})")

    cycle = 0
    while True:
        # Non-blocking check: stop_event.is_set() reads a shared flag.
        # We wrap it in to_thread to avoid blocking the event loop on
        # platforms where the multiprocessing Event uses a lock internally.
        stopped = await asyncio.to_thread(stop_event.is_set)
        if stopped:
            break

        cycle += 1
        log.info(f"[{sid}] Cycle {cycle}: launching 5 sub-tasks")

        results = await asyncio.gather(
            *[_sub_task(i, tag, sid, log) for i in range(5)]
        )

        log.info(f"[{sid}] Cycle {cycle} complete: {results}")

    log.info(f"[{sid}] Exiting (pid={os.getpid()})")
