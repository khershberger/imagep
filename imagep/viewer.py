from annotations import Annotation
from preferences import get_preferences
import json
import logging
import tomllib
from math import sqrt, remainder
from pathlib import Path

from PySide6.QtWidgets import (
    QLabel,
    QStatusBar,
    QVBoxLayout,
    QWidget,
    QTreeWidgetItem,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QWheelEvent,
    QPainter,
    QTransform,
    QPen,
)

from PySide6.QtCore import Qt, QPoint, QRect, Signal

from layers import DeepzoomLayer, Layer, RasterImageLayer


class LayeredViewer(QWidget):
    """Main deepzoom viewer widget managing layers and annotations.

    Responsibilities:
    - Render selected layers and their annotations.
    - Coordinate transforms (pan/zoom) via a QTransform.
    - Interactive annotation creation, selection, dragging, and editing.
    - Emit selection signals so external docks (annotation properties) can sync.
    """

    # Emitted when an annotation is selected; payload is the Annotation object.
    annotation_selected = Signal(object)

    def __init__(self, config: Path = None, selection_widget=None, parent=None):
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
        self.selection_widget = selection_widget
        self.selected_annotation = None
        self._drag_offset = None
        # Reference to annotation dock (set externally) used for live property sync.
        self.annotation_dock = None
        # Layer adjustment parameters (cycled with keypad 5)
        self._adjust_steps = [0.04, 0.2, 1.0, 5.0, 25.0]
        self._adjust_index = 2  # default mid value
        self._scale_base = 0.05  # base scale step
        self._translate_base = 25  # pixels per move at base step
        self._rotation_base = 1.0  # degrees per rotate at base step

    def _annotation_at_pos(self, pos: QPoint):
        """Return annotation under viewer coordinate `pos` or None.

        Uses a simple bounding box around the rendered text. Could be enhanced
        later with better shape or tolerance logic.

        Parameters
        ----------
        pos: QPoint
            Position in canvas coordinates to check for annotation hit.
        """
        from PySide6.QtGui import QFont, QFontMetrics
        from PySide6.QtCore import QRect

        for layer in self.get_layers():
            # Convert pos from viewer coordinates to layer coordinates
            for ann in getattr(layer, "annotations", []):
                if ann.bounding_box.contains(pos):
                    return ann
        return None

    def set_selection_widget(self, selection_widget):
        self.selection_widget = selection_widget

    def get_layers(self, all=False):
        # Return all layer objects from the config_tree_item
        layers = []
        if not hasattr(self, "selection_widget") or self.selection_widget is None:
            return layers

        if all:
            for i in range(self.selection_widget.childCount()):
                item = self.selection_widget.child(i)
                layer = item.data(0, Qt.UserRole)
                if isinstance(layer, Layer):
                    layers.append(layer)
        else:
            tree_widget = self.selection_widget.treeWidget()
            selected_items = tree_widget.selectedItems() if tree_widget else []
            for item in selected_items:
                layer = item.data(0, Qt.UserRole)
                if isinstance(layer, Layer):
                    layers.append(layer)
        return layers

    def get_transform(self, source, target, layer=None):
        """Transform a point between coordinate systems.

        Parameters
        ----------
        source: str
            Source coordinate system: "canvas", "viewer", or "layer".
        target: str
            Target coordinate system: "canvas", "viewer", or "layer".
        layer: Layer | None
            Layer to use for "layer" coordinate system. If None, uses first selected layer.

        Returns
        -------
        QTransform
            Transformation from source to target coordinate system.
        """
        if source == target:
            return QTransform()

        if layer is None and (source == "layer" or target == "layer"):
            # Assume first selected layer for layer coordinates
            layers = self.get_layers()
            if not layers:
                raise ValueError(
                    "No layers available for layer coordinate transformation."
                )
            layer = layers[0]

        # Build transformation from source to viewer
        if source == "canvas":
            source_to_viewer = self.canvas_to_viewer
        elif source == "viewer":
            source_to_viewer = QTransform()  # Identity
        elif source == "layer":
            source_to_viewer = layer.layer_to_canvas * self.canvas_to_viewer

        # Build transformation from viewer to target
        if target == "canvas":
            viewer_to_target = self.canvas_to_viewer.inverted()[0]
        elif target == "viewer":
            viewer_to_target = QTransform()  # Identity
        elif target == "layer":
            viewer_to_target = layer.layer_to_canvas.inverted()[0]

        return source_to_viewer * viewer_to_target

    def _on_add_annotation(
        self, text: str, color: QColor, font_size: int, target_layer_name
    ):
        """Signal handler from annotation dock to begin placing a new annotation.

        Parameters
        ----------
        text: str
            Initial annotation label.
        color: QColor
            Annotation text color.
        font_size: int
            Font size to use.
        target_layer_name: str | None
            Name of target layer or None to use current selected layer.
        """

        prefs = get_preferences()
        ann_defaults = prefs.annotation_defaults
        # Use dock values if provided, else fallback to preferences
        use_color = (
            color if color else QColor(ann_defaults.get("text_color", "#0000FF"))
        )
        use_font_size = font_size if font_size else ann_defaults.get("font_size", 18)
        pos = QPoint(self.width() // 2, self.height() // 2)
        self.annotation_preview = Annotation(
            label=text,
            color=use_color,
            position=pos,
            parent=self,
            fontsize=use_font_size,
        )

        self._target_layer_name = target_layer_name
        self.annotation_tool_active = True
        self.placing_annotation = True
        self.setCursor(Qt.CrossCursor)
        self.update()

    def set_annotation_tool_state(self, state: bool):
        """Enable/disable annotation placement tool (used by legacy toolbar dot action)."""
        self.annotation_tool_active = state
        if state:
            # Create a simple default preview if none has been created via dock.
            if not getattr(self, "annotation_preview", None):
                pos = QPoint(self.width() // 2, self.height() // 2)
                self.annotation_preview = Annotation(
                    label="",
                    color=Qt.blue,
                    position=pos,
                    parent=self,
                    fontsize=18,
                )
            self.placing_annotation = True
            self.setCursor(Qt.CrossCursor)
        else:
            self.annotation_preview = None
            self.placing_annotation = False
            self.setCursor(Qt.ArrowCursor)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        pos_canvas = self.get_transform("viewer", "canvas").map(event.pos())

        if getattr(self, "annotation_tool_active", False) and getattr(
            self, "placing_annotation", False
        ):
            # Move preview dot with mouse
            if self.annotation_preview:
                self.annotation_preview.position = event.pos()
                self.update()

        elif (
            self.selected_annotation
            and self._drag_offset is not None
            and event.buttons() & Qt.LeftButton
        ):
            # Drag selected annotation
            self.selected_annotation.position = pos_canvas - self._drag_offset
            self.update()

        elif self.dragging:
            delta = event.pos() - self.last_mouse_pos
            self.canvas_to_viewer *= QTransform().translate(delta.x(), delta.y())
            self.last_mouse_pos = event.pos()
            self.update()
        self._update_status(event.pos())

    def mousePressEvent(self, event: QMouseEvent):
        pos_canvas = self.get_transform("viewer", "canvas").map(event.pos())

        if event.button() == Qt.LeftButton:
            ann = self._annotation_at_pos(pos_canvas)
            if ann:
                # Update selected annotation
                if self.selected_annotation is not None:
                    self.selected_annotation.set_selection_status(False)
                self.selected_annotation = ann
                self.selected_annotation.set_selection_status(True)

                # Update drag offset
                self._drag_offset = pos_canvas - ann.position

                # Emit selection signal so dock can sync controls
                self.annotation_selected.emit(ann)
                self.update()
            else:
                if self.selected_annotation is not None:
                    self.selected_annotation.set_selection_status(False)
                self.selected_annotation = None
                self._drag_offset = None
            self.dragging = True
            self.last_mouse_pos = event.pos()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if (
            getattr(self, "annotation_tool_active", False)
            and getattr(self, "placing_annotation", False)
            and event.button() == Qt.LeftButton
        ):
            # Fix the annotation position on second click
            self.placing_annotation = False

            # Transfer preview annotation to layer
            annotation = self.annotation_preview

            # Determine target layer
            layer = None
            if getattr(self, "_target_layer_name", None):
                for layer_obj in self.get_layers(all=True):
                    if (layer_obj.objectName() or "") == self._target_layer_name:
                        layer = layer_obj
                        break
            if layer is None:
                # Fallback to currently selected layer
                try:
                    layer = self.get_layers()[0]
                except IndexError:
                    layer = None
            if layer is None:
                # No layer available; abort placement
                self.annotation_preview = None
                self.annotation_tool_active = False
                self.placing_annotation = False
                self.setCursor(Qt.ArrowCursor)
                return
            annotation._parent = layer

            # Transform position from viewer to canvas coordinates
            annotation.position = self.canvas_to_viewer.inverted()[0].map(
                annotation.position
            )

            # Scale font:
            annotation.font_size = annotation.font_size // self.get_scale()

            if not hasattr(layer, "annotations"):
                layer.annotations = []
            layer.annotations.append(annotation)
            self.setCursor(Qt.IBeamCursor)

            # # Ask for label input via main window
            mw = self.parent().parent()
            mw.deactivate_dot_tool()
            # if hasattr(mw, "start_label_input"):
            #     mw.start_label_input(annotation, lambda: mw.deactivate_dot_tool())
            self.update()

        # End drag of annotation
        if self.selected_annotation and self._drag_offset is not None:
            self._drag_offset = None
        if event.button() == Qt.LeftButton:
            self.dragging = False

    def getPainter(self) -> QPainter:
        return self._painter

    def paintEvent(self, event):
        self._painter = QPainter(self)

        # Fill background from preferences
        prefs = get_preferences()
        bg = prefs.background_color
        try:
            from PySide6.QtGui import QColor

            self._painter.fillRect(self.rect(), QColor(bg))
        except Exception:
            self._painter.fillRect(self.rect(), Qt.black)

        # Only paint the selected layers
        selected_layers = self.get_layers()
        for layer in selected_layers:
            self._painter.save()
            layer.paint_layer(self.canvas_to_viewer)
            self._painter.restore()

        for layer in self.get_layers(all=True):
            # Set painter to canvas coordinates
            self._painter.save()
            self._painter.setTransform(self.canvas_to_viewer)

            # Paint annotations here
            for annotation in getattr(layer, "annotations", []):
                annotation.paintEvent(event)

            # Set painter back to viewer coordinates
            self._painter.restore()

        # self._painter.setPen(QPen(Qt.red, 2))
        self.draw_grid(self._painter, 125)

        if getattr(self, "placing_annotation", False) and getattr(
            self, "placing_annotation", None
        ):
            # Draw preview annotation
            self.annotation_preview.paintEvent(event)

        self._painter.end()
        self._painter = None

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

        painter.setPen(QPen(Qt.red, 1))

        for k in range(0, int(self.rect().width() / step_size)):
            x = round(k * step_size - offset_x)
            painter.drawLine(x, 0, x, self.rect().height())

        for k in range(0, int(self.rect().height() / step_size)):
            y = round(k * step_size - offset_y)
            painter.drawLine(0, y, self.rect().width(), y)

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

    def resizeEvent(self, event):
        self.update()

    def get_scale(self):
        return sqrt(abs(self.canvas_to_viewer.determinant()))

    def _update_status(self, pos):
        self.status_label.setText("I do not work right now...")

    def load_config_json(self, config: Path):
        with config.open("rt") as fin:
            config_dict = json.load(fin)

        # Only parse first component for now
        component = config_dict["components"][0]

        ppm = component["layers"][0]["pixelsPerMeter"]
        for idx, item in enumerate(component["layers"]):
            cls = Layer
            if item["source"] is not None:
                source = config.parent / Path(item["source"]).name
                if source.suffix == ".dzi":
                    cls = DeepzoomLayer
                else:
                    cls = RasterImageLayer
            else:
                source = item["source"]

            new_layer = cls(
                str(source),
                self,
                name=item["name"],
                scale=ppm / item["pixelsPerMeter"],
                pixels_per_meter=item["pixelsPerMeter"],
                offset=-QPoint(*item["origin"]),
                rotation=item["rotation"],
                rotation_center=QPoint(0, 0),
                mirror=item.get("mirror", False),
            )

            for item in item.get("annotations", []):
                ann = Annotation(
                    parent=new_layer,
                    label=item.get("label", ""),
                    color=QColor(item.get("color", Qt.blue)),
                    line_width=item.get("line_width", 2),
                    fontsize=item.get("font_size", 10),
                    justification=item.get("justification", "center_center"),
                    position=QPoint(*item.get("position", (0, 0))),
                )
                if not hasattr(new_layer, "annotations"):
                    new_layer.annotations = []
                new_layer.annotations.append(ann)

            new_item = QTreeWidgetItem([new_layer.objectName() or f"Layer {idx}"])
            new_item.setData(0, Qt.UserRole, new_layer)
            self.selection_widget.addChild(new_item)
        self.selection_widget.setExpanded(True)

    def dump_config_json(self, config: Path):
        config_dict = {"components": []}
        component = {"layers": []}
        ppm = None
        for layer in self.get_layers(all=True):
            if ppm is None:
                ppm = layer.pixels_per_meter
            layer_dict = {
                "name": layer.objectName(),
                # Attempt to record source path if DeepZoom image; raster images may not expose a reader
                "source": getattr(layer, "source", None),
                "pixelsPerMeter": ppm / layer.scale_layer,
                "origin": [-layer.offset_layer.x(), -layer.offset_layer.y()],
                "rotation": layer.rotation,
                "mirror": layer.mirror,
                "annotations": [
                    ann.to_dict() for ann in getattr(layer, "annotations", [])
                ],
            }
            component["layers"].append(layer_dict)

        config_dict["components"].append(component)

        with config.open("wt") as fout:
            json.dump(config_dict, fout, indent=4)

    # --- Layer Transform Hotkeys --------------------------------------------
    def keyPressEvent(self, event):
        """Handle numeric keypad hotkeys for layer transform adjustments.

        Mappings:
        KP_1: Decrease scale
        KP_2: Translate down
        KP_3: Increase scale
        KP_4: Translate left
        KP_5: Cycle adjustment step size
        KP_6: Translate right
        KP_7: Rotate counter-clockwise
        KP_8: Translate up
        KP_9: Rotate clockwise
        """
        # Handle layer navigation with 'w' (up) and 's' (down) before requiring selection
        if self.selection_widget is not None:
            tree_widget = self.selection_widget.treeWidget()
            if tree_widget:
                current = tree_widget.currentItem()
                parent = current.parent() if current else None
                siblings_parent = parent if parent else self.selection_widget
                if event.key() == Qt.Key_W:  # select previous sibling
                    if current:
                        idx = siblings_parent.indexOfChild(current)
                        if idx > 0:
                            tree_widget.setCurrentItem(siblings_parent.child(idx - 1))
                            self.update()
                            return
                elif event.key() == Qt.Key_S:  # select next sibling
                    if current:
                        idx = siblings_parent.indexOfChild(current)
                        if idx < siblings_parent.childCount() - 1:
                            tree_widget.setCurrentItem(siblings_parent.child(idx + 1))
                            self.update()
                            return

        # Work only when a layer is selected for transform hotkeys
        layers = self.get_layers()
        if not layers:
            return
        layer = layers[0]

        key = event.key()
        # Only react to keypad; fall back to normal digits if keypad modifier absent
        step_factor = self._adjust_steps[self._adjust_index]

        if key == Qt.Key_5:
            # Cycle adjustment index
            self._adjust_index = (self._adjust_index + 1) % len(self._adjust_steps)
            self.log.info(
                "Adjustment step set to %s", self._adjust_steps[self._adjust_index]
            )
            return

        # Scale adjustments
        if key == Qt.Key_3:  # Increase scale (multiply)
            layer.scale(1.0 + self._scale_base * step_factor)
        elif key == Qt.Key_1:  # Decrease scale (divide)
            layer.scale(1.0 / (1.0 + self._scale_base * step_factor))
        # Translation
        elif key == Qt.Key_2:  # Down
            layer.translate(0, self._translate_base * step_factor)
        elif key == Qt.Key_8:  # Up
            layer.translate(0, -self._translate_base * step_factor)
        elif key == Qt.Key_4:  # Left
            layer.translate(-self._translate_base * step_factor, 0)
        elif key == Qt.Key_6:  # Right
            layer.translate(self._translate_base * step_factor, 0)
        # Rotation
        elif key == Qt.Key_7:  # CCW
            layer.rotate(-self._rotation_base * step_factor)
        elif key == Qt.Key_9:  # CW
            layer.rotate(self._rotation_base * step_factor)
        else:
            # Unhandled key; pass to base implementation
            return super().keyPressEvent(event)

        self.update()

    def load_config_toml(self, config):
        with open(config, "rb") as fin:
            config_dict = tomllib.load(fin)
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

    # --- Annotation Dock Integration -------------------------------------------------
    def set_annotation_dock(self, dock):
        """Attach the annotation dock to the viewer and wire live editing.

        Parameters
        ----------
        dock: AnnotationDockWidget
            Dock providing annotation creation & property editing UI.
        """
        self.annotation_dock = dock
        # Live property updates when dock controls change.
        dock.settingsChanged.connect(self._on_dock_settings_changed)

    def _on_dock_settings_changed(self):
        """Apply dock property changes to the currently selected annotation.

        Executed when the user changes color/font size/text in the dock while an
        annotation is selected. Updates annotation in-place and repaints.
        """
        if not self.selected_annotation or not self.annotation_dock:
            return
        ann = self.selected_annotation
        ann.label = self.annotation_dock.text
        ann.color = self.annotation_dock.color
        ann.font_size = self.annotation_dock.font_size
        self.update()
