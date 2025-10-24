import os
import sys
import threading
import subprocess
import queue
from pathlib import Path
from datetime import datetime
import shutil
import re

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import tkinter.font as tkfont

import ttkbootstrap as tb
from ttkbootstrap.constants import *


# ---------------------------------------------------------------------------
# Console Pane
# ---------------------------------------------------------------------------
class ConsolePane(ttk.Frame):
    def __init__(self, master: tk.Misc):
        super().__init__(master)

        self.text = tk.Text(
            self,
            height=10,
            wrap="word",
            background="#0d1117",
            foreground="#e6edf3",
            insertbackground="#e6edf3",
            relief="flat",
            borderwidth=0,
            padx=8,
            pady=6,
        )
        self.text.configure(state="disabled")

        yscroll = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=yscroll.set)

        self.text.tag_configure("stdout", foreground="#7ee787")
        self.text.tag_configure("stderr", foreground="#ff7b72")
        self.text.tag_configure("system", foreground="#8b949e")

        self.text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self._queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self.after(60, self._flush_queue)

    def clear(self) -> None:
        self._append("", clear=True)

    def write(self, text: str, tag: str = "system") -> None:
        self._queue.put((text, tag))

    def writeline(self, text: str = "", tag: str = "system") -> None:
        self.write(text + "\n", tag)

    def _flush_queue(self) -> None:
        try:
            while True:
                text, tag = self._queue.get_nowait()
                self._append(text, tag=tag)
        except queue.Empty:
            pass
        finally:
            self.after(60, self._flush_queue)

    def _append(self, text: str, tag: str | None = None, clear: bool = False) -> None:
        self.text.configure(state="normal")
        if clear:
            self.text.delete("1.0", "end")
        if text:
            if tag:
                self.text.insert("end", text, (tag,))
            else:
                self.text.insert("end", text)
        self.text.see("end")
        self.text.configure(state="disabled")


# ---------------------------------------------------------------------------
# Code Editor with optional simple syntax highlighting
# ---------------------------------------------------------------------------
class CodeEditor(ttk.Frame):
    def __init__(self, master: tk.Misc, on_modified=None):
        super().__init__(master)
        self.on_modified = on_modified

        self.language: str | None = None  # "python", "c", "cpp", "java", or None
        self._dirty = False
        self._highlight_job: str | None = None

        self._font = self._choose_monospace_font()

        self.text = tk.Text(
            self,
            wrap="none",
            background="#0d1117",
            foreground="#e6edf3",
            insertbackground="#e6edf3",
            relief="flat",
            borderwidth=0,
            undo=True,
            padx=8,
            pady=6,
            font=self._font,
        )
        yscroll = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        xscroll = ttk.Scrollbar(self, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)

        # Syntax tags (colors tuned for dark theme)
        self.text.tag_configure("keyword", foreground="#79c0ff")
        self.text.tag_configure("comment", foreground="#8b949e")
        self.text.tag_configure("string", foreground="#a5d6ff")
        self.text.tag_configure("number", foreground="#d2a8ff")
        self.text.tag_configure("defname", foreground="#7ee787")

        self.text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # Track modifications for status bar and optional highlighting
        self.text.bind("<<Modified>>", self._handle_modified)

    # ------------------------------ Public API ------------------------------
    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def set_language_from_path(self, path: Path | None) -> None:
        if not path:
            self.language = None
            return
        ext = path.suffix.lower()
        if ext == ".py":
            self.language = "python"
        elif ext in (".c", ".h"):
            self.language = "c"
        elif ext in (".cpp", ".cc", ".cxx", ".hpp"):
            self.language = "cpp"
        elif ext == ".java":
            self.language = "java"
        else:
            self.language = None
        self._schedule_highlight()

    def load_file(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8", errors="replace")
        self._replace_content(text)
        self._dirty = False
        self.text.edit_modified(False)
        self.set_language_from_path(path)

    def get_content(self) -> str:
        return self.text.get("1.0", "end-1c")

    def save_file(self, path: Path) -> None:
        content = self.get_content()
        path.write_text(content, encoding="utf-8")
        self._dirty = False
        self.text.edit_modified(False)

    # --------------------------- Internal Helpers ---------------------------
    def _replace_content(self, text: str) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        if text:
            self.text.insert("1.0", text)
        self.text.see("1.0")
        self.text.configure(state="normal")
        self._schedule_highlight()

    def _handle_modified(self, _):
        if self.text.edit_modified():
            self._dirty = True
            self.text.edit_modified(False)
            if self.on_modified:
                self.on_modified()
            self._schedule_highlight()

    def _schedule_highlight(self):
        if self._highlight_job:
            try:
                self.after_cancel(self._highlight_job)
            except Exception:
                pass
        self._highlight_job = self.after(250, self._apply_syntax_highlighting)

    def _choose_monospace_font(self):
        families = set(tkfont.families())
        candidates = [
            "Consolas",
            "Fira Code",
            "JetBrains Mono",
            "DejaVu Sans Mono",
            "Courier New",
            "Monospace",
        ]
        for name in candidates:
            if name in families:
                return (name, 11)
        return ("TkFixedFont", 11)

    # ------------------------ Syntax Highlight (Simple) ---------------------
    def _apply_syntax_highlighting(self):
        self._highlight_job = None
        lang = self.language
        # Clear old tags
        for tag in ("keyword", "comment", "string", "number", "defname"):
            self.text.tag_remove(tag, "1.0", "end")

        if not lang:
            return

        # Very simple highlighter, line-by-line
        content = self.get_content()
        lines = content.splitlines()

        # Keyword sets
        py_keywords = {
            "False", "None", "True", "and", "as", "assert", "async", "await",
            "break", "class", "continue", "def", "del", "elif", "else", "except",
            "finally", "for", "from", "global", "if", "import", "in", "is",
            "lambda", "nonlocal", "not", "or", "pass", "raise", "return",
            "try", "while", "with", "yield",
        }
        c_keywords = {
            "auto", "break", "case", "char", "const", "continue", "default",
            "do", "double", "else", "enum", "extern", "float", "for", "goto",
            "if", "inline", "int", "long", "register", "restrict", "return",
            "short", "signed", "sizeof", "static", "struct", "switch",
            "typedef", "union", "unsigned", "void", "volatile", "while",
        }
        cpp_keywords = c_keywords | {
            "alignas", "alignof", "and", "and_eq", "asm", "bitand", "bitor",
            "bool", "catch", "char16_t", "char32_t", "class", "compl", "concept",
            "consteval", "constexpr", "constinit", "decltype", "delete", "explicit",
            "export", "friend", "mutable", "namespace", "new", "noexcept", "not",
            "not_eq", "operator", "or", "or_eq", "private", "protected", "public",
            "reinterpret_cast", "requires", "static_assert", "template", "this",
            "thread_local", "throw", "try", "typeid", "typename", "using",
            "virtual", "wchar_t", "xor", "xor_eq",
        }
        java_keywords = {
            "abstract", "assert", "boolean", "break", "byte", "case", "catch",
            "char", "class", "const", "continue", "default", "do", "double",
            "else", "enum", "extends", "final", "finally", "float", "for",
            "goto", "if", "implements", "import", "instanceof", "int", "interface",
            "long", "native", "new", "package", "private", "protected", "public",
            "return", "short", "static", "strictfp", "super", "switch", "synchronized",
            "this", "throw", "throws", "transient", "try", "void", "volatile", "while",
        }

        keyword_set = (
            py_keywords if lang == "python" else
            cpp_keywords if lang == "cpp" else
            c_keywords if lang == "c" else
            java_keywords if lang == "java" else set()
        )

        string_regex = re.compile(r'''("[^"]*"|'[^']*')''')
        number_regex = re.compile(r"\b(?:0x[0-9a-fA-F]+|\d+\.\d+|\d+)\b")
        def_regex = re.compile(r"\b(def|class)\s+([A-Za-z_][A-Za-z0-9_]*)") if lang == "python" else None

        for idx, line in enumerate(lines, start=1):
            # Comments
            if lang == "python":
                cpos = line.find('#')
                if cpos != -1:
                    self._add_tag(idx, cpos, len(line), "comment")
            elif lang in ("c", "cpp", "java"):
                cpos = line.find('//')
                if cpos != -1:
                    self._add_tag(idx, cpos, len(line), "comment")
            # Strings
            for m in string_regex.finditer(line):
                self._add_tag(idx, m.start(), m.end(), "string")
            # Numbers
            for m in number_regex.finditer(line):
                self._add_tag(idx, m.start(), m.end(), "number")
            # Keywords
            start = 0
            while start < len(line):
                m = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", line[start:])
                if not m:
                    break
                word = m.group(1)
                s = start + m.start(1)
                e = start + m.end(1)
                if word in keyword_set:
                    self._add_tag(idx, s, e, "keyword")
                start = e
            # def/class names (Python)
            if def_regex and (m := def_regex.search(line)):
                name = m.group(2)
                # highlight only the name
                name_start = line.find(name)
                if name_start != -1:
                    self._add_tag(idx, name_start, name_start + len(name), "defname")

    def _add_tag(self, line: int, col_start: int, col_end: int, tag: str) -> None:
        start_index = f"{line}.{col_start}"
        end_index = f"{line}.{col_end}"
        self.text.tag_add(tag, start_index, end_index)


# ---------------------------------------------------------------------------
# File Explorer
# ---------------------------------------------------------------------------
class FileExplorer(ttk.Frame):
    def __init__(self, master: tk.Misc, on_open_file=None, root_path: Path | None = None):
        super().__init__(master)
        self.on_open_file = on_open_file
        self.root_path: Path = Path(root_path) if root_path else Path.cwd()
        self._node_paths: dict[str, Path] = {}

        header = ttk.Label(self, text="EXPLORER", anchor="w", padding=(8, 6))
        header.configure(style="Secondary.TLabel")
        header.pack(fill="x")

        self.tree = ttk.Treeview(self, show="tree")
        yscroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)

        self.tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewOpen>>", self._on_open_node)
        self.tree.bind("<Double-1>", self._on_double_click)

        self.populate()

    def set_root(self, path: Path) -> None:
        self.root_path = path
        self.populate()

    def populate(self) -> None:
        self.tree.delete(*self.tree.get_children(""))
        self._node_paths.clear()
        root_iid = self._insert_node("", self.root_path)
        self.tree.item(root_iid, open=True)
        self._populate_children(root_iid, self.root_path)

    def _insert_node(self, parent: str, path: Path) -> str:
        iid = self.tree.insert(parent, "end", text=path.name or str(path), open=False)
        self._node_paths[iid] = path
        # add a dummy child if directory to make it expandable
        if path.is_dir():
            self.tree.insert(iid, "end")
        return iid

    def _populate_children(self, iid: str, path: Path) -> None:
        # Clear dummy
        for child in self.tree.get_children(iid):
            self.tree.delete(child)
        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return
        for entry in entries:
            # Skip some heavy or irrelevant directories
            if entry.name in {".git", "__pycache__", "node_modules", ".venv", "venv"}:
                continue
            self._insert_node(iid, entry)

    def _on_open_node(self, event=None):
        iid = self.tree.focus()
        path = self._node_paths.get(iid)
        if path and path.is_dir():
            self._populate_children(iid, path)

    def _on_double_click(self, event=None):
        item = self.tree.focus()
        path = self._node_paths.get(item)
        if path and path.is_file():
            if self.on_open_file:
                self.on_open_file(path)


# ---------------------------------------------------------------------------
# Compiler Application
# ---------------------------------------------------------------------------
class CompilerApp:
    def __init__(self):
        self.app = tb.Window(themename="darkly")
        self.app.title("VS Code-like Compiler Interface")
        self.app.geometry("1200x800")

        # State
        self.active_path: Path | None = None
        self.running = False

        self._build_ui()
        self._bind_shortcuts()
        self._update_status("Ready")

    # ------------------------------ UI Building -----------------------------
    def _build_ui(self):
        self._configure_styles()

        # Overall layout: toolbar (top), paned (center), status (bottom)
        self.toolbar = ttk.Frame(self.app, padding=(8, 6))
        self.toolbar.pack(side="top", fill="x")
        self._build_toolbar(self.toolbar)

        # Paned containers
        self.hpaned = ttk.Panedwindow(self.app, orient=tk.HORIZONTAL)
        self.hpaned.pack(side="top", fill="both", expand=True)

        # Left: File Explorer
        left_frame = ttk.Frame(self.hpaned)
        self.file_explorer = FileExplorer(left_frame, on_open_file=self._open_path, root_path=Path.cwd())
        self.file_explorer.pack(fill="both", expand=True)

        # Right: Vertical split for editor and console
        right_container = ttk.Panedwindow(self.hpaned, orient=tk.VERTICAL)

        # Editor container with small top bar (filename)
        editor_container = ttk.Frame(right_container)
        self.editor_title = ttk.Label(editor_container, text="Untitled", anchor="w", padding=(8, 6))
        self.editor_title.pack(fill="x")
        self.editor = CodeEditor(editor_container, on_modified=self._on_editor_modified)
        self.editor.pack(fill="both", expand=True)

        # Console container
        console_container = ttk.Frame(right_container)
        console_title = ttk.Label(console_container, text="OUTPUT", anchor="w", padding=(8, 6))
        console_title.pack(fill="x")
        self.console = ConsolePane(console_container)
        self.console.pack(fill="both", expand=True)

        right_container.add(editor_container, weight=3)
        right_container.add(console_container, weight=1)

        # Add to main paned
        self.hpaned.add(left_frame, weight=0)
        self.hpaned.add(right_container, weight=1)

        # Set initial pane sizes
        self.app.after(50, lambda: self.hpaned.sashpos(0, 260))  # left sidebar width

        # Status bar
        self.statusbar = ttk.Frame(self.app)
        self.statusbar.pack(side="bottom", fill="x")
        self.status_file = ttk.Label(self.statusbar, text="File: Untitled", padding=(8, 4))
        self.status_state = ttk.Label(self.statusbar, text="Ready", padding=(8, 4))
        self.status_time = ttk.Label(self.statusbar, text="", padding=(8, 4))
        self.status_file.pack(side="left")
        self.status_state.pack(side="left")
        self.status_time.pack(side="right")
        self._tick_time()

    def _configure_styles(self):
        style = ttk.Style()
        style.configure("Toolbar.TButton", relief="flat", borderwidth=0, padding=(10, 6))
        style.map(
            "Toolbar.TButton",
            background=[("active", style.lookup("TFrame", "background"))],
            relief=[("active", "flat")],
        )
        style.configure("Secondary.TLabel", foreground="#8b949e")

    def _build_toolbar(self, parent: ttk.Frame):
        # Using ttkbootstrap Toolbutton for a flat look
        self.btn_open = tb.Toolbutton(parent, text="Open", bootstyle=SECONDARY, cursor="hand2", style="Toolbar.TButton", command=self._action_open)
        self.btn_save = tb.Toolbutton(parent, text="Save", bootstyle=SECONDARY, cursor="hand2", style="Toolbar.TButton", command=self._action_save)
        sep1 = ttk.Separator(parent, orient="vertical")
        self.btn_compile = tb.Toolbutton(parent, text="Compile", bootstyle=INFO, cursor="hand2", style="Toolbar.TButton", command=self._action_compile)
        self.btn_run = tb.Toolbutton(parent, text="Run", bootstyle=SUCCESS, cursor="hand2", style="Toolbar.TButton", command=self._action_run)

        self.btn_open.pack(side="left")
        self.btn_save.pack(side="left")
        sep1.pack(side="left", fill="y", padx=8)
        self.btn_compile.pack(side="left")
        self.btn_run.pack(side="left")

    def _bind_shortcuts(self):
        self.app.bind_all("<Control-o>", lambda e: self._action_open())
        self.app.bind_all("<Control-s>", lambda e: self._action_save())
        self.app.bind_all("<F7>", lambda e: self._action_compile())
        self.app.bind_all("<F5>", lambda e: self._action_run())

    # ------------------------------ Status Bar ------------------------------
    def _tick_time(self):
        self.status_time.configure(text=datetime.now().strftime("%H:%M:%S"))
        self.app.after(1000, self._tick_time)

    def _update_status(self, state: str):
        self.status_state.configure(text=state)

    def _update_filename_status(self):
        name = "Untitled" if not self.active_path else self.active_path.name
        if self.editor.is_dirty:
            name += " *"
        self.editor_title.configure(text=name)
        self.status_file.configure(text=f"File: {name}")
        title = name + " - VS Code-like Compiler Interface"
        self.app.title(title)

    def _on_editor_modified(self):
        self._update_filename_status()

    # ------------------------------ Actions ---------------------------------
    def _open_path(self, path: Path):
        try:
            self.editor.load_file(path)
            self.active_path = path
            self.editor.set_language_from_path(path)
            self.console.writeline(f"Opened: {str(path)}", tag="system")
            self._update_filename_status()
        except Exception as ex:
            messagebox.showerror("Open Error", f"Failed to open file:\n{ex}")

    def _action_open(self):
        initial = str(self.active_path.parent) if self.active_path else str(Path.cwd())
        filetypes = [
            ("All Files", "*.*"),
            ("Python", "*.py"),
            ("C", "*.c;*.h"),
            ("C++", "*.cpp;*.cc;*.cxx;*.hpp"),
            ("Java", "*.java"),
        ]
        path = filedialog.askopenfilename(initialdir=initial, filetypes=filetypes)
        if path:
            self._open_path(Path(path))

    def _action_save(self):
        if self.active_path is None:
            self._action_save_as()
            return
        try:
            self.editor.save_file(self.active_path)
            self.console.writeline(f"Saved: {str(self.active_path)}", tag="system")
            self._update_filename_status()
        except Exception as ex:
            messagebox.showerror("Save Error", f"Failed to save file:\n{ex}")

    def _action_save_as(self):
        initial = str(self.active_path.parent) if self.active_path else str(Path.cwd())
        path = filedialog.asksaveasfilename(initialdir=initial)
        if path:
            try:
                p = Path(path)
                self.editor.save_file(p)
                self.active_path = p
                self.editor.set_language_from_path(p)
                self.console.writeline(f"Saved As: {str(p)}", tag="system")
                self._update_filename_status()
            except Exception as ex:
                messagebox.showerror("Save Error", f"Failed to save file:\n{ex}")

    def _action_compile(self):
        if not self._ensure_save_before_action():
            return
        if not self.active_path:
            messagebox.showinfo("Compile", "No active file to compile.")
            return
        self._run_background(self._compile_worker)

    def _action_run(self):
        if not self._ensure_save_before_action():
            return
        if not self.active_path:
            messagebox.showinfo("Run", "No active file to run.")
            return
        self._run_background(self._run_worker)

    def _ensure_save_before_action(self) -> bool:
        if self.editor.is_dirty:
            res = messagebox.askyesnocancel("Unsaved Changes", "Save changes before proceeding?")
            if res is None:
                return False
            if res:
                self._action_save()
        return True

    # ------------------------ Background Task Runner ------------------------
    def _set_running(self, running: bool):
        self.running = running
        state = "disabled" if running else "normal"
        for b in (self.btn_open, self.btn_save, self.btn_compile, self.btn_run):
            b.configure(state=state)
        self._update_status("Running..." if running else "Ready")

    def _run_background(self, target):
        if self.running:
            return
        self._set_running(True)
        t = threading.Thread(target=self._task_wrapper, args=(target,), daemon=True)
        t.start()

    def _task_wrapper(self, target):
        try:
            target()
        except Exception as ex:
            self.console.writeline(f"Error: {ex}", tag="stderr")
        finally:
            self.app.after(0, lambda: self._set_running(False))

    # --------------------------- Compile / Run ------------------------------
    def _compile_worker(self):
        assert self.active_path is not None
        path = self.active_path
        lang = self._detect_language(path)
        self.console.writeline("========== Compile ==========")
        self.console.writeline(f"File: {path}")
        if lang == "python":
            cmd = [sys.executable, "-m", "py_compile", str(path)]
            self._execute_command(cmd, cwd=str(path.parent))
        elif lang in ("c", "cpp"):
            compiler = "gcc" if lang == "c" else "g++"
            if shutil.which(compiler) is None:
                self.console.writeline(f"{compiler} not found in PATH", tag="stderr")
                return
            build_dir = path.parent / "build"
            build_dir.mkdir(exist_ok=True)
            out = build_dir / path.stem
            cmd = [compiler, str(path), "-O2", "-o", str(out)]
            self._execute_command(cmd, cwd=str(path.parent))
        elif lang == "java":
            if shutil.which("javac") is None:
                self.console.writeline("javac not found in PATH", tag="stderr")
                return
            cmd = ["javac", str(path)]
            self._execute_command(cmd, cwd=str(path.parent))
        else:
            self.console.writeline("Unsupported file type for compile.", tag="stderr")

    def _run_worker(self):
        assert self.active_path is not None
        path = self.active_path
        lang = self._detect_language(path)
        self.console.writeline("========== Run ==========")
        self.console.writeline(f"File: {path}")
        if lang == "python":
            cmd = [sys.executable, str(path)]
            self._execute_command(cmd, cwd=str(path.parent))
        elif lang in ("c", "cpp"):
            build_dir = path.parent / "build"
            out = build_dir / path.stem
            if not out.exists():
                self.console.writeline("Binary not found. Compiling first...", tag="system")
                self._compile_worker()
            if out.exists():
                cmd = [str(out)]
                self._execute_command(cmd, cwd=str(build_dir))
        elif lang == "java":
            if shutil.which("java") is None:
                self.console.writeline("java runtime not found in PATH", tag="stderr")
                return
            # Ensure compiled
            class_file = path.with_suffix(".class")
            if not class_file.exists():
                self.console.writeline("Class not found. Compiling first...", tag="system")
                self._compile_worker()
            classname = path.stem
            cmd = ["java", "-cp", str(path.parent), classname]
            self._execute_command(cmd, cwd=str(path.parent))
        else:
            self.console.writeline("Unsupported file type for run.", tag="stderr")

    def _detect_language(self, path: Path) -> str | None:
        ext = path.suffix.lower()
        if ext == ".py":
            return "python"
        if ext in (".c", ".h"):
            return "c"
        if ext in (".cpp", ".cc", ".cxx", ".hpp"):
            return "cpp"
        if ext == ".java":
            return "java"
        return None

    def _execute_command(self, cmd: list[str], cwd: str | None = None):
        self.console.writeline("$ " + " ".join(self._quote_arg(a) for a in cmd), tag="system")
        try:
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                shell=False,
            )
            if proc.stdout:
                self.console.write(proc.stdout, tag="stdout")
            if proc.stderr:
                self.console.write(proc.stderr, tag="stderr")
            code = proc.returncode
            self.console.writeline(f"[exit {code}]", tag="system")
        except Exception as ex:
            self.console.writeline(f"Execution failed: {ex}", tag="stderr")

    @staticmethod
    def _quote_arg(a: str) -> str:
        if any(ch.isspace() for ch in a):
            return f'"{a}"'
        return a

    # ------------------------------ Main Loop -------------------------------
    def run(self):
        self.app.mainloop()


def main():
    app = CompilerApp()
    app.run()


if __name__ == "__main__":
    main()
