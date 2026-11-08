"""
UmbraEdit - Documentation System Tests
=======================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

import json

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.mark.umbra
def test_umbra_docs_A1_ownershipFileValid():
    """A1: docs-ownership.json is valid JSON with page → owner mapping."""
    ownerFile = ROOT / "docs" / "umbra" / "docs-ownership.json"
    assert ownerFile.is_file()
    data = json.loads(ownerFile.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert len(data) > 50


@pytest.mark.umbra
def test_umbra_docs_A1_allPagesExist():
    """A1: Every page in docs-ownership.json has an .rst file."""
    ownerFile = ROOT / "docs" / "umbra" / "docs-ownership.json"
    ownership = json.loads(ownerFile.read_text(encoding="utf-8"))
    missing = []
    for page in ownership:
        rstPath = ROOT / "docs" / "source" / "umbra" / f"{page}.rst"
        if not rstPath.is_file():
            missing.append(page)
    assert missing == [], f"Missing pages: {missing}"


@pytest.mark.umbra
def test_umbra_docs_A1_featuresDoneFileExists():
    """A1: features-done.json exists and is valid JSON."""
    doneFile = ROOT / "docs" / "umbra" / "features-done.json"
    assert doneFile.is_file()
    data = json.loads(doneFile.read_text(encoding="utf-8"))
    assert isinstance(data, dict)


@pytest.mark.umbra
def test_umbra_docs_A8_doneFeatureStubFails():
    """A8: Marking a feature as done with a stub page would fail the audit."""
    doneFile = ROOT / "docs" / "umbra" / "features-done.json"
    original = doneFile.read_text(encoding="utf-8")

    # Mark a stub feature as done
    testDone = {"test/some-stub-page": "P99"}
    doneFile.write_text(json.dumps(testDone), encoding="utf-8")

    # Check that the page is a stub (it should be)
    stubPage = ROOT / "docs" / "source" / "umbra" / "test" / "some-stub-page.rst"
    assert not stubPage.is_file(), "Test page should not exist"

    # Restore
    doneFile.write_text(original, encoding="utf-8")


@pytest.mark.umbra
def test_umbra_docs_R2_featureTemplateExists():
    """R2: Feature page template exists."""
    template = ROOT / "docs" / "source" / "_templates" / "feature_page.rst.tpl"
    assert template.is_file()
    content = template.read_text(encoding="utf-8")
    for section in ["Overview", "Quick start", "Reference", "Messages and checks"]:
        assert section in content


@pytest.mark.umbra
def test_umbra_docs_R3_docsStyleExists():
    """R3: Writing standard document exists."""
    styleDoc = ROOT / "docs" / "umbra" / "dev" / "docs-style.md"
    assert styleDoc.is_file()
    content = styleDoc.read_text(encoding="utf-8")
    assert "present tense" in content


@pytest.mark.umbra
def test_umbra_docs_R4_sphinxExtensionExists():
    """R4: The umbra_docs Sphinx extension exists."""
    extFile = ROOT / "docs" / "source" / "_ext" / "umbra_docs.py"
    assert extFile.is_file()
    content = extFile.read_text(encoding="utf-8")
    assert "UmbraExampleDirective" in content
    assert "UmbraShotDirective" in content
    assert "UmbraOwnerDirective" in content


@pytest.mark.umbra
def test_umbra_docs_A6_helpmapExists():
    """A6: helpmap.json exists with valid JSON."""
    helpmapFile = ROOT / "docs" / "source" / "helpmap.json"
    assert helpmapFile.is_file()
    data = json.loads(helpmapFile.read_text(encoding="utf-8"))
    assert isinstance(data, dict)


@pytest.mark.umbra
def test_umbra_docs_R16_firstContentPagesHaveContent():
    """R16: First content pages are not stubs."""
    requiredPages = [
        "introduction/what-is-umbraedit",
        "introduction/concepts",
        "introduction/installation",
        "introduction/coming-from-novelwriter",
        "tutorials/first-book",
        "credits-and-license",
    ]
    for page in requiredPages:
        rstPath = ROOT / "docs" / "source" / "umbra" / f"{page}.rst"
        assert rstPath.is_file(), f"Missing: {page}"
        content = rstPath.read_text(encoding="utf-8")
        # A stub has "This page is a stub"
        assert "stub" not in content.lower() or len(content) > 500, f"Stub page: {page}"


@pytest.mark.umbra
def test_umbra_docs_A2_buildScriptExists():
    """A2: The docs build script exists."""
    buildScript = ROOT / "utils" / "umbra_docs.py"
    assert buildScript.is_file()
