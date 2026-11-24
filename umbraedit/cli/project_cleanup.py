"""
UmbraEdit - CLI Project Session Cleanup
========================================

Shared helpers for releasing exclusive project sessions from standalone
command-line and API processes.

Copyright (C) 2026 B.D. Murphy and UmbraEdit contributors.

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

from typing import Any

logger = logging.getLogger(__name__)


def releaseProject(project: Any) -> bool:
    """Release one project session.

    ``None`` is accepted as a successful result for compatibility with
    older project implementations that did not return a status value.
    """
    try:
        released = project.releaseSession()
    except Exception as exc:
        logger.warning("Could not release project session: %s", exc)
        return False
    return released is not False


def releaseProjects(projects: list[Any]) -> bool:
    """Release all registered project sessions.

    Projects whose cleanup fails remain in the list so a later dispatcher
    or process-exit hook can retry the same validated lock ownership.
    """
    pending: list[Any] = []
    for project in list(projects):
        if releaseProject(project):
            projects[:] = [item for item in projects if item is not project]
        else:
            pending.append(project)
    projects[:] = pending
    return not pending
