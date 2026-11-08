"""
UmbraEdit - Name Mention Detection
===================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Finds entity name mentions in text (tag, display name, name parts,
aliases) with word boundaries, case-insensitive matching, possessives
and hyphenated forms. Longest match wins. Also detects capitalised
words that match no entity ("names without a sheet"). Qt-free.
"""  # noqa

from __future__ import annotations

import hashlib
import re
import unicodedata

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from umbraedit.umbra.sheet import EntityRow, full_name

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable
# Minimum length of a matchable form; single letters are not names.
_MIN_FORM_LEN = 2

# Candidate words: word characters plus apostrophes and hyphens.
_WORD_RE = re.compile(r"(?<!\w)([\w\u2019'\u002d]+)", re.UNICODE)

# Sentence-ending punctuation or a line break ends a sentence.
_SENTENCE_END_RE = re.compile(r"[.!?…\u201d\u2019\"')\]]+\s*|\n+")


@dataclass
class Mention:
    """One mention of an entity form in a text.

    Attributes:
        start: Start offset in the original text.
        end: End offset (exclusive) in the original text.
        tag: The entity tag the mention resolves to.
        matchedForm: The exact form that matched.

    """

    start: int
    end: int
    tag: str
    matchedForm: str


@dataclass
class UntrackedName:
    """A capitalised word that matches no entity.

    Attributes:
        word: The word (title-cased for display).
        count: Number of occurrences.
        examples: Example contexts from the text.

    """

    word: str
    count: int
    examples: list[str] = field(default_factory=list)


##
#  Mention matching
##


def entityForms(row: EntityRow) -> list[str]:
    """Return the deduplicated matchable name forms of an entity.

    Forms are the tag, display name, name parts (fn, mn, ln, nick,
    title), the computed full name, and the aliases. Single-character
    forms are skipped.
    """
    attrs = row.attrs
    candidates = [
        row.tag,
        row.displayName,
        attrs.get("fn", ""),
        attrs.get("mn", ""),
        attrs.get("ln", ""),
        attrs.get("nick", ""),
        attrs.get("title", ""),
        full_name(attrs),
        *row.aliases,
    ]
    forms: list[str] = []
    for candidate in candidates:
        candidate = candidate.strip()
        if len(candidate) >= _MIN_FORM_LEN and candidate not in forms:
            forms.append(candidate)
    return forms


def _normForm(text: str) -> str:
    """Normalise a form for matching: NFKC and case-fold."""
    return unicodedata.normalize("NFKC", text).casefold()


@dataclass
class MentionMatcher:
    """Compiled matcher for a fixed set of entities."""

    pattern: re.Pattern[str]
    lookup: dict[str, list[tuple[str, str]]]  # normalised form -> [(tag, form)]


def _hasCjk(text: str) -> bool:
    """Return True when the text contains CJK ideographs or kana.

    CJK text has no word separators, so name matching cannot use word
    boundaries there; names match as substrings instead.
    """
    return any(
        0x3040 <= ord(char) <= 0x30FF or 0x3400 <= ord(char) <= 0x9FFF or 0xF900 <= ord(char) <= 0xFAFF for char in text
    )


def buildMatcher(entities: Iterable[EntityRow]) -> MentionMatcher | None:
    r"""Build a compiled mention matcher for the given entities.

    Returns None when no entity has a matchable form. A single
    alternation keeps the scan linear in the text size (R10); the
    alternatives are sorted longest-first so the longest form wins at
    each position. Word boundaries are `(?<!\\w)` / `(?!\\w)`: the
    apostrophes in possessives and the hyphens in hyphenated forms are
    not word characters, so "Uncle Bob's" and "Bob-faced" match. Forms
    containing CJK ideographs match without boundaries, because CJK
    text has no word separators.
    """
    lookup: dict[str, list[tuple[str, str]]] = {}
    regularForms: set[str] = set()
    cjkForms: set[str] = set()
    for row in entities:
        for form in entityForms(row):
            norm = _normForm(form)
            if not norm:
                continue
            normForms = cjkForms if _hasCjk(norm) else regularForms
            normForms.add(norm)
            entries = lookup.setdefault(norm, [])
            if not any(tag == row.tag and existing == form for tag, existing in entries):
                entries.append((row.tag, form))
    if not lookup:
        return None

    alternatives: list[str] = []
    if regularForms:
        escaped = sorted((re.escape(form) for form in regularForms), key=len, reverse=True)
        alternatives.append(rf"(?<!\w)(?:{'|'.join(escaped)})(?!\w)")
    if cjkForms:
        escaped = sorted((re.escape(form) for form in cjkForms), key=len, reverse=True)
        alternatives.append(rf"(?:{'|'.join(escaped)})")
    pattern = re.compile("|".join(alternatives), re.IGNORECASE | re.UNICODE)
    return MentionMatcher(pattern=pattern, lookup=lookup)


def findMentions(
    text: str,
    entities: Iterable[EntityRow],
    matcher: MentionMatcher | None = None,
) -> list[Mention]:
    """Find all entity mentions in a text.

    Matching is case-insensitive with NFKC-normalised forms, respects
    word boundaries, and tolerates possessives ("Bob's") and hyphens
    ("Bob-faced"). The longest form wins at each position ("Uncle Bob"
    before "Bob"). Matches never overlap. When several entities share
    the same longest form, one mention is emitted per entity.
    """
    if not text:
        return []
    if matcher is None:
        matcher = buildMatcher(list(entities))
    if matcher is None:
        return []

    mentions: list[Mention] = []
    for match in matcher.pattern.finditer(text):
        norm = _normForm(match.group(0))
        for tag, form in matcher.lookup.get(norm, []):
            mentions.append(Mention(start=match.start(), end=match.end(), tag=tag, matchedForm=form))
    mentions.sort(key=lambda m: (m.start, m.tag))
    return mentions


##
#  Per-document cache (P07 R3/R10)
##


def textHash(text: str) -> str:
    """Return the SHA-256 hash of a document text (cache key)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class MentionCache:
    """Cache of mention lists keyed by (key, textHash).

    Keys are document handles or any stable identifier. Unchanged
    documents reuse the cached result, so a project-wide re-scan only
    re-scans documents that changed (R10). The compiled matcher is
    rebuilt only when the entity forms change.
    """

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], list[Mention]] = {}
        self._matcher: MentionMatcher | None = None
        self._matcherKey: str = ""

    def matcherFor(self, entities: Iterable[EntityRow]) -> MentionMatcher | None:
        """Return the compiled matcher, rebuilding only when needed."""
        entityList = list(entities)
        formsKey = hashlib.sha256(
            repr(sorted((row.tag, form) for row in entityList for form in entityForms(row))).encode("utf-8")
        ).hexdigest()
        if self._matcher is None or formsKey != self._matcherKey:
            self._matcher = buildMatcher(entityList)
            self._matcherKey = formsKey
        return self._matcher

    def find(
        self,
        key: str,
        text: str,
        entities: Iterable[EntityRow],
    ) -> list[Mention]:
        """Return the mentions of one document, using the cache."""
        digest = textHash(text)
        cacheKey = (key, digest)
        cached = self._entries.get(cacheKey)
        if cached is not None:
            return cached
        matcher = self.matcherFor(entities)
        mentions = findMentions(text, [], matcher=matcher)
        self._entries[cacheKey] = mentions
        self._prune()
        return mentions

    def _prune(self) -> None:
        """Drop all entries when the cache grows past its bound."""
        if len(self._entries) > 4096:
            self._entries.clear()


def findMentionsProject(
    texts: list[tuple[str, str]],
    entities: Iterable[EntityRow],
    cache: MentionCache | None = None,
) -> dict[str, list[Mention]]:
    """Find mentions across a project's documents.

    `texts` is a list of (key, text) pairs. When a cache is given, only
    documents whose text hash changed are re-scanned (R10).
    """
    useCache = cache if cache is not None else MentionCache()
    result: dict[str, list[Mention]] = {}
    for key, text in texts:
        result[key] = useCache.find(key, text, entities)
    return result


##
#  Untracked names (P07 R6)
##


def _sentenceStarts(text: str) -> set[int]:
    """Return the offsets that start a new sentence or line."""
    starts = {0}
    for match in _SENTENCE_END_RE.finditer(text):
        starts.add(match.end())
    return starts


def findUntrackedNames(
    texts: str | Iterable[str],
    entities: Iterable[EntityRow],
    stoplist: Iterable[str] = (),
    minCount: int = 3,
) -> list[UntrackedName]:
    """Find capitalised words that match no entity.

    A word qualifies when it occurs at least `minCount` times across
    all texts AND at least once not at the start of a sentence (a word
    that only ever starts a sentence is not a name). Words on the
    stoplist (case-insensitive) and words covered by an entity mention
    or by a multi-word entity form are excluded.
    """
    if isinstance(texts, str):
        texts = [texts]
    textList = [text for text in texts if text]

    matcher = buildMatcher(list(entities))

    # Every form covered by an entity is tracked. Word-wise parts of
    # multi-word forms ("Uncle Bob" covers "Bob" and "Uncle") too.
    tracked: set[str] = set()
    if matcher is not None:
        for norm in matcher.lookup:
            tracked.add(norm)
            for part in norm.split():
                tracked.add(part)
    stops = {_normForm(word) for word in stoplist if word}

    counts: dict[str, int] = {}
    seenMidSentence: set[str] = set()
    examples: dict[str, str] = {}
    for text in textList:
        starts = _sentenceStarts(text)
        for match in _WORD_RE.finditer(text):
            word = match.group(1)
            if not word or not word[0].isupper():
                continue
            norm = _normForm(word)
            if not norm or norm in stops or norm in tracked:
                continue
            counts[norm] = counts.get(norm, 0) + 1
            if match.start() not in starts:
                seenMidSentence.add(norm)
                if norm not in examples:
                    contextStart = max(0, match.start() - 20)
                    contextEnd = min(len(text), match.end() + 20)
                    examples[norm] = text[contextStart:contextEnd].replace("\n", " ").strip()

    result: list[UntrackedName] = []
    for norm, count in counts.items():
        if count < minCount or norm not in seenMidSentence:
            continue
        result.append(UntrackedName(word=norm.title(), count=count, examples=[examples.get(norm, "")]))
    result.sort(key=lambda name: (-name.count, name.word))
    return result
