"""
Portfolio Builder
=================
Builds Conservative / Balanced / Growth portfolios and compares them.

IMPORTANT: All return figures are ASSUMPTIONS based on historical data.
They are NOT guaranteed future returns. This is for educational comparison only.

Investment assumptions (configurable):
    FD:          7.0% p.a.   (typical large bank FD rate 2025)
    Debt MF:     7.5% p.a.   (short-duration debt fund avg)
    Gold:        8.0% p.a.   (10-year CAGR estimate)
    Equity MF:   12.0% p.a.  (Nifty50 long-term CAGR ~12%)
"""
from dataclasses import dataclass, field
from typing import Optional
from copilot.backend.finance.sip import calculate_sip_future_value, SIPResult
from copilot.backend.finance.fd import calculate_fd_maturity
from copilot.backend.finance.tax import calculate_tax, TAX_RULES


# ─── Configurable investment assumptions ─────────────────────────────────────
INVESTMENT_ASSUMPTIONS = {
    "version": "2025-09",
    "disclaimer": (
        "Returns shown are ASSUMED based on historical averages. "
        "Past performance does not guarantee future results. "
        "Equity returns can be negative in short term."
    ),
    "fd":       {"expected_return_pct": 7.0,  "risk": "low",      "asset_class_tax": "fd",       "liquidity": "medium"},
    "debt_mf":  {"expected_return_pct": 7.5,  "risk": "low",      "asset_class_tax": "debt_mf",  "liquidity": "high"},
    "gold":     {"expected_return_pct": 8.0,  "risk": "medium",   "asset_class_tax": "gold",     "liquidity": "medium"},
    "equity":   {"expected_return_pct": 12.0, "risk": "high",     "asset_class_tax": "equity_mf","liquidity": "high"},
}

# ─── Allocation strategies (pct must sum to 1.0) ─────────────────────────────
ALLOCATION_STRATEGIES = {
    "conservative": {
        "fd":      0.50,
        "debt_mf": 0.30,
        "gold":    0.10,
        "equity":  0.10,
        "description": "Capital preservation with modest growth. Suits short horizon or low risk tolerance.",
    },
    "balanced": {
        "fd":      0.25,
        "debt_mf": 0.20,
        "gold":    0.15,
        "equity":  0.40,
        "description": "Balanced growth with moderate risk. Suits medium horizon (2-5 years).",
    },
    "growth": {
        "fd":      0.10,
        "debt_mf": 0.10,
        "gold":    0.10,
        "equity":  0.70,
        "description": "Higher growth potential with higher volatility. Suits long horizon (5+ years) and high risk tolerance.",
    },
}


@dataclass
class AssetAllocation:
    asset: str
    allocation_pct: float
    monthly_amount: float
    expected_return_pct: float
    maturity_value: float
    gross_gain: float
    tax_amount: float
    net_gain: float
    net_maturity_value: float


@dataclass
class PortfolioResult:
    strategy: str
    description: str
    monthly_contribution: float
    tenure_months: int
    total_invested: float
    gross_maturity_value: float
    total_tax: float
    net_maturity_value: float
    blended_cagr_pct: float
    allocations: list[AssetAllocation] = field(default_factory=list)
    assumptions_used: dict = field(default_factory=dict)
    disclaimer: str = ""

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "description": self.description,
            "monthly_contribution": round(self.monthly_contribution, 2),
            "tenure_months": self.tenure_months,
            "total_invested": round(self.total_invested, 2),
            "gross_maturity_value": round(self.gross_maturity_value, 2),
            "total_tax": round(self.total_tax, 2),
            "net_maturity_value": round(self.net_maturity_value, 2),
            "blended_cagr_pct": round(self.blended_cagr_pct, 2),
            "allocations": [
                {
                    "asset": a.asset,
                    "allocation_pct": round(a.allocation_pct * 100, 1),
                    "monthly_amount": round(a.monthly_amount, 2),
                    "expected_return_pct": a.expected_return_pct,
                    "maturity_value": round(a.maturity_value, 2),
                    "tax_amount": round(a.tax_amount, 2),
                    "net_maturity_value": round(a.net_maturity_value, 2),
                }
                for a in self.allocations
            ],
            "disclaimer": self.disclaimer,
        }


def build_portfolio(
    monthly_contribution: float,
    tenure_months: int,
    strategy: str,
    annual_income: float = 600000.0,
    assumptions: dict = INVESTMENT_ASSUMPTIONS,
    allocations: dict = ALLOCATION_STRATEGIES,
) -> PortfolioResult:
    """
    Builds a single portfolio strategy.

    Args:
        monthly_contribution: Monthly savings in ₹
        tenure_months:        Investment horizon in months
        strategy:             'conservative' | 'balanced' | 'growth'
        annual_income:        For tax slab calculation
        assumptions:          Return assumptions dict
        allocations:          Allocation strategies dict

    Returns:
        PortfolioResult with per-asset and blended performance
    """
    if monthly_contribution <= 0:
        raise ValueError("Monthly contribution must be positive")
    if tenure_months <= 0:
        raise ValueError("Tenure must be at least 1 month")

    strat = allocations.get(strategy, allocations["balanced"])
    alloc_dict = {k: v for k, v in strat.items() if k not in ("description",)}
    desc = strat.get("description", "")

    asset_results: list[AssetAllocation] = []
    total_maturity = 0.0
    total_tax = 0.0
    total_invested = monthly_contribution * tenure_months

    for asset, pct in alloc_dict.items():
        monthly_for_asset = round(monthly_contribution * pct, 2)
        if monthly_for_asset <= 0:
            continue

        asset_info = assumptions.get(asset, {"expected_return_pct": 7.0, "asset_class_tax": "fd"})
        return_pct = asset_info["expected_return_pct"]

        if asset == "fd":
            # For FD, treat as recurring deposits (approximate as SIP with FD rate)
            sip = calculate_sip_future_value(monthly_for_asset, return_pct, tenure_months)
            gross_maturity = sip.maturity_value
            gross_gain = sip.estimated_returns
        else:
            sip = calculate_sip_future_value(monthly_for_asset, return_pct, tenure_months)
            gross_maturity = sip.maturity_value
            gross_gain = sip.estimated_returns

        tax_result = calculate_tax(
            asset_class=asset_info.get("asset_class_tax", asset),
            gross_gain=gross_gain,
            holding_months=tenure_months,
            annual_income=annual_income,
        )

        net_gain = tax_result.net_gain
        net_maturity = round(monthly_for_asset * tenure_months + net_gain, 2)

        asset_results.append(AssetAllocation(
            asset=asset,
            allocation_pct=pct,
            monthly_amount=monthly_for_asset,
            expected_return_pct=return_pct,
            maturity_value=round(gross_maturity, 2),
            gross_gain=round(gross_gain, 2),
            tax_amount=round(tax_result.total_tax, 2),
            net_gain=round(net_gain, 2),
            net_maturity_value=round(net_maturity, 2),
        ))

        total_maturity += gross_maturity
        total_tax += tax_result.total_tax

    net_maturity_value = round(total_maturity - total_tax, 2)

    # Blended CAGR
    years = tenure_months / 12.0
    if total_invested > 0 and net_maturity_value > 0 and years > 0:
        blended_cagr = round(((net_maturity_value / total_invested) ** (1 / years) - 1) * 100, 2)
    else:
        blended_cagr = 0.0

    return PortfolioResult(
        strategy=strategy,
        description=desc,
        monthly_contribution=monthly_contribution,
        tenure_months=tenure_months,
        total_invested=round(total_invested, 2),
        gross_maturity_value=round(total_maturity, 2),
        total_tax=round(total_tax, 2),
        net_maturity_value=net_maturity_value,
        blended_cagr_pct=blended_cagr,
        allocations=asset_results,
        assumptions_used={k: v.get("expected_return_pct") for k, v in assumptions.items() if isinstance(v, dict)},
        disclaimer=assumptions.get("disclaimer", ""),
    )


def compare_portfolios(
    monthly_contribution: float,
    tenure_months: int,
    annual_income: float = 600000.0,
) -> list[PortfolioResult]:
    """
    Builds and compares all three portfolio strategies.

    Returns:
        [conservative_result, balanced_result, growth_result]
    """
    results = []
    for strategy in ("conservative", "balanced", "growth"):
        result = build_portfolio(
            monthly_contribution=monthly_contribution,
            tenure_months=tenure_months,
            strategy=strategy,
            annual_income=annual_income,
        )
        results.append(result)
    return results
