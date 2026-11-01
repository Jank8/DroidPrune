"""Windows theme integration: dark/light mode, accent colour and palette."""

from __future__ import annotations

import os
from dataclasses import dataclass

from PySide6.QtGui import QColor
from qfluentwidgets import Theme, setTheme, setThemeColor

from ..core.models import Action, Level, State

FALLBACK_ACCENT = "#4cc2ff"


def system_is_light() -> bool:
    """True when Windows uses the light app theme (env var overrides it)."""
    forced = os.environ.get("UAD_THEME", "").strip().lower()
    if forced in ("light", "dark"):
        return forced == "light"
    if os.name != "nt":
        return False
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            return bool(winreg.QueryValueEx(key, "AppsUseLightTheme")[0])
    except OSError:
        return False


def system_accent_hex() -> str:
    """The active Windows accent colour (DWM stores it as 0xAABBGGRR)."""
    if os.name != "nt":
        return FALLBACK_ACCENT
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM"
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AccentColor")
        red, green, blue = value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF
        if (red, green, blue) == (0, 0, 0):
            raise ValueError("black accent")
        return f"#{red:02x}{green:02x}{blue:02x}"
    except (OSError, ValueError, TypeError):
        return FALLBACK_ACCENT


def _c(value: str | QColor, alpha: int = 255) -> QColor:
    color = QColor(value) if isinstance(value, str) else QColor(value)
    color.setAlpha(alpha)
    return color


def hexa(color: QColor) -> str:
    return f"#{color.red():02x}{color.green():02x}{color.blue():02x}"


def rgba(color: QColor, alpha: int | None = None) -> str:
    alpha = color.alpha() if alpha is None else alpha
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha})"


@dataclass(frozen=True)
class Palette:
    light: bool
    accent: QColor
    accent_hex: str
    text: QColor
    dim: QColor
    faint: QColor
    border: QColor
    row_hover: QColor
    row_selected: QColor
    card: QColor
    card_border: QColor
    safe: QColor
    caution: QColor
    risky: QColor
    active: QColor
    absent: QColor


def _build(light: bool, accent_hex: str) -> Palette:
    accent = QColor(accent_hex)
    if not accent.isValid():
        accent = QColor(FALLBACK_ACCENT)
    if light:
        return Palette(
            light=True,
            accent=accent,
            accent_hex=hexa(accent),
            text=QColor("#1a1c1f"),
            dim=QColor("#5b6169"),
            faint=QColor("#858c95"),
            border=QColor(0, 0, 0, 22),
            row_hover=QColor(0, 0, 0, 10),
            row_selected=_c(accent, 20),
            card=QColor(255, 255, 255, 232),
            card_border=QColor(0, 0, 0, 16),
            safe=QColor("#0f8a52"),
            caution=QColor("#a86400"),
            risky=QColor("#c02b2b"),
            active=QColor("#5f6b78"),
            absent=QColor("#9aa0a8"),
        )
    return Palette(
        light=False,
        accent=accent,
        accent_hex=hexa(accent),
        text=QColor("#f2f5f9"),
        dim=QColor("#9ba5b1"),
        faint=QColor("#77828f"),
        border=QColor(255, 255, 255, 26),
        row_hover=QColor(255, 255, 255, 12),
        row_selected=_c(accent, 18),
        card=QColor(255, 255, 255, 14),
        card_border=QColor(255, 255, 255, 24),
        safe=QColor("#3ddc97"),
        caution=QColor("#f0b13d"),
        risky=QColor("#ff6b6b"),
        active=QColor("#8c98a6"),
        absent=QColor("#6b7682"),
    )


PALETTE = _build(system_is_light(), system_accent_hex())


def palette() -> Palette:
    return PALETTE


def refresh(light: bool | None = None, accent_hex: str | None = None) -> Palette:
    global PALETTE
    PALETTE = _build(
        system_is_light() if light is None else light,
        accent_hex or system_accent_hex(),
    )
    return PALETTE


def apply(light: bool | None = None) -> Palette:
    """Apply the Fluent theme + accent and refresh the palette."""
    global PALETTE
    light = system_is_light() if light is None else bool(light)
    PALETTE = _build(light, system_accent_hex())
    setTheme(Theme.LIGHT if light else Theme.DARK)
    setThemeColor(PALETTE.accent)
    return PALETTE


def level_color(level: Level) -> QColor:
    return {
        Level.SAFE: PALETTE.safe,
        Level.CAUTION: PALETTE.caution,
        Level.RISKY: PALETTE.risky,
    }[level]


def action_color(action: Action) -> QColor:
    if action is Action.UNINSTALL:
        return QColor("#b45309") if PALETTE.light else QColor("#ff9f43")
    return PALETTE.accent


def state_color(state: State) -> QColor:
    if state is State.DISABLED:
        return PALETTE.caution
    if state is State.UNINSTALLED:
        return PALETTE.risky
    if state is State.ABSENT:
        return PALETTE.absent
    if state is State.ACTIVE:
        return PALETTE.active
    return PALETTE.faint


def pill_style(color: QColor, *, bg_alpha: int = 38, border: bool = False) -> str:
    border_css = f"1px solid {rgba(color, 90)}" if border else "none"
    return (
        f"color: {hexa(color)};"
        f"background: {rgba(color, bg_alpha)};"
        f"border: {border_css};"
        "border-radius: 9px;"
        "padding: 1px 8px;"
    )
