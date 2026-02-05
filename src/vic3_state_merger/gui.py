import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from vic3_state_merger.cli import _default_data_dir, run_merge


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
    )


def _validate_inputs(
    merge_file: str,
    game_root: str,
    mod_dir: str,
    small_state_limit: str,
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
    return True, ""


def main() -> None:
    root = tk.Tk()
    root.title("State Merger")
    root.geometry("640x420")
    root.minsize(640, 420)

    notebook = ttk.Notebook(root)
    main_tab = ttk.Frame(notebook, padding=12)
    help_tab = ttk.Frame(notebook, padding=12)
    notebook.add(main_tab, text="Merge")
    notebook.add(help_tab, text="Help")
    notebook.pack(fill="both", expand=True)

    merge_file_var = tk.StringVar()
    game_root_var = tk.StringVar()
    mod_dir_var = tk.StringVar()
    small_state_limit_var = tk.StringVar(value="4")
    ignore_small_states_var = tk.BooleanVar(value=False)
    status_var = tk.StringVar(value="Idle")

    main_tab.columnconfigure(1, weight=1)

    ttk.Label(main_tab, text="Merge file (merge_states.json)").grid(row=0, column=0, sticky="w")
    merge_entry = ttk.Entry(main_tab, textvariable=merge_file_var)
    merge_entry.grid(row=0, column=1, sticky="ew", padx=(8, 8))
    ttk.Button(main_tab, text="Browse...", command=lambda: _browse_file(merge_file_var)).grid(
        row=0, column=2, sticky="e"
    )

    ttk.Label(main_tab, text="Game root folder").grid(row=1, column=0, sticky="w", pady=(8, 0))
    game_root_entry = ttk.Entry(main_tab, textvariable=game_root_var)
    game_root_entry.grid(row=1, column=1, sticky="ew", padx=(8, 8), pady=(8, 0))
    ttk.Button(main_tab, text="Browse...", command=lambda: _browse_folder(game_root_var)).grid(
        row=1, column=2, sticky="e", pady=(8, 0)
    )

    ttk.Label(main_tab, text="Mod output folder").grid(row=2, column=0, sticky="w", pady=(8, 0))
    mod_entry = ttk.Entry(main_tab, textvariable=mod_dir_var)
    mod_entry.grid(row=2, column=1, sticky="ew", padx=(8, 8), pady=(8, 0))
    ttk.Button(main_tab, text="Browse...", command=lambda: _browse_folder(mod_dir_var)).grid(
        row=2, column=2, sticky="e", pady=(8, 0)
    )

    ttk.Label(main_tab, text="Small state limit").grid(row=3, column=0, sticky="w", pady=(8, 0))
    small_limit_entry = ttk.Entry(main_tab, textvariable=small_state_limit_var, width=8)
    small_limit_entry.grid(row=3, column=1, sticky="w", padx=(8, 8), pady=(8, 0))

    ignore_checkbox = ttk.Checkbutton(
        main_tab,
        text="Ignore small states",
        variable=ignore_small_states_var,
    )
    ignore_checkbox.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))

    status_label = ttk.Label(main_tab, textvariable=status_var)
    status_label.grid(row=5, column=0, columnspan=3, sticky="w", pady=(12, 0))

    run_button = ttk.Button(main_tab, text="Run")
    run_button.grid(row=6, column=0, pady=(16, 0), sticky="w")

    help_text = tk.Text(help_tab, wrap="word", height=10)
    help_text.insert("1.0", _build_help_text())
    help_text.configure(state="disabled")
    help_text.pack(fill="both", expand=True)

    def _set_running(is_running: bool) -> None:
        state = "disabled" if is_running else "normal"
        run_button.configure(state=state)
        merge_entry.configure(state=state)
        game_root_entry.configure(state=state)
        mod_entry.configure(state=state)
        small_limit_entry.configure(state=state)
        ignore_checkbox.configure(state=state)

    def _run_merge() -> None:
        merge_file = merge_file_var.get().strip()
        game_root = game_root_var.get().strip()
        mod_dir = mod_dir_var.get().strip()
        small_state_limit = small_state_limit_var.get().strip()
        valid, error_message = _validate_inputs(
            merge_file,
            game_root,
            mod_dir,
            small_state_limit,
        )
        if not valid:
            messagebox.showerror("Invalid input", error_message)
            return

        status_var.set("Running...")
        _set_running(True)

        def _worker() -> None:
            try:
                limit = int(small_state_limit)
                data_dir = _default_data_dir(mod_dir)
                run_merge(
                    merge_file=merge_file,
                    mod_dir=mod_dir,
                    game_root=game_root,
                    data_dir=data_dir,
                    small_state_limit=limit,
                    ignore_small_states=ignore_small_states_var.get(),
                )
            except Exception as exc:  # pragma: no cover - UI error display
                root.after(0, lambda: messagebox.showerror("Merge failed", str(exc)))
                root.after(0, lambda: status_var.set("Failed"))
            else:
                root.after(0, lambda: status_var.set("Completed"))
            finally:
                root.after(0, lambda: _set_running(False))

        threading.Thread(target=_worker, daemon=True).start()

    run_button.configure(command=_run_merge)

    root.mainloop()


if __name__ == "__main__":
    main()
