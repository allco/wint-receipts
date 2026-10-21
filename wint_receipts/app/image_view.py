"""Zoomable page image: wheel to zoom, drag to pan, double-click to fit."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView


class ImageView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._item = QGraphicsPixmapItem()
        self._item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._scene.addItem(self._item)
        self.setScene(self._scene)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._fit = True

    def set_png(self, png: bytes | None) -> None:
        pix = QPixmap()
        if png:
            pix.loadFromData(png, "PNG")
        self._item.setPixmap(pix)
        self._scene.setSceneRect(self._item.boundingRect())
        self.fit()

    def fit(self) -> None:
        self._fit = True
        self.resetTransform()
        if not self._item.pixmap().isNull():
            self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)

    def zoom(self, factor: float) -> None:
        self._fit = False
        self.scale(factor, factor)

    def wheelEvent(self, event):  # noqa: N802 - Qt API
        self.zoom(1.25 if event.angleDelta().y() > 0 else 0.8)

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        self.fit()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if self._fit:
            self.fit()
