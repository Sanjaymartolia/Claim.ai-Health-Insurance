"""A run that fails after a review decision (a database error, an MCP timeout) used to leave its
case reporting "running" with no decision pending: no route moved it forward (found in Docker,
2026-11-25). The case now says `stopped` and names the step, and `POST /claims/{id}/retry`
resumes from that step. A retry carries no decision: settlement still verifies the approvals."""

import pytest

from claimsense.graph import nodes as N

from .conftest import ALICE, BOB, auth, decide, get, sse, start


@pytest.fixture
def fail_once(monkeypatch):
    """Make one graph step raise once, as a transient tool failure would."""

    def arm(step: str) -> None:
        original = getattr(N.Nodes, step)
        armed = {"on": True}

        def flaky(self, s):
            if armed["on"]:
                armed["on"] = False
                raise RuntimeError("transient: database is locked")
            return original(self, s)

        monkeypatch.setattr(N.Nodes, step, flaky)

    return arm


def retry(client, case_id: str, key: str = ALICE):
    return client.post(f"/claims/{case_id}/retry", headers=auth(key))


def test_a_failed_settlement_is_reported_as_stopped_and_a_retry_settles_it(client, fail_once):
    sse(start(client, "CLM-0004", case_id="R-SETTLE"))
    fail_once("settle")
    events = sse(decide(client, "R-SETTLE", ALICE))
    assert ("error", {"error": "RuntimeError"}) in events
    case = get(client, "R-SETTLE")
    assert case["status"] == "stopped" and case["stopped_at"] == ["settle"]
    assert "database is locked" not in str(case)  # only the step name, never the message

    events = sse(retry(client, "R-SETTLE"))
    assert events[-1][0] == "done" and events[-1][1]["status"] == "settled"
    case = get(client, "R-SETTLE")
    assert case["status"] == "settled" and case["stopped_at"] == []


def test_a_run_that_failed_before_its_first_review_can_be_retried(client, fail_once):
    from prometheus_client import REGISTRY

    def routed() -> float:
        return sum(
            REGISTRY.get_sample_value("claimsense_claims_total", {"outcome": r}) or 0.0
            for r in ("ready_for_approval", "needs_review")
        )

    fail_once("coverage")
    events = sse(start(client, "CLM-0004", case_id="R-START"))
    assert events[-1] == ("error", {"error": "RuntimeError"})
    assert get(client, "R-START")["stopped_at"] == ["coverage"]
    before = routed()
    events = sse(retry(client, "R-START"))
    assert any(name == "review" for name, _ in events)
    assert get(client, "R-START")["status"] == "awaiting_review"
    assert routed() == before + 1  # the retried first run records its route, as a start does


def test_a_paid_claim_whose_history_write_failed_keeps_its_status(client, fail_once):
    sse(start(client, "CLM-0004", case_id="R-MEMORY"))
    fail_once("memory_update")
    sse(decide(client, "R-MEMORY", ALICE))
    case = get(client, "R-MEMORY")
    assert case["status"] == "settled" and case["stopped_at"] == ["memory_update"]
    sse(retry(client, "R-MEMORY", BOB))  # any signed-in reviewer may retry: it decides nothing
    assert get(client, "R-MEMORY")["stopped_at"] == []


def test_retry_is_refused_when_nothing_stopped(client):
    sse(start(client, "CLM-0004", case_id="R-NONE"))
    assert retry(client, "R-NONE").status_code == 409  # waiting for a review, not stopped
    assert retry(client, "NO-SUCH-CASE").status_code == 404
    sse(decide(client, "R-NONE", ALICE))
    assert retry(client, "R-NONE").status_code == 409  # finished


def test_a_retry_after_a_lost_settlement_reply_ends_settled_with_history(client, monkeypatch):
    """The write committed but its answer never came (an MCP timeout). The retry used to be
    refused as a second payment, so a paid claim read 'escalated' and kept no claim history."""
    from claimsense.agents import PolicyInfo
    from claimsense.api import runner as R
    from claimsense.mcp_servers.claims_db import ClaimsDatabase

    monkeypatch.setenv("CLAIMSENSE_APPROVAL_SECRET", "test-only-approval-secret-0123456789")
    db = ClaimsDatabase(":memory:")
    lost = {"on": True}
    init, services = R.CaseService.__init__, R.CaseService._services

    def real_db_init(self, *args, **kwargs):
        init(self, *args, **kwargs)
        self.stub_approvals = db.approval_store

    def real_db_services(self, packet):
        s = services(self, packet)
        db.upsert_policy(PolicyInfo.model_validate(packet["fixture_policy"]))
        s.get_policy, s.claim_history = db.get_policy, db.claim_history
        s.record_history, s.record_repudiation = db.record_history, db.record_repudiation

        def settle(**kw):
            receipt = db.settle_claim(**kw)  # committed ...
            if lost["on"]:
                lost["on"] = False
                raise TimeoutError("no answer in 30 s")  # ... but the reply never arrived
            return receipt

        s.settle_claim = settle
        return s

    monkeypatch.setattr(R.CaseService, "__init__", real_db_init)
    monkeypatch.setattr(R.CaseService, "_services", real_db_services)

    sse(start(client, "CLM-0004", case_id="R-LOST"))
    sse(decide(client, "R-LOST", ALICE))
    assert get(client, "R-LOST")["stopped_at"] == ["settle"]
    events = sse(retry(client, "R-LOST"))
    assert events[-1][1]["status"] == "settled"
    case = get(client, "R-LOST")
    assert case["status"] == "settled" and case["settlement"]["amount"] == "67067.10"
    assert db._conn.execute("SELECT count(*) FROM settlements").fetchone()[0] == 1  # noqa: SLF001
    assert db._conn.execute("SELECT count(*) FROM claims").fetchone()[0] == 1  # noqa: SLF001


def test_a_security_stop_is_named_and_cannot_be_retried(client, monkeypatch):
    """A retry cannot fix an ACL breach (every retry failed the same way) and must not reset the
    tool budget: the case names the class and the route refuses."""
    from claimsense.agents import ToolPermissionError

    def acl_breach(self, s):
        raise ToolPermissionError("settlement may not call settle_claim")

    sse(start(client, "CLM-0004", case_id="R-ACL"))
    monkeypatch.setattr(N.Nodes, "settle", acl_breach)
    sse(decide(client, "R-ACL", ALICE))
    case = get(client, "R-ACL")
    assert case["stopped_at"] == ["settle"] and case["stopped_error"] == "ToolPermissionError"
    assert case["retryable"] is False and "may not call" not in str(case)
    response = retry(client, "R-ACL")
    assert response.status_code == 409 and "cannot fix" in response.json()["detail"]


def test_a_transient_stop_is_named_and_retryable(client, fail_once):
    sse(start(client, "CLM-0004", case_id="R-TRANSIENT"))
    fail_once("settle")
    sse(decide(client, "R-TRANSIENT", ALICE))
    case = get(client, "R-TRANSIENT")
    assert case["stopped_error"] == "RuntimeError" and case["retryable"] is True


def test_a_failed_then_retried_claim_is_processed_once(client, fail_once):
    """Claims processed counted the failed run as `error` and the retry as `settled`: two."""
    from prometheus_client import REGISTRY

    from claimsense.api import metrics

    def processed() -> float:
        return sum(
            REGISTRY.get_sample_value("claimsense_claims_processed_total", {"outcome": o}) or 0.0
            for o in metrics.OUTCOMES
        )

    sse(start(client, "CLM-0004", case_id="R-COUNT"))
    before = processed()
    fail_once("settle")
    sse(decide(client, "R-COUNT", ALICE))
    sse(retry(client, "R-COUNT"))
    assert processed() == before + 1
