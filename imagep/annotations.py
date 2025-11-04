from typing import Self

from PySide6.QtCore import Qt, QRect, QSize
from PySide6.QtGui import (
    QColor,
    QFont,
    QPen,
)


class Annotation:
    @classmethod
    def from_dict(cls, properties: dict) -> Self:
        return cls(None)

    def __init__(
        self,
        parent,
        pos,
        label,
        color: QColor = Qt.blue,
        shape="circle",
        radius=2,
        size=QSize(10, 10),
        line_width=2,
        fontsize=10,
    ):
        self._parent = parent

    def parent(self):
        return self._parent

    def _paint_point(self):
        self.painter.setPen(QPen(self.color, self.line_width))  # Red pen, 2px wide
        # painter.setBrush(QColor(255, 0, 0, 100))  # Semi-transparent red brush

    def _paint_circle(self):
        self.painter.setPen(QPen(self.color, self.line_width))  # Red pen, 2px wide
        self.painter.drawEllipse(
            self.pos.x() - self.radius,
            self.pos.y() - self.radius,
            2 * self.radius,
            2 * self.radius,
        )

    def _paint_rectangle(self):
        self.painter.drawRect(QRect(self.pos, self.size))

    def _paint_label(self):
        # Add label text
        self.painter.setPen(self.color)  # Blue pen
        self.painter.setFont(QFont("Arial", self.font_size, QFont.Bold))
        self.painter.drawText(
            QRect(self.pos, QSize(self.width(), self.height())),
            Qt.AlignTop | Qt.AlignLeft,
            self.label,
        )
