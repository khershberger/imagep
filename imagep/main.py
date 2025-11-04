import logging
import sys
from PySide6.QtCore import Qt, QPoint, QPointF, QSize
from PySide6.QtGui import QPainter, QColor, QIcon, QAction, QPixmap, QPen
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
    QMenuBar,
    QMenu,
    QToolBar,
)

from viewer import LayeredViewer
# from status_floating_window import StatusFloatingWindow

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("PIL.PngImagePlugin").setLevel(logging.WARNING)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DeepZoom Viewer")
        self.viewer = None
        self.status_window = StatusFloatingWindow(self)
        self.status_window.show()
        self.init_ui()

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

    def create_menubar(self):
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("File")
        file_menu.addAction("Open")
        file_menu.addAction("Save")
        file_menu.addSeparator()
        file_menu.addAction("Exit")

        # Annotations menu
        annotations_menu = menubar.addMenu("Annotations")
        for action in self.actions.values():
            annotations_menu.addAction(action)

    def create_toolbar(self):
        toolbar = QToolBar()
        toolbar.setIconSize(QSize(32, 32))
        for action in self.actions.values():
            toolbar.addAction(action)
        self.addToolBar(toolbar)

    def init_ui(self):
        self.create_actions()
        self.create_menubar()
        self.create_toolbar()

        central = QWidget()
        vbox = QVBoxLayout(central)

        # Input controls
        hbox = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Enter .dzi file path or URL...")
        # self.input_edit.setText("sample.dzi")
        self.input_edit.setText("collection.toml")
        browse_btn = QPushButton("Browse")
        load_btn = QPushButton("Load")
        hbox.addWidget(QLabel("DeepZoom Source:"))
        hbox.addWidget(self.input_edit)
        hbox.addWidget(browse_btn)
        hbox.addWidget(load_btn)
        vbox.addLayout(hbox)

        # Viewer placeholder
        self.viewer_container = QVBoxLayout()
        vbox.addLayout(self.viewer_container)
        central.setLayout(vbox)
        self.setCentralWidget(central)

        # Connect
        browse_btn.clicked.connect(self.browse_file)
        load_btn.clicked.connect(self.load_config)

    def browse_file(self):
        file, _ = QFileDialog.getOpenFileName(
            self, "Select DeepZoom .dzi File", "", "DeepZoom Files (*.dzi)"
        )
        if file:
            self.input_edit.setText(file)

    def load_config(self):
        source = self.input_edit.text().strip()
        if not source:
            return
        # Remove old viewer if present
        if self.viewer:
            try:
                self.viewer.mouseMoveEvent.disconnect()
            except Exception:
                pass
            self.viewer.setParent(None)
            self.viewer.deleteLater()
            self.viewer = None
        try:
            self.viewer = LayeredViewer(config=source)
            self.viewer_container.addWidget(self.viewer)
            self.viewer.setMouseTracking(True)
            self.viewer.mouseMoveEvent = self._make_mouse_move_event(
                self.viewer.mouseMoveEvent
            )
        except Exception as e:
            error_label = QLabel(f"Failed to load: {e}")
            self.viewer_container.addWidget(error_label)

    def update_status_window(self, event):
        # Screen coordinates
        global_pos = self.viewer.mapToGlobal(event.position())

        # Compose status

        current_layer = self.viewer.layers[0]

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
            "Tile Level Scale": current_layer.current_scale_level,
            "Tile Level": current_layer.current_level,
        }

        self.status_window.set_status(status)

    def _make_mouse_move_event(self, orig_mouse_move_event):
        def mouse_move_event(event):
            # Call original event
            orig_mouse_move_event(event)

            self.update_status_window(event)

        return mouse_move_event


class StatusFloatingWindow(QDialog):
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
        self.adjustSize()
        self.move(50, 50)

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
    win = MainWindow()
    win.resize(1200, 900)
    win.move(300, 50)
    win.show()
    sys.exit(app.exec())
