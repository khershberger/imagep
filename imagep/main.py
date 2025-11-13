import base64
import io
import logging
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QCoreApplication, QPoint, QPointF, QSize
from PySide6.QtGui import (
    QPainter,
    QColor,
    QIcon,
    QAction,
    QPixmap,
    QPen,
    QWheelEvent,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QMainWindow,
    QFileDialog,
    QLineEdit,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
    QLabel,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QDockWidget,
)

from annotations import AnnotationDockWidget
from icons import MICROSCOPE as MAIN_WINDOW_ICON
from preferences import get_preferences
from viewer import LayeredViewer

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("PIL.PngImagePlugin").setLevel(logging.WARNING)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DeepZoom Viewer")
        self.setDockOptions(QMainWindow.AllowNestedDocks | QMainWindow.AllowTabbedDocks)

        self.last_path = ""

        self.layer_list_dock = None
        self.layer_tree_widget = None

        # Set window icon
        icon_data = base64.b64decode(MAIN_WINDOW_ICON)
        pixmap = QPixmap()
        pixmap.loadFromData(icon_data)
        self.setWindowIcon(QIcon(pixmap))

        # Build UI and apply preferences
        self.init_ui()
        self.apply_preferences_startup()
        self._connect_preferences()

    def init_ui(self):
        self.create_actions()
        self.create_menubar()
        self.create_toolbar()

        central = QWidget()
        vbox = QVBoxLayout(central)

        # Input controls
        hbox = QHBoxLayout()
        self.definition_load_edit = QLineEdit()
        self.definition_load_edit.setPlaceholderText("Definition file to load...")
        self.last_path = Path(self.definition_load_edit.text().strip()).parent  # TEMP!

        browse_btn = QPushButton("Browse")
        load_btn = QPushButton("Load")
        hbox.addWidget(QLabel("DeepZoom Source:"))
        hbox.addWidget(self.definition_load_edit)
        hbox.addWidget(browse_btn)
        hbox.addWidget(load_btn)
        vbox.addLayout(hbox)

        # Viewer
        self.viewer = LayeredViewer()
        vbox.addWidget(self.viewer)
        self.viewer.setMouseTracking(True)
        self.viewer.mouseMoveEvent = self._make_mouse_move_event(
            self.viewer.mouseMoveEvent
        )

        # Setup central widget
        central.setLayout(vbox)
        self.setCentralWidget(central)

        # Add dockable layer tree
        self.layer_tree_widget = QTreeWidget()
        self.layer_tree_widget.setColumnWidth(0, 200)
        self.layer_tree_widget.setHeaderLabels(["Config / Layers"])
        self.layer_tree_widget.itemSelectionChanged.connect(self.on_layer_selected)
        self.layer_list_dock = QDockWidget("Layers", self)
        self.layer_list_dock.setWidget(self.layer_tree_widget)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.layer_list_dock)

        # Create status dock
        self.status_widget = DebugStatusWidget(self)
        self.status_dock = QDockWidget("Status", self)
        self.status_dock.setWidget(self.status_widget)
        self.addDockWidget(Qt.RightDockWidgetArea, self.status_dock)

        # Annotation dock widget (refactored)
        self.annotation_dock = AnnotationDockWidget(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.annotation_dock)
        # Connect dock signals to viewer
        self.annotation_dock.addAnnotation.connect(self.viewer._on_add_annotation)
        self.viewer.annotation_selected.connect(self.annotation_dock.sync_to_annotation)
        self.viewer.set_annotation_dock(self.annotation_dock)

        # Connect
        browse_btn.clicked.connect(self.browse_file)
        load_btn.clicked.connect(self.load_definition)
        # Layer list refresh when selection changes (for future multi-layer support)
        self.layer_tree_widget.itemSelectionChanged.connect(
            self.refresh_annotation_layers
        )
        self.refresh_annotation_layers()

    def refresh_annotation_layers(self):
        """Populate the annotation dock's layer selector with current layers."""
        if (
            not hasattr(self.viewer, "selection_widget")
            or self.viewer.selection_widget is None
        ):
            return
        names = []
        root = self.viewer.selection_widget
        for i in range(root.childCount()):
            child = root.child(i)
            layer = child.data(0, Qt.UserRole)
            if layer is not None:
                names.append(layer.objectName() or f"Layer {i}")
        self.annotation_dock.refresh_layer_list(names)

    def create_icon(self, icon_type):
        icon = QIcon()
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setPen(QPen(QColor(0, 0, 0), 2))

        if icon_type == "dot":
            painter.setBrush(QColor(0, 0, 0))
            painter.drawEllipse(12, 12, 8, 8)
        elif icon_type == "ruler":
            painter.drawLine(4, 28, 28, 4)
            # Add small perpendicular lines at ends
            painter.drawLine(2, 26, 6, 30)
            painter.drawLine(26, 2, 30, 6)
        elif icon_type == "rectangle":
            painter.drawRect(8, 8, 16, 16)

        painter.end()
        icon.addPixmap(pixmap)
        return icon

    def create_actions(self):
        self.actions = {}
        for tool in ["dot", "ruler", "rectangle"]:
            action = QAction(self.create_icon(tool), tool.capitalize(), self)
            action.setStatusTip(f"Add {tool} annotation")
            self.actions[tool] = action
        self.setup_annotation_tools()

    def create_menubar(self):
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("File")
        file_menu.addAction("Open")
        file_menu.addAction("Save")
        save_as_action = QAction("Save As", self)
        save_as_action.triggered.connect(self.save_as)
        file_menu.addAction(save_as_action)
        file_menu.addSeparator()
        file_menu.addAction("Exit")

        # Recent Files submenu (populated dynamically)
        self.recent_files_menu = file_menu.addMenu("Recent Files")
        self._rebuild_recent_files_menu()

        # Preferences action
        prefs_action = QAction("Preferences", self)
        prefs_action.triggered.connect(self.open_preferences_dialog)
        menubar.addAction(prefs_action)

        # Annotations menu
        annotations_menu = menubar.addMenu("Annotations")
        for action in self.actions.values():
            annotations_menu.addAction(action)

    def save_as(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save As", str(self.last_path), "JSON Files (*.json);;All Files (*)"
        )

        if not file_path:
            return

        self.last_path = Path(file_path)
        if self.viewer:
            self.viewer.dump_config_json(Path(file_path))

    def create_toolbar(self):
        toolbar = QToolBar()
        toolbar.setIconSize(QSize(32, 32))
        for action in self.actions.values():
            toolbar.addAction(action)
        self.addToolBar(toolbar)

    def browse_file(self):
        file, _ = QFileDialog.getOpenFileName(
            self,
            caption="Select Configuration or Image File",
            dir=str(self.last_path),
            filter="JSON Files (*.json);;Image Files (*.jpg *.jpeg *.png);;All Files (*)",
        )
        if file:
            self.definition_load_edit.setText(file)
            self.last_path = Path(file).parent
            # Track recent file selection (not yet loaded)
            get_preferences().add_recent_file(file)
            get_preferences().save()
            self._rebuild_recent_files_menu()

    def load_definition(self):
        config = Path(self.definition_load_edit.text().strip())
        self.last_path = config
        # Create new tree item root for config/image context if not already
        config_item = QTreeWidgetItem([config.name])
        self.layer_tree_widget.addTopLevelItem(config_item)
        self.viewer.set_selection_widget(config_item)

        try:
            if config.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                # Treat as a single raster image layer
                self.viewer.add_image_layer(config)
            else:
                # Assume JSON DeepZoom config
                self.viewer.load_config_json(config)
            self.layer_tree_widget.setCurrentItem(config_item)
            self.refresh_annotation_layers()
            # Update MRU on successful load
            get_preferences().add_recent_file(str(config))
            get_preferences().save()
            self._rebuild_recent_files_menu()
        except Exception as e:
            print(f"Failed to load: {e}")

    def on_layer_selected(self):
        if self.viewer:
            self.viewer.update()

    # ToDo:  Fix this so that it works
    # def wheelEvent(self, event: QWheelEvent):
    #     self.update_status_window(event)

    def status_widget_widget(self, event):
        # Screen coordinates
        global_pos = self.viewer.mapToGlobal(event.position())

        # Compose status
        try:
            current_layer = self.viewer.get_layers()[0]
        except IndexError:
            return

        mouse_pos = QPoint(event.position().x(), event.position().y())

        status = {
            "Mouse (Screen)": global_pos,
            "Mouse (Viewer)": mouse_pos,
            "Mouse (Canvas)": self.viewer.canvas_to_viewer.inverted()[0].map(mouse_pos),
            "Mouse (Layer)": current_layer.layer_to_canvas.inverted()[0].map(
                self.viewer.canvas_to_viewer.inverted()[0].map(mouse_pos)
            ),
            "Canvas Scale": self.viewer.get_scale(),
            "Layer Scale": current_layer.get_scale(),
            "Scale Effective": self.viewer.get_scale() * current_layer.get_scale(),
            "Tile Level Scale": getattr(current_layer, "current_scale_level", None),
            "Tile Level": getattr(current_layer, "current_level", None),
        }

        self.status_widget.set_status(status)

    def _make_mouse_move_event(self, orig_mouse_move_event):
        def mouse_move_event(event):
            # Call original event
            orig_mouse_move_event(event)

            self.status_widget_widget(event)

        return mouse_move_event

    def setup_annotation_tools(self):
        self.active_tool = None
        self.dot_action = self.actions["dot"]
        self.dot_action.setCheckable(True)
        self.dot_action.triggered.connect(self.activate_dot_tool)
        self.annotation_label_edit = None

    def activate_dot_tool(self):
        # Visual indication
        for t, act in self.actions.items():
            act.setChecked(t == "dot")
        self.active_tool = "dot"
        if self.viewer:
            self.viewer.set_annotation_tool_state(True)

    def deactivate_dot_tool(self):
        # Called after label input is finished
        self.actions["dot"].setChecked(False)
        self.viewer.set_annotation_tool_state(False)

    def start_label_input(self, annotation, finish_callback):
        # Create a QLineEdit overlay for label input
        if self.annotation_label_edit:
            self.annotation_label_edit.deleteLater()
        self.annotation_label_edit = QLineEdit(self)
        self.annotation_label_edit.setPlaceholderText("Enter label...")
        self.annotation_label_edit.setFixedWidth(120)
        self.annotation_label_edit.setText(annotation.label)

        # Place at annotation position (approximate)
        pos = self.viewer.canvas_to_viewer.map(
            annotation.parent().layer_to_canvas.map(annotation.position)
        )
        pos = self.viewer.mapToGlobal(pos)

        self.annotation_label_edit.move(self.mapFromGlobal(pos))
        self.annotation_label_edit.show()
        self.annotation_label_edit.setFocus()

        def on_text_changed(text):
            annotation.label = text
            self.viewer.update()

        self.annotation_label_edit.textChanged.connect(on_text_changed)

        def finish():
            annotation.label = self.annotation_label_edit.text()
            self.annotation_label_edit.deleteLater()
            self.annotation_label_edit = None
            finish_callback()

        self.annotation_label_edit.returnPressed.connect(finish)

    # --- Preferences Integration ------------------------------------------
    def apply_preferences_startup(self):
        prefs = get_preferences()
        # Background handled in viewer paint; request repaint
        self.viewer.update()
        # Default zoom: adjust viewer transform to target scale
        target = prefs.default_zoom
        current = self.viewer.get_scale()
        if current > 0 and target != current:
            factor = target / current
            self.viewer.canvas_to_viewer = (
                self.viewer.canvas_to_viewer * QTransform().scale(factor, factor)
            )
        # Annotation defaults: set dock starting values
        ann = prefs.annotation_defaults
        self.annotation_dock.text_input.setText("")
        self.annotation_dock.fontsize_input.setText(str(ann.get("font_size", 18)))
        # Color is applied lazily when creating new annotation; could update button text
        # Grid visibility triggers repaint
        self.viewer.update()

    def _connect_preferences(self):
        prefs = get_preferences()
        prefs.changed.connect(self.on_pref_changed)

    def on_pref_changed(self, key: str, value):
        """Respond to runtime preference changes (live apply where possible)."""
        if key in {"background_color", "show_grid"}:
            self.viewer.update()
        elif key == "recent_files" or key == "recent_files_max":
            self._rebuild_recent_files_menu()
        elif key == "default_zoom":
            # Adjust transform to new zoom keeping current center
            current = self.viewer.get_scale()
            target = float(value)
            if current > 0 and target != current:
                factor = target / current
                self.viewer.canvas_to_viewer = (
                    self.viewer.canvas_to_viewer * QTransform().scale(factor, factor)
                )
                self.viewer.update()
        elif key == "annotation_defaults":
            # Update dock font size default only (text color applied when creating new annotation)
            self.annotation_dock.fontsize_combo.setCurrentText(
                str(value.get("font_size", 18))
            )

    def _rebuild_recent_files_menu(self):
        if not hasattr(self, "recent_files_menu"):
            return
        self.recent_files_menu.clear()
        prefs = get_preferences()
        for path in prefs.recent_files:
            act = QAction(path, self)
            act.triggered.connect(lambda checked=False, p=path: self._open_recent(p))
            self.recent_files_menu.addAction(act)
        if not prefs.recent_files:
            empty = QAction("(None)", self)
            empty.setEnabled(False)
            self.recent_files_menu.addAction(empty)

    def _open_recent(self, path: str):
        self.definition_load_edit.setText(path)
        self.load_definition()

    def open_preferences_dialog(self):
        from preferences_dialog import PreferencesDialog

        dlg = PreferencesDialog(self)
        dlg.exec()


class DebugStatusWidget(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        # self.setAttribute(Qt.WA_TranslucentBackground)
        # self.setStyleSheet(
        #     "background: rgba(255,255,255,0.9); border: 1px solid #888; border-radius: 6px;"
        # )
        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)
        self.labels = {}
        self.readouts = {}

        self.add_readout("Mouse (Native)")
        self.add_readout("Mouse (Global)")

        self.add_readout("Mouse (Layer)")
        self.add_readout("Viewer Scale")
        self.add_readout("Viewer Offset")
        self.add_readout("Layer Scale")
        self.add_readout("Layer Offset")
        self.add_readout("Level")

        # self.resize(260, 120)
        # self.adjustSize()
        # self.move(50, 50)

    def add_readout(self, key):
        hbox = QHBoxLayout()
        label = QLabel(f"{key}:")
        label.setStyleSheet("font-weight: bold; min-width: 70px;")
        readout = QLabel("")
        # readout.setStyleSheet(
        #     "background: #fff; border: 1px solid #ccc; padding: 2px 6px; border-radius: 3px;"
        # )
        hbox.addWidget(label)
        hbox.addWidget(readout)
        self.layout.addLayout(hbox)

        self.labels[key] = label
        self.readouts[key] = readout

    def set_status(self, status_dict):
        # CHeck that there is a readout for each key in status_dict
        for key in status_dict.keys():
            if key not in self.readouts:
                self.add_readout(key)

        for key, readout in self.readouts.items():
            val = status_dict.get(key, "")
            if isinstance(val, QPointF):
                val = f"({val.x():.2f}, {val.y():.2f})"
            if isinstance(val, QPoint):
                val = f"({val.x()}, {val.y()})"

            readout.setText(str(val))
        self.adjustSize()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    QCoreApplication.setApplicationName("ImageP")
    win = MainWindow()
    win.resize(1200, 900)
    win.move(300, 50)
    win.show()
    sys.exit(app.exec())
