"""
UmbraEdit - Sync Gate Rules
===========================

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

import logging

from typing import TYPE_CHECKING, Any

from umbraedit.umbra.gates import (
    OP_AUDIO_CHAPTER,
    OP_BUILD_RUN,
    OP_PUBLISH_PACKAGE,
    Finding,
    GateRule,
    registerGate,
)
from umbraedit.umbra.jsonio import readJson
from umbraedit.umbra.paths import stateFile
from umbraedit.umbra.sync.conflicts import ConflictsStore

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

# Rule IDs
RULE_SYNC_CONFLICT_OPEN = "syncConflictOpen"
RULE_SYNC_STALE = "syncStale"


def _openConflictsCount(scope: Any) -> int:
    """Return the number of open conflicts for the project."""
    if not scope.project:
        return 0
    storagePath = scope.project.storage.storagePath
    if not storagePath:
        return 0
    store = ConflictsStore(storagePath)
    return store.open_count()


def _checkSyncConflictOpen(scope: Any) -> Iterable[Finding]:
    """Block: open sync conflicts block publish and audio operations."""
    count = _openConflictsCount(scope)
    if count == 0:
        return
    yield Finding(
        ruleId=RULE_SYNC_CONFLICT_OPEN,
        severity="block",
        message=f"{count} open sync conflict(s) - resolve before publishing or building audio.",
        fix="Open the Conflicts panel and resolve all open conflicts.",
        handle=None,
        line=None,
        detail={"openConflicts": count},
    )


def _checkSyncStale(scope: Any) -> Iterable[Finding]:
    """Advisory: last successful pull older than configured threshold."""
    if not scope.project:
        return
    storagePath = scope.project.storage.storagePath
    if not storagePath:
        return

    # Get stale threshold from settings
    from umbraedit.umbra.settings import umbraSettings

    staleMinutes = umbraSettings.getInt("sync.staleMinutes", STALE_DEFAULT_MINUTES)

    statePath = stateFile(storagePath)
    if not statePath.is_file():
        return
    try:
        data = readJson(statePath, default={})
    except Exception:
        return

    if not isinstance(data, dict):
        return

    lastSuccess = data.get("lastSuccessAt", "")
    if not lastSuccess:
        return

    try:
        from datetime import datetime

        try:
            from datetime import UTC
        except ImportError:
            from datetime import timezone as UTC

        lastTime = datetime.strptime(lastSuccess, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        now = datetime.now(UTC)
        deltaMinutes = (now - lastTime).total_seconds() / 60.0
        if deltaMinutes > staleMinutes:
            yield Finding(
                ruleId=RULE_SYNC_STALE,
                severity="advisory",
                message=f"Last successful sync was {int(deltaMinutes)} minutes ago (threshold: {staleMinutes}m).",
                fix="Run 'Sync now' to pull and push changes.",
                handle=None,
                line=None,
                detail={"staleMinutes": int(deltaMinutes), "threshold": staleMinutes},
            )
    except ValueError:
        return


STALE_DEFAULT_MINUTES = 60

registerGate(
    GateRule(
        ruleId=RULE_SYNC_CONFLICT_OPEN,
        title="Sync Conflict Open",
        operations=frozenset({OP_BUILD_RUN, OP_PUBLISH_PACKAGE, OP_AUDIO_CHAPTER}),
        defaultSeverity="block",
        relaxable=False,
        check=_checkSyncConflictOpen,
    )
)

registerGate(
    GateRule(
        ruleId=RULE_SYNC_STALE,
        title="Sync Stale",
        operations=frozenset({OP_BUILD_RUN, OP_PUBLISH_PACKAGE}),
        defaultSeverity="advisory",
        relaxable=True,
        check=_checkSyncStale,
    )
)
