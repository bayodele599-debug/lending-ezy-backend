"""Single contract for illustrative financing-plan repayment terms.

Long mortgage illustrations are only available for the explicit personal
home-purchase planning purpose; they are not lender product commitments.
"""
SHORT_TERMS = frozenset({6, 12, 18, 24, 36, 48, 60})
MORTGAGE_TERMS = frozenset({60, 120, 180, 240, 300, 360})
MORTGAGE_PURPOSE = "Home purchase & mortgage"


def valid_plan_term(kind: str, purpose: str, months: int) -> bool:
    if purpose == MORTGAGE_PURPOSE:
        return kind == "personal" and months in MORTGAGE_TERMS
    return months in SHORT_TERMS
