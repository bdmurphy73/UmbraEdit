"""
UmbraEdit - Command Line Interface
==================================

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

import argparse
import json
import logging
import sys

from pathlib import Path
from typing import Any

from umbraedit.cli.api import DEFAULT_PORT, cmd_serve

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_BLOCKED = 2
EXIT_ERROR = 1


def _load_project(project_path: str | Path) -> Any:
    """Open a project without Qt."""
    from umbraedit.core.project import NWProject

    project = NWProject()
    if not project.openProject(str(project_path)):
        print(f"Error: cannot open project '{project_path}'", file=sys.stderr)
        sys.exit(EXIT_ERROR)
    return project


def _write_json(data: Any) -> None:
    """Write JSON to stdout with sorted keys and trailing newline."""
    text = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    sys.stdout.write(text)


def cmd_verify(args: argparse.Namespace) -> int:
    """Run the verify command."""
    project_path = Path(args.project)
    if not project_path.is_dir():
        print(f"Error: project path not found: {project_path}", file=sys.stderr)
        return EXIT_ERROR

    project = _load_project(project_path)

    from umbraedit.umbra.verify import verifyProject

    try:
        result = verifyProject(project.storage.storagePath)  # type: ignore[arg-type]
    except Exception as exc:
        print(f"Error: verification failed: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        _write_json(result.to_dict() if hasattr(result, "to_dict") else result)  # type: ignore[attr-defined]
    else:
        print(f"Verify: {'OK' if getattr(result, 'valid', False) else 'FAILED'}")
        for issue in getattr(result, "issues", []):
            print(f"  - {issue}")

    return EXIT_OK if getattr(result, "valid", False) else EXIT_ERROR


def cmd_gates(args: argparse.Namespace) -> int:
    """Run the gates command."""
    project_path = Path(args.project)
    if not project_path.is_dir():
        print(f"Error: project path not found: {project_path}", file=sys.stderr)
        return EXIT_ERROR

    project = _load_project(project_path)

    from umbraedit.umbra.gates import GateScope, reportToJson, runGates

    scope = GateScope(
        project=project,
        edition=args.edition or "",
        options={},
    )

    try:
        report = runGates(args.operation, scope)
    except Exception as exc:
        print(f"Error: gates check failed: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        _write_json(reportToJson(report))
    else:
        status = "BLOCKED" if report.blocked else "OK"
        print(f"Gates {args.operation}: {status}")
        for f in report.findings:
            sev = f.severity.upper()
            print(f"  [{sev}] {f.ruleId}: {f.message}  (fix: {f.fix})")

    return EXIT_BLOCKED if report.blocked else EXIT_OK


def cmd_history_list(args: argparse.Namespace) -> int:
    """List history revisions."""
    project_path = Path(args.project)
    if not project_path.is_dir():
        print(f"Error: project path not found: {project_path}", file=sys.stderr)
        return EXIT_ERROR

    project = _load_project(project_path)

    from umbraedit.umbra.history import HistoryManager

    mgr = HistoryManager(project.storage.storagePath, project)  # type: ignore[arg-type]

    revisions = []
    for handle in project.index.iterHandles():  # type: ignore[attr-defined]
        store = mgr._storeForHandle(handle)  # noqa: SLF001
        revs = [
            {
                "handle": handle,
                "id": rev.id,
                "at": rev.at,
                "kind": rev.kind,
                "label": rev.label,
                "sha256": rev.sha256,
                "words": rev.words,
            }
            for rev in store.listRevisions()
        ]
        revisions.extend(revs)

    if args.json:
        _write_json(revisions)
    else:
        for r in revisions:
            print(f"{r['handle']} {r['id']} {r['at']} {r['kind']} {r['label']}")

    return EXIT_OK


def cmd_history_restore(args: argparse.Namespace) -> int:
    """Restore a history revision."""
    project_path = Path(args.project)
    if not project_path.is_dir():
        print(f"Error: project path not found: {project_path}", file=sys.stderr)
        return EXIT_ERROR

    project = _load_project(project_path)

    from umbraedit.umbra.history import HistoryManager

    mgr = HistoryManager(project.storage.storagePath, project)  # type: ignore[arg-type]

    store = mgr._storeForHandle(args.handle)  # noqa: SLF001
    content = store.readRevision(args.revision)
    if content is None:
        print(f"Error: revision {args.revision} not found for {args.handle}", file=sys.stderr)
        return EXIT_ERROR

    doc_file = project.storage.contentPath / f"{args.handle}.md"  # type: ignore[attr-defined]
    doc_file.write_text(content, encoding="utf-8")

    if args.json:
        _write_json({"handle": args.handle, "revision": args.revision, "restored": True})
    else:
        print(f"Restored {args.handle} from revision {args.revision}")

    return EXIT_OK


def cmd_merge(args: argparse.Namespace) -> int:
    """Run three-way merge."""
    base_path = Path(args.base)
    ours_path = Path(args.ours)
    theirs_path = Path(args.theirs)

    for p in (base_path, ours_path, theirs_path):
        if not p.is_file():
            print(f"Error: file not found: {p}", file=sys.stderr)
            return EXIT_ERROR

    from umbraedit.umbra.merge import merge_units

    base_text = base_path.read_text(encoding="utf-8")
    ours_text = ours_path.read_text(encoding="utf-8")
    theirs_text = theirs_path.read_text(encoding="utf-8")

    result = merge_units(base_text, ours_text, theirs_text)

    if args.json:
        _write_json({
            "conflicts": len(result.conflicts),  # type: ignore[attr-defined]
            "merged": "\n".join(u.lines for u in result.units),  # type: ignore[attr-defined]
        })
    else:
        print(f"Merge: {len(result.conflicts)} conflict(s)")  # type: ignore[attr-defined]
        for u in result.units:  # type: ignore[attr-defined]
            print("\n".join(u.lines))

    return EXIT_OK


def cmd_utterances(args: argparse.Namespace) -> int:
    """Derive utterances for a project."""
    project_path = Path(args.project)
    if not project_path.is_dir():
        print(f"Error: project path not found: {project_path}", file=sys.stderr)
        return EXIT_ERROR

    project = _load_project(project_path)

    from umbraedit.umbra.utterances import deriveUtterances

    handles = [args.handle] if args.handle else list(project.index.iterHandles())  # type: ignore[attr-defined]

    all_utterances = []
    for handle in handles:
        doc_file = project.storage.contentPath / f"{handle}.md"  # type: ignore[attr-defined]
        if not doc_file.is_file():
            continue
        text = doc_file.read_text(encoding="utf-8")
        utts = deriveUtterances(handle=handle, text=text, project=project)
        all_utterances.extend(u.__dict__ for u in utts)

    if args.json:
        _write_json(all_utterances)
    else:
        for u in all_utterances:
            print(f"{u.get('id', '')} {u.get('speaker', '')} {u.get('text', '')[:80]}")

    return EXIT_OK


def cmd_audio_build_chapter(args: argparse.Namespace) -> int:
    """Build audio for a chapter."""
    project_path = Path(args.project)
    if not project_path.is_dir():
        print(f"Error: project path not found: {project_path}", file=sys.stderr)
        return EXIT_ERROR

    project = _load_project(project_path)

    from umbraedit.umbra.audio import build_audio_chapter

    try:
        result = build_audio_chapter(project, args.edition or "main", args.handle)
    except Exception as exc:
        print(f"Error: audio build failed: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        _write_json(result)
    else:
        print(f"Audio chapter built: {result.get('success')}")

    return EXIT_OK


def cmd_audio_build_book(args: argparse.Namespace) -> int:
    """Build audio book."""
    project_path = Path(args.project)
    if not project_path.is_dir():
        print(f"Error: project path not found: {project_path}", file=sys.stderr)
        return EXIT_ERROR

    project = _load_project(project_path)

    from umbraedit.umbra.audio import build_audio_book

    try:
        result = build_audio_book(project, args.edition or "main")
    except Exception as exc:
        print(f"Error: audio book build failed: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        _write_json(result)
    else:
        print(f"Audio book built: {result.get('success')}")

    return EXIT_OK


def cmd_audio(args: argparse.Namespace) -> int:
    """Audio subcommand dispatcher."""
    if args.audio_cmd == "build-chapter":
        return cmd_audio_build_chapter(args)
    if args.audio_cmd == "build-book":
        return cmd_audio_build_book(args)
    print("Error: unknown audio command", file=sys.stderr)
    return EXIT_ERROR


def cmd_ingest_plan(args: argparse.Namespace) -> int:
    """Plan DOCX ingestion."""
    docx_path = Path(args.docx)
    if not docx_path.is_file():
        print(f"Error: DOCX file not found: {docx_path}", file=sys.stderr)
        return EXIT_ERROR

    from umbraedit.umbra.ingest.pipeline import DocxIngestPipeline

    try:
        pipeline = DocxIngestPipeline(docx_path.parent)  # type: ignore[arg-type]
        result = pipeline.process(docx_path)  # type: ignore[attr-defined]
    except Exception as exc:
        print(f"Error: ingest plan failed: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        _write_json(result)
    else:
        print(f"Ingest processed: {result}")

    return EXIT_OK


def cmd_build(args: argparse.Namespace) -> int:
    """Build manuscript for a target format."""
    project_path = Path(args.project)
    if not project_path.is_dir():
        print(f"Error: project path not found: {project_path}", file=sys.stderr)
        return EXIT_ERROR

    project = _load_project(project_path)

    from umbraedit.manuscript.buildsettings import BuildSettings
    from umbraedit.manuscript.docbuild import DocumentBuilder

    build_settings = BuildSettings()
    builder = DocumentBuilder(project, build_settings)

    try:
        # Queue all documents and iterate build preview
        builder.queueAll()  # type: ignore[attr-defined]
        for _ in builder.iterBuildPreview(False):  # type: ignore[attr-defined]
            pass
    except Exception as exc:
        print(f"Error: build failed: {exc}", file=sys.stderr)
        return EXIT_ERROR

    print(f"Build {args.target} complete")
    return EXIT_OK


def cmd_publish(args: argparse.Namespace) -> int:
    """Publish a project."""
    project_path = Path(args.project)
    if not project_path.is_dir():
        print(f"Error: project path not found: {project_path}", file=sys.stderr)
        return EXIT_ERROR

    project = _load_project(project_path)

    from umbraedit.umbra.publish import build_publish_package

    try:
        result = build_publish_package(project, args.edition or "main", args.retailer or "")
    except Exception as exc:
        print(f"Error: publish failed: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        _write_json(result)
    else:
        print(f"Publish: {'OK' if result.get('success') else 'FAILED'}")

    return EXIT_OK if result.get("success") else EXIT_ERROR


def cmd_sync_once(args: argparse.Namespace) -> int:
    """Run sync once."""
    project_path = Path(args.project)
    if not project_path.is_dir():
        print(f"Error: project path not found: {project_path}", file=sys.stderr)
        return EXIT_ERROR

    project = _load_project(project_path)

    try:
        from umbraedit.umbra.sync.client import createClient

        client = createClient(project)  # type: ignore[arg-type]
        client.syncOnce()  # type: ignore[attr-defined]
    except Exception as exc:
        print(f"Error: sync failed: {exc}", file=sys.stderr)
        return EXIT_ERROR

    print("Sync complete")
    return EXIT_OK


def cmd_metadata_get(args: argparse.Namespace) -> int:
    """Get metadata value."""
    project_path = Path(args.project)
    if not project_path.is_dir():
        print(f"Error: project path not found: {project_path}", file=sys.stderr)
        return EXIT_ERROR

    project = _load_project(project_path)

    from umbraedit.umbra.metadata import getValue, loadMetadata

    metadata = loadMetadata(project.storage.storagePath)
    value = getValue(metadata, args.key)

    if args.json:
        _write_json({"key": args.key, "value": value})
    else:
        print(f"{args.key} = {value}")

    return EXIT_OK


def cmd_metadata_set(args: argparse.Namespace) -> int:
    """Set metadata value."""
    project_path = Path(args.project)
    if not project_path.is_dir():
        print(f"Error: project path not found: {project_path}", file=sys.stderr)
        return EXIT_ERROR

    project = _load_project(project_path)

    from umbraedit.umbra.metadata import loadMetadata, saveMetadata, setValue

    metadata = loadMetadata(project.storage.storagePath)
    success = setValue(metadata, args.key, args.value)

    if not success:
        print(f"Error: cannot set {args.key}", file=sys.stderr)
        return EXIT_ERROR

    saveMetadata(project.storage.storagePath, metadata)

    if args.json:
        _write_json({"key": args.key, "value": args.value, "set": True})
    else:
        print(f"Set {args.key} = {args.value}")

    return EXIT_OK


def cmd_covers_check(args: argparse.Namespace) -> int:
    """Check covers."""
    project_path = Path(args.project)
    if not project_path.is_dir():
        print(f"Error: project path not found: {project_path}", file=sys.stderr)
        return EXIT_ERROR

    project = _load_project(project_path)

    from umbraedit.umbra.covers import loadCovers

    covers = loadCovers(project.storage.storagePath)

    if args.json:
        _write_json(covers)
    else:
        for fmt, cover in covers.items():
            print(f"{fmt}: {cover.get('file', 'none')}")

    return EXIT_OK


def cmd_pronunciation_check(args: argparse.Namespace) -> int:
    """Check pronunciation."""
    project_path = Path(args.project)
    if not project_path.is_dir():
        print(f"Error: project path not found: {project_path}", file=sys.stderr)
        return EXIT_ERROR

    project = _load_project(project_path)

    from umbraedit.umbra.pronunciation import entityHasPron

    missing = [
        entity.tag
        for entity in project.index.iterEntities()  # type: ignore[attr-defined]
        if entity.kind == "character" and not entityHasPron(entity, args.language or "en")
    ]

    if args.json:
        _write_json({"missing": missing})
    else:
        for tag in missing:
            print(f"Missing pronunciation: {tag}")

    return EXIT_OK


def cmd_pronunciation_export(args: argparse.Namespace) -> int:
    """Export pronunciation lexicon."""
    project_path = Path(args.project)
    if not project_path.is_dir():
        print(f"Error: project path not found: {project_path}", file=sys.stderr)
        return EXIT_ERROR

    project = _load_project(project_path)

    from umbraedit.umbra.lexicon import exportLexicon

    try:
        output_path = Path(args.output) if args.output else project.storage.storagePath / "lexicon.pls"  # type: ignore[attr-defined]
        exportLexicon(project, args.language or "en", output_path)
    except Exception as exc:
        print(f"Error: pronunciation export failed: {exc}", file=sys.stderr)
        return EXIT_ERROR

    print(f"Pronunciation exported to {output_path}")
    return EXIT_OK


def cmd_pronunciation(args: argparse.Namespace) -> int:
    """Pronunciation subcommand dispatcher."""
    if args.pronunciation_cmd == "check":
        return cmd_pronunciation_check(args)
    if args.pronunciation_cmd == "export":
        return cmd_pronunciation_export(args)
    print("Error: unknown pronunciation command", file=sys.stderr)
    return EXIT_ERROR


def cmd_voices_list(args: argparse.Namespace) -> int:
    """List voices."""
    project_path = Path(args.project)
    if not project_path.is_dir():
        print(f"Error: project path not found: {project_path}", file=sys.stderr)
        return EXIT_ERROR

    project = _load_project(project_path)

    from umbraedit.umbra.voicestore import VoiceStore

    store = VoiceStore(project.storage.storagePath)
    voices = store.listVoices()

    if args.json:
        _write_json(voices)
    else:
        for v in voices:
            print(f"{getattr(v, 'code', '')} {getattr(v, 'label', '')}")

    return EXIT_OK


def cmd_voices_add(args: argparse.Namespace) -> int:
    """Add a voice matrix."""
    print("Error: voices add not yet implemented", file=sys.stderr)
    return EXIT_ERROR


def cmd_voices_verify(args: argparse.Namespace) -> int:
    """Verify voices."""
    print("Error: voices verify not yet implemented", file=sys.stderr)
    return EXIT_ERROR


def cmd_voices(args: argparse.Namespace) -> int:
    """Voices subcommand dispatcher."""
    if args.voices_cmd == "list":
        return cmd_voices_list(args)
    if args.voices_cmd == "add":
        return cmd_voices_add(args)
    if args.voices_cmd == "verify":
        return cmd_voices_verify(args)
    print("Error: unknown voices command", file=sys.stderr)
    return EXIT_ERROR


def cmd_guide_status(args: argparse.Namespace) -> int:
    """Show guide status."""
    project_path = Path(args.project)
    if not project_path.is_dir():
        print(f"Error: project path not found: {project_path}", file=sys.stderr)
        return EXIT_ERROR

    project = _load_project(project_path)

    from umbraedit.umbra.guide import staleParaNotes

    stale = staleParaNotes("", project)

    if args.json:
        _write_json({"stale": len(stale)})
    else:
        print(f"Guide: {len(stale)} stale note(s)")

    return EXIT_OK


def cmd_analysis_run(args: argparse.Namespace) -> int:
    """Run analysis."""
    print("Error: analysis run not yet implemented", file=sys.stderr)
    return EXIT_ERROR


def cmd_translate_job(args: argparse.Namespace) -> int:
    """Create translation job."""
    print("Error: translate job not yet implemented", file=sys.stderr)
    return EXIT_ERROR


def cmd_translate_import(args: argparse.Namespace) -> int:
    """Import translation result."""
    print("Error: translate import not yet implemented", file=sys.stderr)
    return EXIT_ERROR


def cmd_translate(args: argparse.Namespace) -> int:
    """Translate subcommand dispatcher."""
    if args.translate_cmd == "job":
        return cmd_translate_job(args)
    if args.translate_cmd == "import":
        return cmd_translate_import(args)
    print("Error: unknown translate command", file=sys.stderr)
    return EXIT_ERROR


def cmd_proposals_import(args: argparse.Namespace) -> int:
    """Import proposals from a JSON file."""
    project_path = Path(args.project)
    if not project_path.is_dir():
        print(f"Error: project path not found: {project_path}", file=sys.stderr)
        return EXIT_ERROR

    project = _load_project(project_path)

    file_path = Path(args.file)
    if not file_path.is_file():
        print(f"Error: proposal file not found: {file_path}", file=sys.stderr)
        return EXIT_ERROR

    from umbraedit.umbra.proposals import import_proposals

    try:
        result = import_proposals(project, file_path)
    except Exception as exc:
        print(f"Error: proposal import failed: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        _write_json(result)
    else:
        print(f"Proposals imported: {result['accepted']} accepted, {result['skipped']} skipped")

    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(prog="umbraedit-cli", description="UmbraEdit CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # verify
    p = subparsers.add_parser("verify", help="Verify a project")
    p.add_argument("project", help="Project path")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.set_defaults(func=cmd_verify)

    # gates
    p = subparsers.add_parser("gates", help="Run gate checks")
    p.add_argument("project", help="Project path")
    p.add_argument("--operation", required=True, help="Gate operation")
    p.add_argument("--edition", default="", help="Edition ID")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.set_defaults(func=cmd_gates)

    # history
    p_hist = subparsers.add_parser("history", help="History commands")
    hist_sub = p_hist.add_subparsers(dest="history_cmd")
    p_hist_list = hist_sub.add_parser("list", help="List history revisions")
    p_hist_list.add_argument("project", help="Project path")
    p_hist_list.add_argument("--json", action="store_true")
    p_hist_list.set_defaults(func=cmd_history_list)
    p_hist_restore = hist_sub.add_parser("restore", help="Restore a revision")
    p_hist_restore.add_argument("project", help="Project path")
    p_hist_restore.add_argument("handle", help="Document handle")
    p_hist_restore.add_argument("revision", help="Revision ID")
    p_hist_restore.set_defaults(func=cmd_history_restore)

    # merge
    p = subparsers.add_parser("merge", help="Three-way merge")
    p.add_argument("base", help="Base file")
    p.add_argument("ours", help="Ours file")
    p.add_argument("theirs", help="Theirs file")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_merge)

    # utterances
    p = subparsers.add_parser("utterances", help="Derive utterances")
    p.add_argument("project", help="Project path")
    p.add_argument("--handle", help="Document handle")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_utterances)

    # audio
    p_audio = subparsers.add_parser("audio", help="Audio commands")
    audio_sub = p_audio.add_subparsers(dest="audio_cmd")
    p_audio_ch = audio_sub.add_parser("build-chapter", help="Build audio chapter")
    p_audio_ch.add_argument("project", help="Project path")
    p_audio_ch.add_argument("handle", help="Chapter handle")
    p_audio_ch.add_argument("--edition", default="main")
    p_audio_ch.add_argument("--json", action="store_true")
    p_audio_ch.set_defaults(func=cmd_audio_build_chapter)
    p_audio_book = audio_sub.add_parser("build-book", help="Build audio book")
    p_audio_book.add_argument("project", help="Project path")
    p_audio_book.add_argument("--edition", default="main")
    p_audio_book.add_argument("--json", action="store_true")
    p_audio_book.set_defaults(func=cmd_audio_build_book)

    # ingest
    p = subparsers.add_parser("ingest", help="Ingest commands")
    ingest_sub = p.add_subparsers(dest="ingest_cmd")
    p_ingest_plan = ingest_sub.add_parser("plan", help="Plan DOCX ingestion")
    p_ingest_plan.add_argument("docx", help="DOCX file path")
    p_ingest_plan.add_argument("--json", action="store_true")
    p_ingest_plan.set_defaults(func=cmd_ingest_plan)

    # build
    p = subparsers.add_parser("build", help="Build manuscript")
    p.add_argument("project", help="Project path")
    p.add_argument("--target", required=True, help="Build target")
    p.set_defaults(func=cmd_build)

    # publish
    p = subparsers.add_parser("publish", help="Publish project")
    p.add_argument("project", help="Project path")
    p.add_argument("--edition", default="main")
    p.add_argument("--retailer", default="")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_publish)

    # sync
    p_sync = subparsers.add_parser("sync", help="Sync commands")
    sync_sub = p_sync.add_subparsers(dest="sync_cmd")
    p_sync_once = sync_sub.add_parser("once", help="Run sync once")
    p_sync_once.add_argument("project", help="Project path")
    p_sync_once.set_defaults(func=cmd_sync_once)

    # metadata
    p_meta = subparsers.add_parser("metadata", help="Metadata commands")
    meta_sub = p_meta.add_subparsers(dest="metadata_cmd")
    p_meta_get = meta_sub.add_parser("get", help="Get metadata value")
    p_meta_get.add_argument("project", help="Project path")
    p_meta_get.add_argument("key", help="Metadata key")
    p_meta_get.add_argument("--json", action="store_true")
    p_meta_get.set_defaults(func=cmd_metadata_get)
    p_meta_set = meta_sub.add_parser("set", help="Set metadata value")
    p_meta_set.add_argument("project", help="Project path")
    p_meta_set.add_argument("key", help="Metadata key")
    p_meta_set.add_argument("value", help="Metadata value")
    p_meta_set.set_defaults(func=cmd_metadata_set)

    # covers
    p = subparsers.add_parser("covers", help="Cover commands")
    p.add_argument("project", help="Project path")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_covers_check)

    # pronunciation
    p_pron = subparsers.add_parser("pronunciation", help="Pronunciation commands")
    pron_sub = p_pron.add_subparsers(dest="pronunciation_cmd")
    p_pron_check = pron_sub.add_parser("check", help="Check pronunciation")
    p_pron_check.add_argument("project", help="Project path")
    p_pron_check.add_argument("--language", default="en")
    p_pron_check.add_argument("--json", action="store_true")
    p_pron_check.set_defaults(func=cmd_pronunciation_check)
    p_pron_export = pron_sub.add_parser("export", help="Export pronunciation")
    p_pron_export.add_argument("project", help="Project path")
    p_pron_export.add_argument("--language", default="en")
    p_pron_export.add_argument("--output", help="Output path")
    p_pron_export.set_defaults(func=cmd_pronunciation_export)

    # voices
    p_voices = subparsers.add_parser("voices", help="Voice commands")
    voices_sub = p_voices.add_subparsers(dest="voices_cmd")
    p_voices_list = voices_sub.add_parser("list", help="List voices")
    p_voices_list.add_argument("project", help="Project path")
    p_voices_list.add_argument("--json", action="store_true")
    p_voices_list.set_defaults(func=cmd_voices_list)
    p_voices_add = voices_sub.add_parser("add", help="Add voice")
    p_voices_add.add_argument("project", help="Project path")
    p_voices_add.set_defaults(func=cmd_voices_add)
    p_voices_verify = voices_sub.add_parser("verify", help="Verify voices")
    p_voices_verify.add_argument("project", help="Project path")
    p_voices_verify.set_defaults(func=cmd_voices_verify)

    # guide
    p = subparsers.add_parser("guide", help="Guide commands")
    p.add_argument("project", help="Project path")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_guide_status)

    # analysis
    p = subparsers.add_parser("analysis", help="Analysis commands")
    p.add_argument("project", help="Project path")
    p.set_defaults(func=cmd_analysis_run)

    # translate
    p_translate = subparsers.add_parser("translate", help="Translate commands")
    translate_sub = p_translate.add_subparsers(dest="translate_cmd")
    p_translate_job = translate_sub.add_parser("job", help="Create translation job")
    p_translate_job.add_argument("project", help="Project path")
    p_translate_job.set_defaults(func=cmd_translate_job)
    p_translate_import = translate_sub.add_parser("import", help="Import translation")
    p_translate_import.add_argument("project", help="Project path")
    p_translate_import.set_defaults(func=cmd_translate_import)

    # proposals
    p_proposals = subparsers.add_parser("proposals", help="Proposal commands")
    proposals_sub = p_proposals.add_subparsers(dest="proposals_cmd")
    p_proposals_import = proposals_sub.add_parser("import", help="Import proposals")
    p_proposals_import.add_argument("project", help="Project path")
    p_proposals_import.add_argument("file", help="Proposal JSON file path")
    p_proposals_import.add_argument("--json", action="store_true", help="JSON output")
    p_proposals_import.set_defaults(func=cmd_proposals_import)

    # serve
    p = subparsers.add_parser("serve", help="Serve local HTTP API")
    p.add_argument("project", help="Project path")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to listen on")
    p.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return EXIT_ERROR

    if not hasattr(args, "func") or args.func is None:
        parser.print_help()
        return EXIT_ERROR

    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        return EXIT_ERROR
    except Exception as exc:
        logger.exception("CLI error")
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_ERROR
