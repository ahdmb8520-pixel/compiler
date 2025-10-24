#!/usr/bin/env python3

import os
import sys
import shutil
import subprocess
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
import tkinter.font as tkfont

import ttkbootstrap as tb
from ttkbootstrap.constants import *


class CompilerIDEApp:
    def __init__(self, base_dir: Path | None = None, theme_name: str = "darkly") -> None:
        self.base_dir: Path = Path(base_dir or os.getcwd()).resolve()
        self.root: tb.Window = tb.Window(themename=theme_name)
        self.root.title("Compiler Interface IDE")
        self.root.geometry("1200x720")

        self.current_file: Path | None = None
        self.last_executable: Path | None = None

        self.status_var = tk.StringVar(value="Ready")

        self._build_layout()
        self._populate_explorer_root()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- UI Construction ----------
    def _build_layout(self) -> None:
        # Paned window with three horizontal panes
        self.panes = tb.Panedwindow(self.root, orient=tk.HORIZONTAL)
        self.panes.pack(fill=tk.BOTH, expand=True)

        # Left: File Explorer
        self.explorer_frame = tb.Frame(self.panes, padding=5)
        self._build_explorer(self.explorer_frame)

        # Middle: Editor + Toolbar
        self.editor_frame = tb.Frame(self.panes, padding=(5, 5, 2, 5))
        self._build_editor(self.editor_frame)

        # Right: Output Console
        self.console_frame = tb.Frame(self.panes, padding=5)
        self._build_console(self.console_frame)

        # Add panes with initial weights
        self.panes.add(self.explorer_frame, weight=1)
        self.panes.add(self.editor_frame, weight=3)
        self.panes.add(self.console_frame, weight=2)

        # Status Bar
        status_bar = tb.Frame(self.root, bootstyle="secondary")
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_label = tb.Label(
            status_bar,
            textvariable=self.status_var,
            anchor="w",
            padding=(10, 2),
        )
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _build_explorer(self, parent: tk.Widget) -> None:
        header = tb.Label(parent, text=f"File Explorer — {self._rel(self.base_dir)}", anchor="w")
        header.pack(fill=tk.X, padx=2, pady=(0, 4))

        self.tree = tb.Treeview(parent, columns=("fullpath", "type"), show="tree")
        yscroll = tb.Scrollbar(parent, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Events
        self.tree.bind("<<TreeviewOpen>>", self._on_tree_expand)
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<Return>", self._on_tree_double_click)

    def _build_editor(self, parent: tk.Widget) -> None:
        # Toolbar
        toolbar = tb.Frame(parent)
        toolbar.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))

        self.open_btn = tb.Button(toolbar, text="Open", command=self.open_selected_file, width=10)
        self.save_btn = tb.Button(toolbar, text="Save", command=self.save_current_file, width=10)
        self.compile_btn = tb.Button(toolbar, text="Compile", command=self.compile_current_file, width=10)
        self.run_btn = tb.Button(toolbar, text="Run", command=self.run_current_file, width=10)

        for w in (self.open_btn, self.save_btn, self.compile_btn, self.run_btn):
            w.pack(side=tk.LEFT, padx=(0, 6))

        # Editor Text
        fixed_font = tkfont.nametofont("TkFixedFont").copy()
        try:
            fixed_font.configure(size=11)
        except Exception:
            pass

        editor_container = tb.Frame(parent)
        editor_container.pack(fill=tk.BOTH, expand=True)

        self.editor = tk.Text(
            editor_container,
            wrap="none",
            undo=True,
            font=fixed_font,
            background="#111518",
            foreground="#EAEAEA",
            insertbackground="#EAEAEA",
            borderwidth=0,
            relief=tk.FLAT,
        )
        yscroll = tb.Scrollbar(editor_container, orient=tk.VERTICAL, command=self.editor.yview)
        xscroll = tb.Scrollbar(editor_container, orient=tk.HORIZONTAL, command=self.editor.xview)
        self.editor.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)

        self.editor.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        xscroll.pack(side=tk.BOTTOM, fill=tk.X)

    def _build_console(self, parent: tk.Widget) -> None:
        header = tb.Label(parent, text="Output Console", anchor="w")
        header.pack(fill=tk.X, padx=2, pady=(0, 4))

        console_container = tb.Frame(parent)
        console_container.pack(fill=tk.BOTH, expand=True)

        self.console = tk.Text(
            console_container,
            wrap="word",
            state=tk.DISABLED,
            background="#0C0C0C",
            foreground="#FFFFFF",
            insertbackground="#FFFFFF",
            borderwidth=0,
            relief=tk.FLAT,
        )
        yscroll = tb.Scrollbar(console_container, orient=tk.VERTICAL, command=self.console.yview)
        self.console.configure(yscrollcommand=yscroll.set)

        self.console.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)

    # ---------- File Explorer Logic ----------
    def _populate_explorer_root(self) -> None:
        self.tree.delete(*self.tree.get_children(""))
        root_id = self._insert_node("", self.base_dir)
        self.tree.item(root_id, open=True)
        self._populate_children(root_id, self.base_dir)

    def _insert_node(self, parent: str, path: Path) -> str:
        text = path.name if parent else str(path)
        node_id = self.tree.insert(
            parent,
            "end",
            text=text,
            values=(str(path), "dir" if path.is_dir() else "file"),
            open=False,
        )
        if path.is_dir():
            # Dummy child so the expander appears
            self.tree.insert(node_id, "end", text="…")
        return node_id

    def _populate_children(self, node_id: str, directory: Path) -> None:
        try:
            entries = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except PermissionError:
            return
        except FileNotFoundError:
            return

        # Clear existing dummy
        for child in self.tree.get_children(node_id):
            if not self.tree.set(child, "fullpath"):
                self.tree.delete(child)

        for child_path in entries:
            # Skip virtual or inaccessible entries silently
            try:
                self._insert_node(node_id, child_path)
            except Exception:
                continue

    def _on_tree_expand(self, _event=None) -> None:
        node_id = self.tree.focus()
        fullpath = self.tree.set(node_id, "fullpath")
        if not fullpath:
            return
        path = Path(fullpath)
        if path.is_dir():
            self._populate_children(node_id, path)

    def _on_tree_double_click(self, _event=None) -> None:
        node_id = self.tree.focus()
        fullpath = self.tree.set(node_id, "fullpath")
        type_ = self.tree.set(node_id, "type")
        if type_ == "file" and fullpath:
            self.open_file(Path(fullpath))

    # ---------- Editor Actions ----------
    def open_selected_file(self) -> None:
        node_id = self.tree.focus()
        path_str = self.tree.set(node_id, "fullpath") if node_id else ""
        path = Path(path_str) if path_str else None
        if not path or not path.is_file():
            # Fallback to file dialog if nothing selected
            initdir = str(self.base_dir)
            filename = filedialog.askopenfilename(initialdir=initdir)
            if not filename:
                return
            path = Path(filename)
        self.open_file(path)

    def open_file(self, path: Path) -> None:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="latin-1", errors="replace")
        except Exception as exc:
            messagebox.showerror("Open Error", f"Failed to open file:\n{exc}")
            return

        self.editor.delete("1.0", tk.END)
        self.editor.insert("1.0", text)
        self.editor.edit_reset()
        self.editor.edit_modified(False)
        self.current_file = path
        self._set_status(f"Opened {self._rel(path)}")
        self.root.title(f"Compiler Interface IDE — {self._rel(path)}")

    def save_current_file(self) -> None:
        if self.current_file is None:
            initdir = str(self.base_dir)
            filename = filedialog.asksaveasfilename(initialdir=initdir)
            if not filename:
                return
            self.current_file = Path(filename)

        try:
            content = self.editor.get("1.0", tk.END)
            # Avoid writing trailing Tk newline if undesired
            if content.endswith("\n") and not content.strip():
                content = ""
            self.current_file.write_text(content, encoding="utf-8")
        except Exception as exc:
            messagebox.showerror("Save Error", f"Failed to save file:\n{exc}")
            return

        self.editor.edit_modified(False)
        self._set_status(f"Saved {self._rel(self.current_file)}")

    # ---------- Compile and Run ----------
    def compile_current_file(self) -> None:
        if not self._ensure_current_file_saved():
            return
        path = self.current_file
        assert path is not None
        self._run_async(lambda: self._compile(path), task_name="Compiling")

    def run_current_file(self) -> None:
        if not self._ensure_current_file_saved():
            return
        path = self.current_file
        assert path is not None
        self._run_async(lambda: self._run(path), task_name="Running")

    def _ensure_current_file_saved(self) -> bool:
        if self.current_file is None:
            messagebox.showinfo("No file", "Please open or save a file first.")
            return False
        if self.editor.edit_modified():
            if messagebox.askyesno("Unsaved changes", "Save changes before proceeding?"):
                self.save_current_file()
            else:
                return False
        return True

    def _compile(self, path: Path) -> None:
        self._clear_console()
        self._append_console(f"Compiling {self._rel(path)}\n\n")
        ext = path.suffix.lower()
        cwd = str(path.parent)

        try:
            if ext == ".py":
                cmd = [sys.executable, "-m", "py_compile", str(path.name)]
                self._append_console(f"$ {' '.join(cmd)}\n")
                completed = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
                self._handle_completed_process(completed)
                if completed.returncode == 0:
                    self._append_console("\nPython byte-compile successful.\n")
            elif ext == ".c":
                if not shutil.which("gcc"):
                    self._append_console("gcc not found. Please install GCC.\n")
                    return
                out = path.with_suffix("")
                cmd = ["gcc", "-O2", "-Wall", "-o", out.name, path.name]
                self._append_console(f"$ {' '.join(cmd)}\n")
                completed = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
                self._handle_completed_process(completed)
                if completed.returncode == 0:
                    self.last_executable = out
            elif ext in {".cpp", ".cc", ".cxx"}:
                if not shutil.which("g++"):
                    self._append_console("g++ not found. Please install G++.\n")
                    return
                out = path.with_suffix("")
                cmd = ["g++", "-std=c++17", "-O2", "-Wall", "-o", out.name, path.name]
                self._append_console(f"$ {' '.join(cmd)}\n")
                completed = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
                self._handle_completed_process(completed)
                if completed.returncode == 0:
                    self.last_executable = out
            elif ext == ".java":
                if not shutil.which("javac"):
                    self._append_console("javac not found. Please install JDK.\n")
                    return
                cmd = ["javac", path.name]
                self._append_console(f"$ {' '.join(cmd)}\n")
                completed = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
                self._handle_completed_process(completed)
                # For Java, the runnable target is class name (basename)
                if completed.returncode == 0:
                    self.last_executable = path.with_suffix(".class")
            else:
                self._append_console(f"Unsupported file type: {ext}\n")
        except Exception as exc:
            self._append_console(f"Error: {exc}\n")

    def _run(self, path: Path) -> None:
        self._clear_console()
        self._append_console(f"Running {self._rel(path)}\n\n")
        ext = path.suffix.lower()
        cwd = str(path.parent)

        try:
            if ext == ".py":
                cmd = [sys.executable, path.name]
                self._append_console(f"$ {' '.join(cmd)}\n")
                completed = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
                self._handle_completed_process(completed)
            elif ext == ".c":
                exe = path.with_suffix("")
                if not exe.exists():
                    self._append_console("Executable not found. Compiling first...\n\n")
                    self._compile(path)
                if exe.exists():
                    cmd = [str(exe)]
                    self._append_console(f"$ {' '.join(cmd)}\n")
                    completed = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
                    self._handle_completed_process(completed)
            elif ext in {".cpp", ".cc", ".cxx"}:
                exe = path.with_suffix("")
                if not exe.exists():
                    self._append_console("Executable not found. Compiling first...\n\n")
                    self._compile(path)
                if exe.exists():
                    cmd = [str(exe)]
                    self._append_console(f"$ {' '.join(cmd)}\n")
                    completed = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
                    self._handle_completed_process(completed)
            elif ext == ".java":
                if not shutil.which("java"):
                    self._append_console("java runtime not found. Please install JDK/JRE.\n")
                    return
                class_name = path.stem
                class_file = path.with_suffix(".class")
                if not class_file.exists():
                    self._append_console("Class not found. Compiling first...\n\n")
                    self._compile(path)
                if class_file.exists():
                    cmd = ["java", "-cp", ".", class_name]
                    self._append_console(f"$ {' '.join(cmd)}\n")
                    completed = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
                    self._handle_completed_process(completed)
            else:
                self._append_console(f"Unsupported file type: {ext}\n")
        except Exception as exc:
            self._append_console(f"Error: {exc}\n")

    # ---------- Async and Console ----------
    def _run_async(self, func, task_name: str) -> None:
        self._set_status(f"{task_name}…")
        self._set_toolbar_state(False)

        def task_wrapper():
            try:
                func()
            finally:
                self.root.after(0, lambda: (self._set_status("Ready"), self._set_toolbar_state(True)))

        threading.Thread(target=task_wrapper, daemon=True).start()

    def _clear_console(self) -> None:
        def do_clear() -> None:
            self.console.configure(state=tk.NORMAL)
            self.console.delete("1.0", tk.END)
            self.console.configure(state=tk.DISABLED)

        self._call_ui(do_clear)

    def _append_console(self, text: str) -> None:
        def do_append() -> None:
            self.console.configure(state=tk.NORMAL)
            self.console.insert(tk.END, text)
            self.console.see(tk.END)
            self.console.configure(state=tk.DISABLED)

        self._call_ui(do_append)

    def _handle_completed_process(self, completed: subprocess.CompletedProcess) -> None:
        if completed.stdout:
            self._append_console(completed.stdout)
        if completed.stderr:
            self._append_console(completed.stderr)
        self._append_console(f"\n[exit code {completed.returncode}]\n")

    def _set_toolbar_state(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for btn in (self.open_btn, self.save_btn, self.compile_btn, self.run_btn):
            btn.configure(state=state)

    def _set_status(self, text: str) -> None:
        self._call_ui(self.status_var.set, text)

    def _rel(self, path: Path) -> str:
        try:
            return os.path.relpath(str(path), str(self.base_dir))
        except Exception:
            return str(path)

    def _call_ui(self, func, *args, **kwargs) -> None:
        """Invoke a callable on the Tk UI thread.

        If called from a background thread, schedule via `after(0)`.
        """
        if threading.current_thread() is threading.main_thread():
            func(*args, **kwargs)
        else:
            self.root.after(0, lambda: func(*args, **kwargs))

    # ---------- App Lifecycle ----------
    def _on_close(self) -> None:
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    app = CompilerIDEApp()
    app.run()


if __name__ == "__main__":
    main()
