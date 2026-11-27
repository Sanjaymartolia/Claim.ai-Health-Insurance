"""AGT-02a: clause 6.2, the specific waiting period (ADR-0011).

Listed conditions are not covered until 24 months (6.2.1 to 6.2.20) or 36 months (6.2.21, 6.2.22)
after the first policy's inception. Two Domain-lead rulings (2026-11-12):
1. An admission outside the policy period cites clause 2 only: no waiting period applies to a stay
   that cover never began for.
2. Accidents are exempt by 6.2(a), but the claim carries no accident indicator, so the wait is
   applied and a person decides (fails safe).
"""

from datetime import date

import pytest

from claimsense.agents import Team, make_stub_services
from claimsense.agents.coverage import CoverageAgent
from claimsense.contracts import Claim, DeductionReason
from claimsense.graph import LocalRunner, Status

from .conftest import POLICY, C, room_breach_packet

ADMITTED = date(2026, 5, 10)  # room_breach_packet's admission date


def _check(diagnosis, procedure, first_inception, **claim_over):
    policy = POLICY.model_copy(update={"first_inception": first_inception})
    services = make_stub_services(policies={policy.policy_number: policy})
    packet = room_breach_packet(diagnosis=diagnosis, procedure=procedure, **claim_over)
    return CoverageAgent(services).check_admissibility(Claim.model_validate(packet["claim"]))


STONES = ("Right ureteric calculus", "Ureteroscopy with stone removal")


def test_urinary_stones_inside_24_months_are_not_admissible():
    adm = _check(*STONES, date(2026, 3, 1))
    assert not adm.admissible
    assert C.SPECIFIC_WAITING_PERIOD in adm.clause_ids
    assert any("6.2.18" in r for r in adm.reasons)


def test_urinary_stones_after_24_months_are_admissible():
    assert _check(*STONES, date(2024, 4, 10)).admissible


@pytest.mark.parametrize(
    ("first_inception", "admissible"),
    [
        (date(2024, 5, 11), False),  # 24 months end on 2026-05-11: admitted one day early
        (date(2024, 5, 10), True),  # exactly 24 months: the wait has expired
    ],
)
def test_the_24_month_boundary(first_inception, admissible):
    assert _check(*STONES, first_inception).admissible is admissible


@pytest.mark.parametrize(
    ("first_inception", "admissible"),
    [(date(2023, 11, 10), False), (date(2023, 4, 10), True)],  # 30 and 37 months
)
def test_joint_replacement_waits_36_months(first_inception, admissible):
    adm = _check("Osteoarthritis knee", "Total knee arthroplasty", first_inception)
    assert adm.admissible is admissible
    if not admissible:
        assert any("6.2.21" in r for r in adm.reasons)


def test_a_malignant_calculus_is_not_under_6_2_18():
    adm = _check("Gall bladder carcinoma with calculi", "Cholecystectomy", date(2026, 3, 1))
    assert C.SPECIFIC_WAITING_PERIOD not in adm.clause_ids


def test_an_unlisted_condition_is_admissible():
    assert _check("Acute appendicitis", "Appendectomy", date(2026, 3, 1)).admissible


def test_out_of_period_cites_only_the_operative_clause():
    """Ruling 1, CLM-0013's shape: a hysterectomy (6.2.6) admitted before the first policy began.
    Neither the 30-day wait nor the 24-month wait applies; the stay is outside cover (clause 2)."""
    adm = _check(
        "Fibroid uterus",
        "Hysterectomy",
        date(2026, 1, 1),
        admission_date="2025-12-28",
        discharge_date="2025-12-31",
    )
    assert adm.clause_ids == [C.POLICY_PERIOD]
    assert len(adm.reasons) == 1


def test_a_gated_claim_is_repudiated_with_a_zero_worksheet():
    """Through the graph: ADR-0010 turns the 6.2 ruling into a Rs 0 worksheet citing 6.2."""
    policy = POLICY.model_copy(update={"first_inception": date(2026, 3, 1)})
    services = make_stub_services(policies={policy.policy_number: policy})
    packet = room_breach_packet(diagnosis=STONES[0], procedure=STONES[1])
    out = LocalRunner(Team(services)).run(
        packet, lambda p: {"decision": "approve", "approver_id": "adj-1"}
    )
    assert out["status"] == Status.REPUDIATED
    assert out["worksheet"].total_payable == 0
    reasons = {(d.reason, d.clause_id) for line in out["worksheet"].lines for d in line.deductions}
    assert reasons == {(DeductionReason.WAITING_PERIOD, C.SPECIFIC_WAITING_PERIOD)}


@pytest.mark.parametrize(
    ("first_inception", "admissible"),
    [(date(2023, 5, 25), False), (date(2023, 5, 10), True)],
)
def test_the_ped_wait_is_36_calendar_months(first_inception, admissible):
    """AGT-08: 36 * 30 = 1,080 days ended the wait on 2026-05-09 for a 2023-05-25 policy, so a
    2026-05-10 admission for a declared PED was admitted. 36 months end on 2026-05-25 (ADR-0004)."""
    policy = POLICY.model_copy(
        update={"first_inception": first_inception, "declared_peds": ["diabetes"]}
    )
    services = make_stub_services(policies={policy.policy_number: policy})
    packet = room_breach_packet(diagnosis="diabetes with complications", procedure=None)
    adm = CoverageAgent(services).check_admissibility(Claim.model_validate(packet["claim"]))
    assert adm.admissible is admissible
    assert (C.PED_WAITING_PERIOD in adm.clause_ids) is not admissible


def test_an_empty_search_result_does_not_crash_coverage():
    """AGT-07: the fallback path read ps[0] even when search returned nothing."""
    services = make_stub_services(policies={POLICY.policy_number: POLICY})
    services.policy_search = lambda **_kw: []
    claim = Claim.model_validate(room_breach_packet()["claim"])
    choices, _, notes = CoverageAgent(services).choose_clauses(claim)
    assert set(choices) == {line.line_id for line in claim.bill_lines}
    assert all(c == C.HOSPITALISATION for c in choices.values()) and notes


def test_coverage_searches_with_the_bill_wording():
    """AGT-05: REWRITE turned 'consumables' into 'excluded items consumables non-payable' before
    search, which has its own glossary, and pushed clause 4.1 out of the top 5."""
    services = make_stub_services(policies={POLICY.policy_number: POLICY})
    queries = []
    search = services.policy_search
    services.policy_search = lambda **kw: queries.append(kw["query"]) or search(**kw)
    claim = Claim.model_validate(room_breach_packet()["claim"])
    CoverageAgent(services).candidates(claim)
    assert queries == [line.description.lower() for line in claim.bill_lines]
