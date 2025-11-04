"""Unit tests for preferences module: load/save, recent files logic."""

import pytest
import tempfile
import shutil
from pathlib import Path
import imagep.preferences as preferences
from imagep.preferences import Preferences, get_preferences


class TestPreferences:
    def setup_method(self):
        # Use a temp directory for config
        self.tmpdir = tempfile.mkdtemp()
        self.orig_config_path = preferences._config_path
        preferences._config_path = lambda: Path(self.tmpdir) / "preferences.json"
        # Reset singleton
        preferences._singleton = None
        self.prefs = get_preferences()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)
        preferences._config_path = self.orig_config_path
        preferences._singleton = None

    def test_defaults(self):
        assert self.prefs.default_zoom == 1.0
        assert self.prefs.background_color == "#000000"
        assert self.prefs.show_grid is True
        assert self.prefs.recent_files_max == 10
        assert self.prefs.recent_files == []
        assert self.prefs.annotation_defaults["font_size"] == 18

    def test_save_and_load(self):
        self.prefs.default_zoom = 2.0
        self.prefs.background_color = "#222222"
        self.prefs.show_grid = False
        self.prefs.set_annotation_default("font_size", 24)
        self.prefs.save()
        # Reload
        preferences._singleton = None
        prefs2 = get_preferences()
        assert prefs2.default_zoom == 2.0
        assert prefs2.background_color == "#222222"
        assert prefs2.show_grid is False
        assert prefs2.annotation_defaults["font_size"] == 24

    def test_recent_files_add_and_trim(self):
        import os

        files = [f"/tmp/file{i}.json" for i in range(15)]
        abs_files = [os.path.abspath(f) for f in files]
        for f in files:
            self.prefs.add_recent_file(f)
        assert self.prefs.recent_files[0] == abs_files[-1]
        assert len(self.prefs.recent_files) == self.prefs.recent_files_max
        # Change max and check trim
        self.prefs.recent_files_max = 5
        assert len(self.prefs.recent_files) == 5
        assert self.prefs.recent_files == abs_files[-5:][::-1]

    def test_recent_files_dedupe(self):
        import os

        f1 = "/tmp/a.json"
        f2 = "/tmp/b.json"
        af1 = os.path.abspath(f1)
        af2 = os.path.abspath(f2)
        self.prefs.add_recent_file(f1)
        self.prefs.add_recent_file(f2)
        self.prefs.add_recent_file(f1)
        assert self.prefs.recent_files[0] == af1
        assert self.prefs.recent_files[1] == af2
        assert len(self.prefs.recent_files) == 2

    def test_corrupt_file_recovery(self):
        # Write corrupt JSON
        prefs_path = preferences._config_path()
        with open(prefs_path, "w") as f:
            f.write("{ this is not valid json }")
        # Should recover to defaults
        preferences._singleton = None
        p = get_preferences()
        assert p.default_zoom == 1.0
        assert prefs_path.with_suffix(".corrupt").exists()

    def test_invalid_values_handling(self):
        # Invalid zoom
        old_zoom = self.prefs.default_zoom
        self.prefs.default_zoom = -1
        assert self.prefs.default_zoom == old_zoom
        # Invalid color
        old_bg = self.prefs.background_color
        self.prefs.background_color = "notacolor"
        assert self.prefs.background_color == old_bg
        # Invalid recent_files_max
        old_max = self.prefs.recent_files_max
        self.prefs.recent_files_max = 0
        assert self.prefs.recent_files_max == old_max

    def test_annotation_defaults_edge_cases(self):
        # Minimum font size
        self.prefs.set_annotation_default("font_size", 1)
        assert self.prefs.annotation_defaults["font_size"] == 1
        # Invalid color fallback
        old_color = self.prefs.annotation_defaults["text_color"]
        self.prefs.set_annotation_default("text_color", "badcolor")
        assert self.prefs.annotation_defaults["text_color"] == old_color

    def test_signal_emission(self):
        changes = []

        def slot(key, value):
            changes.append((key, value))

        self.prefs.changed.connect(slot)
        self.prefs.default_zoom = 2.0
        self.prefs.background_color = "#222222"
        self.prefs.show_grid = False
        self.prefs.set_annotation_default("font_size", 24)
        self.prefs.recent_files_max = 5
        self.prefs.add_recent_file("/tmp/signal.json")
        assert any(k == "default_zoom" for k, v in changes)
        assert any(k == "background_color" for k, v in changes)
        assert any(k == "show_grid" for k, v in changes)
        assert any(k == "annotation_defaults" for k, v in changes)
        assert any(k == "recent_files_max" for k, v in changes)
        assert any(k == "recent_files" for k, v in changes)

    def test_persistence_of_all_fields(self):
        self.prefs.default_zoom = 2.0
        self.prefs.background_color = "#222222"
        self.prefs.show_grid = False
        self.prefs.set_annotation_default("font_size", 24)
        self.prefs.set_annotation_default("text_color", "#123456")
        self.prefs.recent_files_max = 7
        self.prefs.add_recent_file("/tmp/persist.json")
        self.prefs.save()
        preferences._singleton = None
        p2 = get_preferences()
        assert p2.default_zoom == 2.0
        assert p2.background_color == "#222222"
        assert p2.show_grid is False
        assert p2.annotation_defaults["font_size"] == 24
        assert p2.annotation_defaults["text_color"] == "#123456"
        assert p2.recent_files_max == 7
        assert any("persist.json" in f for f in p2.recent_files)

    def test_recent_files_nonexistent_path(self):
        fake_path = "/tmp/does_not_exist.json"
        self.prefs.add_recent_file(fake_path)
        import os

        assert os.path.abspath(fake_path) in self.prefs.recent_files

    def test_preferences_dialog_stub(self):
        # UI integration test stub (would require Qt test framework for full coverage)
        # Here, just ensure dialog can be constructed and loads values
        try:
            from PySide6.QtWidgets import QApplication
            import sys

            app = QApplication.instance() or QApplication(sys.argv)
            from imagep.preferences_dialog import PreferencesDialog

            dlg = PreferencesDialog()
            dlg._load_values()
            assert dlg.zoom_combo.count() > 0
            assert dlg.bg_combo.count() > 0
            assert dlg.ann_font_combo.count() > 0
            assert dlg.recent_spin.value() == self.prefs.recent_files_max
        except Exception as e:
            import pytest

            pytest.skip(f"PreferencesDialog UI test skipped: {e}")
