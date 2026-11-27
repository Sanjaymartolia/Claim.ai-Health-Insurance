"""Hand-worked cases for the product calculator (`calc.adjudication.adjudicate`, T15).

Each expected amount is worked out in the comment from the policy wording, not read from the code.
Clauses: 12.1 room limit (2% of sum insured, at most Rs 5,000/day), Note 4.1.1(b) proportional cut
on linked charges after a room breach (medicines excluded), 9.5 co-pay 5% of the admissible amount,
clause 2 cover only during the policy period (ADR-0010: the gate deducts every line in full).
"""

from decimal import Decimal

from claimsense.agents import clauses as C
from claimsense.calc.adjudication import PolicyRules, adjudicate
from claimsense.contracts import Claim, DeductionReason


def _line(line_id, category, amount, days=None):
    line = {
        "line_id": line_id,
        "description": category,
        "category": category,
        "amount": amount,
        "source": {"document": "bill.txt", "start": 0, "end": 3, "text": "row"},
    }
    if days:
        line["days"] = days
    return line


def _claim(lines, sum_insured="200000.00", discharge="2026-05-13"):
    return Claim.model_validate(
        {
            "claim_id": "CLM-CALC-1",
            "policy_number": "POL-CALC",
            "patient_pseudonym": "PT-CALC",
            "admission_date": "2026-05-10",
            "discharge_date": discharge,
            "diagnosis": "appendicitis",
            "procedure": "Appendectomy",
            "room_category": "single_private",
            "sum_insured": sum_insured,
            "bill_lines": lines,
            "bill_total": str(sum(Decimal(line["amount"]) for line in lines)),
        }
    )


def test_room_breach_caps_the_room_and_cuts_linked_charges_proportionally():
    # SI 2,00,000: room limit = min(2% = 4,000, 5,000) = Rs 4,000/day (12.1).
    # Room 21,000 for 3 days = 7,000/day: payable 3 x 4,000 = 12,000.00.
    # Ratio 4,000 / 7,000 = 4/7 on linked charges (4.1.1(b)):
    #   surgeon 15,000 x 4/7 = 8,571.43; OT 30,000 x 4/7 = 17,142.86.
    # Medicines are never cut: 8,000.00. Gloves chosen as non-payable: 0.00.
    # Admissible 12,000 + 8,571.43 + 17,142.86 + 8,000 = 45,714.29.
    # Co-pay 5% (9.5) = 2,285.71. Payable 45,714.29 - 2,285.71 = 43,428.58.
    claim = _claim(
        [
            _line("L1", "room", "21000.00", 3),
            _line("L2", "doctor_fees", "15000.00"),
            _line("L3", "ot", "30000.00"),
            _line("L4", "medicines", "8000.00"),
            _line("L5", "consumables", "2000.00"),
        ]
    )
    ws = adjudicate(claim, {"L5": C.NON_PAYABLE_ITEMS}, PolicyRules())
    payable = {line.line_id: line.payable for line in ws.lines}
    assert payable == {
        "L1": Decimal("12000.00"),
        "L2": Decimal("8571.43"),
        "L3": Decimal("17142.86"),
        "L4": Decimal("8000.00"),
        "L5": Decimal("0.00"),
    }
    assert ws.co_pay.amount == Decimal("2285.71")
    assert ws.total_payable == Decimal("43428.58")


def test_no_breach_means_only_the_co_pay_comes_off():
    # SI 5,00,000: room limit = min(10,000, 5,000) = 5,000/day. Room 6,000 for 2 days = 3,000/day:
    # under the limit, so nothing is cut. Admissible 6,000 + 4,000 = 10,000.
    # Co-pay 5% = 500.00. Payable 9,500.00.
    claim = _claim(
        [_line("L1", "room", "6000.00", 2), _line("L2", "doctor_fees", "4000.00")],
        sum_insured="500000.00",
        discharge="2026-05-12",
    )
    ws = adjudicate(claim, {}, PolicyRules())
    assert all(not line.deductions for line in ws.lines)
    assert ws.co_pay.amount == Decimal("500.00")
    assert ws.total_payable == Decimal("9500.00")


def test_an_out_of_period_claim_is_deducted_in_full_under_clause_2():
    # Clause 2 covers only stays "during the policy period". The admissibility gate cites it for
    # every line (ADR-0010), so every line is deducted in full: payable 0, co-pay 0.
    lines = [_line("L1", "room", "6000.00", 2), _line("L2", "doctor_fees", "4000.00")]
    claim = _claim(lines, sum_insured="500000.00", discharge="2026-05-12")
    ws = adjudicate(claim, {"L1": C.POLICY_PERIOD, "L2": C.POLICY_PERIOD}, PolicyRules())
    assert [line.payable for line in ws.lines] == [Decimal("0.00"), Decimal("0.00")]
    assert all([d.reason for d in line.deductions] == [DeductionReason.OTHER] for line in ws.lines)
    assert ws.total_payable == Decimal("0.00")
