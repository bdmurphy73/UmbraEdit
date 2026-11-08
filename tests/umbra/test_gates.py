"""
UmbraEdit - Gate Engine Tests
==============================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.
"""  # noqa

from __future__ import annotations

from pathlib import Path

import pytest

from umbraedit.umbra.gates import (
    Finding,
    GateBlockedError,
    GateRule,
    GateScope,
    OP_BUILD_RUN,
    registerGate,
    requireGates,
    runGates,
    reportToJson,
    saveReport,
)


@pytest.fixture(autouse=True)
def _cleanGates():
    """Save and restore the gates registry around each test."""
    from umbraedit.umbra import gates as gatesMod
    saved = dict(gatesMod._gates)
    yield
    gatesMod._gates.clear()
    gatesMod._gates.update(saved)


def _makeRule(ruleId: str, severity: str, findings: list[Finding] | None = None, relaxable: bool = False):
    """Create a simple gate rule for testing."""
    return GateRule(
        ruleId=ruleId,
        title=f"Test Rule {ruleId}",
        operations=frozenset({OP_BUILD_RUN}),
        defaultSeverity=severity,
        relaxable=relaxable,
        check=lambda scope: findings or [],
    )


def _makeFinding(ruleId: str, severity: str) -> Finding:
    return Finding(
        ruleId=ruleId, severity=severity,
        message=f"Test {ruleId}", fix=f"Fix {ruleId}",
    )


# R1: registerGate, runGates, requireGates

def test_umbra_gates_R1_registerGate():
    """R1: registerGate accepts a new rule."""
    rule = _makeRule("test.rule", "advisory")
    registerGate(rule)
    assert rule.ruleId in {r.ruleId for r in __import__("umbraedit.umbra.gates", fromlist=["registeredGates"]).registeredGates()}


def test_umbra_gates_A4_duplicateRuleId():
    """A4: Duplicate ruleId registration raises ValueError."""
    rule = _makeRule("dup.rule", "advisory")
    registerGate(rule)
    with pytest.raises(ValueError, match="already registered"):
        registerGate(rule)


def test_umbra_gates_R1_runGates_clean():
    """R1: runGates returns clean report when no rules match."""
    scope = GateScope(project=None)
    report = runGates("nonexistent.operation", scope)
    assert not report.blocked
    assert report.findings == []


def test_umbra_gates_R1_runGates_blocked():
    """R1: runGates returns blocked report when a block rule fires."""
    registerGate(_makeRule("block.rule", "block", [_makeFinding("block.rule", "block")]))
    scope = GateScope(project=None)
    report = runGates(OP_BUILD_RUN, scope)
    assert report.blocked
    assert len(report.findings) == 1


def test_umbra_gates_R1_requireGates_raises():
    """R1: requireGates raises GateBlockedError on block finding."""
    registerGate(_makeRule("block.rule", "block", [_makeFinding("block.rule", "block")]))
    scope = GateScope(project=None)
    with pytest.raises(GateBlockedError):
        requireGates(OP_BUILD_RUN, scope)


def test_umbra_gates_R1_requireGates_passes():
    """R1: requireGates returns report when no blocking findings."""
    registerGate(_makeRule("ok.rule", "advisory", [_makeFinding("ok.rule", "advisory")]))
    scope = GateScope(project=None)
    report = requireGates(OP_BUILD_RUN, scope)
    assert not report.blocked


# R2: Raising rule produces gateRuleFailed

def test_umbra_gates_A2_raisingRule():
    """A2: A rule that raises produces a gateRuleFailed block finding."""
    def badCheck(scope):
        raise RuntimeError("Simulated bug in gate rule")

    registerGate(GateRule(
        ruleId="buggy.rule", title="Buggy",
        operations=frozenset({OP_BUILD_RUN}),
        defaultSeverity="advisory", relaxable=True, check=badCheck,
    ))
    scope = GateScope(project=None)
    report = runGates(OP_BUILD_RUN, scope)
    assert report.blocked
    assert any(f.ruleId == "gateRuleFailed" for f in report.findings)


# R3: GateScope

def test_umbra_gates_R3_gateScope():
    """R3: GateScope holds project, handles, edition, and options."""
    scope = GateScope(project=None, handles=["a", "b"], edition="test", options={"key": "val"})
    assert scope.handles == ["a", "b"]
    assert scope.edition == "test"
    assert scope.options == {"key": "val"}


# R4: Advisory rules can be relaxed

def test_umbra_gates_A3_relaxAdvisory():
    """A3: An advisory rule listed as relaxed gives no finding."""

    class FakeSettings:
        def __init__(self, relaxMap):
            self._relax = relaxMap
        def getBool(self, key, default=False):
            return self._relax.get(key, default)

    rule = _makeRule("relax.rule", "advisory", [_makeFinding("relax.rule", "advisory")], relaxable=True)
    registerGate(rule)
    scope = GateScope(project=None)
    settings = FakeSettings({"gates.relax.relax.rule": True})
    report = runGates(OP_BUILD_RUN, scope, settings)
    assert not report.blocked
    assert len(report.findings) == 0


def test_umbra_gates_A3_blockCannotRelax():
    """A3: A block rule with the same relax setting still blocks."""

    class FakeSettings:
        def __init__(self, relaxMap):
            self._relax = relaxMap
        def getBool(self, key, default=False):
            return self._relax.get(key, default)

    rule = _makeRule("hard.block", "block", [_makeFinding("hard.block", "block")], relaxable=False)
    registerGate(rule)
    scope = GateScope(project=None)
    settings = FakeSettings({"gates.relax.hard.block": True})
    report = runGates(OP_BUILD_RUN, scope, settings)
    assert report.blocked


# R7: Built-in rules

def test_umbra_gates_R7_builtinRulesRegistered():
    """R7: Built-in rules emptyDocumentIncluded and unknownReferenceTag are registered."""
    from umbraedit.umbra.gates import getGate
    assert getGate("emptyDocumentIncluded") is not None
    assert getGate("unknownReferenceTag") is not None


# R8: JSON report schema

def test_umbra_gates_R8_reportSchema():
    """R8: Report JSON has the correct schema keys."""
    report = runGates("nonexistent.op", GateScope(project=None))
    data = reportToJson(report)
    assert data["v"] == 1
    assert "operation" in data
    assert "blocked" in data
    assert "ranAt" in data
    assert "findings" in data
    assert isinstance(data["findings"], list)


def test_umbra_gates_R8_saveReport(tmp_path: Path):
    """R8: saveReport writes the report to umbra/cache/gate-report.json."""
    report = runGates("nonexistent.op", GateScope(project=None))
    savedPath = saveReport(report, tmp_path)
    assert savedPath == tmp_path / "umbra" / "cache" / "gate-report.json"
    assert savedPath.is_file()
    import json
    data = json.loads(savedPath.read_text(encoding="utf-8"))
    assert data["v"] == 1


def test_umbra_gates_A6_jsonDeterministic():
    """A6: The JSON report is deterministic apart from ranAt."""
    registerGate(_makeRule("det.rule", "advisory", [_makeFinding("det.rule", "advisory")]))
    scope = GateScope(project=None)
    report1 = runGates(OP_BUILD_RUN, scope)
    report2 = runGates(OP_BUILD_RUN, scope)
    json1 = reportToJson(report1)
    json2 = reportToJson(report2)
    # Remove ranAt for comparison
    json1.pop("ranAt")
    json2.pop("ranAt")
    assert json1 == json2
