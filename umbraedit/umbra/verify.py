"""
UmbraEdit - Verification and Repair
=====================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

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

import datetime
import hashlib
import logging

from dataclasses import dataclass
from pathlib import Path  # noqa: TC003

from umbraedit.umbra.paths import historyDir, lostFoundDir
from umbraedit.umbra.voiceline import parseVoiceLine

logger = logging.getLogger(__name__)

# Severity levels
SEVERITY_INFO = "info"
SEVERITY_REPAIR = "repair"
SEVERITY_BLOCK = "block"
SEVERITY_ADVISORY = "advisory"
SEVERITY_UNRECOVERABLE = "unrecoverable"

# Rule IDs
RULE_MALFORMED_HEADER = "annotationMalformedHeader"
RULE_MISSING_TAG = "missingTag"
RULE_INVALID_ENCODING = "invalidEncoding"
RULE_UNEXPECTED_TRAILING_WS = "trailingWhitespace"
RULE_NO_FINAL_NEWLINE = "noFinalNewline"
RULE_NULL_BYTE = "nullByte"
RULE_INVALID_ANNOTATION = "invalidAnnotation"
RULE_EXTERNAL_EDIT = "externalEdit"
RULE_UNKNOWN_HEADING_KEYWORD = "unknownHeadingKeyword"
RULE_DUPLICATE_KEYWORD = "duplicateKeyword"
RULE_INVALID_KEYWORD_VALUE = "invalidKeywordValue"
RULE_TAG_FILENAME_MISMATCH = "tagFilenameMismatch"
RULE_EMPTY_BODY = "emptyBody"
RULE_ORPHAN_FILE = "orphanFile"
RULE_MISSING_FILE = "missingFile"
RULE_UNEXPECTED_EOF = "unexpectedEOF"
RULE_MISSING_CONTENT_PATH = "missingContentPath"

# Rule titles for display
RULE_TITLES: dict[str, str] = {
    RULE_MALFORMED_HEADER: "Malformed Header",
    RULE_MISSING_TAG: "Missing Tag",
    RULE_INVALID_ENCODING: "Invalid Encoding",
    RULE_UNEXPECTED_TRAILING_WS: "Trailing Whitespace",
    RULE_NO_FINAL_NEWLINE: "Missing Final Newline",
    RULE_NULL_BYTE: "Null Byte",
    RULE_INVALID_ANNOTATION: "Invalid Annotation",
    RULE_EXTERNAL_EDIT: "External Edit",
    RULE_UNKNOWN_HEADING_KEYWORD: "Unknown Heading Keyword",
    RULE_DUPLICATE_KEYWORD: "Duplicate Keyword",
    RULE_INVALID_KEYWORD_VALUE: "Invalid Keyword Value",
    RULE_TAG_FILENAME_MISMATCH: "Tag Filename Mismatch",
    RULE_EMPTY_BODY: "Empty Body",
    RULE_ORPHAN_FILE: "Orphan File",
    RULE_MISSING_FILE: "Missing File",
    RULE_UNEXPECTED_EOF: "Unexpected End of File",
    RULE_MISSING_CONTENT_PATH: "Missing Content Path",
}

# Fix messages for each rule
RULE_FIXES: dict[str, str] = {
    RULE_MALFORMED_HEADER: "Repair the header block or remove the document.",
    RULE_MISSING_TAG: "Add a @tag line to the document header.",
    RULE_INVALID_ENCODING: "Re-encode the file as UTF-8 or restore from backup.",
    RULE_UNEXPECTED_TRAILING_WS: "Remove trailing whitespace from the last line.",
    RULE_NO_FINAL_NEWLINE: "Add a trailing newline to the file.",
    RULE_NULL_BYTE: "Remove null bytes or restore from backup.",
    RULE_INVALID_ANNOTATION: "Correct or remove the invalid annotation.",
    RULE_EXTERNAL_EDIT: "Accept the external change and update the hash.",
    RULE_UNKNOWN_HEADING_KEYWORD: "Remove the unknown keyword or correct it.",
    RULE_DUPLICATE_KEYWORD: "Remove the duplicate keyword.",
    RULE_INVALID_KEYWORD_VALUE: "Correct the keyword value.",
    RULE_TAG_FILENAME_MISMATCH: "Rename the file to match the tag or change the tag.",
    RULE_EMPTY_BODY: "Add text content to the document.",
    RULE_ORPHAN_FILE: "Move to lost+found or remove from project.",
    RULE_MISSING_FILE: "Restore from history or recreate the document.",
    RULE_UNEXPECTED_EOF: "Restore from backup or rewrite the document.",
    RULE_MISSING_CONTENT_PATH: "Ensure the project folder structure is correct.",
}


@dataclass(frozen=True)
class Problem:
    """A problem found during verification.

    Attributes:
        ruleId: The rule that was violated.
        severity: "info", "advisory", "repair", "block", "unrecoverable".
        message: Human-readable description.
        fix: Suggested fix.
        handle: Document handle, if applicable.
        line: Line number, if applicable.
        detail: Additional details.

    """

    ruleId: str
    severity: str
    message: str
    fix: str
    handle: str | None = None
    line: int | None = None
    detail: dict | None = None


@dataclass(frozen=True)
class VerifyReport:
    """Result of verifying a project.

    Attributes:
        projectPath: Path to the project.
        findings: List of findings from verification.
        ranAt: UTC ISO 8601 timestamp when verification ran.

    """

    projectPath: str
    findings: list[Problem]
    ranAt: str

    @property
    def blocked(self) -> bool:
        """Return True if any finding has severity 'block'."""
        return any(f.severity == "block" for f in self.findings)


def _sha256File(path: Path) -> str:
    """Return the SHA-256 hash of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _sha256Text(text: str) -> str:
    """Return the SHA-256 hash of text content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _readDocumentText(path: Path) -> str | None:
    """Read a document file as UTF-8 text. Returns None if unreadable."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None
    except OSError:
        return None


def _parseHeader(text: str) -> tuple[dict[str, str], str] | None:
    """Parse the document header (+++ block).

    Returns (metadata_dict, body_text) or None if no valid header.
    """
    if not text.startswith("+++\n"):
        return None

    lines = text.split("\n")
    close_idx = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "+++":
            close_idx = i
            break

    if close_idx < 0:
        return None

    header_lines = lines[1:close_idx]
    body = "\n".join(lines[close_idx + 1 :])

    meta: dict[str, str] = {}
    for line in header_lines:
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()

    return meta, body


def _parseVoiceLineForVerify(line: str) -> bool:
    """Check if a %Voice: line is valid using the P05 parser."""
    try:
        return parseVoiceLine(line) is not None
    except Exception:
        return False


def verifyDocument(docFile: Path) -> list[Problem]:
    """Verify a single document file.

    Args:
        docFile: Path to the .md document file.

    Returns:
        List of Problem objects describing any issues found.

    """
    findings: list[Problem] = []

    # Read the file
    raw_text = _readDocumentText(docFile)
    if raw_text is None:
        findings.append(
            Problem(
                ruleId=RULE_INVALID_ENCODING,
                severity="block",
                message=f"Document '{docFile.name}' is not valid UTF-8.",
                fix="Re-encode the file as UTF-8 or restore from backup.",
                handle=docFile.stem,
                detail={"file": docFile.name},
            )
        )
        return findings

    # Check for NUL bytes
    if "\x00" in raw_text:
        findings.append(
            Problem(
                ruleId=RULE_NULL_BYTE,
                severity="block",
                message=f"Document '{docFile.name}' contains null bytes.",
                fix="Remove null bytes or restore from backup.",
                handle=docFile.stem,
                detail={"file": docFile.name},
            )
        )
        return findings

    # Parse header
    parsed = _parseHeader(raw_text)
    if parsed is None:
        findings.append(
            Problem(
                ruleId=RULE_MALFORMED_HEADER,
                severity="block",
                message=f"Document '{docFile.name}' has no valid header block.",
                fix="Add a valid +++ header block to the document.",
                handle=docFile.stem,
                detail={"file": docFile.name},
            )
        )
        return findings

    meta, body = parsed

    # Check for required @tag
    tag = meta.get("tag", "")
    if not tag:
        findings.append(
            Problem(
                ruleId=RULE_MISSING_TAG,
                severity="block",
                message=f"Document '{docFile.name}' has no '@tag' in header.",
                fix="Add '@tag: <tagname>' to the document header.",
                handle=docFile.stem,
                detail={"file": docFile.name},
            )
        )
        return findings

    # Check tag matches filename
    if tag != docFile.stem:
        findings.append(
            Problem(
                ruleId=RULE_TAG_FILENAME_MISMATCH,
                severity="block",
                message=f"Tag '{tag}' does not match filename '{docFile.stem}'.",
                fix=f"Rename file to '{tag}.md' or change tag to '{docFile.stem}'.",
                handle=tag,
                detail={"tag": tag, "filename": docFile.stem},
            )
        )

    # Check for trailing whitespace on the last content line
    lines = raw_text.split("\n")
    # Find the last non-empty line (skip trailing empty from final newline)
    lastContentLine = ""
    for line in reversed(lines):
        if line:
            lastContentLine = line
            break
    if lastContentLine and lastContentLine.endswith((" ", "\t")):
        findings.append(
            Problem(
                ruleId=RULE_UNEXPECTED_TRAILING_WS,
                severity=SEVERITY_ADVISORY,
                message=f"Document '{docFile.name}' has trailing whitespace.",
                fix="Remove trailing whitespace from the last line.",
                handle=docFile.stem,
                detail={"file": docFile.name},
            )
        )

    # Check for missing final newline
    if not raw_text.endswith("\n"):
        findings.append(
            Problem(
                ruleId=RULE_NO_FINAL_NEWLINE,
                severity=SEVERITY_ADVISORY,
                message=f"Document '{docFile.name}' does not end with a newline.",
                fix="Add a trailing newline to the file.",
                handle=docFile.stem,
                detail={"file": docFile.name},
            )
        )

    # Check for empty body
    if not body.strip():
        findings.append(
            Problem(
                ruleId=RULE_EMPTY_BODY,
                severity=SEVERITY_ADVISORY,
                message=f"Document '{docFile.name}' has no body text.",
                fix="Add text content to the document.",
                handle=docFile.stem,
                detail={"file": docFile.name, "tag": tag},
            )
        )

    # Check %Voice: lines
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped.startswith("%Voice:"):
            try:
                if not _parseVoiceLineForVerify(line):
                    findings.append(
                        Problem(
                            ruleId=RULE_INVALID_ANNOTATION,
                            severity=SEVERITY_ADVISORY,
                            message=f"Document '{docFile.name}' has an invalid %Voice: line.",
                            fix="Correct or remove the malformed %Voice: line.",
                            handle=docFile.stem,
                            detail={"file": docFile.name, "line": stripped[:50]},
                        )
                    )
                    break
            except Exception:
                findings.append(
                    Problem(
                        ruleId=RULE_INVALID_ANNOTATION,
                        severity=SEVERITY_ADVISORY,
                        message=f"Document '{docFile.name}' has an invalid %Voice: line.",
                        fix="Correct or remove the malformed %Voice: line.",
                        handle=docFile.stem,
                        detail={"file": docFile.name, "line": stripped[:50]},
                    )
                )
                break

    return findings


def verifyProject(projectPath: Path) -> VerifyReport:
    """Verify all documents in a project.

    Args:
        projectPath: Path to the project directory.

    Returns:
        VerifyReport with findings from all documents.

    """
    findings: list[Problem] = []

    contentPath = projectPath / "content"
    if not contentPath.is_dir():
        findings.append(
            Problem(
                ruleId=RULE_MISSING_CONTENT_PATH,
                severity="block",
                message=f"Project content path not found: {contentPath}",
                fix="Ensure the project folder structure is correct.",
                detail={"projectPath": str(projectPath)},
            )
        )
        return VerifyReport(projectPath=str(projectPath), findings=findings, ranAt="")

    for docFile in sorted(contentPath.glob("*.md")):
        doc_findings = verifyDocument(docFile)
        findings.extend(doc_findings)

    ranAt = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return VerifyReport(projectPath=str(projectPath), findings=findings, ranAt=ranAt)


def verifyAndRepair(projectPath: Path) -> VerifyReport:
    """Verify and repair a project.

    First runs verification, then attempts to fix any issues found.
    """
    report = verifyProject(projectPath)

    # Process each finding and attempt repair
    for finding in report.findings:
        _attemptFix(projectPath, finding)

    # Re-verify after repairs
    return verifyProject(projectPath)


def _attemptFix(projectPath: Path, finding: Problem) -> None:
    """Attempt to fix a finding."""
    contentPath = projectPath / "content"
    if not contentPath.is_dir():
        return

    ruleId = finding.ruleId
    handle = finding.handle or ""

    if ruleId == RULE_EXTERNAL_EDIT:
        # External edit - update the hash, accept the change
        docFile = contentPath / f"{handle}.md"
        if docFile.is_file():
            try:
                new_hash = _sha256File(docFile)
                text = docFile.read_text(encoding="utf-8")
                parts = text.split("+++", 2)
                if len(parts) >= 3:
                    header = parts[1]
                    body = parts[2]
                    new_header_lines = []
                    for line in header.split("\n"):
                        if line.strip().startswith("textHash:"):
                            new_header_lines.append(f"textHash: {new_hash}")
                        else:
                            new_header_lines.append(line)
                    new_header = "\n".join(new_header_lines)
                    new_text = f"+++\n{new_header}\n+++\n{body}"
                    docFile.write_text(new_text, encoding="utf-8", newline="\n")
            except Exception:
                logger.exception("Could not update hash for %s", docFile)

    elif ruleId == RULE_UNEXPECTED_EOF:
        # Truncated file - try to restore from backup
        _restoreFromBackup(projectPath, handle)

    elif ruleId == RULE_NULL_BYTE:
        # Null bytes - try to restore from backup
        _restoreFromBackup(projectPath, handle)

    elif ruleId == RULE_ORPHAN_FILE:
        # Move to lost+found
        _moveToLostFound(projectPath, handle)

    elif ruleId == RULE_MISSING_FILE:
        # Restore from history if available
        _restoreFromBackup(projectPath, handle)


def _restoreFromBackup(projectPath: Path, handle: str) -> None:
    """Restore a document from backup (last history revision)."""
    contentPath = projectPath / "content"
    docFile = contentPath / f"{handle}.md"

    history_dir = historyDir(projectPath) / handle
    if not history_dir.is_dir():
        return

    backup_files = sorted(history_dir.glob("*.nwd.gz"), reverse=True)
    if not backup_files:
        return

    backup_file = backup_files[0]
    try:
        import gzip

        with gzip.open(backup_file, "rb") as f:
            backup_text = f.read().decode("utf-8")
        docFile.write_text(backup_text, encoding="utf-8", newline="\n")
    except Exception:
        logger.exception("Could not restore from backup %s", backup_file)


def _moveToLostFound(projectPath: Path, handle: str) -> None:
    """Move an orphan file to the lost+found folder."""
    contentPath = projectPath / "content"
    docFile = contentPath / f"{handle}.md"
    if not docFile.is_file():
        return

    lostFound = lostFoundDir(projectPath)
    dest = lostFound / f"{handle}.md"
    try:
        docFile.rename(dest)
    except OSError:
        logger.exception("Could not move %s to lost+found", docFile)
