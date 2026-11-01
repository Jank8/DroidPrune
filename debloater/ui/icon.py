"""Application icon drawn entirely in code - no image assets needed."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QIcon, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QRadialGradient)


def _draw_glyph(painter: QPainter, px: float) -> None:
    """Android head with a removal badge, scaled to ``px`` pixels."""
    u = px / 256.0

    # Soft glow behind the head.
    glow = QRadialGradient(QPointF(px * 0.50, px * 0.44), px * 0.42)
    glow.setColorAt(0.0, QColor(76, 194, 255, 95))
    glow.setColorAt(1.0, QColor(76, 194, 255, 0))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(glow))
    painter.drawEllipse(QPointF(px * 0.50, px * 0.44), px * 0.42, px * 0.42)

    # Head: a smooth dome.
    left, right = px * 0.255, px * 0.745
    base = px * 0.720
    top = px * 0.375
    head = QPainterPath()
    head.moveTo(left, base)
    head.cubicTo(left, top, right, top, right, base)
    head.closeSubpath()

    head_gradient = QLinearGradient(0, top, 0, base)
    head_gradient.setColorAt(0.0, QColor("#f4f9ff"))
    head_gradient.setColorAt(1.0, QColor("#b7d6ff"))
    painter.setBrush(QBrush(head_gradient))
    painter.setPen(Qt.NoPen)
    painter.drawPath(head)

    # Antennae.
    pen = QPen(QColor("#dcebff"))
    pen.setWidthF(max(1.4, px * 0.020))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.drawLine(
        QPointF(px * 0.385, px * 0.445), QPointF(px * 0.318, px * 0.300)
    )
    painter.drawLine(
        QPointF(px * 0.615, px * 0.445), QPointF(px * 0.682, px * 0.300)
    )

    # Eyes.
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#101b33"))
    eye_r = px * 0.030
    painter.drawEllipse(QPointF(px * 0.415, px * 0.575), eye_r, eye_r)
    painter.drawEllipse(QPointF(px * 0.585, px * 0.575), eye_r, eye_r)

    # Removal badge in the lower-right corner.
    badge = QPointF(px * 0.765, px * 0.775)
    radius = px * 0.150
    painter.setBrush(QColor("#0d1730"))
    painter.drawEllipse(badge, radius * 1.16, radius * 1.16)

    badge_gradient = QLinearGradient(
        badge.x() - radius, badge.y() - radius, badge.x() + radius, badge.y() + radius
    )
    badge_gradient.setColorAt(0.0, QColor("#5fd0ff"))
    badge_gradient.setColorAt(1.0, QColor("#2f8bff"))
    painter.setBrush(QBrush(badge_gradient))
    painter.drawEllipse(badge, radius, radius)

    pen = QPen(QColor("#061226"))
    pen.setWidthF(max(1.6, px * 0.026))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    half = radius * 0.46
    painter.drawLine(
        QPointF(badge.x() - half, badge.y()), QPointF(badge.x() + half, badge.y())
    )


def build_icon(size: int = 256) -> QIcon:
    icon = QIcon()
    for px in (16, 20, 24, 32, 40, 48, 64, 96, 128, 256):
        if px > size * 2:
            continue
        pixmap = QPixmap(px, px)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)

        u = px / 256.0
        background = QLinearGradient(0, 0, 0, px)
        background.setColorAt(0.0, QColor("#0a1224"))
        background.setColorAt(0.55, QColor("#101d3d"))
        background.setColorAt(1.0, QColor("#17264f"))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(background))
        painter.drawRoundedRect(QRectF(1, 1, px - 2, px - 2), 56 * u, 56 * u)

        # Faint grid for a technical feel.
        grid_pen = QPen(QColor(255, 255, 255, 14))
        grid_pen.setWidthF(max(0.5, px * 0.0035))
        painter.setPen(grid_pen)
        for index in range(1, 6):
            x = px * index / 6.0
            painter.drawLine(QPointF(x, px * 0.08), QPointF(x, px * 0.92))
        for index in range(1, 4):
            y = px * index / 4.0
            painter.drawLine(QPointF(px * 0.08, y), QPointF(px * 0.92, y))

        _draw_glyph(painter, px)

        # Thin inner highlight.
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 26), max(0.6, px * 0.004)))
        painter.drawRoundedRect(
            QRectF(1.5, 1.5, px - 3, px - 3), 55 * u, 55 * u
        )

        painter.end()
        icon.addPixmap(pixmap)
    return icon
