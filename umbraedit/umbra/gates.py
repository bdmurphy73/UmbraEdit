"""
UmbraEdit - Gate Engine
========================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

One engine that runs blocking checks before an operation changes
anything or produces output. A blocked operation does nothing.
"""  # noqa

from __future__ import annotations

import json
import logging

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Operations
OP_EDIT_SAVE = "edit.save"
OP_SYNC_PUSH = "sync.push"
OP_BACKUP_ROTATE = "backup.rotate"
OP_IMPORT_COMMIT = "import.commit"
OP_BUILD_RUN = "build.run"
OP_PREVIEW_BUILD = "preview.build"
OP_PUBLISH_PACKAGE = "publish.package"
OP_PUBLISH_HANDOFF = "publish.handoff"
OP_AUDIO_CHAPTER = "audio.chapter"
OP_AUDIO_BOOK = "audio.book"
OP_TRANSLATION_EXPORT = "translation.export"

ALL_OPERATIONS = frozenset({
    OP_EDIT_SAVE, OP_SYNC_PUSH, OP_BACKUP_ROTATE, OP_IMPORT_COMMIT,
    OP_BUILD_RUN, OP_PREVIEW_BUILD, OP_PUBLISH_PACKAGE, OP_PUBLISH_HANDOFF,
    OP_AUDIO_CHAPTER, OP_AUDIO_BOOK, OP_TRANSLATION_EXPORT,
})


@dataclass(frozen=True)
class Finding:
    ruleId: str
    severity: str  # "block" | "advisory"
    message: str
    fix: str
    handle: str | None = None
    line: int | None = None
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class GateRule:
    ruleId: str
    title: str
    operations: frozenset[str]
    defaultSeverity: str
    relaxable: bool
    check: Callable[[Any], Iterable[Finding]]


@dataclass(frozen=True)
class GateScope:
    project: Any
    handles: list[str] | None = None
    edition: str | None = None
    options: dict = field(default_factory=dict)
    # Set by runGates so checks can tell which operation is running
    operation: str = ""


@dataclass(frozen=True)
class GateReport:
    operation: str
    blocked: bool
    findings: list[Finding]
    ranAt: str


class GateBlockedError(Exception):
    def __init__(self, report: GateReport) -> None:
        self.report = report
        blocking = [f for f in report.findings if f.severity == "block"]
        messages = "; ".join(f"[{f.ruleId}] {f.message}" for f in blocking)
        super().__init__(f"Operation '{report.operation}' blocked: {messages}")


_gates: dict[str, GateRule] = {}


def registerGate(rule: GateRule) -> None:
    if rule.ruleId in _gates:
        raise ValueError(f"Gate rule '{rule.ruleId}' is already registered")
    _gates[rule.ruleId] = rule


def getGate(ruleId: str) -> GateRule | None:
    return _gates.get(ruleId)


def registeredGates() -> list[GateRule]:
    return sorted(_gates.values(), key=lambda r: r.ruleId)


def _effectiveSeverity(rule: GateRule, settings: Any) -> str:
    if rule.defaultSeverity == "block":
        if settings and settings.getBool(f"gates.relax.{rule.ruleId}", False):
            logger.warning("Attempt to relax blocking gate '%s' ignored", rule.ruleId)
        return "block"
    if rule.relaxable and settings and settings.getBool(f"gates.relax.{rule.ruleId}", False):
        return "none"
    return rule.defaultSeverity


def _runSingleRule(rule: GateRule, scope: GateScope, settings: Any) -> list[Finding]:
    severity = _effectiveSeverity(rule, settings)
    if severity == "none":
        return []
    try:
        findings = list(rule.check(scope))
        return [
            Finding(
                ruleId=f.ruleId, severity=severity, message=f.message,
                fix=f.fix, handle=f.handle, line=f.line, detail=f.detail,
            )
            for f in findings
        ]
    except Exception as exc:
        logger.exception("Gate rule '%s' raised an exception", rule.ruleId)
        return [
            Finding(
                ruleId="gateRuleFailed", severity="block",
                message=f"Gate rule '{rule.ruleId}' failed: {exc}",
                fix="Report this as a bug.",
                handle=None, line=None,
                detail={"failedRule": rule.ruleId, "error": str(exc)},
            )
        ]


def runGates(operation: str, scope: GateScope, settings: Any | None = None) -> GateReport:
    ranAt = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    scope = replace(scope, operation=operation)
    allFindings: list[Finding] = []
    for rule in sorted(_gates.values(), key=lambda r: r.ruleId):
        if operation not in rule.operations:
            continue
        allFindings.extend(_runSingleRule(rule, scope, settings))
    blocked = any(f.severity == "block" for f in allFindings)
    return GateReport(operation=operation, blocked=blocked, findings=allFindings, ranAt=ranAt)


def requireGates(operation: str, scope: GateScope, settings: Any | None = None) -> GateReport:
    report = runGates(operation, scope, settings)
    if report.blocked:
        raise GateBlockedError(report)
    return report


def reportToJson(report: GateReport) -> dict:
    return {
        "v": 1, "operation": report.operation, "blocked": report.blocked,
        "ranAt": report.ranAt,
        "findings": [
            {"ruleId": f.ruleId, "severity": f.severity, "message": f.message,
             "fix": f.fix, "handle": f.handle, "line": f.line, "detail": f.detail}
            for f in report.findings
        ],
    }


def saveReport(report: GateReport, projectPath: Path) -> Path:
    from umbraedit.umbra.paths import cacheDir
    cachePath = cacheDir(projectPath)
    reportPath = cachePath / "gate-report.json"
    data = reportToJson(report)
    text = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    reportPath.parent.mkdir(parents=True, exist_ok=True)
    reportPath.write_text(text, encoding="utf-8", newline="\n")
    return reportPath


def _checkEmptyDocumentIncluded(scope: GateScope) -> Iterable[Finding]:
    if not scope.project:
        return
    proj = scope.project
    contentPath = proj.storage.contentPath
    if not contentPath:
        return
    for item in proj.tree:
        if not item.isFileType() or not item.isDocumentLayout():
            continue
        if scope.handles and item.itemHandle not in scope.handles:
            continue
        docFile = contentPath / f"{item.itemHandle}.md"
        if docFile.is_file() and docFile.stat().st_size > 0:
            content = docFile.read_text(encoding="utf-8")
            parts = content.split("+++", 2)
            body = parts[2] if len(parts) >= 3 else content
            if not body.strip():
                yield Finding(
                    ruleId="emptyDocumentIncluded", severity="advisory",
                    message=f"Document '{item.itemName}' is included in the build but has no text.",
                    fix="Add text to the document or exclude it from the build.",
                    handle=item.itemHandle, line=None,
                    detail={"itemName": item.itemName},
                )


def _checkUnknownReferenceTag(scope: GateScope) -> Iterable[Finding]:
    if not scope.project:
        return
    proj = scope.project
    index = proj.index
    for item in proj.tree:
        if not item.isFileType():
            continue
        if scope.handles and item.itemHandle not in scope.handles:
            continue
        tHandle = item.itemHandle
        itemNode = index.getItemData(tHandle)
        if itemNode is None:
            continue
        for headingKey, heading in itemNode.headings():
            for tagName, keywordClasses in heading.references.items():
                if tagName not in index._tagsIndex:
                    item_ = proj.tree[tHandle]
                    itemName = item_.itemName if item_ else tHandle
                    keywords = ", ".join(keywordClasses)
                    yield Finding(
                        ruleId="unknownReferenceTag", severity="block",
                        message=f"'{keywords}' in '{itemName}' references tag '{tagName}' which does not exist.",
                        fix="Create the referenced note or remove the reference.",
                        handle=tHandle, line=heading.line,
                        detail={"tagName": tagName, "keywords": list(keywordClasses)},
                    )


registerGate(GateRule(
    ruleId="emptyDocumentIncluded", title="Empty Document Included",
    operations=frozenset({OP_BUILD_RUN, OP_PREVIEW_BUILD}),
    defaultSeverity="advisory", relaxable=True, check=_checkEmptyDocumentIncluded,
))

registerGate(GateRule(
    ruleId="unknownReferenceTag", title="Unknown Reference Tag",
    operations=frozenset({OP_BUILD_RUN, OP_PREVIEW_BUILD}),
    defaultSeverity="block", relaxable=False, check=_checkUnknownReferenceTag,
))

# UmbraEdit (P06/P07/P08): feature gate rules. Imported last so the built-in
# rules above are registered first; the feature modules import this one.
from umbraedit.umbra import (
    prongates,  # noqa: F401
    sheetgates,  # noqa: F401
    speakergates,  # noqa: F401
    voicematrixgates,  # noqa: F401
    voicegates,  # noqa: F401
)
