"""
Scenario Simulator
==================
Runs Bear / Base / Bull scenarios for each investment option and portfolio.

Also supports parameterized "what-if" scenarios:
    - What if equity falls 20%?
    - What if I invest ₹15k instead of ₹10k?
    - What if I need money one year earlier?

IMPORTANT: All projections are based on assumptions, NOT guarantees.
"""
from dataclasses import dataclass, field
from typing import Optional
from copilot.backend.finance.sip import calculate_sip_future_value
from copilot.backend.finance.fd import calculate_fd_maturity
from copilot.backend.finance.tax import calculate_tax
from copilot.backend.finance.portfolio import build_portfolio, INVESTMENT_ASSUMPTIONS


# ─── Scenario definitions ─────────────────────────────────────────────────────
BASE_SCENARIOS = {
    "bear": {
        "label": "Bear (Pessimistic)",
        "equity_return_pct": 6.0,
        "fd_return_pct": 6.5,
        "gold_return_pct": 6.0,
        "debt_mf_return_pct": 6.5,
        "inflation_pct": 7.5,
        "description": "Market downturn — equity underperforms, inflation stays high.",
    },
    "base": {
        "label": "Base (Expected)",
        "equity_return_pct": 12.0,
        "fd_return_pct": 7.0,
        "gold_return_pct": 8.0,
        "debt_mf_return_pct": 7.5,
        "inflation_pct": 6.0,
        "description": "Historical averages — reasonable assumptions for planning.",
    },
    "bull": {
        "label": "Bull (Optimistic)",
        "equity_return_pct": 18.0,
        "fd_return_pct": 7.5,
        "gold_return_pct": 10.0,
        "debt_mf_return_pct": 8.5,
        "inflation_pct": 5.0,
        "description": "Strong market performance — equity outperforms significantly.",
    },
}


@dataclass
class ScenarioOutcome:
    scenario_key: str
    scenario_label: str
    monthly_contribution: float
    tenure_months: int
    total_invested: float
    # per-option projected values
    fd_value: float
    equity_sip_value: float
    gold_value: float
    debt_mf_value: float
    conservative_portfolio_value: float
    balanced_portfolio_value: float
    growth_portfolio_value: float
    # tax impacts
    fd_post_tax: float
    equity_post_tax: float
    gold_post_tax: float
    description: str

    def to_dict(self) -> dict:
        return {
            "scenario": self.scenario_label,
            "total_invested": round(self.total_invested, 2),
            "fd_value": round(self.fd_value, 2),
            "equity_sip_value": round(self.equity_sip_value, 2),
            "gold_value": round(self.gold_value, 2),
            "debt_mf_value": round(self.debt_mf_value, 2),
            "conservative_portfolio": round(self.conservative_portfolio_value, 2),
            "balanced_portfolio": round(self.balanced_portfolio_value, 2),
            "growth_portfolio": round(self.growth_portfolio_value, 2),
            "fd_post_tax": round(self.fd_post_tax, 2),
            "equity_post_tax": round(self.equity_post_tax, 2),
            "gold_post_tax": round(self.gold_post_tax, 2),
            "description": self.description,
        }


@dataclass
class ScenarioSet:
    monthly_contribution: float
    tenure_months: int
    total_invested: float
    goal_amount: float
    bear: ScenarioOutcome
    base: ScenarioOutcome
    bull: ScenarioOutcome
    disclaimer: str = (
        "Projections are based on assumed returns and historical trends. "
        "They are NOT guaranteed. Equity returns can be significantly negative in short periods."
    )

    def to_dict(self) -> dict:
        return {
            "monthly_contribution": round(self.monthly_contribution, 2),
            "tenure_months": self.tenure_months,
            "total_invested": round(self.total_invested, 2),
            "goal_amount": round(self.goal_amount, 2),
            "scenarios": {
                "bear": self.bear.to_dict(),
                "base": self.base.to_dict(),
                "bull": self.bull.to_dict(),
            },
            "disclaimer": self.disclaimer,
        }


def _run_single_scenario(
    scenario_key: str,
    monthly_contribution: float,
    tenure_months: int,
    annual_income: float,
    scenario_def: dict,
) -> ScenarioOutcome:
    """Runs one scenario and returns projected values for each investment option."""
    total_invested = monthly_contribution * tenure_months

    fd_sip = calculate_sip_future_value(monthly_contribution, scenario_def["fd_return_pct"], tenure_months)
    fd_gain = fd_sip.estimated_returns
    fd_tax = calculate_tax("fd", fd_gain, tenure_months, annual_income)
    fd_post_tax = round(fd_sip.maturity_value - fd_tax.total_tax, 2)

    equity_sip = calculate_sip_future_value(monthly_contribution, scenario_def["equity_return_pct"], tenure_months)
    eq_gain = equity_sip.estimated_returns
    eq_tax = calculate_tax("equity_mf", eq_gain, tenure_months, annual_income)
    equity_post_tax = round(equity_sip.maturity_value - eq_tax.total_tax, 2)

    gold_sip = calculate_sip_future_value(monthly_contribution, scenario_def["gold_return_pct"], tenure_months)
    gold_gain = gold_sip.estimated_returns
    gold_tax = calculate_tax("gold", gold_gain, tenure_months, annual_income)
    gold_post_tax = round(gold_sip.maturity_value - gold_tax.total_tax, 2)

    debt_sip = calculate_sip_future_value(monthly_contribution, scenario_def["debt_mf_return_pct"], tenure_months)

    # Override assumption returns for portfolio under this scenario
    from copy import deepcopy
    scenario_assumptions = deepcopy(INVESTMENT_ASSUMPTIONS)
    scenario_assumptions["fd"]["expected_return_pct"] = scenario_def["fd_return_pct"]
    scenario_assumptions["debt_mf"]["expected_return_pct"] = scenario_def["debt_mf_return_pct"]
    scenario_assumptions["gold"]["expected_return_pct"] = scenario_def["gold_return_pct"]
    scenario_assumptions["equity"]["expected_return_pct"] = scenario_def["equity_return_pct"]

    cons = build_portfolio(monthly_contribution, tenure_months, "conservative", annual_income, scenario_assumptions)
    bal  = build_portfolio(monthly_contribution, tenure_months, "balanced",     annual_income, scenario_assumptions)
    grw  = build_portfolio(monthly_contribution, tenure_months, "growth",       annual_income, scenario_assumptions)

    return ScenarioOutcome(
        scenario_key=scenario_key,
        scenario_label=scenario_def["label"],
        monthly_contribution=monthly_contribution,
        tenure_months=tenure_months,
        total_invested=round(total_invested, 2),
        fd_value=round(fd_sip.maturity_value, 2),
        equity_sip_value=round(equity_sip.maturity_value, 2),
        gold_value=round(gold_sip.maturity_value, 2),
        debt_mf_value=round(debt_sip.maturity_value, 2),
        conservative_portfolio_value=round(cons.net_maturity_value, 2),
        balanced_portfolio_value=round(bal.net_maturity_value, 2),
        growth_portfolio_value=round(grw.net_maturity_value, 2),
        fd_post_tax=fd_post_tax,
        equity_post_tax=equity_post_tax,
        gold_post_tax=gold_post_tax,
        description=scenario_def["description"],
    )


def run_scenarios(
    monthly_contribution: float,
    tenure_months: int,
    goal_amount: float,
    annual_income: float = 600000.0,
    custom_scenarios: Optional[dict] = None,
) -> ScenarioSet:
    """
    Runs Bear / Base / Bull scenarios and returns a ScenarioSet.

    Args:
        monthly_contribution: Monthly savings in ₹
        tenure_months:        Investment horizon in months
        goal_amount:          Target corpus in ₹
        annual_income:        User's annual income (for tax calculation)
        custom_scenarios:     Override or extend default scenarios

    Returns:
        ScenarioSet with all three scenario outcomes
    """
    scenarios = dict(BASE_SCENARIOS)
    if custom_scenarios:
        scenarios.update(custom_scenarios)

    total_invested = monthly_contribution * tenure_months

    bear = _run_single_scenario("bear", monthly_contribution, tenure_months, annual_income, scenarios["bear"])
    base = _run_single_scenario("base", monthly_contribution, tenure_months, annual_income, scenarios["base"])
    bull = _run_single_scenario("bull", monthly_contribution, tenure_months, annual_income, scenarios["bull"])

    return ScenarioSet(
        monthly_contribution=monthly_contribution,
        tenure_months=tenure_months,
        total_invested=round(total_invested, 2),
        goal_amount=goal_amount,
        bear=bear,
        base=base,
        bull=bull,
    )
