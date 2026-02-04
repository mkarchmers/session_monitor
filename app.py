"""
Example Panel app with session monitoring.
Run with: panel serve app.py --port 5001
"""

import time
import threading

import panel as pn

from session_client import SessionClient

pn.extension(disconnect_notification="Connection lost, session was terminated")


class TaskRunner(pn.viewable.Viewer):

    def __init__(self):
        super().__init__()
        self.task_name = pn.widgets.TextInput(
            name="Task Name",
            value="My Task",
            placeholder="Enter task name...",
        )

        self.duration = pn.widgets.IntSlider(
            name="Duration (seconds)",
            start=5,
            end=120,
            step=5,
            value=30,
        )

        self.run_button = pn.widgets.Button(
            name="Run Task",
            button_type="primary",
        )
        self.run_button.on_click(self._run_task)

        self.status = pn.pane.Markdown("Status: **Idle**")

    def _run_task(self, event):
        """Run the task in a background thread."""
        task_name = self.task_name.value or "Unnamed Task"
        duration = self.duration.value

        self.run_button.disabled = True
        self.status.object = f"Status: **Running** - {task_name} ({duration}s)"

        def do_task():
            tracker = SessionClient.get_tracker(app_name="task_runner")
            with tracker.task(task_name):
                time.sleep(duration)
            self.run_button.disabled = False
            self.status.object = "Status: **Idle** - Task completed"

        thread = threading.Thread(target=do_task, daemon=True)
        thread.start()

    def __panel__(self):
        return pn.Column(
            pn.pane.Markdown("## Task Runner"),
            self.task_name,
            self.duration,
            self.run_button,
            pn.layout.Divider(),
            self.status,
            width=400,
        )


class App:

    def run(self):
        # Initialize session tracker (starts heartbeat)
        SessionClient.get_tracker(app_name="task_runner")

        task_runner = TaskRunner()
        template = pn.template.BootstrapTemplate(title="Task Runner")

        template.main.append(task_runner)
        template.servable()


app = App()
app.run()
