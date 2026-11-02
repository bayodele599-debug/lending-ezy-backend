"""Precise Decimal illustrative amortization. Does NOT calculate regulated APR."""
from decimal import Decimal, ROUND_HALF_UP, localcontext
CENT = Decimal("0.01")

def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)

def amortize(principal: Decimal, annual_rate_bps: int, months: int) -> dict:
    if principal <= 0 or principal != cents(principal):
        raise ValueError("Principal must be positive with at most two decimals")
    if not (0 <= annual_rate_bps <= 10000) or not (1 <= months <= 360):
        raise ValueError("Rate or term is out of the sandbox range")
    with localcontext() as ctx:
        ctx.prec = 38
        rate = Decimal(annual_rate_bps) / Decimal(120000)
        if rate == 0:
            installment = cents(principal / Decimal(months))
        else:
            factor = (Decimal(1) + rate) ** months
            installment = cents(principal * rate * factor / (factor - Decimal(1)))
        balance = principal
        total_interest = Decimal("0")
        total_paid = Decimal("0")
        schedule = []
        for index in range(1, months + 1):
            interest = cents(balance * rate)
            paid_principal = min(balance, installment - interest)
            if index == months:
                paid_principal = balance
            if paid_principal <= 0:
                raise ValueError("Schedule does not amortize")
            payment = paid_principal + interest
            balance = cents(balance - paid_principal)
            total_interest += interest
            total_paid += payment
            schedule.append({"installment": index, "payment": str(payment), "principal": str(paid_principal), "interest": str(interest), "balance": str(balance)})
        return {
            "monthly_payment": schedule[0]["payment"],
            "total_interest": str(total_interest),
            "total_repayment": str(total_paid),
            "schedule": schedule,
            "assumptions": "Fixed nominal annual rate; monthly payments and compounding; no fees. Illustrative, not an APR or credit offer."
        }
