# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

"""Exercise GUI logging controls and worker callbacks without a display."""

import sys
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from vic3_state_merger import gui

pytestmark = pytest.mark.smoke


@pytest.fixture
def window(monkeypatch, tmp_path, request):
    interpreter = tk.Tcl()
    string_var, boolean_var = tk.StringVar, tk.BooleanVar
    monkeypatch.setattr(
        tk, "StringVar", lambda **kw: string_var(master=interpreter, **kw)
    )
    monkeypatch.setattr(
        tk, "BooleanVar", lambda **kw: boolean_var(master=interpreter, **kw)
    )
    widgets, workers, callbacks = [], [], []

    def widget(kind, parent=None, **options):
        control = Mock()
        control.kind, control.parent = kind, parent
        control.options, control.layout = options, {}
        control.configure.side_effect = lambda **kw: options.update(kw)
        control.grid.side_effect = lambda **kw: control.layout.update(kw)
        control.after.side_effect = lambda delay, callback: callbacks.append(callback)
        widgets.append(control)
        return control

    root = widget("root")
    monkeypatch.setattr(tk, "Tk", lambda: root)
    monkeypatch.setattr(tk, "Text", lambda parent, **kw: widget("Text", parent, **kw))
    for kind in ("Notebook", "Frame", "Label", "Entry", "Button", "Checkbutton"):
        monkeypatch.setattr(
            gui.ttk, kind, lambda parent, kind=kind, **kw: widget(kind, parent, **kw)
        )
    finish_startup, showerror = Mock(), Mock()
    monkeypatch.setattr(gui, "_finish_startup", finish_startup)
    monkeypatch.setattr(gui.messagebox, "showerror", showerror)
    monkeypatch.setattr(
        gui.threading,
        "Thread",
        lambda target, daemon: SimpleNamespace(start=lambda: workers.append(target)),
    )
    monkeypatch.chdir(tmp_path)
    report = tmp_path / "startup.json" if getattr(request, "param", False) else None
    arguments = ["state-merger"]
    if report is not None:
        arguments += ["--smoke-test", str(report)]
    monkeypatch.setattr(sys, "argv", arguments)
    gui.main()

    def find(text):
        return next(w for w in widgets if w.options.get("text") == text)

    checkbox = find("Enable log file")
    log_entry = next(
        w for w in widgets if w.kind == "Entry" and w.parent == checkbox.parent
    )
    browse = next(
        w for w in widgets if w.kind == "Button" and w.parent == checkbox.parent
    )
    run = find("Run")
    main_tab = run.parent
    entries = {
        w.layout["row"]: w.options["textvariable"]
        for w in widgets
        if w.kind == "Entry" and w.parent == main_tab
    }
    entries[0].set("plan.json")
    entries[1].set("game")
    entries[2].set(str(tmp_path / "mod"))
    return SimpleNamespace(
        root=root,
        widgets=widgets,
        workers=workers,
        callbacks=callbacks,
        checkbox=checkbox,
        entry=log_entry,
        browse=browse,
        run=run,
        enabled=checkbox.options["variable"],
        path=log_entry.options["textvariable"],
        main_tab=main_tab,
        entries=entries,
        report=report,
        finish_startup=finish_startup,
        showerror=showerror,
    )


def test_logging_controls_default_toggle_and_bottom_layout(window, tmp_path):
    assert window.enabled.get() is False
    assert window.entry.options["state"] == window.browse.options["state"] == "disabled"
    assert window.path.get() == ""
    assert not list(tmp_path.iterdir())
    window.root.geometry.assert_called_once_with("640x500")
    window.root.minsize.assert_called_once_with(640, 500)
    assert window.checkbox.parent.layout["row"] > window.run.layout["row"]
    assert window.checkbox.parent.layout["sticky"] == "sew"
    window.main_tab.rowconfigure.assert_called_once_with(7, weight=1)

    data = tmp_path / "data"
    data.mkdir()
    window.enabled.set(True)
    window.checkbox.options["command"]()
    assert window.path.get() == str(data / "state-merger.log")
    assert window.entry.options["state"] == window.browse.options["state"] == "normal"
    custom = str(tmp_path / "日志" / "custom.log")
    window.path.set(custom)
    window.enabled.set(False)
    window.checkbox.options["command"]()
    assert window.path.get() == custom
    assert window.entry.options["state"] == window.browse.options["state"] == "disabled"
    window.enabled.set(True)
    window.checkbox.options["command"]()
    assert window.path.get() == custom


@pytest.mark.parametrize("selected", ["", "chosen.log"])
def test_log_file_browse(window, monkeypatch, selected):
    window.enabled.set(True)
    window.checkbox.options["command"]()
    original = window.path.get()
    choose = Mock(return_value=selected)
    monkeypatch.setattr(gui.filedialog, "asksaveasfilename", choose)
    window.browse.options["command"]()
    assert window.path.get() == (selected or original)
    assert choose.call_args.kwargs["initialfile"] == "state-merger.log"
    assert choose.call_args.kwargs["defaultextension"] == ".log"


def test_enabled_blank_path_prevents_merge(window):
    window.enabled.set(True)
    window.path.set("  ")
    window.run.options["command"]()
    assert window.workers == []
    window.showerror.assert_called_once_with(
        "Invalid input", "Log file path is required when logging is enabled."
    )


@pytest.mark.parametrize("enabled", [False, True])
def test_worker_uses_captured_logging_and_restores_controls(
    window, monkeypatch, enabled
):
    window.enabled.set(enabled)
    window.path.set("custom.log")
    setup = Mock(return_value=Path("custom.log").resolve() if enabled else None)
    merge = Mock()
    monkeypatch.setattr(gui, "_configure_merge_logging", setup)
    monkeypatch.setattr(gui, "run_merge", merge)
    window.run.options["command"]()
    for control in (window.checkbox, window.entry, window.browse, window.run):
        assert control.options["state"] == "disabled"
    # Changes after dispatch must not affect the pending worker's settings.
    window.path.set("different.log")
    window.enabled.set(not enabled)
    window.workers.pop()()
    setup.assert_called_once_with("custom.log" if enabled else None)
    merge.assert_called_once()
    window.enabled.set(enabled)
    for callback in window.callbacks:
        callback()
    assert window.checkbox.options["state"] == "normal"
    assert (
        window.entry.options["state"]
        == window.browse.options["state"]
        == ("normal" if enabled else "disabled")
    )


@pytest.mark.parametrize("failure", ["setup", "merge", "disabled"])
def test_failure_dialog_only_includes_successfully_opened_log(
    window, monkeypatch, failure
):
    enabled = failure != "disabled"
    window.enabled.set(enabled)
    window.path.set("custom.log")
    path = Path("custom.log").resolve()
    setup = Mock(return_value=path if enabled else None)
    if failure == "setup":
        setup.side_effect = OSError("Cannot open log")
    merge = Mock(side_effect=ValueError("Merge failed"))
    monkeypatch.setattr(gui, "_configure_merge_logging", setup)
    monkeypatch.setattr(gui, "run_merge", merge)
    monkeypatch.setattr(gui.logger, "exception", Mock())
    window.run.options["command"]()
    window.workers.pop()()
    for callback in window.callbacks:
        callback()
    message = window.showerror.call_args.args[1]
    assert ("Diagnostic log:" in message) == (failure == "merge")
    if failure == "setup":
        assert "Cannot open log" in message
        merge.assert_not_called()


@pytest.mark.parametrize("window", [True], indirect=True)
def test_smoke_launch_creates_no_log(window, tmp_path):
    assert window.enabled.get() is False
    assert window.workers == []
    window.finish_startup.assert_called_once_with(window.root, window.report)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("repair", [False, True])
def test_spline_repair_toggle_and_captured_worker_setting(window, monkeypatch, repair):
    controls = {
        w.options.get("text"): w for w in window.widgets if w.kind == "Checkbutton"
    }
    splines = controls["Merge spline network"]
    repairs = controls["Repair spline errors"]
    assert repairs.options["variable"].get() is True
    splines.options["variable"].set(False)
    splines.options["command"]()
    assert repairs.options["state"] == "disabled"
    splines.options["variable"].set(True)
    splines.options["command"]()
    assert repairs.options["state"] == "normal"
    repairs.options["variable"].set(repair)
    merge = Mock()
    monkeypatch.setattr(gui, "run_merge", merge)
    window.run.options["command"]()
    assert repairs.options["state"] == "disabled"
    repairs.options["variable"].set(not repair)
    window.workers.pop()()
    assert merge.call_args.kwargs["repair_splines"] is repair
    # Restoring the UI must respect spline merging being disabled.
    splines.options["variable"].set(False)
    for callback in window.callbacks:
        callback()
    assert repairs.options["state"] == "disabled"


@pytest.mark.parametrize("enabled", [False, True])
def test_draft_dialog_uses_captured_log_destination(window, monkeypatch, enabled):
    window.enabled.set(enabled)
    window.path.set("custom.log")
    path = Path("custom.log").resolve()
    monkeypatch.setattr(
        gui, "_configure_merge_logging", lambda _: path if enabled else None
    )
    monkeypatch.setattr(gui, "run_merge", lambda **_: SimpleNamespace(status="draft"))
    warning = Mock()
    monkeypatch.setattr(gui.messagebox, "showwarning", warning)
    window.run.options["command"]()
    window.workers.pop()()
    for callback in window.callbacks:
        callback()
    title, message = warning.call_args.args
    assert title == "Draft exported"
    if enabled:
        assert str(path) in message
    else:
        assert "Enable file logging and rerun" in message
        assert str(path) not in message
