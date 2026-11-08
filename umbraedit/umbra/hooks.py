"""
UmbraEdit - Hook Registry
=========================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Provides a simple named hook registry. Features register callbacks
that are called at specific points in upstream code. Handlers run in
registration order. An exception in one handler is logged and does
not stop the others.
"""  # noqa

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Named hook lists
_hooks: dict[str, list[Callable]] = defaultdict(list)


def register(name: str, fn: Callable) -> None:
    """Register a handler for a named hook."""
    if fn not in _hooks[name]:
        _hooks[name].append(fn)


def unregister(name: str, fn: Callable) -> None:
    """Remove a handler for a named hook."""
    if fn in _hooks[name]:
        _hooks[name].remove(fn)


def call(name: str, *args: Any, **kwargs: Any) -> list[Any]:
    """Call all handlers for a named hook in registration order.

    An exception in one handler is logged and does not stop the others.
    Returns a list of handler return values (None for failed handlers).
    """
    results = []
    for fn in _hooks.get(name, []):
        try:
            results.append(fn(*args, **kwargs))
        except Exception:
            logger.exception("Hook '%s' handler %s raised an exception", name, fn)
            results.append(None)
    return results


def callGating(name: str, *args: Any, **kwargs: Any) -> list[Any]:
    """Call all handlers for a named gating hook.

    Unlike `call`, an exception in a gating handler stops the chain.
    Returns a list of handler return values.
    """
    results = []
    for fn in _hooks.get(name, []):
        results.append(fn(*args, **kwargs))
    return results


def clear(name: str | None = None) -> None:
    """Clear all handlers for a hook, or all hooks if name is None."""
    if name is None:
        _hooks.clear()
    else:
        _hooks[name].clear()


def handlerCount(name: str) -> int:
    """Return the number of registered handlers for a hook."""
    return len(_hooks.get(name, []))


# Hook name constants (for type safety and documentation)
DOCUMENT_SAVED = "document.saved"
DOCUMENT_LOADING = "document.loading"
INDEX_SCAN_LINE = "index.scanLine"
INDEX_FINISHED = "index.finished"
HIGHLIGHTER_RULES = "highlighter.rules"
TOKENIZER_PREPROCESS = "tokenizer.preprocess"
TOKENIZER_SHORTCODES = "tokenizer.shortcodes"
BUILD_STAGES = "build.stages"
BUILD_STARTED = "build.started"
PROJECT_OPENED = "project.opened"
PROJECT_CLOSING = "project.closing"
GUI_DOCKS = "gui.docks"
GUI_MENUS = "gui.menus"
EDITOR_CONTEXT = "editor.context"
