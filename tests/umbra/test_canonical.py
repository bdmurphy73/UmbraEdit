"""UmbraEdit - Canonical Text Hash Tests.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""

from __future__ import annotations

import pytest

from umbraedit.umbra.canonical import canonicalTextHash


@pytest.mark.umbra
def test_umbra_canonical_R6_sameText():
    """R6: Same text without annotations gives the same hash."""
    text = "Hello world.\n\nMore text."
    assert canonicalTextHash(text) == canonicalTextHash(text)


@pytest.mark.umbra
def test_umbra_canonical_A5_annotationRemoved():
    """A5: %Voice: lines are removed from the hash."""
    text1 = "Hello world."
    text2 = "%Voice: spk=Bob\nHello world."
    assert canonicalTextHash(text1) == canonicalTextHash(text2)


@pytest.mark.umbra
def test_umbra_canonical_A5_attrTagsRemoved():
    """A5: [attr] tags are removed but content is kept."""
    text1 = "said Uncle Bob."
    text2 = "[attr]said Uncle Bob.[/attr]"
    assert canonicalTextHash(text1) == canonicalTextHash(text2)


@pytest.mark.umbra
def test_umbra_canonical_A5_attrDropRemoved():
    """A5: [attr:drop] tags are removed."""
    text1 = "Some text."
    text2 = "[attr:drop]Some text.[/attr]"
    assert canonicalTextHash(text1) == canonicalTextHash(text2)


@pytest.mark.umbra
def test_umbra_canonical_A5_uttTagsRemoved():
    """A5: [utt] tags are removed but content is kept."""
    text1 = "Two speakers here."
    text2 = "[utt:spk=Ana;tone=happy:2]Two speakers here.[/utt]"
    assert canonicalTextHash(text1) == canonicalTextHash(text2)


@pytest.mark.umbra
def test_umbra_canonical_A5_changeAnnotationNoHashChange():
    """A5: Changing only a speaker or tone does not change the hash."""
    text1 = "%Voice: spk=Bob tone=calm\n\u201cHello,\u201d he said."
    text2 = "%Voice: spk=Ana tone=excited:3\n\u201cHello,\u201d he said."
    assert canonicalTextHash(text1) == canonicalTextHash(text2)


@pytest.mark.umbra
def test_umbra_canonical_R6_contentChangeChangesHash():
    """R6: Changing the actual text content changes the hash."""
    text1 = "Hello world."
    text2 = "Hello there."
    assert canonicalTextHash(text1) != canonicalTextHash(text2)


@pytest.mark.umbra
def test_umbra_canonical_R6_unicodeText():
    """R6: Unicode text (Chinese, curly quotes) is hashed correctly."""
    text = "\u201c\u4f60\u597d\u201d he said. Caf\u00e9."
    assert len(canonicalTextHash(text)) == 64


@pytest.mark.umbra
def test_umbra_canonical_R6_emptyText():
    """R6: Empty text gives a valid hash."""
    assert len(canonicalTextHash("")) == 64
