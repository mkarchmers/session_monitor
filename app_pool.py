"""
Demo: shared pool with per-session cancellation (Option 2).

A global aiomultiprocess Pool is shared across all sessions.
Each session submits tasks via pool.apply() and uses a per-session
stop event for cancellation — killing one session does not affect
other sessions' work or the pool itself.

When all sessions are killed (e.g. via the dashboard "Kill All" button),
the pool is automatically terminated and its subprocesses are killed.

Run with: panel serve app_pool.py --port 5001
"""

import asyncio
import logging
import platform

import aiomultiprocess as amp

# Use "fork" on macOS/Linux to avoid pickle/module-resolution issues
# with Panel-served apps.  On Windows only "spawn" is available, but
# the CWD is in sys.path by default so `import worker` works there.
if platform.system() != "Windows":
    amp.set_start_method("fork")

import panel as pn

from pool_manager import (
    decrement_sessions,
    get_manager,
    get_pool,
    increment_sessions,
)
from session_client import SessionClient
from worker import worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(process)d] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

pn.extension(disconnect_notification="Session terminated by administrator")


# ── Panel app ───────────────────────────────────────────────────────


class PoolApp:
    def run(self) -> None:
        tracker = SessionClient.get_tracker(
            app_name="pool_app", heartbeat_interval=5
        )
        pool = get_pool()
        increment_sessions()

        status_md = pn.pane.Markdown("**Idle** — no workers running")
        run_btn = pn.widgets.Button(name="Run 2 Workers", button_type="primary")

        stop_event = get_manager().Event()

        # ── on_kill: signal this session's workers, decrement ref counter
        # Capture decrement_sessions via default arg so the reference
        # survives when Panel clears this script's namespace on reload.

        def kill_handler(_decr=decrement_sessions):
            stop_event.set()
            _decr()

        tracker.on_kill(kill_handler)

        # ── Button handler (async — Panel supports this) ───────

        async def on_click(event):
            run_btn.disabled = True
            status_md.object = "**Running** — 2 workers active"
            stop_event.clear()

            with tracker.task("Processing (2 workers)"):
                sid = tracker.session_id
                await asyncio.gather(
                    pool.apply(worker, (1, stop_event, sid)),
                    pool.apply(worker, (2, stop_event, sid)),
                )

            run_btn.disabled = False
            status_md.object = "**Idle** — workers finished"

        run_btn.on_click(on_click)

        template = pn.template.BootstrapTemplate(title="Pool App")
        template.main.append(
            pn.Column(
                pn.pane.Markdown("## Subprocess Demo (Shared Pool)"),
                pn.pane.Markdown(
                    "Submits 2 tasks to a global pool. Each logs every 5 s.\n\n"
                    "Kill from the monitor dashboard to stop them."
                ),
                run_btn,
                pn.layout.Divider(),
                status_md,
                width=500,
            )
        )
        template.servable()


app = PoolApp()
app.run()
