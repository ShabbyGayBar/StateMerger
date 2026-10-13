# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path

import pytest

from scripts import validate_artifacts
from vic3_state_merger import gui

pytestmark = pytest.mark.smoke


class StartupWindow(tk.Tk):
    """Tk test double that never creates a Tcl interpreter or display window."""

    def __init__(self, fail: BaseException | None = None, callback: bool = False):
        self.fail = fail
        self.callback = callback
        self.destroyed = False

    def update_idletasks(self):
        pass

    def update(self):
        if self.callback:
            self.report_callback_exception(RuntimeError, RuntimeError("callback"), None)
        if self.fail:
            raise self.fail

    def destroy(self):
        self.destroyed = True


def test_gui_smoke_mode_reports_version_and_destroys_window(tmp_path):
    window = StartupWindow()
    report = tmp_path / "startup.json"
    gui._finish_startup(window, report)
    assert window.destroyed
    assert json.loads(report.read_text()) == {
        "status": "ok",
        "version": gui.__version__,
    }


@pytest.mark.parametrize("callback", [False, True])
def test_gui_startup_failure_does_not_report_success(tmp_path, callback):
    window = StartupWindow(
        fail=None if callback else RuntimeError("startup"), callback=callback
    )
    report = tmp_path / "startup.json"
    with pytest.raises(RuntimeError):
        gui._finish_startup(window, report)
    assert window.destroyed
    assert not report.exists()


def test_gui_normal_launch_enters_mainloop():
    class NormalWindow(StartupWindow):
        entered = False

        def mainloop(self, n: int = 0) -> None:
            self.entered = True

    window = NormalWindow()
    gui._finish_startup(window, None)
    assert window.entered


def test_gui_removes_stale_report_before_startup_failure(tmp_path, monkeypatch):
    report = tmp_path / "startup.json"
    report.write_text('{"status": "ok"}')
    monkeypatch.setattr(sys, "argv", ["state-merger", "--smoke-test", str(report)])

    def fail():
        raise RuntimeError("Tk startup failed")

    monkeypatch.setattr(gui.tk, "Tk", fail)
    with pytest.raises(RuntimeError):
        gui.main()
    assert not report.exists()


@pytest.mark.parametrize("failure", ["exit", "missing", "version", "timeout"])
def test_packaged_exe_failure_and_timeout(monkeypatch, failure):
    class Process:
        pid = 123
        killed = False

        def wait(self, timeout=None):
            if failure == "timeout" and not self.killed:
                assert timeout is not None
                raise subprocess.TimeoutExpired("exe", timeout)
            return int(failure == "exit")

        def kill(self):
            self.killed = True

    process = Process()
    killed_trees = []

    def taskkill(command, **kwargs):
        killed_trees.append(command)
        process.killed = True
        return subprocess.CompletedProcess(command, 0)

    def start(command, **kwargs):
        report = Path(command[-1])
        if failure == "version":
            report.write_text(json.dumps({"status": "ok", "version": "wrong"}))
        return process

    monkeypatch.setattr(validate_artifacts.subprocess, "Popen", start)
    monkeypatch.setattr(validate_artifacts.subprocess, "run", taskkill)
    with pytest.raises(RuntimeError):
        validate_artifacts.validate_exe(Path("state-merger.exe"), "3.2.1")
    if failure == "timeout":
        if os.name == "nt":
            assert killed_trees == [["taskkill", "/F", "/T", "/PID", "123"]]
        else:
            assert process.killed


def test_packaged_exe_fresh_report_and_clean_environment(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/checkout/src")

    def start(command, **kwargs):
        report = Path(command[-1])
        assert not report.exists()
        assert "PYTHONPATH" not in kwargs["env"]
        report.write_text(json.dumps({"status": "ok", "version": "3.2.1"}))

        class Process:
            def wait(self, timeout):
                assert timeout == 60
                return 0

        return Process()

    monkeypatch.setattr(validate_artifacts.subprocess, "Popen", start)
    validate_artifacts.validate_exe(Path("state-merger.exe"), "3.2.1")
