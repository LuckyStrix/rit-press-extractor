"""A bare window: pick an input folder and an output file, press Start, watch the status.

It runs the same `process` command as the terminal in a separate process, so the window
never freezes, Cancel can stop it cleanly, and nothing about processing differs.
"""
from __future__ import annotations

import os
import queue
import re
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_DIR / "data" / "results.csv"
JOB_RAM_GB = 1.5  # each parallel job loads its own OCR models
MAX_JOBS = 4

_READ = re.compile(r"^\s+read (?P<page>(?P<file>.+?) p\d+)")
_RESULT = re.compile(r"^\s+\[(?P<mark>ok|REVIEW)\s*\]")
_DONE = re.compile(r"^Done\.")


def _ram_gb() -> float:
    try:
        if os.name == "nt":
            import ctypes

            class Mem(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                            ("avail", ctypes.c_ulonglong), ("pt", ctypes.c_ulonglong), ("pa", ctypes.c_ulonglong),
                            ("vt", ctypes.c_ulonglong), ("va", ctypes.c_ulonglong), ("ve", ctypes.c_ulonglong)]

            mem = Mem(length=ctypes.sizeof(Mem))
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
            return mem.avail / 2**30
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable"):
                    return int(line.split()[1]) / 2**20
    except (OSError, AttributeError, ValueError):
        pass
    return 4.0


def default_jobs() -> int:
    """Photos to read at once: half the cores, as many as the free memory allows, at most MAX_JOBS."""
    return max(1, min(MAX_JOBS, (os.cpu_count() or 2) // 2, int(_ram_gb() // JOB_RAM_GB)))


def pdf_dir_for(output: Path) -> Path:
    return output.with_name(output.stem + "_pdfs")


def build_command(folder: Path, output: Path, jobs: int, box: str = "", folder_no: str = "",
                  template: str = "") -> list[str]:
    cmd = [sys.executable, "-m", "extractor", "process", str(folder), "-o", str(output), "-j", str(jobs)]
    if box and folder_no:  # numbers the releases and writes one named PDF each, next to the results file
        cmd += ["--box", box, "--folder", folder_no, "--pdfs", str(pdf_dir_for(output))]
    # Always said outright, so an empty box means no spreadsheet even when local/ has a template.
    return cmd + ["--metadata-template", template]


def default_template() -> str:
    from .metadata import DEFAULT_TEMPLATE

    return str(DEFAULT_TEMPLATE) if DEFAULT_TEMPLATE.exists() else ""


@dataclass
class RunState:
    """What the window shows, rebuilt from the lines `process` prints."""
    total_pages: int = 0
    pages_seen: set[str] = field(default_factory=set)
    releases: int = 0
    review: int = 0
    done: bool = False
    failed: bool = False
    status: str = "Ready"
    notes: list[str] = field(default_factory=list)  # per-folder summaries (list pages, subjects)
    tail: list[str] = field(default_factory=list)  # last lines, kept to explain a failure

    @property
    def fraction(self) -> float:
        if self.done:
            return 1.0
        return min(len(self.pages_seen) / self.total_pages, 1.0) if self.total_pages else 0.0

    def feed(self, line: str) -> None:
        line = line.rstrip()
        self.tail = (self.tail + [line])[-8:]
        if m := _READ.match(line):
            self.pages_seen.add(m["page"])
            self.status = f"Reading {m['page']}  ({len(self.pages_seen)} of {self.total_pages or '?'} pages)"
        elif m := _RESULT.match(line):
            self.releases += 1
            self.review += m["mark"] == "REVIEW"
            self.status = f"{self.releases} releases so far, {self.review} need review"
        elif _DONE.match(line):
            self.done = True
            self.status = f"Finished: {self.releases} releases, {self.review} need review"
        elif re.match(r"^\s+\S.*list page", line):
            self.notes.append(line.strip())

    def finish(self, returncode: int, cancelled: bool = False) -> None:
        if cancelled:
            self.status = "Stopped. Rows saved so far are in the results file."
        elif returncode != 0 and not self.done:
            self.failed = True
            self.status = "Failed: " + (next((t for t in reversed(self.tail) if t.strip()), "see the log below"))


def _stop(proc: subprocess.Popen) -> None:
    """Stop the run and the worker processes it started."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        os.killpg(proc.pid, signal.SIGTERM)


class App:
    """The window. Everything the buttons do is a method, so it can also be driven from code."""

    def __init__(self, root):
        import tkinter as tk
        from tkinter import scrolledtext, ttk

        self.root = root
        root.title("RIT Press Release Extractor")
        root.minsize(640, 420)
        self.folder, self.output = tk.StringVar(), tk.StringVar(value=str(DEFAULT_OUTPUT))
        self.box, self.folder_no = tk.StringVar(), tk.StringVar()
        self.template = tk.StringVar(value=default_template())
        self._filled = ("", "")  # what the folder name last filled in, to tell it from typed values
        self.folder.trace_add("write", self._refill_filing)
        self.status = tk.StringVar(value="Choose a folder of scans and press Start.")
        self.lines: queue.Queue = queue.Queue()
        self.proc: subprocess.Popen | None = None
        self.state = RunState()
        self.cancelled = False

        frame = ttk.Frame(root, padding=12)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(7, weight=1)
        ttk.Label(frame, text="Input folder").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.folder).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(frame, text="Browse…", command=self.pick_folder).grid(row=0, column=2)
        ttk.Label(frame, text="Output file").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.output).grid(row=1, column=1, sticky="ew", padx=8)
        ttk.Button(frame, text="Browse…", command=self.pick_output).grid(row=1, column=2)

        ttk.Label(frame, text="Box / Folder #").grid(row=2, column=0, sticky="w", pady=4)
        filing = ttk.Frame(frame)
        filing.grid(row=2, column=1, columnspan=2, sticky="w", padx=8)
        ttk.Entry(filing, textvariable=self.box, width=8).pack(side="left")
        ttk.Label(filing, text=" / ").pack(side="left")
        ttk.Entry(filing, textvariable=self.folder_no, width=8).pack(side="left")
        ttk.Label(filing, text="  Optional: numbers the releases and saves a named PDF of each").pack(side="left")

        ttk.Label(frame, text="Metadata template").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.template).grid(row=3, column=1, sticky="ew", padx=8)
        ttk.Button(frame, text="Browse…", command=self.pick_template).grid(row=3, column=2)
        ttk.Label(frame, text="Optional: also saves a metadata spreadsheet (.xlsx) beside the results, "
                  "and may set how the PDFs are named").grid(row=4, column=1, columnspan=2, sticky="w", padx=8)

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=3, sticky="w", pady=8)
        self.start = ttk.Button(buttons, text="Start", command=self.begin)
        self.cancel = ttk.Button(buttons, text="Cancel", command=self.stop, state="disabled")
        self.open_btn = ttk.Button(buttons, text="Open results folder", command=self.show_results, state="disabled")
        for b in (self.start, self.cancel, self.open_btn):
            b.pack(side="left", padx=(0, 8))

        self.bar = ttk.Progressbar(frame, maximum=100)
        self.bar.grid(row=6, column=0, columnspan=3, sticky="ew")
        self.log = scrolledtext.ScrolledText(frame, height=12, state="disabled", font=("TkFixedFont", 9))
        self.log.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=8)
        ttk.Label(frame, textvariable=self.status, wraplength=600).grid(row=8, column=0, columnspan=3, sticky="w")
        root.protocol("WM_DELETE_WINDOW", self.close)

    # --- choosing files ---
    def pick_folder(self) -> None:
        from tkinter import filedialog

        if chosen := filedialog.askdirectory(title="Folder of scans"):
            self.folder.set(chosen)

    def _refill_filing(self, *_) -> None:
        """Box and folder follow the chosen folder's name, and are blank when it has none."""
        from .catalog import infer_box_folder

        typed = (self.box.get(), self.folder_no.get())
        if typed not in (("", ""), self._filled):  # the user typed these; keep them
            return
        self._filled = infer_box_folder(Path(self.folder.get().strip()))
        self.box.set(self._filled[0])
        self.folder_no.set(self._filled[1])

    def pick_template(self) -> None:
        from tkinter import filedialog

        if chosen := filedialog.askopenfilename(title="Metadata template", filetypes=[("Template (JSON)", "*.json")]):
            self.template.set(chosen)

    def pick_output(self) -> None:
        from tkinter import filedialog

        if chosen := filedialog.asksaveasfilename(
                title="Results file", defaultextension=".csv", initialfile=Path(self.output.get()).name,
                filetypes=[("Spreadsheet (CSV)", "*.csv")]):
            self.output.set(chosen)

    # --- running ---
    def _append(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _problem(self, title: str, message: str) -> None:
        from tkinter import messagebox

        messagebox.showerror(title, message)

    def begin(self) -> None:
        src, out = Path(self.folder.get().strip()), self.output.get().strip()
        if not src.is_dir():
            return self._problem("Input folder", "Choose a folder that contains the scans.")
        if not out:
            return self._problem("Output file", "Choose where to save the results.")
        try:
            from .loader import find_inputs

            files = find_inputs([src])
        except Exception:
            files = []
        if not files:
            return self._problem("Input folder", "That folder has no scans or PDFs the tool can read.")
        box, folder_no = self.box.get().strip(), self.folder_no.get().strip()
        if bool(box) != bool(folder_no):
            return self._problem("Box / Folder #", "Fill in both the box and the folder number, or leave both empty.")
        if box:
            from .catalog import Naming
            from .loader import find_inputs

            try:
                Naming(box, folder_no)
            except ValueError as exc:
                return self._problem("Box / Folder #", str(exc))
            if len({f.parent for f in find_inputs([src])}) > 1:
                return self._problem("Box / Folder #", "That folder holds several subfolders, and a box and folder "
                                     "number name one physical folder. Choose one subfolder, or clear both fields.")
        template = self.template.get().strip()
        if template:
            from .metadata import Template

            try:
                Template.load(Path(template))
            except ValueError as exc:
                return self._problem("Metadata template", str(exc))
        total = 0
        for f in files:  # the progress bar counts pages: one scanner PDF can hold a whole folder
            from .loader import page_count

            try:
                total += page_count(f)
            except Exception:
                total += 1
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        kwargs = {"creationflags": 0x00000200} if os.name == "nt" else {"start_new_session": True}
        self.proc = subprocess.Popen(build_command(src, Path(out), default_jobs(), box, folder_no, template), cwd=PROJECT_DIR, env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)
        self.state, self.cancelled = RunState(total_pages=total), False
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()
        self.start.configure(state="disabled")
        self.cancel.configure(state="normal")
        self.open_btn.configure(state="disabled")
        self.bar.configure(value=0)
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.status.set("Starting: loading the OCR models can take a minute…")
        self.root.after(100, self._poll)

    def _reader(self, proc: subprocess.Popen) -> None:
        for raw in proc.stdout:
            self.lines.put(raw.decode("utf-8", "replace"))
        self.lines.put(None)

    def _poll(self) -> None:
        ended = False
        try:
            while True:
                line = self.lines.get_nowait()
                if line is None:
                    ended = True
                    break
                self._append(line.rstrip())
                self.state.feed(line)
        except queue.Empty:
            pass
        self.bar.configure(value=100 * self.state.fraction)
        if ended:
            self.proc.wait()
            self.state.finish(self.proc.returncode, self.cancelled)
            self.start.configure(state="normal")
            self.cancel.configure(state="disabled")
            self.open_btn.configure(state="normal")
        else:
            self.root.after(100, self._poll)
        self.status.set(self.state.status)

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.cancelled = True
            _stop(self.proc)
            self.status.set("Stopping…")

    def show_results(self) -> None:
        target = Path(self.output.get()).resolve().parent
        if os.name == "nt":
            os.startfile(target)  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def close(self) -> None:
        self.stop()
        self.root.destroy()


def run() -> int:
    import tkinter as tk

    os.umask(0o077)
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0
