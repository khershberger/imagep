import logging
import tomllib
from math import sqrt, remainder

from PySide6.QtWidgets import (
    QLabel,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QMouseEvent,
    QWheelEvent,
    QPainter,
    QPen,
    QTransform,
)
from PySide6.QtCore import Qt, QPoint, QRect, QSize

from layers import DeepzoomLayer


class LayeredViewer(QWidget):
    def __init__(self, source=None, config=None, parent=None):
        super().__init__(parent)
        self.log = logging.getLogger("DeepzoomViewer")
        self.dragging = False
        self.last_mouse_pos = QPoint(0, 0)
        self.status_bar = QStatusBar(self)
        self.status_label = QLabel()
        self.status_bar.addWidget(self.status_label)
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        layout.addWidget(self.status_bar)
        self.setLayout(layout)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.WheelFocus)

        self.canvas_to_viewer = QTransform()

        # Create layers
        if config is not None:
            with open(config, "rb") as fin:
                config_dict = tomllib.load(fin)
            self.layers = []
            for key, value in config_dict["layers"].items():
                new = DeepzoomLayer(
                    value["source"],
                    self,
                    scale=value["scale"],
                    offset=QPoint(*value["offset"]),
                    rotation=value["rotation"],
                    rotation_center=QPoint(*value["origin"]),
                )
                new.set_annotations(value.get("annotations", []))
                self.layers.append(new)

        elif source is not None:
            self.layers = [
                DeepzoomLayer(
                    source,
                    self,
                    scale=1.0,
                    offset=QPoint(-0, -0),
                    rotation=0.0,
                    rotation_center=QPoint(0, 0),
                ),
                # DeepzoomLayer(
                #     source,
                #     self,
                #     scale=2.0,
                #     offset=QPoint(-127, -127),
                #     rotation=5.0,
                #     rotation_center=QPoint(127, 127),
                # ),
                # DeepzoomLayer(
                #     source,
                #     self,
                #     scale=0.5,
                #     offset=QPoint(254, 254),
                #     rotation=-5.0,
                #     rotation_center=QPoint(127, 127),
                # ),
            ]
        else:
            raise Exception(
                "No valid configuration information provided to DeepzoomViewer"
            )

    def paintEvent(self, event):
        painter = QPainter(self)
        for layer in self.layers:
            painter.save()
            layer.paint_layer(painter, self.canvas_to_viewer)
            painter.restore()

        painter.setPen(QPen(Qt.red, 1))

        # Draw Grid
        self.draw_grid(painter, 127)

        # Draw blue dot at viewer origin
        painter.setPen(QPen(Qt.blue, 10))
        self.annotate_point(
            painter,
            self.canvas_to_viewer.map(QPoint(0, 0)),
            "(0,0)",
            radius=4,
            fontsize=14,
        )

        # Draw point at viewer (127, 127)
        self.annotate_point(
            painter,
            self.canvas_to_viewer.map(QPoint(127, 127)),
            "(127, 127)",
            radius=4,
            fontsize=14,
        )

        painter.end()

    def draw_grid(self, painter, grid_size, min_pixels=32):
        # These are scaled to screen pixels
        step_size = grid_size * self.get_scale()

        # Adjust step_size if grid squares go below min_pixels
        tmp = int(min_pixels / step_size) + 1
        step_size *= tmp
        grid_size *= tmp

        def signed_modulo(n, d):
            return n - (d * int(n / d))

        def calc_grid_offset(offset_viewer, step_size):
            tmp = remainder(offset_viewer, step_size)
            if tmp > 0.0:
                tmp -= step_size
            return tmp

        offset_viewer = -self.canvas_to_viewer.map(QPoint(0, 0))

        offset_x = calc_grid_offset(offset_viewer.x(), step_size)
        offset_y = calc_grid_offset(offset_viewer.y(), step_size)

        for k in range(0, int(self.rect().width() / step_size)):
            x = round(k * step_size - offset_x)
            painter.drawLine(x, 0, x, self.rect().height())

        for k in range(0, int(self.rect().height() / step_size)):
            y = round(k * step_size - offset_y)
            painter.drawLine(0, y, self.rect().width(), y)

    def annotate_point(
        self,
        painter: QPainter,
        pos,
        label,
        color: QColor = Qt.blue,
        shape="circle",
        radius=2,
        size=QSize(10, 10),
        line_width=2,
        fontsize=10,
    ):
        painter.setPen(QPen(color, line_width))  # Red pen, 2px wide
        # painter.setBrush(QColor(255, 0, 0, 100))  # Semi-transparent red brush

        if shape == "circle":
            painter.drawEllipse(
                pos.x() - radius,
                pos.y() - radius,
                2 * radius,
                2 * radius,
            )
        elif shape == "rect":
            painter.drawRect(QRect(pos, size))

        # Add label text
        painter.setPen(color)  # Blue pen
        painter.setFont(QFont("Arial", fontsize, QFont.Bold))
        painter.drawText(
            QRect(pos, QSize(self.width(), self.height())),
            Qt.AlignTop | Qt.AlignLeft,
            label,
        )

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        factor = 1.25 if delta > 0 else 0.8

        # Update transform
        scaling = QTransform()
        scaling.translate(event.position().x(), event.position().y())
        scaling.scale(factor, factor)
        scaling.translate(-event.position().x(), -event.position().y())
        self.canvas_to_viewer = self.canvas_to_viewer * scaling

        self.update()
        self.parent().parent().update_status_window(event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.last_mouse_pos = event.pos()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.dragging:
            delta = event.pos() - self.last_mouse_pos
            self.canvas_to_viewer *= QTransform().translate(delta.x(), delta.y())
            self.last_mouse_pos = event.pos()
            self.update()
        self._update_status(event.pos())

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.dragging = False

    def resizeEvent(self, event):
        self.update()

    def _create_transform(self):
        canvas_to_viewer = QTransform()
        canvas_to_viewer.scale(self.scale_canvas, self.scale_canvas)
        canvas_to_viewer.translate(-self.offset_canvas.x(), -self.offset_canvas.y())
        return canvas_to_viewer

    def get_scale(self):
        return sqrt(abs(self.canvas_to_viewer.determinant()))

    def _update_status(self, pos):
        # # On-screen coordinates
        # x, y = pos.x(), pos.y()
        # # Full image pixel coordinates
        # level = self.layer._choose_level()
        # scale = self.layer._level_scale(level)
        # (img_x, img_y) = self.layer.pow_to_img(pos)
        # # img_x = int((x + self.layer.offset_canvas.x()) / (self.scale_canvas * scale))
        # # img_y = int((y + self.layer.offset_canvas.y()) / (self.scale_canvas * scale))
        # self.status_label.setText(
        #     f"Screen: ({x},{y}) | Image: ({img_x},{img_y}) | Scale: {self.scale:.2f} | Level: {level}"
        # )
        self.status_label.setText("I do not work right now...")
