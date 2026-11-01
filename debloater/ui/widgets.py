"""Small reusable Fluent widgets used across the pages."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QSizePolicy,
                               QVBoxLayout, QWidget)

from qfluentwidgets import (BodyLabel, CaptionLabel, FluentIcon, IconWidget)

from . import theme


def font(size: float, weight: QFont.Weight = QFont.Weight.Normal,
         family: str = "Segoe UI", italic: bool = False) -> QFont:
    value = QFont(family)
    value.setPointSizeF(size)
    value.setWeight(weight)
    value.setItalic(italic)
    return value


class Card(QFrame):
    """A rounded surface painted from the palette.

    QFluentWidgets' ``CardWidget`` animates its background through a global
    theme signal, which crashes Qt 6.12 when pages containing cards are hidden
    and shown.  A plain painted frame is both lighter and safe.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._radius = 8
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def setBorderRadius(self, radius: int) -> None:  # noqa: N802 - Qt style API
        self._radius = int(radius)
        self.update()

    def borderRadius(self) -> int:  # noqa: N802
        return self._radius

    def paintEvent(self, event) -> None:  # noqa: N802
        palette = theme.palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(palette.card)
        painter.setPen(QPen(palette.card_border, 1))
        painter.drawRoundedRect(rect, self._radius, self._radius)


class Pill(QLabel):
    """A small rounded tag (safety level, state, counts)."""

    def __init__(self, text: str = "", color: QColor | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setContentsMargins(0, 0, 0, 0)
        self.set_color(color or theme.palette().accent)
        current = self.font()
        current.setPointSizeF(8)
        current.setWeight(QFont.Weight.DemiBold)
        self.setFont(current)

    def set_color(self, color: QColor, bg_alpha: int = 38) -> None:
        self.setStyleSheet(
            f"QLabel {{ {theme.pill_style(color, bg_alpha=bg_alpha)} }}"
        )


class Dot(QWidget):
    def __init__(self, color: QColor, size: int = 9,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._size = size
        self.setFixedSize(size + 6, size + 6)

    def set_color(self, color: QColor) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        glow = QColor(self._color)
        glow.setAlpha(60)
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(0, 0, self.width(), self.height())
        painter.setBrush(self._color)
        offset = (self.width() - self._size) / 2
        painter.drawEllipse(int(offset), int(offset), self._size, self._size)


class StatCard(Card):
    """A compact KPI tile used on the home page."""

    def __init__(self, caption: str, value: str = "0", hint: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(92)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(0)

        self.caption = CaptionLabel(caption)
        self.caption.setTextColor(theme.palette().dim, theme.palette().dim)
        layout.addWidget(self.caption)

        self.value = QLabel(value)
        self.value.setFont(font(21, QFont.Weight.DemiBold))
        self.value.setStyleSheet(f"color: {theme.palette().accent_hex};")
        self._muted = False
        layout.addWidget(self.value)

        self.hint = CaptionLabel(hint)
        self.hint.setTextColor(theme.palette().faint, theme.palette().faint)
        layout.addWidget(self.hint)
        layout.addStretch(1)

    def set_value(self, value: str, hint: str | None = None,
                  muted: bool = False) -> None:
        self.value.setText(str(value))
        self._muted = muted
        if hint is not None:
            self.hint.setText(hint)
        self.apply_palette()

    def apply_palette(self) -> None:
        palette = theme.palette()
        self.caption.setTextColor(palette.dim, palette.dim)
        self.hint.setTextColor(palette.faint, palette.faint)
        color = palette.dim if self._muted else palette.accent
        self.value.setStyleSheet(f"color: {theme.hexa(color)};")


class PageHeader(QWidget):
    """Title + subtitle block at the top of each page."""

    def __init__(self, title: str, subtitle: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.title = QLabel(title)
        self.title.setFont(font(19, QFont.Weight.DemiBold))
        layout.addWidget(self.title)
        self.subtitle = QLabel(subtitle)
        self.subtitle.setFont(font(9.5))
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.subtitle)
        self.apply_palette()

    def set_subtitle(self, text: str) -> None:
        self.subtitle.setText(text)

    def apply_palette(self) -> None:
        palette = theme.palette()
        self.title.setStyleSheet(f"color: {theme.hexa(palette.text)};")
        self.subtitle.setStyleSheet(f"color: {theme.hexa(palette.dim)};")


class EmptyState(QWidget):
    def __init__(self, icon: FluentIcon, title: str, body: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 40, 24, 40)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignCenter)

        self.icon = IconWidget(icon)
        self.icon.setFixedSize(48, 48)
        layout.addWidget(self.icon, 0, Qt.AlignHCenter)

        self.title = QLabel(title)
        self.title.setFont(font(13, QFont.Weight.DemiBold))
        self.title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title)

        self.body = BodyLabel(body)
        self.body.setAlignment(Qt.AlignCenter)
        self.body.setWordWrap(True)
        self.body.setMaximumWidth(420)
        layout.addWidget(self.body, 0, Qt.AlignHCenter)

        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        self.actions.setAlignment(Qt.AlignCenter)
        layout.addLayout(self.actions)
        self.apply_palette()

    def add_action(self, button: QWidget) -> None:
        self.actions.addWidget(button)

    def apply_palette(self) -> None:
        palette = theme.palette()
        self.title.setStyleSheet(f"color: {theme.hexa(palette.text)};")
        self.body.setTextColor(palette.dim, palette.dim)


class CategoryRow(QWidget):
    """A category entry with a right-aligned package count."""

    def __init__(self, name: str, count: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(6)
        self.name_label = BodyLabel(name)
        self.name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.name_label, 1)
        self.count_label = CaptionLabel(str(count))
        layout.addWidget(self.count_label, 0, Qt.AlignRight)
        self.apply_palette()

    def apply_palette(self) -> None:
        palette = theme.palette()
        self.name_label.setTextColor(palette.text, palette.text)
        self.count_label.setTextColor(palette.faint, palette.faint)


class LevelBar(QWidget):
    """A slim stacked bar showing the safety mix of a set of packages."""

    def __init__(self, counts: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._counts = dict(counts)
        self.setMinimumHeight(8)
        self.setMaximumHeight(8)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_counts(self, counts: dict) -> None:
        self._counts = dict(counts)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        palette = theme.palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        total = sum(self._counts.values())
        rect = QRectF(self.rect())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(palette.border)
        painter.drawRoundedRect(rect, 4, 4)
        if total <= 0:
            return
        radius = 4.0
        x = 0.0
        colors = {
            "safe": palette.safe,
            "caution": palette.caution,
            "risky": palette.risky,
        }
        painter.setClipPath(self._rounded_path(rect, radius))
        for key, color in colors.items():
            value = self._counts.get(key, 0)
            if not value:
                continue
            width = rect.width() * value / total
            painter.setBrush(color)
            painter.drawRect(QRectF(x, 0, width, rect.height()))
            x += width
        painter.setClipping(False)

    @staticmethod
    def _rounded_path(rect: QRectF, radius: float):
        from PySide6.QtGui import QPainterPath

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        return path


class HLine(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.HLine)
        self.setFixedHeight(1)
        self.apply_palette()

    def apply_palette(self) -> None:
        palette = theme.palette()
        self.setStyleSheet(
            f"background: {theme.rgba(palette.border)}; border: none;"
        )


class KeyValueRow(QWidget):
    """A label/value line used in detail panels."""

    def __init__(self, key: str, value: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(8)
        self.key = CaptionLabel(key)
        self.key.setMinimumWidth(92)
        self.value = QLabel(value)
        self.value.setFont(font(9))
        self.value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.value.setWordWrap(True)
        layout.addWidget(self.key, 0, Qt.AlignTop)
        layout.addWidget(self.value, 1)
        self.apply_palette()

    def set_value(self, text: str) -> None:
        self.value.setText(text)

    def apply_palette(self) -> None:
        palette = theme.palette()
        self.key.setTextColor(palette.faint, palette.faint)
        self.value.setStyleSheet(f"color: {theme.hexa(palette.text)};")


def labelled_value(value: str, size: float = 9,
                   weight: QFont.Weight = QFont.Weight.Normal) -> QLabel:
    label = QLabel(value)
    label.setFont(font(size, weight))
    return label
