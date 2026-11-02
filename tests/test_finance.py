from decimal import Decimal
import pytest
from app.finance import amortize

def test_amortizing_schedule_reaches_zero():
    result = amortize(Decimal("10000.00"), 1200, 12)
    assert len(result["schedule"]) == 12
    assert result["schedule"][-1]["balance"] == "0.00"
    assert sum(Decimal(s["principal"]) for s in result["schedule"]) == Decimal("10000.00")
    assert Decimal(result["total_repayment"]) == Decimal("10000.00") + Decimal(result["total_interest"])

def test_zero_interest():
    result = amortize(Decimal("100.00"), 0, 3)
    assert result["total_interest"] == "0.00"
    assert result["schedule"][-1]["balance"] == "0.00"

@pytest.mark.parametrize("amount", ["-10", "0", "1.001"])
def test_invalid_principal(amount):
    with pytest.raises(ValueError):
        amortize(Decimal(amount), 200, 12)
