# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse
import json
import logging
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from vic3_state_merger import __version__
from vic3_state_merger.cli import _default_data_dir, run_merge
from vic3_state_merger.legal import LICENSE_NOTICE
from vic3_state_merger.logging_config import configure_logging

logger = logging.getLogger(__name__)


def _configure_merge_logging(log_file: str | None) -> Path | None:
    # Discard the previous run's handlers even if the new destination fails.
    configure_logging("DEBUG", console=False)
    if log_file is None:
        return None
    log_path = Path(log_file).expanduser().resolve()
    configure_logging("DEBUG", log_file=log_path, console=False)
    return log_path


def _browse_log_file(var: tk.StringVar) -> None:
    current = Path(var.get()).expanduser()
    path = filedialog.asksaveasfilename(
        title="Select diagnostic log file",
        initialdir=str(current.parent),
        initialfile=current.name or "state-merger.log",
        defaultextension=".log",
        confirmoverwrite=False,  # Existing logs are appended to and rotated.
        filetypes=[("Log files", "*.log"), ("All files", "*")],
    )
    if path:
        var.set(path)


def _browse_file(var: tk.StringVar) -> None:
    path = filedialog.askopenfilename(
        title="Select merge_states.json",
        filetypes=[("JSON files", "*.json"), ("All files", "*")],
    )
    if path:
        var.set(path)


def _browse_folder(var: tk.StringVar) -> None:
    path = filedialog.askdirectory(title="Select mod output folder")
    if path:
        var.set(path)


def _build_help_text() -> str:
    return (
        "State Merger GUI\n\n"
        "Inputs:\n"
        "- Merge file: Path to merge_states.json (merge plan).\n"
        "- Game root: Victoria 3 game root directory.\n"
        "- Mod output folder: Target mod folder where merged files are written.\n"
        "- Small state limit: Integer limit used by the merger.\n"
        "- Ignore small states: If enabled, small states are ignored when merging.\n\n"
        "Run:\n"
        "- Click Run to execute the merge with the provided settings.\n"
        "- Enable log file at the bottom of the Merge tab to save DEBUG diagnostics.\n"
        "- Type a log file path or use Browse; logging is off by default.\n"
        "- The suggested state-merger.log is in the resolved cache/data directory.\n"
    )


def _build_license_text() -> str:
    return LICENSE_NOTICE


def _validate_inputs(
    merge_file: str,
    game_root: str,
    mod_dir: str,
    small_state_limit: str,
    enable_log_file: bool = False,
    log_file: str = "",
) -> tuple[bool, str]:
    if not merge_file:
        return False, "Merge file is required."
    if not game_root:
        return False, "Game root is required."
    if not mod_dir:
        return False, "Mod output folder is required."
    try:
        value = int(small_state_limit)
        if value < 0:
            return False, "Small state limit must be >= 0."
    except ValueError:
        return False, "Small state limit must be an integer."
    if enable_log_file and not log_file.strip():
        return False, "Log file path is required when logging is enabled."
    return True, ""


def _completion_status(result, log_path: Path | None = None):
    """Headless-safe distinction between a finished run and an incomplete draft."""
    if result is not None and result.status == "draft":
        details = (
            f"Diagnostic log: {log_path}"
            if log_path is not None
            else "Enable file logging and rerun for diagnostic details."
        )
        return "Draft exported", f"Spline routes need repair or verification. {details}"
    return "Completed", None


def _finish_startup(root: tk.Tk, report: Path | None) -> None:
    if report is None:
        root.mainloop()
        return
    # Tk normally prints callback exceptions and keeps running. Diagnostic mode
    # must instead fail, without leaving a success report behind.
    errors = []
    root.report_callback_exception = lambda *error: errors.append(error)
    try:
        root.update_idletasks()
        root.update()
        if errors:
            raise RuntimeError("GUI startup callback failed") from errors[0][1]
    finally:
        root.destroy()
    report.write_text(
        json.dumps({"status": "ok", "version": __version__}) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="State Merger GUI")
    parser.add_argument(
        "--smoke-test",
        type=Path,
        metavar="REPORT_PATH",
        help="Construct the GUI, check startup, write a JSON report, and exit",
    )
    report = parser.parse_args().smoke_test
    if report is not None:
        report.unlink(missing_ok=True)
    root = tk.Tk()
    root.title("State Merger")
    root.geometry("640x500")
    root.minsize(640, 500)

    notebook = ttk.Notebook(root)
    main_tab = ttk.Frame(notebook, padding=12)
    help_tab = ttk.Frame(notebook, padding=12)
    license_tab = ttk.Frame(notebook, padding=12)
    notebook.add(main_tab, text="Merge")
    notebook.add(help_tab, text="Help")
    notebook.add(license_tab, text="License")
    notebook.pack(fill="both", expand=True)

    merge_file_var = tk.StringVar()
    game_root_var = tk.StringVar()
    mod_dir_var = tk.StringVar()
    small_state_limit_var = tk.StringVar(value="4")
    ignore_small_states_var = tk.BooleanVar(value=False)
    spline_network_var = tk.BooleanVar(value=True)
    enable_log_file_var = tk.BooleanVar(value=False)
    log_file_var = tk.StringVar()
    status_var = tk.StringVar(value="Idle")

    main_tab.columnconfigure(1, weight=1)

    ttk.Label(main_tab, text="Merge file (merge_states.json)").grid(
        row=0, column=0, sticky="w"
    )
    merge_entry = ttk.Entry(main_tab, textvariable=merge_file_var)
    merge_entry.grid(row=0, column=1, sticky="ew", padx=(8, 8))
    ttk.Button(
        main_tab, text="Browse...", command=lambda: _browse_file(merge_file_var)
    ).grid(row=0, column=2, sticky="e")

    ttk.Label(main_tab, text="Game root folder").grid(
        row=1, column=0, sticky="w", pady=(8, 0)
    )
    game_root_entry = ttk.Entry(main_tab, textvariable=game_root_var)
    game_root_entry.grid(row=1, column=1, sticky="ew", padx=(8, 8), pady=(8, 0))
    ttk.Button(
        main_tab, text="Browse...", command=lambda: _browse_folder(game_root_var)
    ).grid(row=1, column=2, sticky="e", pady=(8, 0))

    ttk.Label(main_tab, text="Mod output folder").grid(
        row=2, column=0, sticky="w", pady=(8, 0)
    )
    mod_entry = ttk.Entry(main_tab, textvariable=mod_dir_var)
    mod_entry.grid(row=2, column=1, sticky="ew", padx=(8, 8), pady=(8, 0))
    ttk.Button(
        main_tab, text="Browse...", command=lambda: _browse_folder(mod_dir_var)
    ).grid(row=2, column=2, sticky="e", pady=(8, 0))

    ttk.Label(main_tab, text="Small state limit").grid(
        row=3, column=0, sticky="w", pady=(8, 0)
    )
    small_limit_entry = ttk.Entry(main_tab, textvariable=small_state_limit_var, width=8)
    small_limit_entry.grid(row=3, column=1, sticky="w", padx=(8, 8), pady=(8, 0))

    ignore_checkbox = ttk.Checkbutton(
        main_tab,
        text="Ignore small states",
        variable=ignore_small_states_var,
    )
    ignore_checkbox.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
    spline_checkbox = ttk.Checkbutton(
        main_tab, text="Merge spline network", variable=spline_network_var
    )
    spline_checkbox.grid(row=4, column=2, sticky="w", pady=(8, 0))

    status_label = ttk.Label(main_tab, textvariable=status_var)
    status_label.grid(row=5, column=0, columnspan=3, sticky="w", pady=(12, 0))

    run_button = ttk.Button(main_tab, text="Run")
    run_button.grid(row=6, column=0, pady=(16, 0), sticky="w")

    main_tab.rowconfigure(7, weight=1)
    log_frame = ttk.Frame(main_tab, padding=(0, 12, 0, 0))
    log_frame.grid(row=8, column=0, columnspan=3, sticky="sew")
    log_frame.columnconfigure(1, weight=1)

    def _update_log_controls(is_running: bool = False) -> None:
        enabled = enable_log_file_var.get()
        if enabled and not log_file_var.get():
            data_dir = _default_data_dir(mod_dir_var.get().strip())
            log_file_var.set(str(Path(data_dir).resolve() / "state-merger.log"))
        state = "normal" if enabled and not is_running else "disabled"
        log_entry.configure(state=state)
        log_browse.configure(state=state)

    log_checkbox = ttk.Checkbutton(
        log_frame,
        text="Enable log file",
        variable=enable_log_file_var,
        command=_update_log_controls,
    )
    log_checkbox.grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(log_frame, text="Log file").grid(row=1, column=0, sticky="w", pady=(8, 0))
    log_entry = ttk.Entry(log_frame, textvariable=log_file_var, state="disabled")
    log_entry.grid(row=1, column=1, sticky="ew", padx=(8, 8), pady=(8, 0))
    log_browse = ttk.Button(
        log_frame,
        text="Browse...",
        command=lambda: _browse_log_file(log_file_var),
        state="disabled",
    )
    log_browse.grid(row=1, column=2, sticky="e", pady=(8, 0))

    help_text = tk.Text(help_tab, wrap="word", height=10)
    help_text.insert("1.0", _build_help_text())
    help_text.configure(state="disabled")
    help_text.pack(fill="both", expand=True)

    license_text = tk.Text(license_tab, wrap="word", height=10)
    license_text.insert("1.0", _build_license_text())
    license_text.configure(state="disabled")
    license_text.pack(fill="both", expand=True)

    def _set_running(is_running: bool) -> None:
        state = "disabled" if is_running else "normal"
        run_button.configure(state=state)
        merge_entry.configure(state=state)
        game_root_entry.configure(state=state)
        mod_entry.configure(state=state)
        small_limit_entry.configure(state=state)
        ignore_checkbox.configure(state=state)
        spline_checkbox.configure(state=state)
        log_checkbox.configure(state=state)
        _update_log_controls(is_running)

    def _run_merge() -> None:
        merge_file = merge_file_var.get().strip()
        game_root = game_root_var.get().strip()
        mod_dir = mod_dir_var.get().strip()
        small_state_limit = small_state_limit_var.get().strip()
        enable_log_file = enable_log_file_var.get()
        log_file = log_file_var.get().strip()
        valid, error_message = _validate_inputs(
            merge_file,
            game_root,
            mod_dir,
            small_state_limit,
            enable_log_file,
            log_file,
        )
        if not valid:
            messagebox.showerror("Invalid input", error_message)
            return

        status_var.set("Running...")
        _set_running(True)
        ignore_small_states = ignore_small_states_var.get()
        spline_network = spline_network_var.get()

        def _worker() -> None:
            log_path = None
            try:
                limit = int(small_state_limit)
                data_dir = _default_data_dir(mod_dir)
                log_path = _configure_merge_logging(
                    log_file if enable_log_file else None
                )
                result = run_merge(
                    merge_file=merge_file,
                    mod_dir=mod_dir,
                    game_root=game_root,
                    data_dir=data_dir,
                    small_state_limit=limit,
                    ignore_small_states=ignore_small_states,
                    spline_network=spline_network,
                )
            except Exception as exc:  # pragma: no cover - UI boundary
                logger.exception("GUI merge or logging setup failed")
                error_message = str(exc)
                if log_path is not None:
                    error_message += f"\n\nDiagnostic log: {log_path}"
                root.after(
                    0,
                    lambda: messagebox.showerror("Merge failed", error_message),
                )
                root.after(0, lambda: status_var.set("Failed"))
            else:
                status, message = _completion_status(result, log_path)
                root.after(0, lambda: status_var.set(status))
                if message is not None:
                    root.after(
                        0, lambda: messagebox.showwarning("Draft exported", message)
                    )
            finally:
                root.after(0, lambda: _set_running(False))

        threading.Thread(target=_worker, daemon=True).start()

    run_button.configure(command=_run_merge)

    _finish_startup(root, report)


if __name__ == "__main__":
    main()
