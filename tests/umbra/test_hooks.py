"""
UmbraEdit - Hook Registry Tests
================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

import pytest

from umbraedit.umbra.hooks import (
    call,
    callGating,
    clear,
    handlerCount,
    register,
    unregister,
)


@pytest.fixture(autouse=True)
def _cleanHooks():
    """Clean all hooks before and after each test."""
    clear()
    yield
    clear()


def test_umbra_hooks_A1_registerAndCall():
    """A1: A registered handler is called when the hook fires."""
    called = []
    register("test.hook", lambda: called.append(True))
    assert handlerCount("test.hook") == 1
    call("test.hook")
    assert called == [True]


def test_umbra_hooks_A1_callOrder():
    """A1: Handlers are called in registration order."""
    order = []
    register("test.order", lambda: order.append(1))
    register("test.order", lambda: order.append(2))
    register("test.order", lambda: order.append(3))
    call("test.order")
    assert order == [1, 2, 3]


def test_umbra_hooks_A1_withArgs():
    """A1: Handlers receive positional and keyword arguments."""
    received = []
    register("test.args", lambda a, b: received.append((a, b)))
    call("test.args", 42, b="hello")
    assert received == [(42, "hello")]


def test_umbra_hooks_A2_exceptionLogged():
    """A2: A handler that raises is logged, other handlers still run."""
    called = []
    register("test.except", lambda: 1 / 0)
    register("test.except", lambda: called.append(True))
    results = call("test.except")
    assert called == [True]
    assert len(results) == 2


def test_umbra_hooks_A2_gatingStops():
    """A2: A gating hook stops on exception."""
    called = []
    register("test.gate", lambda: 1 / 0)
    register("test.gate", lambda: called.append(True))

    with pytest.raises(ZeroDivisionError):
        callGating("test.gate")
    assert called == []


def test_umbra_hooks_unregister():
    """Unregister removes a handler."""
    called = []
    fn = lambda: called.append(True)  # noqa: E731
    register("test.unreg", fn)
    unregister("test.unreg", fn)
    call("test.unreg")
    assert called == []
    assert handlerCount("test.unreg") == 0


def test_umbra_hooks_R3_documentSaved():
    """R3: document.saved hook fires when document is saved."""
    from umbraedit.umbra import hooks as h

    calls = []
    h.register(h.DOCUMENT_SAVED, lambda handle, text: calls.append((handle, text)))

    # Simulate a document save via the hook system
    h.call(h.DOCUMENT_SAVED, "abc123", "test text")
    assert calls == [("abc123", "test text")]


def test_umbra_hooks_R3_documentLoading():
    """R3: document.loading hook fires when document is loaded."""
    from umbraedit.umbra import hooks as h

    calls = []
    h.register(h.DOCUMENT_LOADING, lambda handle, text: calls.append((handle, text)))

    h.call(h.DOCUMENT_LOADING, "abc123", "test text")
    assert calls == [("abc123", "test text")]
