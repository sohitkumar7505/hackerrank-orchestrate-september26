"""
SIP (Systematic Investment Plan) & Lumpsum Calculator
======================================================
Calculates future value of SIP and lumpsum investments.

SIP Formula:
    FV = P × ((1+r)^n - 1) / r × (1+r)
    where:
        P = monthly investment
        r = monthly rate of return (annual_return / 12 / 100)
        n = number of months

CAGR-based lumpsum:
    FV = P × (1 + annual_return/100)^years
"""
from dataclasses import dataclass
import math


@dataclass
class SIPResult:
    monthly_amount: float
    annual_return_pct: float
    tenure_months: int
    total_invested: float
    estimated_returns: float
    maturity_value: float
    absolute_return_pct: float
    cagr_pct: float

    def to_dict(self) -> dict:
        return {
            "monthly_amount": round(self.monthly_amount, 2),
            "annual_return_pct": self.annual_return_pct,
            "tenure_months": self.tenure_months,
            "total_invested": round(self.total_invested, 2),
            "estimated_returns": round(self.estimated_returns, 2),
            "maturity_value": round(self.maturity_value, 2),
            "absolute_return_pct": round(self.absolute_return_pct, 2),
            "cagr_pct": round(self.cagr_pct, 2),
        }


def calculate_sip_future_value(
    monthly_amount: float,
    annual_return_pct: float,
    tenure_months: int,
) -> SIPResult:
    """
    Calculates the future value of a monthly SIP.

    NOTE: Returns are assumed/projected and NOT guaranteed.
    Historical data is used as a reference only.

    Args:
        monthly_amount:    Monthly SIP amount in ₹
        annual_return_pct: Expected annual return in % (e.g. 12.0)
        tenure_months:     Investment period in months

    Returns:
        SIPResult with total invested, returns, and maturity value
    """
    if monthly_amount <= 0:
        raise ValueError("Monthly amount must be positive")
    if tenure_months <= 0:
        raise ValueError("Tenure must be at least 1 month")

    total_invested = round(monthly_amount * tenure_months, 2)

    if annual_return_pct == 0.0:
        maturity_value = total_invested
        estimated_returns = 0.0
    else:
        r = annual_return_pct / 12.0 / 100.0
        n = tenure_months
        # Standard SIP future value formula (beginning of period)
        maturity_value = round(monthly_amount * ((((1 + r) ** n) - 1) / r) * (1 + r), 2)
        estimated_returns = round(maturity_value - total_invested, 2)

    absolute_return_pct = round((estimated_returns / total_invested * 100) if total_invested else 0, 2)

    # CAGR based on maturity vs invested
    years = tenure_months / 12.0
    if years > 0 and total_invested > 0 and maturity_value > 0:
        cagr_pct = round(((maturity_value / total_invested) ** (1 / years) - 1) * 100, 2)
    else:
        cagr_pct = 0.0

    return SIPResult(
        monthly_amount=monthly_amount,
        annual_return_pct=annual_return_pct,
        tenure_months=tenure_months,
        total_invested=total_invested,
        estimated_returns=estimated_returns,
        maturity_value=maturity_value,
        absolute_return_pct=absolute_return_pct,
        cagr_pct=cagr_pct,
    )


def calculate_lumpsum_future_value(
    amount: float,
    annual_return_pct: float,
    tenure_months: int,
) -> float:
    """
    Calculates future value of a one-time lumpsum investment.

    NOTE: Returns are assumed/projected and NOT guaranteed.

    Args:
        amount:            Lumpsum amount in ₹
        annual_return_pct: Expected annual return in % (e.g. 12.0)
        tenure_months:     Investment period in months

    Returns:
        Future value in ₹
    """
    if amount <= 0 or tenure_months <= 0:
        return amount
    if annual_return_pct == 0.0:
        return amount

    years = tenure_months / 12.0
    fv = amount * ((1 + annual_return_pct / 100.0) ** years)
    return round(fv, 2)


def required_monthly_sip(
    target_amount: float,
    annual_return_pct: float,
    tenure_months: int,
) -> float:
    """
    Calculates the monthly SIP needed to reach a target amount.

    Args:
        target_amount:     Goal corpus in ₹
        annual_return_pct: Expected annual return in %
        tenure_months:     Investment period in months

    Returns:
        Required monthly SIP in ₹
    """
    if tenure_months <= 0:
        return target_amount
    if annual_return_pct == 0.0:
        return round(target_amount / tenure_months, 2)

    r = annual_return_pct / 12.0 / 100.0
    n = tenure_months
    denominator = (((1 + r) ** n) - 1) / r * (1 + r)
    if denominator == 0:
        return round(target_amount / tenure_months, 2)
    return round(target_amount / denominator, 2)
