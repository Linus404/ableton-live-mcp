"""Fake Framework scheduler for Remote dispatch regression tests; no Live calls."""
import importlib.util
import sys
import threading
import types
from pathlib import Path
from unittest.mock import patch


class FrameworkTicks:
    def __init__(self):
        self.pending = []
        self.scheduled = threading.Event()
        self.ticks = 0
        self.delays = []

    def schedule_message(self, delay, callback):
        self.delays.append(delay)
        remaining = delay - 1
        self.pending.append([remaining if remaining else None, callback])
        self.scheduled.set()

    def tick(self):
        self.ticks += 1
        for task in list(self.pending):
            if task[0] is None:
                self.pending.remove(task)
                task[1]()
            else:
                task[0] -= 1
                if task[0] <= 0:
                    task[0] = None


def load_remote():
    framework = types.ModuleType("_Framework")
    control = types.ModuleType("_Framework.ControlSurface")
    control.ControlSurface = type("ControlSurface", (), {})
    path = Path(__file__).resolve().parents[1] / "Ableton_Live_MCP" / "bridge.py"
    spec = importlib.util.spec_from_file_location("phase2_fake_remote", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"Live": types.ModuleType("Live"),
                                  "_Framework": framework,
                                  "_Framework.ControlSurface": control}):
        spec.loader.exec_module(module)
    return module


def make_remote():
    module = load_remote()
    remote = object.__new__(module.AbletonLiveMCP)
    remote._main_thread_id = threading.get_ident()
    remote._running = True
    remote._check_expected_set_signature = lambda params: None
    remote._encode = lambda value, options: value
    remote._encode_options = lambda params: {}
    scheduler = FrameworkTicks()
    remote.schedule_message = scheduler.schedule_message
    return remote, scheduler


def start_request(remote, method="marker", params=None):
    results = []
    worker = threading.Thread(target=lambda: results.append(remote._dispatch({
        "jsonrpc": "2.0", "id": 17, "method": method, "params": params or {}})))
    worker.start()
    return worker, results
