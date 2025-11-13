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
from PySide6.QtCore import Qt, QPoint, QRectF

from deepzoom.image import DeepzoomImage
from PySide6.QtGui import QImage


class Layer(QWidget):
    """Generic image layer which can represent either a DeepZoom source or a raw raster image.

    For JPEG (or other raster inputs) we store a QImage in `self.image` and paint it directly.
    For DeepZoom sources we create a `DeepzoomImage` image and delegate tiling logic in a subclass.
    """

    def __init__(
        self,
        source: str | None,
        parent: QWidget = None,
        name: str = "New Layer",
        offset: QPoint = QPoint(0, 0),
        scale: float | None = None,
        rotation: float = 0.0,
        mirror: bool = False,
        rotation_center: QPoint = QPoint(0, 0),
        pixels_per_meter: float | None = None,
    ) -> None:
        super().__init__(parent)
        self.log = logging.getLogger("Layer")

        self.setObjectName(name)
        self.source = source
        self.offset_layer = offset
        self.scale_layer = scale or 1.0
        self.rotation = rotation
        self.mirror = mirror
        self.rotation_center = rotation_center
        self.pixels_per_meter = pixels_per_meter

        self.annotations: list = []

        self.layer_to_canvas = self.compute_transform()

        self.image = None

        if source and source != "None":
            lower = source.lower()
            if lower.endswith(".dzi"):
                # DeepZoom tiled source
                self.image = DeepzoomImage(source)
                self.width = self.image.width
                self.height = self.image.height
            else:
                # Assume raster image (e.g., .jpg/.jpeg/.png)
                self.image = QImage(source)
                if self.image.isNull():
                    self.log.warning("Failed to load raster image: %s", source)
                    self.width = 0
                    self.height = 0
                else:
                    self.width = self.image.width()
                    self.height = self.image.height()
        else:
            self.width = 0
            self.height = 0

    def getPainter(self) -> QPainter:
        return self.parent().getPainter()

    def get_scale(self):
        return sqrt(abs(self.layer_to_canvas.determinant()))

    def compute_transform(self):
        # Transformation from layer space to canvas space
        layer_to_canvas = QTransform()
        if self.mirror:
            layer_to_canvas.scale(-1, 1)
        layer_to_canvas.scale(self.scale_layer, self.scale_layer)
        layer_to_canvas.translate(self.offset_layer.x(), self.offset_layer.y())
        layer_to_canvas.rotate(self.rotation)
        layer_to_canvas.translate(
            -self.rotation_center.x(),
            -self.rotation_center.y(),
        )
        return layer_to_canvas

    # --- Dynamic transform mutation helpers ---------------------------------
    def update_transform(self) -> None:
        """Recompute the layer_to_canvas transform after mutating properties."""
        self.layer_to_canvas = self.compute_transform()

    def scale(self, factor: float) -> None:
        """Apply a multiplicative scale change to the layer.

        Parameters
        ----------
        factor : float
            Multiplicative factor (>0). Values >1 zoom in; between 0 and 1 zoom out.
        """
        if factor <= 0:
            return
        self.scale_layer *= factor
        self.update_transform()

    def translate(self, dx: float, dy: float) -> None:
        """Translate the layer in canvas space by (dx, dy) pixels."""
        self.offset_layer += QPoint(int(dx), int(dy))
        self.update_transform()

    def rotate(self, delta_degrees: float) -> None:
        """Apply a relative rotation to the layer and rebuild transform."""
        self.rotation = (self.rotation + delta_degrees) % 360.0
        self.update_transform()


class DeepzoomLayer(Layer):
    def paint_layer(
        self,
        canvas_to_viewer: QTransform,
    ):
        """
        Paint the deep zoom layer onto the given QPainter.

        Parameters:
        - painter: QPainter object to draw on.
        - scale:  Current scale factor of the viewer.
        - center: QPoint representing the center of the view. (Scaled from 0 to 1))
        """

        painter = self.getPainter()

        # Construct layer_to_screen transformation
        layer_to_screen = self.layer_to_canvas * canvas_to_viewer
        screen_to_layer = layer_to_screen.inverted()[0]

        # Set transformation
        painter.setTransform(layer_to_screen)

        if self.image is None:
            return

        # Determine appropriate level & tiling properties
        level = self.image.choose_level(sqrt(abs(layer_to_screen.determinant())))
        scale_level = self.image.level_scale(level)
        max_col, max_row = self.image.max_tile_index(level)
        tile_size = self.image.tile_size

        # Store values
        self.current_level = level
        self.current_scale_level = scale_level

        # Determine visible area
        viewable_area = screen_to_layer.mapRect(self.parent().rect())

        # Determine visible tiles
        top_left = self.image.image_coords_to_tile_index(
            viewable_area.topLeft().x(), viewable_area.topLeft().y(), level
        )
        top_left = QPoint(
            max(0, top_left[0]),
            max(0, top_left[1]),
        )
        bottom_right = self.image.image_coords_to_tile_index(
            viewable_area.bottomRight().x(), viewable_area.bottomRight().y(), level
        )
        bottom_right = QPoint(
            min(max_col, bottom_right[0]),
            min(max_row, bottom_right[1]),
        )

        # self.log.debug(
        #     "Visible Tiles: (R%d,C%d) (R%d,C%d)  Max: (R%d, C%d)",
        #     top_left.y(),
        #     top_left.x(),
        #     bottom_right.y(),
        #     bottom_right.x(),
        #     max_row,
        #     max_col,
        # )

        painter.setPen(QPen(Qt.black, 2))

        for row in range(top_left.y(), bottom_right.y() + 1):
            for col in range(top_left.x(), bottom_right.x() + 1):
                img = self.image.get_tile(level, col, row)

                if img:
                    # In layer coordinates
                    xy_layer = QPoint(
                        int(col * tile_size / scale_level),
                        int(row * tile_size / scale_level),
                    )
                    wh_layer = QPoint(
                        int(img.width() / scale_level),
                        int(img.height() / scale_level),
                    )

                    rect = QRectF(xy_layer, xy_layer + wh_layer)
                    painter.drawImage(rect, img)

                    painter.drawRect(rect)

                    # self.log.debug(
                    #     "Plotting R%d, C%d  (%d,%d), (%d,%d)",
                    #     row,
                    #     col,
                    #     xy_layer.x(),
                    #     xy_layer.y(),
                    #     wh_layer.x(),
                    #     wh_layer.y(),
                    # )

                else:
                    self.log.warning("Error loading tile (R%d, C%d)", row, col)

        # Draw test rectangle
        # painter.setPen(QPen(Qt.black, 10))
        # painter.drawRect(-127, -127, 254, 254)


class RasterImageLayer(Layer):
    """Layer implementation for non-DeepZoom raster images (e.g., JPEG)."""

    def paint_layer(self, canvas_to_viewer: QTransform) -> None:
        painter = self.getPainter()
        layer_to_screen = self.layer_to_canvas * canvas_to_viewer
        painter.setTransform(layer_to_screen)

        if not self.image or self.image.isNull():
            return

        # Draw the full raster image; treat intrinsic pixel size as layer space
        painter.drawImage(QPoint(0, 0), self.image)
