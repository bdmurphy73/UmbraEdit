"""
UmbraEdit - Pronunciation Lexicon Export
=========================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Exports entity pronunciations as a W3C PLS 1.0 lexicon and a JSON
copy. Output is deterministic: lexemes are sorted by grapheme, then by
entity tag. Qt-free.
"""  # noqa

from __future__ import annotations

import json

from dataclasses import dataclass
from typing import Any
from xml.sax.saxutils import escape

from umbraedit.umbra.pronunciation import STATUS_AS_WRITTEN, STATUS_TODO

_PLS_TEMPLATE = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<lexicon version="1.0" '
    'xmlns="http://www.w3.org/2005/01/pronunciation-lexicon" '
    'alphabet="ipa" xml:lang="{lang}">\n'
    "{lexemes}"
    "</lexicon>\n"
)

_LEXEME_PHONEME = "  <lexeme><grapheme>{grapheme}</grapheme><phoneme>{phoneme}</phoneme></lexeme>\n"
_LEXEME_ALIAS = "  <lexeme><grapheme>{grapheme}</grapheme><alias>{alias}</alias></lexeme>\n"


@dataclass
class Lexeme:
    """One lexicon entry: a grapheme with its pronunciation."""

    grapheme: str
    respelling: str
    ipa: str
    tag: str
    source: str  # "entity" | "alias"
    forms: list[str]


def _entityPronStatus(row: Any) -> str:
    """Return the pron_status attribute of an entity row."""
    status = row.attrs.get("pron_status", STATUS_TODO)
    return status if status in (STATUS_AS_WRITTEN, STATUS_TODO, "confirmed") else STATUS_TODO


def collectLexemes(rows: list[Any], lang: str) -> list[Lexeme]:
    """Collect the lexemes for one language from entity rows.

    One lexeme per entity that has an `@pron` entry for the language
    (grapheme: display name, or the tag when there is no display name),
    plus one lexeme per alias with its own respelling. Entities marked
    `asWritten` and entities without any pronunciation are omitted.
    """
    lexemes: list[Lexeme] = []
    for row in rows:
        status = _entityPronStatus(row)
        if status == STATUS_AS_WRITTEN:
            continue

        entityPron = next(((resp, ipa) for pLang, resp, ipa in row.prons if pLang == lang), None)
        forms: list[str] = [row.tag]
        if row.displayName and row.displayName != row.tag:
            forms.append(row.displayName)

        if entityPron is not None:
            resp, ipa = entityPron
            grapheme = row.displayName or row.tag
            plainAliases = [alias for alias in row.aliases if alias not in row.aliasPron]
            forms.extend(plainAliases)
            lexemes.append(
                Lexeme(
                    grapheme=grapheme,
                    respelling=resp,
                    ipa=ipa,
                    tag=row.tag,
                    source="entity",
                    forms=forms,
                )
            )
        else:
            forms.extend(alias for alias in row.aliases if alias not in row.aliasPron)

        # Aliases with their own respelling are separate lexemes
        for alias in row.aliases:
            aliasResp = row.aliasPron.get(alias, "")
            if aliasResp:
                lexemes.append(
                    Lexeme(
                        grapheme=alias,
                        respelling=aliasResp,
                        ipa="",
                        tag=row.tag,
                        source="alias",
                        forms=[alias],
                    )
                )
    return lexemes


def exportLexicon(project: Any, lang: str) -> tuple[str, str]:
    """Export the pronunciation lexicon for one language.

    Returns (plsXml, json). The PLS is W3C PLS 1.0 with one lexeme per
    line, sorted by grapheme then entity tag. Entities with IPA use a
    `<phoneme>` element; entities with only a respelling use `<alias>`.
    The JSON mirrors the lexemes with sorted keys and compact
    separators.
    """
    rows = project.index.iterEntities()
    lexemes = collectLexemes(rows, lang)
    lexemes.sort(key=lambda lex: (lex.grapheme.casefold(), lex.grapheme, lex.tag))

    parts: list[str] = []
    for lex in lexemes:
        grapheme = escape(lex.grapheme)
        if lex.ipa:
            parts.append(_LEXEME_PHONEME.format(grapheme=grapheme, phoneme=escape(lex.ipa)))
        elif lex.respelling:
            parts.append(_LEXEME_ALIAS.format(grapheme=grapheme, alias=escape(lex.respelling)))
    plsXml = _PLS_TEMPLATE.format(lang=escape(lang), lexemes="".join(parts))

    entries = [
        {
            "tag": lex.tag,
            "forms": lex.forms,
            "respelling": lex.respelling,
            "ipa": lex.ipa,
            "source": lex.source,
        }
        for lex in lexemes
        if lex.respelling or lex.ipa
    ]
    jsonData = {"v": 1, "lang": lang, "entries": entries}
    jsonText = json.dumps(jsonData, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    return plsXml, jsonText
