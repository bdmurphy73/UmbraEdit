"""Tests for UmbraEdit CLI (P33)."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

import umbraedit.cli.api as apiMain
import umbraedit.cli.main as cliMain

from umbraedit.cli.api import cmd_serve
from umbraedit.cli.main import (
    EXIT_BLOCKED,
    EXIT_ERROR,
    EXIT_OK,
    _load_project,
    _releaseProjects,
    build_parser,
    main,
)


class TestParser:
    """Tests for the CLI argument parser."""

    def test_parser_exists(self):
        parser = build_parser()
        assert parser is not None

    def test_verify_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["verify", "/tmp/test"])
        assert args.command == "verify"
        assert args.project == "/tmp/test"

    def test_gates_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["gates", "/tmp/test", "--operation", "build.run"])
        assert args.command == "gates"
        assert args.operation == "build.run"

    def test_exit_codes(self):
        assert EXIT_OK == 0
        assert EXIT_BLOCKED == 2
        assert EXIT_ERROR == 1


class TestRecentProjectIsolation:
    """Tests that standalone project opens do not update the recent cache."""

    @pytest.fixture(autouse=True)
    def clearApiSessions(self):
        """Keep deliberately stuck API sessions out of later tests."""
        apiMain._openProjects.clear()
        yield
        apiMain._openProjects.clear()

    def test_cli_loader_opts_out(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """The CLI loader must not track standalone project opens."""
        calls: list[tuple[str, dict[str, object]]] = []

        class FakeProject:
            def openProject(self, path: str, **kwargs: object) -> bool:
                calls.append((path, kwargs))
                return True

            def releaseSession(self) -> None:
                pass

        monkeypatch.setattr("umbraedit.core.project.NWProject", FakeProject)
        project = _load_project(tmp_path)

        assert isinstance(project, FakeProject)
        assert calls == [(str(tmp_path), {"updateRecent": False})]
        _releaseProjects()

    def test_api_server_opts_out(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """The local API server must not track standalone project opens."""
        calls: list[tuple[str, dict[str, object]]] = []

        class FakeProject:
            def openProject(self, path: str, **kwargs: object) -> bool:
                calls.append((path, kwargs))
                return True

            def releaseSession(self) -> None:
                pass

        monkeypatch.setattr("umbraedit.core.project.NWProject", FakeProject)
        monkeypatch.setattr("umbraedit.cli.api.serve", lambda project, port: None)

        assert cmd_serve(Namespace(project=str(tmp_path), port=8123)) == EXIT_OK
        assert calls == [(str(tmp_path), {"updateRecent": False})]

    def test_api_open_failure_releases_session(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """The API must release a partially opened project session."""
        released = False

        class FailingProject:
            def openProject(self, path: str, **kwargs: object) -> bool:
                raise RuntimeError("open failed")

            def releaseSession(self) -> bool:
                nonlocal released
                released = True
                return True

        monkeypatch.setattr("umbraedit.core.project.NWProject", FailingProject)
        with pytest.raises(RuntimeError):
            cmd_serve(Namespace(project=str(tmp_path), port=8123))
        assert released is True

    def test_api_reports_failed_lock_cleanup(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """The API must fail when the project lock remains held."""
        released = False

        class StuckProject:
            def openProject(self, path: str, **kwargs: object) -> bool:
                return True

            def releaseSession(self) -> bool:
                nonlocal released
                released = True
                return False

        monkeypatch.setattr("umbraedit.core.project.NWProject", StuckProject)
        monkeypatch.setattr("umbraedit.cli.api.serve", lambda project, port: None)

        assert cmd_serve(Namespace(project=str(tmp_path), port=8123)) == EXIT_ERROR
        assert released is True

    def test_api_reports_lock_cleanup_error(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """The API must fail when project lock cleanup raises an error."""

        class FailingCleanupProject:
            def openProject(self, path: str, **kwargs: object) -> bool:
                return True

            def releaseSession(self) -> bool:
                raise OSError("cleanup failed")

        monkeypatch.setattr("umbraedit.core.project.NWProject", FailingCleanupProject)
        monkeypatch.setattr("umbraedit.cli.api.serve", lambda project, port: None)

        assert cmd_serve(Namespace(project=str(tmp_path), port=8123)) == EXIT_ERROR

    def test_benchmark_opts_out(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """The benchmark must not track standalone project opens."""
        from utils import umbra_bench

        calls: list[tuple[Path, dict[str, object]]] = []

        class FakeIndex:
            def rebuild(self) -> None:
                pass

        class FakeProject:
            index = FakeIndex()
            tree: list[object] = []
            storage = SimpleNamespace(contentPath=None)

            def openProject(self, path: Path, **kwargs: object) -> bool:
                calls.append((path, kwargs))
                return True

            def releaseSession(self) -> None:
                pass

        monkeypatch.setattr("umbraedit.core.project.NWProject", FakeProject)

        assert isinstance(umbra_bench.bench(tmp_path), dict)
        assert calls == [
            (tmp_path, {"updateRecent": False}),
            (tmp_path, {"updateRecent": False}),
            (tmp_path, {"updateRecent": False}),
        ]

    def test_benchmark_failure_releases_session(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """A failed benchmark phase must release the project session."""
        from utils import umbra_bench

        releases = 0

        class FailingIndex:
            def rebuild(self) -> None:
                raise RuntimeError("rebuild failed")

        class FakeProject:
            index = FailingIndex()

            def openProject(self, path: Path, **kwargs: object) -> bool:
                return True

            def releaseSession(self) -> bool:
                nonlocal releases
                releases += 1
                return True

        monkeypatch.setattr("umbraedit.core.project.NWProject", FakeProject)
        with pytest.raises(RuntimeError):
            umbra_bench.bench(tmp_path)
        assert releases >= 1


class TestProjectSessionCleanup:
    """Tests for standalone project session ownership."""

    def test_loader_registers_project_before_open(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """A failed open must remain registered for dispatcher cleanup."""
        released = False

        class FailingProject:
            def openProject(self, path: str, **kwargs: object) -> bool:
                raise RuntimeError("open failed")

            def releaseSession(self) -> bool:
                nonlocal released
                released = True
                return True

        monkeypatch.setattr("umbraedit.core.project.NWProject", FailingProject)
        cliMain._openProjects.clear()
        with pytest.raises(RuntimeError):
            _load_project(tmp_path)

        assert len(cliMain._openProjects) == 1
        _releaseProjects()
        assert released is True
        assert cliMain._openProjects == []

    def test_release_projects_retries_failed_cleanup(self, monkeypatch: pytest.MonkeyPatch):
        """A failed release must remain pending for a later retry."""
        attempts = 0

        class RetryProject:
            def releaseSession(self) -> bool:
                nonlocal attempts
                attempts += 1
                return attempts > 1

        project = RetryProject()
        monkeypatch.setattr(cliMain, "_openProjects", [project])
        _releaseProjects()
        assert cliMain._openProjects == [project]

        _releaseProjects()
        assert cliMain._openProjects == []
        assert attempts == 2

    def test_main_reports_pending_lock_cleanup(self, monkeypatch: pytest.MonkeyPatch):
        """A successful command must fail if its project lock remains."""
        apiMain._openProjects.clear()

        class StuckProject:
            def releaseSession(self) -> bool:
                return False

        parser = SimpleNamespace(
            parse_args=lambda argv: SimpleNamespace(
                command="test",
                func=lambda args: EXIT_OK,
            )
        )
        monkeypatch.setattr(cliMain, "build_parser", lambda: parser)
        monkeypatch.setattr(cliMain, "_openProjects", [StuckProject()])

        assert main([]) == EXIT_ERROR


class TestVerify:
    """Tests for the verify command."""

    def test_verify_missing_project(self):
        """Verify command with non-existent project returns error."""
        result = main(["verify", "/nonexistent/path"])
        assert result == EXIT_ERROR

    def test_verify_json_flag(self):
        """Verify command accepts --json flag."""
        parser = build_parser()
        args = parser.parse_args(["verify", "/tmp/test", "--json"])
        assert args.json is True


class TestGates:
    """Tests for the gates command."""

    def test_gates_json_output(self):
        """Gates command accepts --json flag."""
        parser = build_parser()
        args = parser.parse_args(["gates", "/tmp/test", "--operation", "build.run", "--json"])
        assert args.json is True


class TestHistory:
    """Tests for history commands."""

    def test_history_list_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["history", "list", "/tmp/test"])
        assert args.history_cmd == "list"

    def test_history_restore_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["history", "restore", "/tmp/test", "ch1", "rev-abc"])
        assert args.history_cmd == "restore"
        assert args.handle == "ch1"
        assert args.revision == "rev-abc"


class TestMerge:
    """Tests for merge command."""

    def test_merge_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["merge", "base.md", "ours.md", "theirs.md"])
        assert args.command == "merge"
        assert args.base == "base.md"
        assert args.ours == "ours.md"
        assert args.theirs == "theirs.md"


class TestUtterances:
    """Tests for utterances command."""

    def test_utterances_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["utterances", "/tmp/test", "--handle", "ch1"])
        assert args.command == "utterances"
        assert args.handle == "ch1"


class TestAudio:
    """Tests for audio commands."""

    def test_audio_build_chapter(self):
        parser = build_parser()
        args = parser.parse_args(["audio", "build-chapter", "/tmp/test", "ch1"])
        assert args.audio_cmd == "build-chapter"
        assert args.handle == "ch1"

    def test_audio_build_book(self):
        parser = build_parser()
        args = parser.parse_args(["audio", "build-book", "/tmp/test"])
        assert args.audio_cmd == "build-book"


class TestIngest:
    """Tests for ingest commands."""

    def test_ingest_plan(self):
        parser = build_parser()
        args = parser.parse_args(["ingest", "plan", "/tmp/test.docx"])
        assert args.ingest_cmd == "plan"
        assert args.docx == "/tmp/test.docx"


class TestBuild:
    """Tests for build command."""

    def test_build_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["build", "/tmp/test", "--target", "epub"])
        assert args.command == "build"
        assert args.target == "epub"


class TestPublish:
    """Tests for publish command."""

    def test_publish_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["publish", "/tmp/test"])
        assert args.command == "publish"


class TestSync:
    """Tests for sync commands."""

    def test_sync_once(self):
        parser = build_parser()
        args = parser.parse_args(["sync", "once", "/tmp/test"])
        assert args.sync_cmd == "once"


class TestMetadata:
    """Tests for metadata commands."""

    def test_metadata_get(self):
        parser = build_parser()
        args = parser.parse_args(["metadata", "get", "/tmp/test", "book.title"])
        assert args.metadata_cmd == "get"
        assert args.key == "book.title"

    def test_metadata_set(self):
        parser = build_parser()
        args = parser.parse_args(["metadata", "set", "/tmp/test", "book.title", "New Title"])
        assert args.metadata_cmd == "set"
        assert args.value == "New Title"


class TestCovers:
    """Tests for covers command."""

    def test_covers_check(self):
        parser = build_parser()
        args = parser.parse_args(["covers", "/tmp/test"])
        assert args.command == "covers"


class TestPronunciation:
    """Tests for pronunciation commands."""

    def test_pronunciation_check(self):
        parser = build_parser()
        args = parser.parse_args(["pronunciation", "check", "/tmp/test"])
        assert args.pronunciation_cmd == "check"

    def test_pronunciation_export(self):
        parser = build_parser()
        args = parser.parse_args(["pronunciation", "export", "/tmp/test"])
        assert args.pronunciation_cmd == "export"


class TestVoices:
    """Tests for voices commands."""

    def test_voices_list(self):
        parser = build_parser()
        args = parser.parse_args(["voices", "list", "/tmp/test"])
        assert args.voices_cmd == "list"

    def test_voices_add(self):
        parser = build_parser()
        args = parser.parse_args(["voices", "add", "/tmp/test"])
        assert args.voices_cmd == "add"

    def test_voices_verify(self):
        parser = build_parser()
        args = parser.parse_args(["voices", "verify", "/tmp/test"])
        assert args.voices_cmd == "verify"


class TestGuide:
    """Tests for guide commands."""

    def test_guide_status(self):
        parser = build_parser()
        args = parser.parse_args(["guide", "/tmp/test"])
        assert args.command == "guide"


class TestAnalysis:
    """Tests for analysis commands."""

    def test_analysis_run(self):
        parser = build_parser()
        args = parser.parse_args(["analysis", "/tmp/test"])
        assert args.command == "analysis"


class TestTranslate:
    """Tests for translate commands."""

    def test_translate_job(self):
        parser = build_parser()
        args = parser.parse_args(["translate", "job", "/tmp/test"])
        assert args.translate_cmd == "job"

    def test_translate_import(self):
        parser = build_parser()
        args = parser.parse_args(["translate", "import", "/tmp/test"])
        assert args.translate_cmd == "import"


class TestLock:
    """Tests for the ProjectLock class."""

    def test_lock_acquire_release(self, tmp_path: Path):
        """Test acquiring and releasing a lock."""
        from umbraedit.cli.lock import ProjectLock

        lock = ProjectLock(tmp_path)
        assert lock.acquire(kind="cli") is True
        assert lock.is_locked() is True

        # Try to acquire again - should fail
        lock2 = ProjectLock(tmp_path)
        assert lock2.acquire(kind="cli") is False

        lock.release()
        assert lock.is_locked() is False

    def test_lock_info(self, tmp_path: Path):
        """Test lock info retrieval."""
        from umbraedit.cli.lock import ProjectLock

        lock = ProjectLock(tmp_path)
        lock.acquire(kind="cli", process="test-process")
        info = lock.lock_info()
        assert info is not None
        assert info["kind"] == "cli"
        assert info["process"] == "test-process"
        assert info["pid"] > 0
        lock.release()

    def test_lock_info_readable_while_held(self, tmp_path: Path):
        """The holder's information must be readable while the lock is
        held. On Windows, the operating system lock is a byte range
        lock, which blocks reads of the locked file, so the information
        is kept in a separate file.
        """
        from umbraedit.cli.lock import ProjectLock

        lock = ProjectLock(tmp_path)
        assert lock.acquire(kind="gui", process="test-gui") is True

        # The information must be readable from another instance too
        other = ProjectLock(tmp_path)
        assert other.is_locked() is True
        info = other.lock_info()
        assert info is not None
        assert info["kind"] == "gui"
        assert info["process"] == "test-gui"

        lock.release()
        assert other.is_locked() is False

    def test_check_write_access(self, tmp_path: Path):
        """Test check_write_access."""
        from umbraedit.cli.lock import check_write_access

        available, info = check_write_access(tmp_path)
        assert available is True
        assert info is None

        # Now lock it and check again
        from umbraedit.cli.lock import ProjectLock

        lock = ProjectLock(tmp_path)
        lock.acquire(kind="cli")
        available, info = check_write_access(tmp_path)
        assert available is False
        assert info is not None
        lock.release()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
