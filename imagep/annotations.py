from typing import Self

from PySide6.QtCore import Qt, QObject, QPoint, QRect, QSize, Signal
from PySide6.QtWidgets import QDockWidget
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
)


class Annotation:
    def __init__(
        self,
        parent: QObject = None,
        label: str = "",
        color: QColor = Qt.blue,
        line_width: int = 2,
        fontsize: int = 10,
        justification: str = "center_center",
        position: QPoint = QPoint(0, 0),
    ):
        self._parent = parent

        self.color = color
        self.line_width = line_width
        self.font_size = fontsize
        self.label = label
        self.justification = justification
        self.position = position
        self.bounding_box = None

        self._selected = False

    def parent(self) -> QObject:
        return self._parent

    def getPainter(self) -> QPainter:
        painter = None
        try:
            painter = self.parent().getPainter()
        except TypeError:
            print("BLEH")
        return painter

    def set_selection_status(self, selected: bool) -> None:
        self._selected = selected

    def to_dict(self):
        return {
            "type": self.__class__.__name__,
            "label": self.label,
            "color": self.color.name()
            if hasattr(self.color, "name")
            else str(self.color),
            "line_width": self.line_width,
            "font_size": self.font_size,
            "justification": self.justification,
            "position": (self.position.x(), self.position.y())
            if hasattr(self.position, "x")
            else self.position,
        }

    def paintEvent(
        self,
        event,
    ):
        painter = self.getPainter()
        painter.setPen(QPen(self.color, self.line_width))  # Red pen, 2px wide
        painter.setFont(QFont("Arial", self.font_size, QFont.Bold))
        painter.drawEllipse(
            self.position.x() - 1,
            self.position.y() - 1,
            2,
            2,
        )
        font_metrics = QFontMetrics(painter.font())
        label_size = font_metrics.size(0, self.label)
        position = QPoint(
            self.position.x() - label_size.width() / 2,
            self.position.y() - label_size.height() / 2,
        )
        self.bounding_box = QRect(position, label_size)
        painter.drawText(
            self.bounding_box,
            Qt.AlignTop | Qt.AlignLeft,
            self.label,
        )

        if self._selected:
            self.draw_selection_box(painter)

    def draw_selection_box(self, painter):
        # Highlight currently selected annotation with a dashed rectangle
        painter.save()
        painter.setPen(QPen(Qt.yellow, 1, Qt.DashLine))
        painter.drawRect(self.bounding_box)
        painter.restore()


class AnnotationCircle(Annotation):
    def __init__(
        self,
        radius: int = 2,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.radius = radius

    def to_dict(self):
        d = super().to_dict()
        d.update(
            {
                "radius": self.radius,
            }
        )
        return d

    def paintEvent(self, event):
        painter = self.getPainter()
        painter.setPen(QPen(self.color, self.line_width))  # Red pen, 2px wide
        painter.drawEllipse(
            self.position.x() - self.radius,
            self.position.y() - self.radius,
            2 * self.radius,
            2 * self.radius,
        )
        return super().paintEvent(event)


class AnnotationRect(Annotation):
    def __init__(
        self,
        size: QSize = QSize(10, 10),
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.size = size

    def to_dict(self):
        d = super().to_dict()
        d.update(
            {
                "size": (self.size.width(), self.size.height())
                if hasattr(self.size, "width")
                else self.size,
            }
        )
        return d

    def paintEvent(self, event):
        painter = self.getPainter()
        painter.setPen(QPen(self.color, self.line_width))  # Red pen, 2px wide
        painter.drawRect(QRect(self.position, self.size))
        return super().paintEvent(event)


class AnnotationLine(Annotation):
    def __init__(
        self,
        position2: QPoint = QPoint(10, 10),
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.position2 = position2

    def to_dict(self):
        d = super().to_dict()
        d.update(
            {
                "position2": (self.position2.x(), self.position2.y())
                if hasattr(self.position2, "x")
                else self.position2,
            }
        )
        return d

    def paintEvent(self, event):
        painter = self.getPainter()
        painter.drawRect(QRect(self.position, self.size))
        return super().paintEvent(event)


class AnnotationDockWidget(QDockWidget):
    """Dock widget providing UI for creating text annotations.

    Integrated into annotations module for simplified imports.
    """

    def sync_to_annotation(self, annotation):
        """Update dock controls to reflect selected annotation properties."""
        self.text_input.setText(annotation.label)
        self._color = annotation.color
        self.fontsize_input.setText(str(annotation.font_size))
        self.settingsChanged.emit()

    addAnnotation = Signal(
        str, QColor, int, object
    )  # text, color, fontSize, targetLayerName/None
    settingsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__("Annotations", parent)
        self._color = QColor(Qt.blue)
        self._build_ui()

    def _build_ui(self):
        from PySide6.QtWidgets import (
            QWidget,
            QVBoxLayout,
            QLabel,
            QLineEdit,
            QPushButton,
            QComboBox,
        )

        container = QWidget(self)
        layout = QVBoxLayout(container)

        layout.addWidget(QLabel("Type:"))
        self.type_label = QLabel("Text")
        layout.addWidget(self.type_label)

        layout.addWidget(QLabel("Text:"))
        self.text_input = QLineEdit()
        self.text_input.textChanged.connect(lambda _: self.settingsChanged.emit())
        layout.addWidget(self.text_input)

        layout.addWidget(QLabel("Color:"))
        self.color_btn = QPushButton("Pick Color")
        self.color_btn.clicked.connect(self._on_pick_color)
        layout.addWidget(self.color_btn)

        layout.addWidget(QLabel("Font Size:"))
        self.fontsize_input = QLineEdit()
        self.fontsize_input.setText("18")
        self.fontsize_input.setPlaceholderText("Enter font size (number)")
        self.fontsize_input.textChanged.connect(self._on_fontsize_changed)
        layout.addWidget(self.fontsize_input)

        layout.addWidget(QLabel("Layer:"))
        self.layer_combo = QComboBox()
        self.layer_combo.addItem("Current Layer", userData=None)
        layout.addWidget(self.layer_combo)

        self.add_btn = QPushButton("Add Annotation")
        self.add_btn.clicked.connect(self._emit_add)
        layout.addWidget(self.add_btn)

        layout.addStretch(1)
        container.setLayout(layout)
        self.setWidget(container)

    def _on_fontsize_changed(self, text):
        # Only emit settingsChanged if text is a valid integer
        try:
            value = int(float(text))
            if value > 0:
                self.settingsChanged.emit()
        except Exception:
            pass

    # Properties
    @property
    def color(self):
        return self._color

    @property
    def font_size(self):
        text = self.fontsize_input.text()
        try:
            value = int(float(text))
            if value > 0:
                return value
        except Exception:
            pass
        return 18  # default fallback

    @property
    def text(self):
        return self.text_input.text()

    def selected_layer_name(self):
        idx = self.layer_combo.currentIndex()
        if idx < 0:
            return None
        return self.layer_combo.currentData()

    # Slots
    def _on_pick_color(self):
        from PySide6.QtWidgets import QColorDialog

        color = QColorDialog.getColor(self._color, self)
        if color.isValid():
            self._color = color
            self.settingsChanged.emit()

    def _emit_add(self):
        self.addAnnotation.emit(
            self.text,
            self.color,
            self.font_size,
            self.selected_layer_name(),
        )

    # External API
    def refresh_layer_list(self, layer_names: list[str]):
        current = self.selected_layer_name()
        self.layer_combo.clear()
        self.layer_combo.addItem("Current Layer", userData=None)
        for name in layer_names:
            self.layer_combo.addItem(name, userData=name)
        if current is not None:
            idx = self.layer_combo.findData(current)
            if idx >= 0:
                self.layer_combo.setCurrentIndex(idx)
