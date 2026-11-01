"""The Fluent window: navigation, page wiring and live theme changes."""

from __future__ import annotations

import os

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QLabel

from qfluentwidgets import (FluentIcon, FluentWindow, NavigationItemPosition)

from .. import APP_NAME, APP_VERSION, REPO_URL
from ..core.controller import Controller
from . import dialogs, theme
from .icon import build_icon
from .pages.activity import ActivityPage
from .pages.home import HomePage
from .pages.packages import PackagesPage
from .pages.profiles import ProfilesPage
from .pages.settings import SettingsPage


class MainWindow(FluentWindow):
    def __init__(self, controller: Controller) -> None:
        super().__init__()
        self.controller = controller
        self._mica_allowed = os.environ.get(
            "UAD_DISABLE_MICA", ""
        ).strip().lower() not in {"1", "true", "yes", "on"}
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(build_icon(256))
        self.resize(1300, 880)
        self.setMinimumSize(1120, 720)
        try:
            theme_matches_windows = theme.palette().light == theme.system_is_light()
            if self._mica_allowed and theme_matches_windows:
                self.setMicaEffectEnabled(True)
            else:
                # FluentWidget enables Mica in its own constructor. A Mica
                # backdrop follows the Windows theme, so it is only usable when
                # the app theme matches it.
                self.setMicaEffectEnabled(False)
        except Exception:
            self._mica_allowed = False
        try:
            self.navigationInterface.setCollapsible(False)
            if os.environ.get("UAD_NO_EXPAND", "").lower() not in {"1", "true"}:
                self.navigationInterface.setExpandWidth(232)
            self.titleBar.setDoubleClickEnabled(True)
        except Exception:
            pass
        try:
            self.stackedWidget.setAnimationEnabled(False)
        except Exception:
            pass

        self.home = HomePage(controller)
        self.packages = PackagesPage(controller)
        self.profiles = ProfilesPage(controller)
        self.activity = ActivityPage(controller)
        self.settings = SettingsPage(controller)

        self.addSubInterface(self.home, FluentIcon.HOME, "Home")
        self.addSubInterface(self.packages, FluentIcon.APPLICATION, "Packages")
        self.addSubInterface(self.profiles, FluentIcon.FOLDER, "Profiles")
        self.addSubInterface(self.activity, FluentIcon.HISTORY, "Activity")
        self.addSubInterface(
            self.settings, FluentIcon.SETTING, "Settings",
            NavigationItemPosition.BOTTOM,
        )
        self._pages = {
            "home": self.home,
            "packages": self.packages,
            "profiles": self.profiles,
            "activity": self.activity,
            "settings": self.settings,
        }

        self.home.navigate.connect(self.switch_to)
        self.settings.themeChanged.connect(self._on_theme_mode)

        self._add_version_label()
        controller.notice.connect(self._notice)

        geometry = controller.restore_geometry()
        if geometry is not None:
            try:
                self.restoreGeometry(geometry)
            except Exception:
                pass

    # ------------------------------------------------------------- chrome
    def _add_version_label(self) -> None:
        try:
            label = QLabel()
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setOpenExternalLinks(True)
            label.setTextInteractionFlags(
                Qt.TextInteractionFlag.LinksAccessibleByMouse
                | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
            )
            label.setCursor(Qt.CursorShape.PointingHandCursor)
            label.setContentsMargins(0, 0, 12, 0)
            label.setToolTip(f"Open {APP_NAME} on GitHub")
            bar = self.titleBar.hBoxLayout
            bar.insertWidget(max(0, bar.count() - 1), label)
            self._version_label = label
            self._style_version_label()
        except Exception:
            self._version_label = None

    def _style_version_label(self) -> None:
        if getattr(self, "_version_label", None) is None:
            return
        color = theme.palette().accent_hex
        self._version_label.setText(
            f'<a href="{REPO_URL}" style="color:{color};'
            f'text-decoration:none;">v{APP_VERSION}</a>'
        )
        self._version_label.setStyleSheet("font: 600 8pt 'Segoe UI';")

    def switch_to(self, name: str) -> None:
        page = self._pages.get(name)
        if page is not None:
            self.switchTo(page)

    # -------------------------------------------------------------- theme
    def _on_theme_mode(self, mode: str) -> None:
        self.apply_theme_mode(mode)

    def apply_theme_mode(self, mode: str) -> None:
        light = theme.system_is_light() if mode == "system" else mode == "light"
        theme.apply(light)
        try:
            self.setMicaEffectEnabled(
                self._mica_allowed and light == theme.system_is_light()
            )
        except Exception:
            pass
        self._refresh_palette()
        self.update()

    def _refresh_palette(self) -> None:
        for page in self._pages.values():
            method = getattr(page, "apply_palette", None)
            if method is not None:
                try:
                    method()
                except Exception:
                    pass
        if getattr(self, "_version_label", None) is not None:
            self._style_version_label()
        self.setWindowIcon(build_icon(256))

    # ------------------------------------------------------------ notices
    def _notice(self, kind: str, message: str) -> None:
        title = {
            "info": "Done",
            "success": "Done",
            "warning": "Heads up",
            "error": "Error",
        }.get(kind, "Notice")
        dialogs.notify(self, kind, title, message)

    # --------------------------------------------------------------- misc
    def nativeEvent(self, event_type, message):  # noqa: N802
        try:
            import ctypes.wintypes

            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == 0x001A:  # WM_SETTINGCHANGE
                QTimer.singleShot(350, self._system_theme_changed)
        except Exception:
            pass
        return super().nativeEvent(event_type, message)

    def _system_theme_changed(self) -> None:
        mode = str(self.controller.setting("theme", "system"))
        if mode == "system":
            self.apply_theme_mode("system")

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.controller.running:
            if not dialogs.confirm(
                self,
                "A run is still in progress",
                "Quit anyway? The command that is currently being sent will "
                "finish, the remaining packages will not be processed.",
                yes_text="Quit",
            ):
                event.ignore()
                return
        try:
            self.controller.save_geometry(self.saveGeometry())
            self.controller.shutdown()
        finally:
            super().closeEvent(event)
