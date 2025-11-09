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
from PySide6.QtCore import Qt, QPoint, QRectF, QSize

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
        viewable_area = screen_to_layer.mapRect(self.parent().rect())

        # Determine visible tiles
        tile_list = self.reader.get_visible_tiles(
            viewable_area.topLeft().x(),
            viewable_area.topLeft().y(),
            viewable_area.width(),
            viewable_area.height(),
            level,
        )

        # Preload all tiles to facilitate parallel IO operations
        self.reader.cache_tiles(tile_list)

        # self.log.debug(
        #     "Visible Tiles: (R%d,C%d) (R%d,C%d)  Max: (R%d, C%d)",
        #     top_left.y(),
        #     top_left.x(),
        #     bottom_right.y(),
        #     bottom_right.x(),
        #     max_row,
        #     max_col,
        # )

        for item in tile_list:
            # This should always be pulling from cache
            img = self.reader.get_tile(item["level"], item["col"], item["row"])
            scale_level = self.reader.level_scale(level)

            if img:
                xy_layer = QPoint(
                    int(item["col"] * tile_size / scale_level),
                    int(item["row"] * tile_size / scale_level),
                )
                wh_layer = QPoint(
                    int(img.width() / scale_level),
                    int(img.height() / scale_level),
                )

                painter.drawImage(
                    QRectF(xy_layer, xy_layer + wh_layer),
                    img,
                )

                # self.log.debug(
                #     "Rendering R%d, C%d  (%d,%d), (%d,%d)",
                #     item["row"],
                #     item["col"],
                #     xy_layer.x(),
                #     xy_layer.y(),
                #     wh_layer.x(),
                #     wh_layer.y(),
                # )
            else:
                self.log.warning(
                    "Error loading tile (R%d, C%d)", item["row"], item["col"]
                )

        # Draw test rectangle
        painter.setPen(QPen(Qt.black, 10))
        painter.drawRect(-127, -127, 254, 254)

        self.paint_annotations(painter)
