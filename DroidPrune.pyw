"""DroidPrune - double-click launcher.

A fresh Python installation has no PySide6 or Fluent Widgets, so the launcher
installs the two runtime dependencies with a small Tk progress window before
importing the application.  Everything else lives in the ``droidprune`` package.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_REQUIRED = (
    ("PySide6", "PySide6>=6.6"),
    ("qfluentwidgets", "PySide6-Fluent-Widgets>=1.6"),
)


def _missing_dependencies() -> list[str]:
    missing = []
    for module, package in _REQUIRED:
        try:
            if importlib.util.find_spec(module) is None:
                missing.append(package)
        except Exception:
            missing.append(package)
    return missing


def _install_dependencies(packages: list[str]) -> bool:
    try:
        import threading
        import tkinter as tk
        from tkinter import ttk
    except Exception:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
             "--no-input", *packages],
            text=True,
        )
        return result.returncode == 0

    window = tk.Tk()
    window.title("DroidPrune - installing dependencies")
    window.geometry("580x160")
    window.configure(bg="#141414")
    window.resizable(False, False)
    tk.Label(
        window,
        text="Installing: " + ", ".join(packages),
        bg="#141414", fg="#4cc2ff", font=("Segoe UI", 10, "bold"),
        anchor="w",
    ).pack(fill="x", padx=16, pady=(18, 4))
    state = tk.Label(
        window, text="starting pip…", bg="#141414", fg="#9aa4ae",
        font=("Segoe UI", 8), anchor="w",
    )
    state.pack(fill="x", padx=16)
    bar = ttk.Progressbar(window, mode="indeterminate")
    bar.pack(fill="x", padx=16, pady=16)
    bar.start(55)

    result = {"ok": False}

    def worker() -> None:
        command = [
            sys.executable, "-m", "pip", "install",
            "--disable-pip-version-check", "--no-input", *packages,
        ]
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=1200
            )
            result["ok"] = completed.returncode == 0
        except Exception:
            result["ok"] = False
        window.after(0, window.destroy)

    threading.Thread(target=worker, daemon=True).start()
    window.mainloop()
    return result["ok"]


def _fatal(message: str) -> None:
    try:
        data = ROOT / "data"
        data.mkdir(parents=True, exist_ok=True)
        (data / "crash.log").write_text(message, encoding="utf-8")
    except OSError:
        pass
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                0, message, "DroidPrune", 0x10
            )
        except Exception:
            pass
    else:
        print(message, file=sys.stderr)


def main() -> int:
    missing = _missing_dependencies()
    if missing:
        if not _install_dependencies(missing):
            _fatal(
                "Could not install the required libraries:\n  "
                + "\n  ".join(missing)
                + "\n\nInstall them manually with:\n"
                + f'"{sys.executable}" -m pip install ' + " ".join(missing)
            )
            return 1
        importlib.invalidate_caches()

    try:
        from droidprune.app import main as run
    except Exception:
        _fatal("The application could not be imported:\n\n" + traceback.format_exc())
        return 1

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
