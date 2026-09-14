"""
Fixed Deposit (FD) Calculator
==============================
Calculates FD maturity value using compound interest.

Formula:
    A = P × (1 + r/n)^(n×t)
    where:
        P = principal
        r = annual interest rate (decimal)
        n = compounding frequency per year
        t = time in years
"""
from dataclasses import dataclass


COMPOUNDING_FREQUENCY = {
    "monthly": 12,
    "quarterly": 4,
    "half_yearly": 2,
    "yearly": 1,
}


@dataclass
class FDResult:
    principal: float
    annual_rate_pct: float
    tenure_months: int
    compounding: str
    maturity_value: float
    interest_earned: float
    effective_annual_yield_pct: float  # CAGR equivalent

    def to_dict(self) -> dict:
        return {
            "principal": round(self.principal, 2),
            "annual_rate_pct": self.annual_rate_pct,
            "tenure_months": self.tenure_months,
            "compounding": self.compounding,
            "maturity_value": round(self.maturity_value, 2),
            "interest_earned": round(self.interest_earned, 2),
            "effective_annual_yield_pct": round(self.effective_annual_yield_pct, 2),
        }


def calculate_fd_maturity(
    principal: float,
    annual_rate_pct: float,
    tenure_months: int,
    compounding: str = "quarterly",
) -> FDResult:
    """
    Calculates FD maturity value.

    Args:
        principal:       Investment amount in ₹
        annual_rate_pct: Annual interest rate in % (e.g. 7.0 for 7%)
        tenure_months:   FD tenure in months
        compounding:     'monthly' | 'quarterly' | 'half_yearly' | 'yearly'

    Returns:
        FDResult with maturity value and interest earned
    """
    if principal <= 0:
        raise ValueError("Principal must be positive")
    if tenure_months <= 0:
        raise ValueError("Tenure must be at least 1 month")

    n = COMPOUNDING_FREQUENCY.get(compounding, 4)
    r = annual_rate_pct / 100.0
    t = tenure_months / 12.0

    maturity_value = round(principal * ((1 + r / n) ** (n * t)), 2)
    interest_earned = round(maturity_value - principal, 2)

    # Effective annual yield (CAGR)
    if t > 0:
        effective_annual_yield_pct = round(((maturity_value / principal) ** (1 / t) - 1) * 100, 4)
    else:
        effective_annual_yield_pct = 0.0

    return FDResult(
        principal=principal,
        annual_rate_pct=annual_rate_pct,
        tenure_months=tenure_months,
        compounding=compounding,
        maturity_value=maturity_value,
        interest_earned=interest_earned,
        effective_annual_yield_pct=effective_annual_yield_pct,
    )
