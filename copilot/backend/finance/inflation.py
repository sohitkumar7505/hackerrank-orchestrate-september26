"""
Inflation Engine
================
Adjusts goal amounts for inflation and calculates required savings.

Default Indian CPI inflation assumption: 6% per annum (FY2025-26 estimate).
This is clearly stated in all outputs — never hidden.
"""
from dataclasses import dataclass


# Default assumptions (configurable)
DEFAULT_INFLATION_RATE_PCT = 6.0   # India CPI average (source: RBI target range)
DEFAULT_SAVINGS_RETURN_PCT = 7.0   # Conservative liquid fund / savings rate


@dataclass
class InflationResult:
    current_amount: float
    future_amount: float               # inflation-adjusted
    inflation_rate_pct: float
    years: float
    inflation_impact: float            # how much more you need
    inflation_impact_pct: float

    def to_dict(self) -> dict:
        return {
            "current_amount": round(self.current_amount, 2),
            "future_amount": round(self.future_amount, 2),
            "inflation_rate_pct": self.inflation_rate_pct,
            "years": round(self.years, 2),
            "inflation_impact": round(self.inflation_impact, 2),
            "inflation_impact_pct": round(self.inflation_impact_pct, 2),
        }


def adjust_for_inflation(
    current_amount: float,
    years: float,
    annual_inflation_pct: float = DEFAULT_INFLATION_RATE_PCT,
) -> InflationResult:
    """
    Adjusts a current amount for inflation over a period.

    Args:
        current_amount:      Amount in today's ₹
        years:               Number of years into the future
        annual_inflation_pct: Annual inflation rate in % (default: 6%)

    Returns:
        InflationResult with future inflation-adjusted amount
    """
    if current_amount <= 0:
        raise ValueError("Amount must be positive")

    future_amount = round(current_amount * ((1 + annual_inflation_pct / 100.0) ** years), 2)
    inflation_impact = round(future_amount - current_amount, 2)
    inflation_impact_pct = round(inflation_impact / current_amount * 100, 2)

    return InflationResult(
        current_amount=current_amount,
        future_amount=future_amount,
        inflation_rate_pct=annual_inflation_pct,
        years=years,
        inflation_impact=inflation_impact,
        inflation_impact_pct=inflation_impact_pct,
    )


def required_monthly_savings_for_goal(
    goal_amount: float,
    horizon_months: int,
    annual_savings_return_pct: float = DEFAULT_SAVINGS_RETURN_PCT,
    annual_inflation_pct: float = DEFAULT_INFLATION_RATE_PCT,
    adjust_for_inflation_flag: bool = True,
) -> dict:
    """
    Calculates the monthly savings required to reach a goal, optionally
    adjusting the goal for inflation.

    Args:
        goal_amount:                 Target amount in today's ₹
        horizon_months:              Months until goal
        annual_savings_return_pct:   Return on savings (e.g. liquid fund 7%)
        annual_inflation_pct:        Inflation assumption
        adjust_for_inflation_flag:   Whether to inflate the goal amount

    Returns:
        Dict with nominal_goal, inflation_adjusted_goal, required_monthly_savings
    """
    from copilot.backend.finance.sip import required_monthly_sip

    years = horizon_months / 12.0
    if adjust_for_inflation_flag and years > 0:
        inflation_result = adjust_for_inflation(goal_amount, years, annual_inflation_pct)
        target = inflation_result.future_amount
    else:
        target = goal_amount
        inflation_result = None

    monthly_needed = required_monthly_sip(target, annual_savings_return_pct, horizon_months)

    return {
        "nominal_goal": round(goal_amount, 2),
        "inflation_adjusted_goal": round(target, 2),
        "annual_inflation_assumption_pct": annual_inflation_pct,
        "annual_return_assumption_pct": annual_savings_return_pct,
        "horizon_months": horizon_months,
        "required_monthly_savings": round(monthly_needed, 2),
        "inflation_impact": round(target - goal_amount, 2) if inflation_result else 0.0,
    }
