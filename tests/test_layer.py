import pytest

from PySide6.QtCore import QPoint
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import (
    QWidget,
)

# from imagep.layers import DeepzoomImage as dz


@pytest.fixture
def create_transform():
    return QTransform()


def test_working():
    assert True


class TestPySide:
    def test_widget(self, qtbot):
        a = QWidget()
        # qtbot.addWidget(a)
        assert isinstance(a, QWidget)


class TestTransforms:
    def setup_method(self, method):
        self.t = QTransform()
        self.pos = QPoint(1, 1)

    def test_translate(self, qtbot):
        # SImple translation
        self.t.reset()
        self.t.translate(1, 1)
        assert self.t.map(self.pos) == QPoint(2, 2)

    def test_scale(self, qtbot):
        # SImple translation
        self.t.reset()
        self.t.scale(2.0, 2.0)
        assert self.t.map(self.pos) == QPoint(2, 2)

    def test_translate_then_scale(self, qtbot):
        # Translate & Rotate
        self.t.reset()
        self.t.rotate(90)  # CCW
        self.t.translate(1, 1)
        assert self.t.map(self.pos) == QPoint(-2, 2)

    def test_composit1(self, qtbot):
        # Translate & Rotate
        self.t.reset()
        self.t.scale(2.0, 2.0)
        self.t.translate(1, 1)
        self.t.rotate(90)  # CCW
        pos2 = self.t.map(self.pos)
        assert pos2 == QPoint(0, 4)
        assert self.t.inverted()[0].map(pos2) == self.pos

    def test_offset_rotate_offset(self, qtbot):
        self.t.reset()
        self.t.translate(0, 1)
        self.t.rotate(90)
        self.t.translate(0, -1)
        pos2 = self.t.map(self.pos)
        assert pos2 == QPoint(0, 2)
        assert self.t.inverted()[0].map(pos2) == self.pos
