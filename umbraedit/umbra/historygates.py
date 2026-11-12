"""
UmbraEdit - Revision History Gate Rules
========================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Gate rules for revision history (P11): write failures are reported
through the gate engine so backup and sync operations can be blocked
when the history system cannot write snapshots.
"""  # noqa

from __future__ import annotations

import logging

from datetime import datetime

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as UTC
from typing import TYPE_CHECKING, Any

from umbraedit.umbra.gates import OP_BACKUP_ROTATE, OP_SYNC_PUSH, Finding, GateRule, registerGate

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)


def _historyWriteFailed(scope: Any) -> Iterable[Finding]:
    """Block: the last history write attempt raised an error.

    This gate blocks backup.rotate and sync.push when the history
    system cannot write snapshots, preventing data loss from
    unversioned changes being backed up or synced.
    """
    from umbraedit.umbra.history import _historyManager

    if _historyManager is None:
        return

    lastError = _historyManager.lastWriteError
    if lastError is None:
        return

    # Only report errors from the last 10 minutes
    now = datetime.now(UTC)
    if (now - lastError).total_seconds() > 10 * 60:
        return

    yield Finding(
        ruleId="historyWriteFailed",
        severity="block",
        message="History write failed - cannot verify revision integrity.",
        fix="Check disk space and permissions for the history folder.",
        handle=None,
        line=None,
        detail={"lastError": lastError.strftime("%Y-%m-%dT%H:%M:%SZ")},
    )


registerGate(
    GateRule(
        ruleId="historyWriteFailed",
        title="History Write Failed",
        operations=frozenset({OP_BACKUP_ROTATE, OP_SYNC_PUSH}),
        defaultSeverity="block",
        relaxable=False,
        check=_historyWriteFailed,
    )
)
