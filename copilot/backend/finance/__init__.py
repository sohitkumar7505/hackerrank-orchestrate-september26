"""
copilot.backend.finance
~~~~~~~~~~~~~~~~~~~~~~~
Deterministic financial calculation engines for the Goal-Based Planning Agent.
All calculations are pure-Python, deterministic, and LLM-free.
"""

from copilot.backend.finance.emi import calculate_emi, EMIResult
from copilot.backend.finance.fd import calculate_fd_maturity, FDResult
from copilot.backend.finance.sip import calculate_sip_future_value, calculate_lumpsum_future_value, SIPResult
from copilot.backend.finance.inflation import adjust_for_inflation, required_monthly_savings_for_goal
from copilot.backend.finance.tax import calculate_tax, TaxResult, TAX_RULES
from copilot.backend.finance.portfolio import compare_portfolios, PortfolioResult
from copilot.backend.finance.scenario import run_scenarios, ScenarioSet

__all__ = [
    "calculate_emi", "EMIResult",
    "calculate_fd_maturity", "FDResult",
    "calculate_sip_future_value", "calculate_lumpsum_future_value", "SIPResult",
    "adjust_for_inflation", "required_monthly_savings_for_goal",
    "calculate_tax", "TaxResult", "TAX_RULES",
    "compare_portfolios", "PortfolioResult",
    "run_scenarios", "ScenarioSet",
]
