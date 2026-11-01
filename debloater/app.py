"""Application entry point."""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from . import APP_ID, APP_NAME, APP_VERSION, ORG_NAME
from .core.controller import Controller
from .paths import BASE_DIR
from .ui import theme
from .ui.icon import build_icon
from .ui.main_window import MainWindow


def _set_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            f"{ORG_NAME}.{APP_ID}"
        )
    except Exception:
        pass


def _initial_theme_mode() -> tuple[str, bool]:
    settings = QSettings(ORG_NAME, APP_ID)
    mode = str(settings.value("theme", "system") or "system")
    light = theme.system_is_light() if mode == "system" else mode == "light"
    return mode, light


def run() -> int:
    _set_app_user_model_id()
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(ORG_NAME)
    app.setWindowIcon(build_icon(256))
    app.setFont(QFont("Segoe UI", 9))

    _mode, light = _initial_theme_mode()
    theme.apply(light)

    controller = Controller()
    window = MainWindow(controller)
    window.show()
    QTimer.singleShot(0, controller.start)
    return app.exec()


def main() -> int:
    try:
        return run()
    except Exception:
        import traceback

        report = traceback.format_exc()
        traceback.print_exc()
        try:
            (BASE_DIR / "data").mkdir(parents=True, exist_ok=True)
            (BASE_DIR / "data" / "crash.log").write_text(report, encoding="utf-8")
        except OSError:
            pass
        if sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(
                0,
                "The application could not start.\n\n" + report,
                f"{APP_NAME} - startup error",
                0x10,
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
