"""tkinter graphical interface."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable, Optional

from .organizer import FileOrganizer, OrganizeResult

POLL_MS = 100


class OrganizerGUI:
    """Main window: choose a folder, preview, start/stop, undo.

    Long operations run in a worker thread so the window stays responsive and
    the Stop button works. The worker never touches widgets directly (tkinter
    is not thread-safe); it puts messages on a queue that the main thread
    drains every ``POLL_MS`` milliseconds.
    """

    def __init__(self, root: tk.Tk, organizer: FileOrganizer, folder: Optional[Path] = None) -> None:
        self.root = root
        self.organizer = organizer
        self.messages: "queue.Queue[tuple]" = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: Optional[threading.Thread] = None
        self._progress_count = 0

        root.title("Smart File Organizer")
        root.geometry("760x520")
        root.minsize(560, 380)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.folder_var = tk.StringVar(value=str(folder) if folder else "")
        self.status_var = tk.StringVar(value="Choose a folder to organize.")
        self._build()
        self._update_buttons()
        self.root.after(POLL_MS, self._poll)

    # ---- layout --------------------------------------------------------

    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)

        folder_row = ttk.Frame(main)
        folder_row.pack(fill="x", **pad)
        ttk.Label(folder_row, text="Folder:").pack(side="left")
        entry = ttk.Entry(folder_row, textvariable=self.folder_var)
        entry.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(folder_row, text="Browse…", command=self.browse).pack(side="left")
        self.folder_var.trace_add("write", lambda *_: self._update_buttons())

        buttons = ttk.Frame(main)
        buttons.pack(fill="x", **pad)
        self.preview_btn = ttk.Button(buttons, text="Preview", command=self.preview)
        self.start_btn = ttk.Button(buttons, text="▶ Start", command=self.start)
        self.stop_btn = ttk.Button(buttons, text="■ Stop", command=self.stop)
        self.undo_btn = ttk.Button(buttons, text="↶ Undo last", command=self.undo)
        for b in (self.preview_btn, self.start_btn, self.stop_btn, self.undo_btn):
            b.pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Open log", command=self.open_log).pack(side="right")

        self.progress = ttk.Progressbar(main, mode="determinate")
        self.progress.pack(fill="x", **pad)

        self.log = ScrolledText(main, height=16, wrap="none", state="disabled", font=("Menlo", 11))
        self.log.pack(fill="both", expand=True, **pad)
        self.log.tag_configure("error", foreground="#c62828")
        self.log.tag_configure("info", foreground="#1565c0")

        ttk.Label(main, textvariable=self.status_var, anchor="w").pack(fill="x", **pad)

    # ---- state ---------------------------------------------------------

    @property
    def busy(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def _folder(self) -> Optional[Path]:
        raw = self.folder_var.get().strip()
        if not raw:
            return None
        path = Path(raw).expanduser()
        if not path.is_dir():
            messagebox.showerror("Invalid folder", f"This folder does not exist:\n{path}")
            return None
        return path.resolve()

    def _update_buttons(self) -> None:
        has_folder = bool(self.folder_var.get().strip())
        idle = not self.busy
        self.preview_btn.state(["!disabled"] if idle and has_folder else ["disabled"])
        self.start_btn.state(["!disabled"] if idle and has_folder else ["disabled"])
        self.undo_btn.state(["!disabled"] if idle and self.organizer.history.sessions else ["disabled"])
        self.stop_btn.state(["!disabled"] if not idle else ["disabled"])

    def write(self, text: str, tag: Optional[str] = None) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", (tag,) if tag else ())
        self.log.see("end")
        self.log.configure(state="disabled")

    # ---- actions -------------------------------------------------------

    def browse(self) -> None:
        chosen = filedialog.askdirectory(title="Choose a folder to organize", mustexist=True)
        if chosen:
            self.folder_var.set(chosen)

    def preview(self) -> None:
        folder = self._folder()
        if folder is None:
            return
        self.write(f"Preview of {folder} (nothing is moved):", "info")
        self._run_in_thread(lambda progress: self.organizer.organize(folder, dry_run=True, progress=progress))

    def start(self) -> None:
        folder = self._folder()
        if folder is None:
            return
        try:
            count = len(self.organizer.plan(folder))
        except OSError as exc:
            messagebox.showerror("Cannot read folder", str(exc))
            return
        if count == 0:
            messagebox.showinfo("Nothing to do", "There are no files at the top level of this folder.")
            return
        if not messagebox.askyesno("Organize", f"Move {count} file(s) into category folders in\n{folder}?"):
            return
        self.write(f"Organizing {folder}", "info")
        self._run_in_thread(
            lambda progress: self.organizer.organize(folder, stop_event=self.stop_event, progress=progress)
        )

    def stop(self) -> None:
        if self.busy:
            self.stop_event.set()
            self.status_var.set("Stopping after the current file…")

    def undo(self) -> None:
        session = self.organizer.history.last()
        if session is None:
            messagebox.showinfo("Undo", "Nothing to undo.")
            return
        if not messagebox.askyesno(
            "Undo", f"Move {len(session.moves)} file(s) back to\n{session.folder}\n(organized {session.started})?"
        ):
            return
        self.write(f"Undoing last organize of {session.folder}", "info")
        folder = Path(session.folder)
        self._run_in_thread(lambda progress: self.organizer.undo_last(folder, progress=progress), undo=True)

    def open_log(self) -> None:
        log_file = self.organizer.log_file
        if not log_file.exists():
            messagebox.showinfo("Log", "No log yet.")
            return
        win = tk.Toplevel(self.root)
        win.title(f"Log - {log_file}")
        win.geometry("900x400")
        text = ScrolledText(win, wrap="none", font=("Menlo", 11))
        text.pack(fill="both", expand=True)
        try:
            lines = log_file.read_text(encoding="utf-8").splitlines()[-500:]
        except OSError as exc:
            lines = [f"Cannot read log: {exc}"]
        text.insert("end", "\n".join(lines))
        text.see("end")
        text.configure(state="disabled")

    def on_close(self) -> None:
        if self.busy:
            if not messagebox.askyesno("Quit", "An operation is running. Stop it and quit?"):
                return
            self.stop_event.set()
            self.worker.join(timeout=5)
        self.root.destroy()

    # ---- threading -----------------------------------------------------

    def _run_in_thread(self, job: Callable[[Callable[[int, int, str], None]], OrganizeResult], undo: bool = False) -> None:
        self.stop_event.clear()
        self._progress_count = 0
        self.progress.configure(value=0, maximum=1)
        self.status_var.set("Working…")

        def progress(done: int, total: int, message: str) -> None:
            self.messages.put(("progress", done, total, message))

        def target() -> None:
            try:
                result = job(progress)
                self.messages.put(("done", result, undo))
            except Exception as exc:  # last-resort guard so the GUI never hangs
                self.messages.put(("error", exc))

        self.worker = threading.Thread(target=target, daemon=True)
        self.worker.start()
        self._update_buttons()

    def _poll(self) -> None:
        try:
            while True:
                msg = self.messages.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    _, done, total, text = msg
                    self._progress_count += 1
                    self.progress.configure(maximum=max(total, 1), value=done)
                    self.status_var.set(f"{done}/{total}")
                    self.write(f"  {text}", "error" if text.startswith(("FAILED", "SKIPPED")) else None)
                elif kind == "done":
                    self._finish(msg[1], msg[2])
                elif kind == "error":
                    self.write(f"Unexpected error: {msg[1]}", "error")
                    self.status_var.set("Error - see log.")
                    self._update_buttons()
        except queue.Empty:
            pass
        self.root.after(POLL_MS, self._poll)

    def _finish(self, result: OrganizeResult, undo: bool) -> None:
        summary = result.summary()
        if undo:
            summary = summary.replace("Moved", "Restored", 1)
        for old, new in result.renamed:
            self.write(f"  renamed (name conflict): {old} -> {new}")
        if self._progress_count == 0:
            # Per-file failures were already shown as they happened; this catches
            # failures before any file was processed (e.g. folder not readable).
            for path, reason in result.failed:
                self.write(f"  ! {path}: {reason}", "error")
        self.write(summary, "error" if result.failed else "info")
        self.status_var.set(summary)
        self._update_buttons()


def launch(organizer: FileOrganizer, folder: Optional[Path] = None) -> None:
    root = tk.Tk()
    OrganizerGUI(root, organizer, folder)
    root.mainloop()
