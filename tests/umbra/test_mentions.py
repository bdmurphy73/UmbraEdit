"""
UmbraEdit - Mention Detection Tests
====================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

import random
import time

from pathlib import Path

import pytest

from umbraedit.umbra.mentions import (
    MentionCache,
    UntrackedName,
    buildMatcher,
    entityForms,
    findMentions,
    findMentionsProject,
    findUntrackedNames,
    textHash,
)
from umbraedit.umbra.sheet import EntityRow


def _rows() -> list[EntityRow]:
    """Standard entity set for mention tests."""
    return [
        EntityRow(
            tag="Katniss",
            handle="h1",
            kind="character",
            displayName="Katniss Everdeen",
            aliases=["Uncle Bob", "Catnip"],
            attrs={"fn": "Katniss", "ln": "Everdeen", "nick": "Kat", "title": "Miss"},
        ),
        EntityRow(
            tag="Hollow",
            handle="h2",
            kind="place",
            displayName="The Hollow",
            aliases=[],
            attrs={"description": "A valley"},
        ),
        EntityRow(
            tag="Bob",
            handle="h3",
            kind="character",
            displayName="Bob Vega",
            aliases=["Bobby"],
            attrs={"fn": "Bob", "ln": "Vega"},
        ),
    ]


@pytest.mark.umbra
def test_mentions_R3_possessive_longestWins():
    """R3/A2: "Uncle Bob's" matches "Uncle Bob", not "Bob"."""
    text = "Uncle Bob\u2019s truck"
    mentions = findMentions(text, _rows())
    assert len(mentions) == 1
    assert text[mentions[0].start : mentions[0].end] == "Uncle Bob"
    assert mentions[0].tag == "Katniss"
    assert mentions[0].matchedForm == "Uncle Bob"


@pytest.mark.umbra
def test_mentions_R3_straightPossessive():
    """R3: straight apostrophe possessives also match."""
    mentions = findMentions("Bob's truck", _rows())
    assert len(mentions) == 1
    assert mentions[0].tag == "Bob"


@pytest.mark.umbra
def test_mentions_R3_wordBoundaries():
    """R3: no matches inside longer words."""
    assert findMentions("Bobcat is a cat", _rows()) == []
    assert findMentions("Holloway street", _rows()) == []


@pytest.mark.umbra
def test_mentions_R3_hyphenated():
    """R3: hyphenated compounds count as mentions."""
    mentions = findMentions("a Bob-faced lie", _rows())
    assert len(mentions) == 1
    assert mentions[0].tag == "Bob"


@pytest.mark.umbra
def test_mentions_R3_caseInsensitive():
    """R3: matching is case-insensitive."""
    mentions = findMentions("katniss EVERDEEN", _rows())
    assert len(mentions) == 1
    assert mentions[0].tag == "Katniss"


@pytest.mark.umbra
def test_mentions_R3_accentsAndUnicode():
    """R3: accented and CJK text works."""
    rows = [EntityRow(tag="Sofía", handle="h4", kind="character")]
    mentions = findMentions("SOFÍA arrived.", rows)
    assert len(mentions) == 1
    rows = [EntityRow(tag="老王", handle="h5", kind="character")]
    mentions = findMentions("老王来了。", rows)
    assert len(mentions) == 1


@pytest.mark.umbra
def test_mentions_R3_allFormSources():
    """R3: tag, display name, fn, ln, nick, full name, alias all match."""
    text = "Katniss, Katniss Everdeen, Kat, Miss Katniss Everdeen, Catnip, Bob Vega."
    mentions = findMentions(text, _rows())
    tags = [m.tag for m in mentions]
    assert tags.count("Katniss") == 5
    assert tags.count("Bob") == 1


@pytest.mark.umbra
def test_mentions_R3_sharedForm_allEntities():
    """R3: two entities sharing a form both get a mention."""
    rows = _rows()
    rows[0].aliases.append("Bobby")  # shared with Bob
    mentions = findMentions("Bobby waved", rows)
    assert {m.tag for m in mentions} == {"Katniss", "Bob"}


@pytest.mark.umbra
def test_mentions_R3_emptyText():
    """R3: empty text gives no mentions."""
    assert findMentions("", _rows()) == []
    assert findMentions("Nothing here", []) == []


@pytest.mark.umbra
def test_mentions_R3_entityForms_deduped():
    """R3: entityForms deduplicates and skips single letters."""
    row = EntityRow(
        tag="Bob",
        handle="h",
        kind="character",
        displayName="Bob",
        aliases=["Bob", "Bobby"],
        attrs={"fn": "Bob", "nick": "B"},
    )
    forms = entityForms(row)
    assert forms == ["Bob", "Bobby"]


@pytest.mark.umbra
def test_mentions_R10_cache_sameText():
    """R10: the cache returns the identical list for unchanged text."""
    cache = MentionCache()
    entities = _rows()
    first = cache.find("doc1", "Uncle Bob waved at Bob.", entities)
    second = cache.find("doc1", "Uncle Bob waved at Bob.", entities)
    assert first is second  # cached identity
    assert len(first) == 2


@pytest.mark.umbra
def test_mentions_R10_cache_invalidation():
    """R10: changed text re-scans; unchanged text is cached."""
    cache = MentionCache()
    entities = _rows()
    cache.find("doc1", "Uncle Bob waved.", entities)
    cache.find("doc2", "Bob waved.", entities)
    # doc1 unchanged → same list object
    again = cache.find("doc1", "Uncle Bob waved.", entities)
    assert again == cache._entries[("doc1", textHash("Uncle Bob waved."))]
    # doc1 changed → new scan
    changed = cache.find("doc1", "Bob Vega waved.", entities)
    assert any(m.tag == "Bob" for m in changed)


@pytest.mark.umbra
def test_mentions_R10_projectScan(tmp_path: Path):
    """R10: first full scan under 20 s; cached re-scan under 1 s."""
    rng = random.Random(20261108)
    filler = ["the", "and", "wind", "over", "under", "said", "went", "cold"]
    entities: list[EntityRow] = []
    for i in range(500):
        entities.append(
            EntityRow(
                tag=f"Person{i:04d}",
                handle=f"h{i:04d}",
                kind="character",
                displayName=f"Name{i:04d} Family{i:04d}",
                aliases=[f"Nick{i:04d}"],
                attrs={"fn": f"Name{i:04d}", "ln": f"Family{i:04d}"},
            )
        )
    texts: list[tuple[str, str]] = []
    for doc in range(4):
        words: list[str] = []
        for _ in range(100_000):
            if rng.random() < 0.004:
                i = rng.randrange(500)
                words.append(rng.choice([f"Name{i:04d}", f"Family{i:04d}", f"Nick{i:04d}"]))
            else:
                words.append(rng.choice(filler))
        texts.append((f"doc{doc}", " ".join(words) + "."))

    cache = MentionCache()
    start = time.perf_counter()
    result = findMentionsProject(texts, entities, cache)
    elapsedFirst = time.perf_counter() - start
    total = sum(len(v) for v in result.values())
    assert total > 0

    # Only one document changed on the second pass
    changedTexts = [(key, text + " Name0001 waved.") if key == "doc1" else (key, text) for key, text in texts]
    start = time.perf_counter()
    findMentionsProject(changedTexts, entities, cache)
    elapsedCached = time.perf_counter() - start

    # Budgets with the CI margin already included by the feature
    assert elapsedFirst < 20.0, f"first scan took {elapsedFirst:.2f} s"
    assert elapsedCached < 1.0, f"cached scan took {elapsedCached:.2f} s"


@pytest.mark.umbra
def test_mentions_R6_untrackedNames_basic():
    """R6: a capitalised word appearing enough times is reported."""
    text = " ".join(["Then Rillifane gave", "the gift."] * 4)
    names = findUntrackedNames(text, [], stoplist=[])
    assert any(n.word == "Rillifane" and n.count >= 4 for n in names)


@pytest.mark.umbra
def test_mentions_R6_sentenceInitialOnly_excluded():
    """R6: a word that only ever starts a sentence is not a name."""
    text = "The king said so. The king did that. The king went home. "
    names = findUntrackedNames(text, [], stoplist=[])
    # "The" is capitalised but only sentence-initial (plus 'The' after '.')
    assert not any(n.word == "The" for n in names)


@pytest.mark.umbra
def test_mentions_R6_minCount():
    """R6: words below the occurrence threshold are skipped."""
    text = "Rillifane appeared once and Rillifane smiled."
    names = findUntrackedNames(text, [], stoplist=[], minCount=3)
    assert not any(n.word == "Rillifane" for n in names)


@pytest.mark.umbra
def test_mentions_R6_stoplist():
    """R6: stoplisted words are excluded."""
    text = " ".join(["Met Gale yesterday, Gale smiled."] * 3)
    assert any(n.word == "Gale" for n in findUntrackedNames(text, [], stoplist=[]))
    assert not any(n.word == "Gale" for n in findUntrackedNames(text, [], stoplist=["gale"]))


@pytest.mark.umbra
def test_mentions_R6_entityForms_tracked():
    """R6: words covered by an entity (or its forms) are not reported."""
    rows = _rows()
    text = " ".join(["Katniss waved. Katniss smiled. Katniss left. Kat unwrapped it. Bob too."])
    names = findUntrackedNames(text, rows, stoplist=[])
    assert not any(n.word.lower() in ("katniss", "everdeen", "kat", "bob") for n in names)


@pytest.mark.umbra
def test_mentions_R6_untrackedName_fields():
    """R6: UntrackedName carries word, count and examples."""
    name = UntrackedName(word="Rillifane", count=5, examples=["gave Rillifane the"])
    assert name.word == "Rillifane"
    assert name.count == 5
    assert name.examples


@pytest.mark.umbra
def test_mentions_R3_matcherNone():
    """R3: buildMatcher returns None for entities without forms."""
    assert buildMatcher([]) is None
    assert buildMatcher([EntityRow(tag="Q", handle="h", kind="character")]) is None


@pytest.mark.umbra
def test_mentions_R3_curlyQuotesText():
    """R3: curly quotes around names do not break matching."""
    mentions = findMentions("\u201cUncle Bob,\u201d she said.", _rows())
    assert len(mentions) == 1
    assert mentions[0].tag == "Katniss"
