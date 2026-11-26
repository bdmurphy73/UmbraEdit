"""
UmbraEdit - Project Image Assets
================================

This file is a part of UmbraEdit.

Copyright (C) 2026 Veronica Berglyd Olsen and UmbraEdit contributors.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""  # noqa

from __future__ import annotations

import logging

from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from umbraedit import SHARED
from umbraedit.core.imageimport import (
    ProjectImage,
    listProjectImages,
    readProjectImageByPath,
)
from umbraedit.core.imagemeta import MAX_IMAGE_DIMENSION

if TYPE_CHECKING:
    from umbraedit.core.safeio import FileIdentity
    from umbraedit.guimain import GuiMain

logger = logging.getLogger(__name__)


class GuiImageAssets(QDockWidget):
    """Dock widget for managing images stored in a project."""

    addImageRequest = pyqtSignal()
    deleteImageRequest = pyqtSignal(object)
    selectImageRequest = pyqtSignal(object, int, int, str)

    def __init__(self, mainGui: GuiMain) -> None:
        super().__init__(mainGui)

        self.mainGui = mainGui
        self.setObjectName("ImageAssetsDock")
        self.setWindowTitle(self.tr("Image Assets"))

        self._images: list[ProjectImage] = []
        self._intrinsicSizes: dict[FileIdentity, tuple[int, int]] = {}
        self._sizes: dict[FileIdentity, tuple[int, int]] = {}
        self._positions: dict[FileIdentity, str] = {}
        self._updatingControls = False

        self._buildUi()
        self._connectSignals()
        self.clearAssets()

    ##
    #  Methods
    ##

    def clearAssets(self) -> None:
        """Clear the asset list and all cached display data."""
        self._images = []
        self._intrinsicSizes.clear()
        self._sizes.clear()
        self._positions.clear()
        self.imageList.clear()
        self._setControlsEnabled(False)

    def refreshAssets(self) -> None:
        """Reload the project image assets from disk."""
        if not SHARED.hasProject:
            self.clearAssets()
            return

        selectedPath = self.currentImage.relativePath if (current := self.currentImage) else None
        try:
            images = listProjectImages(SHARED.project)
        except Exception as exc:
            logger.error("Could not list project image assets", exc_info=exc)
            SHARED.error(self.tr("Could not read the project image assets."), exc=exc)
            self.clearAssets()
            return

        self._images = images
        self._intrinsicSizes.clear()
        self.imageList.blockSignals(True)
        self.imageList.clear()

        selectedItem = None
        for image in images:
            item = QListWidgetItem(self._imageIcon(image), image.path.name)
            item.setData(Qt.ItemDataRole.UserRole, image)
            item.setToolTip(image.relativePath)
            self.imageList.addItem(item)
            if image.relativePath == selectedPath:
                selectedItem = item

        self.imageList.blockSignals(False)
        if selectedItem is not None:
            self.imageList.setCurrentItem(selectedItem)
        elif self.imageList.count() > 0:
            self.imageList.setCurrentRow(0)
        else:
            self._setControlsEnabled(False)

    def selectAsset(self, relativePath: str) -> None:
        """Select an asset by its project-relative path."""
        for row in range(self.imageList.count()):
            item = self.imageList.item(row)
            if item is None:
                continue
            image = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(image, ProjectImage) and image.relativePath == relativePath:
                self.imageList.setCurrentItem(item)
                self.imageList.scrollToItem(item)
                return

    def updateTheme(self) -> None:
        """Update the icons displayed by the asset manager."""
        self.addButton.setIcon(SHARED.theme.getIcon("add:add"))
        self.deleteButton.setIcon(SHARED.theme.getIcon("remove:remove"))
        self.selectButton.setIcon(SHARED.theme.getIcon("btn_insert:action"))
        self.refreshAssets()

    ##
    #  Properties
    ##

    @property
    def currentImage(self) -> Optional[ProjectImage]:
        """Return the currently selected project image."""
        item = self.imageList.currentItem()
        if item is None:
            return None
        image = item.data(Qt.ItemDataRole.UserRole)
        return image if isinstance(image, ProjectImage) else None

    ##
    #  Internal Functions
    ##

    def _buildUi(self) -> None:
        """Build the dock user interface."""
        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.descriptionLabel = QLabel(
            self.tr("Images stored in this project can be inserted into the current document."),
            content,
        )
        self.descriptionLabel.setWordWrap(True)
        layout.addWidget(self.descriptionLabel)

        self.imageList = QListWidget(content)
        self.imageList.setIconSize(QSize(48, 32))
        self.imageList.setAlternatingRowColors(True)
        self.imageList.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        layout.addWidget(self.imageList, 1)

        sizeBox = QFormLayout()
        sizeBox.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.widthSpin = QSpinBox(content)
        self.widthSpin.setRange(1, MAX_IMAGE_DIMENSION)
        self.widthSpin.setSuffix(" px")
        self.widthSpin.setKeyboardTracking(False)
        sizeBox.addRow(self.tr("Width"), self.widthSpin)

        self.heightSpin = QSpinBox(content)
        self.heightSpin.setRange(1, MAX_IMAGE_DIMENSION)
        self.heightSpin.setSuffix(" px")
        self.heightSpin.setKeyboardTracking(False)
        sizeBox.addRow(self.tr("Height"), self.heightSpin)

        self.positionCombo = QComboBox(content)
        self.positionCombo.addItem(self.tr("Left"), "left")
        self.positionCombo.addItem(self.tr("Center"), "center")
        self.positionCombo.addItem(self.tr("Right"), "right")
        sizeBox.addRow(self.tr("Position"), self.positionCombo)

        layout.addLayout(sizeBox)

        buttonBox = QHBoxLayout()
        self.addButton = QPushButton(SHARED.theme.getIcon("add:add"), self.tr("Add"), content)
        self.deleteButton = QPushButton(SHARED.theme.getIcon("remove:remove"), self.tr("Delete"), content)
        self.selectButton = QPushButton(SHARED.theme.getIcon("btn_insert:action"), self.tr("Select"), content)
        buttonBox.addWidget(self.addButton)
        buttonBox.addWidget(self.deleteButton)
        buttonBox.addWidget(self.selectButton)
        layout.addLayout(buttonBox)

        self.setWidget(content)

    def _connectSignals(self) -> None:
        """Connect the dock signals."""
        self.addButton.clicked.connect(self.addImageRequest)
        self.deleteButton.clicked.connect(self._deleteImage)
        self.selectButton.clicked.connect(self._selectImage)
        self.imageList.currentItemChanged.connect(self._selectionChanged)
        self.imageList.itemDoubleClicked.connect(self._itemDoubleClicked)
        self.widthSpin.valueChanged.connect(self._widthChanged)
        self.heightSpin.valueChanged.connect(self._heightChanged)
        self.positionCombo.currentIndexChanged.connect(self._positionChanged)

    def _imageIcon(self, image: ProjectImage) -> QIcon:
        """Return a thumbnail icon for a project image."""
        try:
            data = readProjectImageByPath(SHARED.project, image.relativePath)
            thumbnail = QImage.fromData(data.data)
            if not thumbnail.isNull():
                pixmap = QPixmap.fromImage(thumbnail)
                return QIcon(
                    pixmap.scaled(
                        self.imageList.iconSize(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        except Exception as exc:
            logger.debug("Could not load thumbnail for '%s': %s", image.relativePath, exc)

        return SHARED.theme.getIcon("view:action")

    def _intrinsicSize(self, image: ProjectImage) -> Optional[tuple[int, int]]:
        """Return and cache the intrinsic dimensions of a project image."""
        if size := self._intrinsicSizes.get(image.identity):
            return size
        try:
            data = readProjectImageByPath(SHARED.project, image.relativePath)
            thumbnail = QImage.fromData(data.data)
            if thumbnail.isNull() or thumbnail.width() <= 0 or thumbnail.height() <= 0:
                return None
            size = (thumbnail.width(), thumbnail.height())
        except Exception as exc:
            logger.debug("Could not read dimensions for '%s': %s", image.relativePath, exc)
            return None

        self._intrinsicSizes[image.identity] = size
        return size

    def _selectionChanged(self, _current: Optional[QListWidgetItem], _previous: Optional[QListWidgetItem]) -> None:
        """Update the controls when the selected image changes."""
        image = self.currentImage
        if image is None:
            self._setControlsEnabled(False)
            return

        intrinsic = self._intrinsicSize(image)
        if intrinsic is None:
            self._setControlsEnabled(False)
            self.deleteButton.setEnabled(True)
            return

        cachedSize = self._sizes.get(image.identity)
        if cachedSize is None:
            size = self._fitImageDimensions(intrinsic)
        else:
            # Re-apply the saved width to the current source dimensions.
            # This preserves the aspect ratio if the file contents changed
            # while retaining the user's chosen scale.
            size = self._fitImageDimensions(intrinsic, requestedWidth=cachedSize[0])
        position = self._positions.get(image.identity, "center")
        self._updatingControls = True
        try:
            self.widthSpin.setValue(size[0])
            self.heightSpin.setValue(size[1])
            index = self.positionCombo.findData(position)
            self.positionCombo.setCurrentIndex(max(index, 0))
        finally:
            self._updatingControls = False

        self._setControlsEnabled(True)

    def _setControlsEnabled(self, state: bool) -> None:
        """Enable or disable the image detail controls."""
        self.widthSpin.setEnabled(state)
        self.heightSpin.setEnabled(state)
        self.positionCombo.setEnabled(state)
        self.deleteButton.setEnabled(self.currentImage is not None)
        self.selectButton.setEnabled(state)

    def _widthChanged(self, value: int) -> None:
        """Update the height when the width changes, preserving aspect ratio."""
        if self._updatingControls:
            return
        image = self.currentImage
        intrinsic = self._intrinsicSize(image) if image is not None else None
        if image is None or intrinsic is None:
            return

        width, height = self._fitImageDimensions(intrinsic, requestedWidth=value)
        self._updatingControls = True
        try:
            self.widthSpin.setValue(width)
            self.heightSpin.setValue(height)
        finally:
            self._updatingControls = False
        self._sizes[image.identity] = (width, height)

    def _heightChanged(self, value: int) -> None:
        """Update the width when the height changes, preserving aspect ratio."""
        if self._updatingControls:
            return
        image = self.currentImage
        intrinsic = self._intrinsicSize(image) if image is not None else None
        if image is None or intrinsic is None:
            return

        width, height = self._fitImageDimensions(intrinsic, requestedHeight=value)
        self._updatingControls = True
        try:
            self.widthSpin.setValue(width)
            self.heightSpin.setValue(height)
        finally:
            self._updatingControls = False
        self._sizes[image.identity] = (width, height)

    def _positionChanged(self, _index: int) -> None:
        """Store the selected page position for the current image."""
        if self._updatingControls:
            return
        if image := self.currentImage:
            self._positions[image.identity] = str(self.positionCombo.currentData())

    @staticmethod
    def _fitImageDimensions(
        intrinsic: tuple[int, int],
        *,
        requestedWidth: Optional[int] = None,
        requestedHeight: Optional[int] = None,
    ) -> tuple[int, int]:
        """Fit an image size while preserving its aspect ratio.

        The requested dimension is honoured when possible. If the linked
        dimension would exceed the shared maximum, the requested dimension
        is reduced so that both values remain valid without distorting the
        source image.
        """
        intrinsicWidth, intrinsicHeight = intrinsic
        if intrinsicWidth <= 0 or intrinsicHeight <= 0:
            return 1, 1

        if requestedWidth is not None and requestedHeight is not None:
            width = max(1, min(MAX_IMAGE_DIMENSION, requestedWidth))
            height = max(1, min(MAX_IMAGE_DIMENSION, requestedHeight))
            scale = min(width / intrinsicWidth, height / intrinsicHeight)
        elif requestedWidth is not None:
            width = max(1, min(MAX_IMAGE_DIMENSION, requestedWidth))
            scale = min(width / intrinsicWidth, MAX_IMAGE_DIMENSION / intrinsicHeight)
        elif requestedHeight is not None:
            height = max(1, min(MAX_IMAGE_DIMENSION, requestedHeight))
            scale = min(height / intrinsicHeight, MAX_IMAGE_DIMENSION / intrinsicWidth)
        else:
            scale = min(
                1.0,
                MAX_IMAGE_DIMENSION / intrinsicWidth,
                MAX_IMAGE_DIMENSION / intrinsicHeight,
            )

        return (
            max(1, min(MAX_IMAGE_DIMENSION, round(intrinsicWidth * scale))),
            max(1, min(MAX_IMAGE_DIMENSION, round(intrinsicHeight * scale))),
        )

    def _deleteImage(self) -> None:
        """Request deletion of the selected image."""
        if image := self.currentImage:
            self.deleteImageRequest.emit(image)

    def _selectImage(self) -> None:
        """Request insertion of the selected image."""
        image = self.currentImage
        if image is None:
            return
        self.selectImageRequest.emit(
            image,
            self.widthSpin.value(),
            self.heightSpin.value(),
            str(self.positionCombo.currentData()),
        )

    def _itemDoubleClicked(self, item: QListWidgetItem) -> None:
        """Insert an image when its list entry is double-clicked."""
        if item is self.imageList.currentItem():
            self._selectImage()
