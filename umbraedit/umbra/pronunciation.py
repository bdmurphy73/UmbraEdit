"""
UmbraEdit - Pronunciation of Names
===================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Pronunciation data for entity notes: per-language `@pron` entries with
a respelling and an optional IPA transcription, the `pron_status`
attribute, IPA validation, and an optional external preview command.
Qt-free.
"""  # noqa

from __future__ import annotations

import hashlib
import logging
import subprocess

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from umbraedit.umbra.jsonio import readJson, writeJson
from umbraedit.umbra.sheetedit import SheetEdit, applySheetEdit, parseSheetNote

if TYPE_CHECKING:  # pragma: no cover
    from umbraedit.umbra.sheet import EntityRow

logger = logging.getLogger(__name__)

# Item classes that hold names needing a pronunciation (P07 R2). PLOT
# and TIMELINE are not names. The setting `pron.classes` overrides this
# once a list-type setting exists (see GAPS.md).
PRON_CLASSES: tuple[str, ...] = ("CHARACTER", "WORLD", "OBJECT", "ENTITY")

# Values of the `pron_status` attribute
STATUS_CONFIRMED = "confirmed"
STATUS_AS_WRITTEN = "asWritten"
STATUS_TODO = "todo"
PRON_STATUSES = (STATUS_CONFIRMED, STATUS_AS_WRITTEN, STATUS_TODO)

# Allowed codepoint ranges and single characters for IPA text. The
# feature's list misses common IPA letters that live in Latin-1, Latin
# Extended-A and the Greek block (ae, eth, eng, theta, ...), so they
# are explicitly allowed here.
_IPA_RANGES: tuple[tuple[int, int], ...] = (
    (0x0250, 0x02AF),  # IPA extensions
    (0x1D00, 0x1DBF),  # phonetic extensions
    (0x02B0, 0x02BF),  # modifier letters (aspiration, labialisation)
    (0x02C8, 0x02D1),  # stress and length marks
    (0x0300, 0x036F),  # combining diacritics
    (0x035C, 0x035C),  # tie bar below
    (0x0361, 0x0361),  # tie bar above
)
_IPA_EXTRA: frozenset[str] = frozenset("æðøœŋθβγçχ")
_IPA_ASCII: frozenset[str] = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
_IPA_DELIMS: frozenset[str] = frozenset("/[]")


@dataclass
class Pron:
    """A pronunciation for one entity and language.

    Attributes:
        respelling: Free-text respelling (stress in capitals, syllables
            with hyphens).
        ipa: IPA transcription without the surrounding slashes, when
            recorded.
        status: The `pron_status` value: confirmed, asWritten or todo.
        source: Where the pronunciation comes from: "entity" (an
            `@pron` entry) or "alias" (an alias respelling).

    """

    respelling: str = ""
    ipa: str = ""
    status: str = STATUS_TODO
    source: str = "entity"


@dataclass
class EntityPron:
    """Pronunciation data parsed from one entity note body."""

    tag: str = ""
    displayName: str = ""
    aliasProns: dict[str, str] = field(default_factory=dict)
    prons: dict[str, tuple[str, str]] = field(default_factory=dict)  # lang -> (resp, ipa)
    status: str = STATUS_TODO


@dataclass
class PronSpan:
    """A mention of a named entity together with its pronunciation.

    Produced by `pronunciationSpans` and consumed by the utterance
    index (P11) so the audio package carries per-utterance
    pronunciation.
    """

    start: int
    end: int
    tag: str
    respelling: str
    ipa: str


def validateIpa(text: str) -> list[str]:
    """Validate an IPA transcription and return a list of errors.

    Allowed: IPA extensions (U+0250 to U+02AF), phonetic extensions
    (U+1D00 to U+1DBF), modifier letters, stress and length marks, tie
    bars, combining diacritics (U+0300 to U+036F), ASCII letters, and
    the delimiters `/` and `[ ]`. Delimiters must be balanced. The
    empty string is valid (no IPA recorded).
    """
    errors: list[str] = []
    if not text:
        return errors

    slashPositions: list[int] = []
    bracketStack: list[int] = []
    for i, char in enumerate(text):
        code = ord(char)
        if char in _IPA_ASCII or char in _IPA_EXTRA:
            continue
        if any(lo <= code <= hi for lo, hi in _IPA_RANGES):
            continue
        if char == "/":
            slashPositions.append(i)
            continue
        if char == "[":
            bracketStack.append(i)
            continue
        if char == "]":
            if not bracketStack:
                errors.append(f"Unexpected ']' at position {i}")
            else:
                bracketStack.pop()
            continue
        if char == " ":
            continue
        errors.append(f"Character '{char}' (U+{code:04X}) at position {i} is not valid IPA")

    errors.extend(f"Unbalanced '[' at position {pos}" for pos in bracketStack)
    if len(slashPositions) % 2 != 0:
        pos = slashPositions[-1]
        errors.append(f"Unbalanced '/' at position {pos}")
    return errors


def _stripDelims(text: str) -> str:
    """Strip matching surrounding IPA delimiters (`/.../` or `[...]`)."""
    if len(text) >= 2 and text[0] == "/" and text[-1] == "/":
        return text[1:-1].strip()
    if len(text) >= 2 and text[0] == "[" and text[-1] == "]":
        return text[1:-1].strip()
    return text


def _normName(text: str) -> str:
    """Normalise a display name for staleness tracking."""
    return " ".join(text.split()).casefold()


def parsePronNote(body: str) -> EntityPron:
    """Extract pronunciation data from an entity note body.

    Reads `@tag`, `@alias` (with optional respelling), `@pron` and the
    `pron_status` attribute. Body means the text after the `+++`
    header, when one exists.
    """
    data = EntityPron()
    for line in body.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("@"):
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        if key == "@tag" and not data.tag:
            name, _, display = value.partition("|")
            data.tag = name.strip()
            data.displayName = display.strip()
        elif key == "@alias":
            alias, _, pron = value.partition("|")
            alias = alias.strip()
            if alias:
                pron = pron.strip()
                if pron:
                    data.aliasProns[alias] = pron
        elif key == "@pron":
            lang, _, rest = value.partition("|")
            lang = lang.strip()
            if not lang:
                continue
            respelling, _, ipaRaw = rest.partition("|")
            ipa = _stripDelims(ipaRaw.strip())
            data.prons[lang] = (respelling.strip(), ipa)
        elif key == "@attr":
            attrKey, _, attrValue = value.partition("|")
            if attrKey.strip() == "pron_status":
                status = attrValue.strip()
                if status in PRON_STATUSES:
                    data.status = status
    return data


class Pronunciations:
    """Pronunciation store for one project.

    Reads through the entity index and writes through the note files
    (atomically, via `sheetedit`). The GUI layer routes writes through
    the open editor document when the note is open.
    """

    def __init__(self, project: Any) -> None:
        self._project = project

    ##
    #  Reads
    ##

    def getPronunciation(self, tag: str, lang: str) -> Pron | None:
        """Return the pronunciation for a tag and language, or None.

        Resolution order: an `@pron` entry for the language (source
        entity), then an alias respelling (source alias), then an empty
        Pron when the status is asWritten, else None.
        """
        row = self._project.index.getEntity(tag)
        if row is None:
            return None
        status = row.attrs.get("pron_status", STATUS_TODO)
        if status not in PRON_STATUSES:
            status = STATUS_TODO
        for pronLang, respelling, ipa in row.prons:
            if pronLang == lang:
                return Pron(respelling=respelling, ipa=ipa, status=status, source="entity")
        for respelling in row.aliasPron.values():
            if respelling:
                return Pron(respelling=respelling, ipa="", status=status, source="alias")
        if status == STATUS_AS_WRITTEN:
            return Pron(respelling="", ipa="", status=status, source="entity")
        return None

    ##
    #  Writes
    ##

    def setPronunciation(self, tag: str, lang: str, respelling: str, ipa: str = "") -> list[str]:
        """Set the `@pron` entry for a tag and language.

        Writes the line into the entity note, sets
        `@attr: pron_status | confirmed`, and re-indexes the note.
        Validates the IPA first and returns the validation errors
        without writing when there are any. Returns an empty list on
        success.
        """
        ipaErrors = validateIpa(ipa)
        if ipaErrors:
            return ipaErrors

        handle = self._noteHandle(tag)
        if handle is None:
            return [f"Unknown entity tag: {tag}"]

        text = self._readNote(handle)
        if text is None:
            return [f"Could not read the note for tag: {tag}"]

        edit = parseSheetNote(text)
        prons = [(pLang, pResp, pIpa) for pLang, pResp, pIpa in edit.prons if pLang != lang]
        prons.append((lang, respelling.strip(), ipa.strip()))
        edit.prons = prons
        edit.attrs["pron_status"] = STATUS_CONFIRMED

        if not self._writeNote(handle, text, edit):
            return [f"Could not write the note for tag: {tag}"]
        return []

    def markAsWritten(self, tag: str) -> bool:
        """Set `@attr: pron_status | asWritten` on the entity note."""
        handle = self._noteHandle(tag)
        if handle is None:
            return False
        text = self._readNote(handle)
        if text is None:
            return False
        edit = parseSheetNote(text)
        edit.attrs["pron_status"] = STATUS_AS_WRITTEN
        return self._writeNote(handle, text, edit)

    ##
    #  Note access
    ##

    def _noteHandle(self, tag: str) -> str | None:
        """Return the note handle for a tag, or None."""
        return self._project.index.entityHandle(tag)

    def _readNote(self, tHandle: str) -> str | None:
        """Read the raw note text for a handle."""
        storage = self._project.storage
        contentPath = storage.contentPath
        if not contentPath:
            return None
        docFile = contentPath / f"{tHandle}.md"
        if not docFile.is_file():
            return None
        return docFile.read_text(encoding="utf-8")

    def _writeNote(self, tHandle: str, text: str, edit: SheetEdit) -> bool:
        """Apply a sheet edit and write the note atomically."""
        contentPath = self._project.storage.contentPath
        if not contentPath:
            return False
        docFile = contentPath / f"{tHandle}.md"
        newText = applySheetEdit(text, edit)
        try:
            tmpFile = docFile.with_suffix(".md.tmp")
            with open(tmpFile, "w", encoding="utf-8", newline="\n") as fOut:
                fOut.write(newText)
                fOut.flush()
            tmpFile.replace(docFile)
        except OSError:
            logger.exception("Could not write the entity note '%s'", docFile)
            return False
        # Refresh the index so subsequent reads see the new data
        try:
            self._project.index.reIndexHandle(tHandle)
        except Exception:
            logger.exception("Could not re-index the entity note '%s'", tHandle)
        return True

    ##
    #  Staleness tracking
    ##

    def updatePronSeen(self) -> bool:
        """Record the current name/pronunciation state in the cache.

        Called after a successful export or audio build so the
        `pronunciationStale` gate only flags changes made afterwards.
        """
        seen: dict[str, dict[str, str]] = {}
        for row in self._project.index.iterEntities():
            if row.attrs.get("pron_status", STATUS_TODO) != STATUS_CONFIRMED:
                continue
            seen[row.tag] = {
                "name": hashlib.sha256(_normName(row.displayName or row.tag).encode("utf-8")).hexdigest(),
                "pron": hashlib.sha256(repr(sorted(row.prons)).encode("utf-8")).hexdigest(),
            }
        data = {"v": 1, "seen": seen}
        cachePath = self._seenPath()
        if cachePath is None:
            return False
        writeJson(cachePath, data)
        return True

    def staleEntities(self) -> list[str]:
        """Return the tags whose display name changed since the last
        `updatePronSeen`. Entities with no cache entry are not stale.
        """
        cachePath = self._seenPath()
        if cachePath is None or not cachePath.is_file():
            return []
        try:
            data = readJson(cachePath)
        except Exception:
            return []
        seen = data.get("seen", {}) if isinstance(data, dict) else {}
        stale: list[str] = []
        for row in self._project.index.iterEntities():
            entry = seen.get(row.tag)
            if not isinstance(entry, dict):
                continue
            nameHash = hashlib.sha256(_normName(row.displayName or row.tag).encode("utf-8")).hexdigest()
            if entry.get("name") != nameHash and row.prons:
                stale.append(row.tag)
        return stale

    def _seenPath(self) -> Path | None:
        """Return the pron-seen cache path, or None."""
        storagePath = self._project.storage.storagePath
        if not storagePath:
            return None
        from umbraedit.umbra.paths import pronSeenFile

        return pronSeenFile(Path(storagePath))


##
#  Preview command (P07 R5)
##


def runPronPreview(command: list[str], text: str, ipa: str) -> tuple[bool, str]:
    """Run the user-configured preview command on a name.

    `command` is an argument list where `{text}` and `{ipa}` are
    replaced by the respelling and the IPA. It runs without a shell.
    Returns (ok, output). No network access; the command is entirely
    user-configured and none by default.
    """
    if not command:
        return False, "No preview command configured (setting pron.previewCommand)."
    args = [arg.replace("{text}", text).replace("{ipa}", ipa) for arg in command]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=30, check=False)
    except FileNotFoundError:
        return False, f"Preview command not found: {args[0]}"
    except subprocess.TimeoutExpired:
        return False, "Preview command timed out."
    ok = result.returncode == 0
    output = (result.stdout + result.stderr).strip()
    return ok, output


##
#  Module-level convenience wrappers
##


def getPronunciation(project: Any, tag: str, lang: str) -> Pron | None:
    """Return the pronunciation for a tag and language (see the class)."""
    return Pronunciations(project).getPronunciation(tag, lang)


def setPronunciation(project: Any, tag: str, lang: str, respelling: str, ipa: str = "") -> list[str]:
    """Set a pronunciation on the entity note (see the class)."""
    return Pronunciations(project).setPronunciation(tag, lang, respelling, ipa)


def markAsWritten(project: Any, tag: str) -> bool:
    """Mark an entity's name as read as written (see the class)."""
    return Pronunciations(project).markAsWritten(tag)


def pronunciationSpans(text: str, lang: str, project: Any) -> list[PronSpan]:
    """Return the pronounced name spans in a text.

    Finds the entity mentions in the text and attaches the
    pronunciation for `lang`: the entity's `@pron` entry, or the
    respelling of the alias form that matched. Spans without any
    pronunciation data are skipped; the gates report those.
    """
    from umbraedit.umbra.mentions import findMentions

    rows = project.index.iterEntities()
    mentions = findMentions(text, rows)
    rowByTag = {row.tag: row for row in rows}

    spans: list[PronSpan] = []
    for mention in mentions:
        row = rowByTag.get(mention.tag)
        if row is None:
            continue
        respelling = ""
        ipa = ""
        if mention.matchedForm in row.aliasPron:
            respelling = row.aliasPron[mention.matchedForm]
        else:
            for pronLang, pronResp, pronIpa in row.prons:
                if pronLang == lang:
                    respelling, ipa = pronResp, pronIpa
                    break
        if not respelling and not ipa:
            continue
        spans.append(
            PronSpan(
                start=mention.start,
                end=mention.end,
                tag=mention.tag,
                respelling=respelling,
                ipa=ipa,
            )
        )
    return spans


def entityHasPron(row: EntityRow, lang: str) -> bool:
    """Return True when the entity row has a pronunciation for a language."""
    return any(pronLang == lang for pronLang, _, _ in row.prons)
