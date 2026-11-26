"""
UmbraEdit - Image Metadata Tests
=================================

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

import pytest

from umbraedit.constants import nwKeyWords, nwLabels
from umbraedit.core.imagemeta import (
    MAX_IMAGE_DIMENSION,
    ImageMetadata,
    ImageMetadataError,
    formatImageMetadata,
    parseImageMetadata,
    parseImageMetadataBits,
    referencedImagePaths,
    validateImagePath,
)


@pytest.mark.core
def testImageMeta_Constants():
    """Check that @Image is metadata, but not an insert-menu keyword."""
    assert nwKeyWords.IMAGE_KEY == "@Image"
    assert nwKeyWords.IMAGE_KEY in nwKeyWords.VALID_KEYS
    assert nwKeyWords.IMAGE_KEY in nwKeyWords.META_KEYS
    assert nwKeyWords.IMAGE_KEY not in nwKeyWords.ALL_KEYS
    assert nwLabels.KEY_NAME[nwKeyWords.IMAGE_KEY] == "Image"


@pytest.mark.core
@pytest.mark.parametrize(
    "path",
    [
        "assets/img/foo.png",
        "assets/img/foo.jpg",
        "assets/img/foo bar.png",
        "assets/img/foo-bar_2.png",
    ],
)
def testImageMeta_ValidatePath(path: str):
    """Check valid flat image paths."""
    assert validateImagePath(path) == path


@pytest.mark.core
@pytest.mark.parametrize(
    "path",
    [
        "",
        "   ",
        " assets/img/foo.png",
        "assets/img/foo.png ",
        "assets/img/foo.png/child.png",
        "assets/img/nested/foo.png",
        "assets/img/foo.jpeg",
        "assets/img/foo.PNG",
        "assets/img/.png",
        "assets/img/foo.gif",
        "assets/img/foo,bar.png",
        "assets/img/foo|bar.png",
        "assets/img/../foo.png",
        "assets/img/./foo.png",
        "assets//img/foo.png",
        "assets/images/foo.png",
        "img/foo.png",
        "/assets/img/foo.png",
        "C:/assets/img/foo.png",
        "assets\\img\\foo.png",
    ],
)
def testImageMeta_RejectInvalidPath(path: str):
    """Check that image paths are strictly flat assets/img files."""
    with pytest.raises(ImageMetadataError):
        validateImagePath(path)


@pytest.mark.core
def testImageMeta_RejectNonStringPath():
    """Check that an image path must be a string."""
    with pytest.raises(ImageMetadataError, match="must be a string"):
        validateImagePath(None)  # type: ignore


@pytest.mark.core
def testImageMeta_ParseCanonical():
    """Parse the canonical image metadata grammar."""
    metadata = parseImageMetadata("assets/img/foo.png | width=640 | height=480 | position=center")
    assert metadata == ImageMetadata(
        relativePath="assets/img/foo.png",
        width=640,
        height=480,
        position="center",
    )


@pytest.mark.core
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "assets/img/foo.jpg",
            ImageMetadata("assets/img/foo.jpg", None, None, "center"),
        ),
        (
            "assets/img/foo.jpg | width=640",
            ImageMetadata("assets/img/foo.jpg", 640, None, "center"),
        ),
        (
            "assets/img/foo.jpg | height=480",
            ImageMetadata("assets/img/foo.jpg", None, 480, "center"),
        ),
        (
            "assets/img/foo.jpg | position=left",
            ImageMetadata("assets/img/foo.jpg", None, None, "left"),
        ),
        (
            "assets/img/foo.jpg | position=right",
            ImageMetadata("assets/img/foo.jpg", None, None, "right"),
        ),
    ],
)
def testImageMeta_ParseDefaults(value: str, expected: ImageMetadata):
    """Check omitted dimensions and the default image position."""
    assert parseImageMetadata(value) == expected


@pytest.mark.core
@pytest.mark.parametrize(
    "value",
    [
        "assets/img/foo.png, assets/img/bar.png",
        "assets/img/foo.png | width=0",
        "assets/img/foo.png | width=-1",
        "assets/img/foo.png | width=1.5",
        "assets/img/foo.png | width=+640",
        "assets/img/foo.png | width=640px",
        "assets/img/foo.png | height=0",
        "assets/img/foo.png | height=-480",
        "assets/img/foo.png | height=4.8",
        "assets/img/foo.png | position=middle",
        "assets/img/foo.png | position=Center",
        "assets/img/foo.png | width=640 | width=320",
        "assets/img/foo.png | unknown=value",
        "assets/img/foo.png | width",
        "assets/img/foo.png | width=",
        "assets/img/foo.png | =640",
        "assets/img/foo.png | width=640=320",
        "assets/img/foo.png |",
        "assets/img/foo.png | width=640 |",
        "not/an/image.png",
        "assets/img/nested/foo.png",
    ],
)
def testImageMeta_RejectInvalidGrammar(value: str):
    """Check malformed image metadata values."""
    with pytest.raises(ImageMetadataError):
        parseImageMetadata(value)


@pytest.mark.core
def testImageMeta_ParseBits():
    """Check parsing an exact keyword/value pair."""
    metadata = parseImageMetadataBits(["@Image", "assets/img/foo.png | width=640"])
    assert metadata == ImageMetadata("assets/img/foo.png", 640, None, "center")

    with pytest.raises(ImageMetadataError, match="keyword/value pair"):
        parseImageMetadataBits(("@Image", "assets/img/foo.png"))  # type: ignore
    with pytest.raises(ImageMetadataError, match="exactly one value"):
        parseImageMetadataBits(["@Image"])
    with pytest.raises(ImageMetadataError, match="exactly one value"):
        parseImageMetadataBits(["@Image", "assets/img/foo.png", "extra"])
    with pytest.raises(ImageMetadataError, match="Expected the @Image keyword"):
        parseImageMetadataBits(["@cover", "assets/img/foo.png"])


@pytest.mark.core
def testImageMeta_Format():
    """Check canonical formatting and validation."""
    metadata = ImageMetadata("assets/img/foo.png", 640, 480, "right")
    assert formatImageMetadata(metadata) == ("assets/img/foo.png | width=640 | height=480 | position=right")
    assert formatImageMetadata(ImageMetadata("assets/img/foo.jpg")) == ("assets/img/foo.jpg | position=center")

    with pytest.raises(ImageMetadataError, match="ImageMetadata instance"):
        formatImageMetadata("assets/img/foo.png")  # type: ignore
    with pytest.raises(ImageMetadataError, match="positive integer"):
        formatImageMetadata(ImageMetadata("assets/img/foo.png", 0, None, "center"))
    with pytest.raises(ImageMetadataError, match="positive integer"):
        formatImageMetadata(ImageMetadata("assets/img/foo.png", None, True, "center"))
    with pytest.raises(ImageMetadataError, match="Invalid image position"):
        formatImageMetadata(ImageMetadata("assets/img/foo.png", None, None, "middle"))


@pytest.mark.core
def testImageMeta_DimensionLimits():
    """Check that image dimensions are bounded consistently."""
    assert parseImageMetadata(f"assets/img/foo.png | width={MAX_IMAGE_DIMENSION} | height=1") == ImageMetadata(
        "assets/img/foo.png", MAX_IMAGE_DIMENSION, 1, "center"
    )

    with pytest.raises(ImageMetadataError, match="not exceeding"):
        parseImageMetadata(f"assets/img/foo.png | width={MAX_IMAGE_DIMENSION + 1}")
    with pytest.raises(ImageMetadataError, match="not exceeding"):
        formatImageMetadata(ImageMetadata("assets/img/foo.png", MAX_IMAGE_DIMENSION + 1))

    # Do not let an unbounded decimal string reach Python's integer
    # conversion limit or later float arithmetic.
    with pytest.raises(ImageMetadataError, match="not exceeding"):
        parseImageMetadata("assets/img/foo.png | width=" + ("9" * 5000))


@pytest.mark.core
def testImageMeta_ReferencedPaths():
    """Check conservative extraction of referenced project images."""
    text = "\n".join([
        "@Cover: assets/img/bad.gif, assets/img/cover.png, assets/img/alternate.jpg",
        "@icon: assets/img/icon.png, assets/img/icon-alt.png",
        "@Image: assets/img/scene.png | width=0 | malformed",
        "@Image: assets/img/portrait.png | width=640 | height=480 | position=left",
        "@Image: assets/img/bad,path.png | width=640",
        "@Tag: assets/img/not-an-image.png",
    ])

    assert referencedImagePaths(text) == {
        "assets/img/cover.png",
        "assets/img/alternate.jpg",
        "assets/img/icon.png",
        "assets/img/icon-alt.png",
        "assets/img/scene.png",
        "assets/img/portrait.png",
    }
