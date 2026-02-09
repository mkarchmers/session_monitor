"""Subprocess worker used by app_pool.py."""

import asyncio
import logging
import os


async def worker(task_id: int, stop_event, session_id: str = "") -> None:
    """Async worker: logs every 5 seconds until stop_event is set."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(process)d] %(name)s - %(message)s",
        force=True,
    )
    tag = f"worker-{task_id}"
    sid = session_id[:8]
    log = logging.getLogger(tag)
    log.info(f"[{sid}] Started (pid={os.getpid()})")

    while True:
        # Run the blocking wait in a thread so the event loop isn't blocked.
        # Returns immediately when the event is set (no 5-second delay).
        stopped = await asyncio.to_thread(stop_event.wait, 5)
        if stopped:
            break
        log.info(f"[{sid}] Alive (pid={os.getpid()})")

    log.info(f"[{sid}] Exiting (pid={os.getpid()})")
