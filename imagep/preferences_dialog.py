"""PreferencesDialog: PySide6 dialog for editing application preferences.

Allows editing of:
- Default zoom level (combo: 50%, 100%, 200%)
- Background color (combo: white, black, gray, custom hex)
- Enable/disable grid overlay (checkbox)
- Default annotation properties (color picker, font size combo)
- Recent files list length (spinbox)

Changes are applied immediately via Preferences API.
"""

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QCheckBox,
    QPushButton,
    QSpinBox,
    QColorDialog,
    QWidget,
    QLineEdit,
)
from PySide6.QtGui import QColor
from PySide6.QtCore import Qt

from preferences import get_preferences


class PreferencesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.prefs = get_preferences()
        self._build_ui()
        self._load_values()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Default zoom
        h_zoom = QHBoxLayout()
        h_zoom.addWidget(QLabel("Default Zoom:"))
        self.zoom_combo = QComboBox()
        self.zoom_combo.addItems(["50%", "100%", "200%"])
        h_zoom.addWidget(self.zoom_combo)
        layout.addLayout(h_zoom)

        # Background color
        h_bg = QHBoxLayout()
        h_bg.addWidget(QLabel("Background Color:"))
        self.bg_combo = QComboBox()
        self.bg_combo.addItems(["White", "Black", "Gray", "Custom..."])
        h_bg.addWidget(self.bg_combo)
        self.bg_custom = QLineEdit()
        self.bg_custom.setPlaceholderText("#RRGGBB")
        h_bg.addWidget(self.bg_custom)
        layout.addLayout(h_bg)

        # Grid overlay
        h_grid = QHBoxLayout()
        self.grid_check = QCheckBox("Show Grid Overlay")
        h_grid.addWidget(self.grid_check)
        layout.addLayout(h_grid)

        # Annotation defaults
        layout.addWidget(QLabel("Default Annotation Properties:"))
        h_ann = QHBoxLayout()
        h_ann.addWidget(QLabel("Text Color:"))
        self.ann_color_btn = QPushButton("Pick Color")
        h_ann.addWidget(self.ann_color_btn)
        h_ann.addWidget(QLabel("Font Size:"))
        self.ann_font_combo = QComboBox()
        for size in [10, 12, 14, 16, 18, 24, 32, 48]:
            self.ann_font_combo.addItem(str(size))
        h_ann.addWidget(self.ann_font_combo)
        layout.addLayout(h_ann)

        # Recent files length
        h_recent = QHBoxLayout()
        h_recent.addWidget(QLabel("Recent Files List Length:"))
        self.recent_spin = QSpinBox()
        self.recent_spin.setRange(1, 50)
        h_recent.addWidget(self.recent_spin)
        layout.addLayout(h_recent)

        # Buttons
        btns = QHBoxLayout()
        self.apply_btn = QPushButton("Apply")
        self.cancel_btn = QPushButton("Cancel")
        btns.addWidget(self.apply_btn)
        btns.addWidget(self.cancel_btn)
        layout.addLayout(btns)

        self.setLayout(layout)

        # Connections
        self.apply_btn.clicked.connect(self._apply)
        self.cancel_btn.clicked.connect(self.reject)
        self.ann_color_btn.clicked.connect(self._pick_ann_color)
        self.bg_combo.currentIndexChanged.connect(self._bg_combo_changed)

    def _load_values(self):
        # Zoom
        zoom = self.prefs.default_zoom
        idx = {0.5: 0, 1.0: 1, 2.0: 2}.get(zoom, 1)
        self.zoom_combo.setCurrentIndex(idx)
        # Background
        bg = self.prefs.background_color.lower()
        if bg in {"#ffffff", "white"}:
            self.bg_combo.setCurrentIndex(0)
            self.bg_custom.setText("#ffffff")
        elif bg in {"#000000", "black"}:
            self.bg_combo.setCurrentIndex(1)
            self.bg_custom.setText("#000000")
        elif bg in {"#888888", "gray", "grey"}:
            self.bg_combo.setCurrentIndex(2)
            self.bg_custom.setText("#888888")
        else:
            self.bg_combo.setCurrentIndex(3)
            self.bg_custom.setText(bg)
        # Grid
        self.grid_check.setChecked(self.prefs.show_grid)
        # Annotation
        ann = self.prefs.annotation_defaults
        self.ann_font_combo.setCurrentText(str(ann.get("font_size", 18)))
        self.ann_color = QColor(ann.get("text_color", "#0000FF"))
        # Recent files
        self.recent_spin.setValue(self.prefs.recent_files_max)

    def _bg_combo_changed(self, idx):
        if idx == 0:
            self.bg_custom.setText("#ffffff")
        elif idx == 1:
            self.bg_custom.setText("#000000")
        elif idx == 2:
            self.bg_custom.setText("#888888")
        # Custom: leave as is

    def _pick_ann_color(self):
        color = QColorDialog.getColor(self.ann_color, self)
        if color.isValid():
            self.ann_color = color

    def _apply(self):
        # Zoom
        zoom_map = {0: 0.5, 1: 1.0, 2: 2.0}
        self.prefs.default_zoom = zoom_map.get(self.zoom_combo.currentIndex(), 1.0)
        # Background
        bg = self.bg_custom.text().strip()
        if self.prefs._valid_color(bg):
            self.prefs.background_color = bg
        # Grid
        self.prefs.show_grid = self.grid_check.isChecked()
        # Annotation
        self.prefs.set_annotation_default("text_color", self.ann_color.name())
        self.prefs.set_annotation_default(
            "font_size", int(self.ann_font_combo.currentText())
        )
        # Recent files
        self.prefs.recent_files_max = self.recent_spin.value()
        self.prefs.save()
        self.accept()
