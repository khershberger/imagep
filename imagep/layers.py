import logging
from math import sqrt

from PySide6.QtWidgets import (
    QWidget,
)
from PySide6.QtGui import (
    QPainter,
    QPen,
    QTransform,
)
from PySide6.QtCore import Qt, QPoint, QRectF, QSize, QTimer

from deepzoom.image import DeepzoomImage


class Layer(QWidget):
    def __init__(
        self,
        source,
        parent: DeepzoomImage = None,
        offset: QPoint = QPoint(0, 0),
        scale: float = 1.0,
        rotation: float = 0.0,
        rotation_center: QPoint = QPoint(0, 0),
    ):
        super().__init__(parent)
        self.log = logging.getLogger("DeepzoomLayer")

        self.offset_layer = offset
        self.scale_layer = scale
        self.rotation = rotation
        self.rotation_center = rotation_center

        self.annotations = []

        # Construct layer_to_canvas transformation
        self.layer_to_canvas = QTransform()
        self.layer_to_canvas.scale(self.scale_layer, self.scale_layer)
        self.layer_to_canvas.translate(self.offset_layer.x(), self.offset_layer.y())
        self.layer_to_canvas.rotate(self.rotation)
        self.layer_to_canvas.translate(
            -self.rotation_center.x(),
            -self.rotation_center.y(),
        )

        if source is not None:
            self.reader = DeepzoomImage(source)
            self.width = self.reader.width
            self.height = self.reader.height

        # Create refresh timer
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.timeout.connect(self.parent().update)

    def get_scale(self):
        return sqrt(abs(self.layer_to_canvas.determinant()))

    def set_annotations(self, new):
        self.annotations = new

    def paint_annotations(self, painter):
        for item in self.annotations:
            self.parent().annotate_point(
                painter,
                QPoint(*item["center"]),
                item["label"],
                shape="rect",
                size=QSize(*item["size"]),
                fontsize=10,
            )


class DeepzoomLayer(Layer):
    def paint_layer(
        self,
        painter: QPainter,
        canvas_to_viewer: QTransform,
    ):
        """
        Paint the deep zoom layer onto the given QPainter.

        Parameters:
        - painter: QPainter object to draw on.
        - scale:  Current scale factor of the viewer.
        - center: QPoint representing the center of the view. (Scaled from 0 to 1))
        """

        # Construct layer_to_screen transformation
        layer_to_screen = self.layer_to_canvas * canvas_to_viewer
        screen_to_layer = layer_to_screen.inverted()[0]

        # Set transformation
        painter.setTransform(layer_to_screen)

        # Determine appropriate level & tiling properties
        level = self.reader.choose_level(sqrt(abs(layer_to_screen.determinant())))
        scale_level = self.reader.level_scale(level)
        max_col, max_row = self.reader.max_tile_index(level)
        tile_size = self.reader.tile_size

        # Store values
        self.current_level = level
        self.current_scale_level = scale_level

        # Determine visible area
        viewer_rect = self.parent().rect()
        viewable_rect = screen_to_layer.mapRect(viewer_rect)

        # Determine visible tiles
        tile_list = self.reader.get_visible_tiles(
            viewable_rect.topLeft().x(),
            viewable_rect.topLeft().y(),
            viewable_rect.width(),
            viewable_rect.height(),
            viewer_rect.width(),
            viewer_rect.height(),
            load_data=True,
        )

        complete = True
        for tile in tile_list:
            # This should always be pulling from cache

            if tile.data:
                xy_layer = QPoint(tile.x0, tile.y0)
                wh_layer = QSize(tile.width, tile.height)

                painter.drawImage(
                    QRectF(xy_layer, wh_layer),
                    tile.data,
                )
            else:
                complete = False
                # self.log.warning("Error loading tile (R%d, C%d)", tile.row, tile.col)

        # Register time to triger additional paint event if not all tiles were loaded
        if not complete:
            self.refresh_timer.start(500)

        # Draw tile rectangle
        painter.setPen(QPen(Qt.black, 10))
        painter.drawRect(-127, -127, 254, 254)

        self.paint_annotations(painter)
