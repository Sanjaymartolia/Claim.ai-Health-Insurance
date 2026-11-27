"""Mahesh's tool hooks installed once per claim, with a fresh budget per claim. Off by default."""

import pytest

from claimsense.graph import LocalRunner
from claimsense.graph.nodes import Nodes
from claimsense.hooks.hooks import AuditLog, HookedToolBelt, ToolBudgetExceeded

from .conftest import approve, room_breach_packet

AGENTS = ("extraction", "coverage", "fraud", "critic", "settlement")


def belts(team):
    return [getattr(team, a).belt for a in AGENTS]


def test_hooks_are_off_by_default(team):
    LocalRunner(team).run(room_breach_packet(), approve())
    assert not any(isinstance(b, HookedToolBelt) for b in belts(team))


def test_hooks_installed_for_the_claim_and_restored_after_a_local_run(team):
    seen = []

    def reviewer(p):
        seen.append([isinstance(b, HookedToolBelt) for b in belts(team)])
        return approve()(p)

    LocalRunner(team, tool_hooks=True, hook_options={"audit": AuditLog()}).run(
        room_breach_packet(), reviewer
    )
    assert seen and all(all(row) for row in seen)  # hooked while the claim runs
    assert not any(isinstance(b, HookedToolBelt) for b in belts(team))  # plain afterwards


def test_budget_is_charged_and_blocks_over_the_ceiling(team):
    runner = LocalRunner(team, tool_hooks=True, hook_options={"per_claim": 2, "audit": AuditLog()})
    with pytest.raises(ToolBudgetExceeded):
        runner.run(room_breach_packet(), approve())
    assert not any(isinstance(b, HookedToolBelt) for b in belts(team))  # restored on error too


def long_bill(n: int) -> dict:
    packet = room_breach_packet()
    line = {"description": "Pharmacy item", "category": "medicines", "amount": "100.00"}
    packet["claim"]["bill_lines"] = [
        {
            **line,
            "line_id": f"L{i}",
            "source": {"document": "bill.txt", "start": 0, "end": 3, "text": "row"},
        }
        for i in range(1, n + 1)
    ]
    packet["claim"]["bill_total"] = f"{100 * n}.00"
    return packet


def test_a_long_bill_fits_the_default_budget(team):
    """AGENTIC-09: coverage searches once per line, so a flat 40-call cap stopped long bills."""
    state = LocalRunner(team, tool_hooks=True, hook_options={"audit": AuditLog()}).run(
        long_bill(60), approve()
    )
    assert state["status"] == "settled"


def test_the_per_line_allowance_still_has_a_ceiling(team):
    runner = LocalRunner(
        team, tool_hooks=True, hook_options={"per_claim": 5, "per_line": 0, "audit": AuditLog()}
    )
    with pytest.raises(ToolBudgetExceeded):
        runner.run(long_bill(60), approve())


def test_each_claim_gets_a_fresh_budget(team):
    nodes = Nodes(team, approve(), tool_hooks=True, hook_options={"audit": AuditLog()})
    nodes.ensure_hooks("CLM-A")
    team.coverage.belt.call("get_policy", policy_number="POL-001")
    first = nodes.hook_guard
    assert first.budget.total == 1
    nodes.ensure_hooks("CLM-A")  # same claim (e.g. resume after a pause): same budget
    assert nodes.hook_guard is first
    nodes.ensure_hooks("CLM-B")
    assert nodes.hook_guard is not first and nodes.hook_guard.budget.total == 0
    nodes.restore_hooks()
    assert not any(isinstance(b, HookedToolBelt) for b in belts(team))


def test_build_graph_accepts_the_option(team):
    pytest.importorskip("langgraph")
    from claimsense.graph import build_graph, memory_checkpointer, resume, start

    app = build_graph(
        team,
        checkpointer=memory_checkpointer(),
        tool_hooks=True,
        hook_options={"audit": AuditLog()},
    )
    out, cfg = start(app, room_breach_packet())
    assert all(isinstance(b, HookedToolBelt) for b in belts(team))  # still hooked while paused
    out = resume(app, cfg, {"decision": "approve", "approver_id": "adj-1"})
    assert out["status"] == "settled"


def test_budgets_are_read_from_the_checked_in_config(monkeypatch):
    """The hooks looked for models.yaml in a folder that does not exist and used fallbacks."""
    import yaml

    from claimsense.config import config_path
    from claimsense.hooks import hooks as H

    monkeypatch.delenv("CLAIMSENSE_CONFIG", raising=False)
    monkeypatch.delenv("CLAIMSENSE_REPO", raising=False)
    H._budgets_config.cache_clear()
    expected = yaml.safe_load(config_path().read_text(encoding="utf-8"))["budgets"]
    assert H._budgets_config(H._config_path()) == expected


def test_the_history_write_goes_through_the_settlement_belt(team):
    """AGENTIC-08: memory_update called services.record_history directly: no ACL, budget, audit."""
    audit = AuditLog()
    runner = LocalRunner(team, tool_hooks=True, hook_options={"audit": audit})
    state = runner.run(room_breach_packet(), approve())
    assert state["status"] == "settled"
    [rec] = [r for r in audit.records if r.tool == "record_history"]
    assert rec.agent == "settlement" and rec.status == "ok"


def test_only_the_settlement_agent_may_write_history(team):
    from claimsense.agents import ToolPermissionError

    with pytest.raises(ToolPermissionError):
        team.fraud.belt.call("record_history", claim=None)
