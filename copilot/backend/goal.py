"""
Goal Profile & Risk Profile Models
====================================
Pydantic models for goal-based financial planning.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class GoalProfile(BaseModel):
    """Represents a user's financial goal."""
    goal_type: str = "purchase"
    # Types: purchase, vacation, education, wedding, car, house_down_payment,
    #        emergency_fund, retirement, wealth_creation, other

    item_name: str = "Goal"
    current_cost: float = 0.0           # cost today in ₹
    target_amount: float = 0.0          # inflation-adjusted amount needed
    target_date: Optional[date] = None
    horizon_months: int = 12            # months until goal

    flexibility: str = "flexible"
    # flexible: can wait 3-6 months
    # fixed: hard deadline (flight/wedding/exam fee)
    # aspirational: nice to have, no hard deadline

    priority: str = "important"
    # essential: must achieve (emergency fund, rent)
    # important: high value (vacation, car)
    # nice_to_have: aspirational (luxury item)

    monthly_contribution: float = 0.0   # how much user can save per month for this goal

    def is_short_term(self) -> bool:
        return self.horizon_months <= 12

    def is_medium_term(self) -> bool:
        return 12 < self.horizon_months <= 60

    def is_long_term(self) -> bool:
        return self.horizon_months > 60

    def horizon_label(self) -> str:
        if self.is_short_term():
            return "short-term"
        elif self.is_medium_term():
            return "medium-term"
        else:
            return "long-term"

    @field_validator("flexibility")
    @classmethod
    def validate_flexibility(cls, v):
        allowed = ("flexible", "fixed", "aspirational")
        if v not in allowed:
            raise ValueError(f"flexibility must be one of {allowed}")
        return v

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v):
        allowed = ("essential", "important", "nice_to_have")
        if v not in allowed:
            raise ValueError(f"priority must be one of {allowed}")
        return v


class UserFinancialContext(BaseModel):
    """Extended user financial context for goal planning (beyond profile CSV)."""
    monthly_income: float = 0.0
    monthly_fixed_expenses: float = 0.0    # rent, EMIs, subscriptions
    monthly_variable_expenses: float = 0.0 # food, transport, entertainment
    existing_savings: float = 0.0          # liquid savings
    existing_investments: float = 0.0      # MF, stocks, etc.
    existing_debt: float = 0.0             # total outstanding debt
    monthly_emi_obligations: float = 0.0   # current EMI payments
    emergency_fund: float = 0.0            # current emergency fund
    risk_tolerance: str = "moderate"       # conservative | moderate | aggressive
    annual_income: float = 0.0             # for tax calculation

    @property
    def monthly_surplus(self) -> float:
        """Net monthly available for savings/investments."""
        return max(0, self.monthly_income - self.monthly_fixed_expenses - self.monthly_variable_expenses)

    @property
    def emergency_fund_months(self) -> float:
        """How many months of expenses covered by emergency fund."""
        monthly_expenses = self.monthly_fixed_expenses + self.monthly_variable_expenses
        if monthly_expenses <= 0:
            return 0.0
        return round(self.emergency_fund / monthly_expenses, 1)

    @property
    def debt_to_income_ratio(self) -> float:
        """Debt burden ratio (monthly EMI / monthly income)."""
        if self.monthly_income <= 0:
            return 0.0
        return round(self.monthly_emi_obligations / self.monthly_income, 2)

    @field_validator("risk_tolerance")
    @classmethod
    def validate_risk(cls, v):
        allowed = ("conservative", "moderate", "aggressive")
        if v not in allowed:
            raise ValueError(f"risk_tolerance must be one of {allowed}")
        return v


class RiskProfile(BaseModel):
    """Computed risk profile combining user inputs."""
    score: int = 5                         # 1-10 (1=ultra-conservative, 10=aggressive)
    category: str = "moderate"             # conservative | moderate | aggressive
    income_stability: str = "stable"       # stable | variable | uncertain
    has_adequate_emergency_fund: bool = False
    has_high_debt: bool = False
    reasoning: list[str] = Field(default_factory=list)

    @classmethod
    def compute(cls, ctx: UserFinancialContext, goal: GoalProfile) -> "RiskProfile":
        """
        Computes risk profile from financial context and goal.
        Uses a scoring system — NOT oversimplified rules.
        """
        score = 5  # Start at moderate
        reasoning = []

        # +/- for emergency fund adequacy (rule: 6 months recommended)
        if ctx.emergency_fund_months >= 6:
            score += 1
            reasoning.append(f"✅ Emergency fund adequate ({ctx.emergency_fund_months:.1f} months)")
        elif ctx.emergency_fund_months < 3:
            score -= 2
            reasoning.append(f"⚠️ Emergency fund low ({ctx.emergency_fund_months:.1f} months — 6 months recommended)")

        # +/- for debt burden
        dti = ctx.debt_to_income_ratio
        if dti > 0.40:
            score -= 2
            reasoning.append(f"⚠️ High debt burden ({dti:.0%} of income in EMIs)")
        elif dti > 0.20:
            score -= 1
            reasoning.append(f"ℹ️ Moderate debt burden ({dti:.0%} of income in EMIs)")
        else:
            score += 1
            reasoning.append(f"✅ Low debt burden ({dti:.0%})")

        # +/- for goal horizon
        if goal.is_long_term():
            score += 1
            reasoning.append(f"✅ Long-term goal ({goal.horizon_months} months) — can weather volatility")
        elif goal.is_short_term():
            score -= 2
            reasoning.append(f"⚠️ Short-term goal ({goal.horizon_months} months) — capital preservation is priority")

        # +/- for user's stated risk tolerance
        if ctx.risk_tolerance == "aggressive":
            score += 1
            reasoning.append("✅ User risk tolerance: aggressive")
        elif ctx.risk_tolerance == "conservative":
            score -= 1
            reasoning.append("ℹ️ User risk tolerance: conservative")

        # +/- for goal criticality
        if goal.priority == "essential":
            score -= 1
            reasoning.append("⚠️ Goal is essential — prioritising capital safety")
        elif goal.priority == "nice_to_have":
            score += 1
            reasoning.append("ℹ️ Goal is aspirational — more risk acceptable")

        # Clamp score
        score = max(1, min(10, score))

        # Categorise
        if score <= 4:
            category = "conservative"
        elif score <= 7:
            category = "moderate"
        else:
            category = "aggressive"

        # Income stability heuristic
        income_stability = "stable"
        if ctx.monthly_income <= 0:
            income_stability = "uncertain"

        return cls(
            score=score,
            category=category,
            income_stability=income_stability,
            has_adequate_emergency_fund=ctx.emergency_fund_months >= 6,
            has_high_debt=dti > 0.40,
            reasoning=reasoning,
        )

    def recommended_strategy(self) -> str:
        """Returns portfolio strategy name based on risk profile."""
        if self.category == "conservative":
            return "conservative"
        elif self.category == "aggressive":
            return "growth"
        else:
            return "balanced"
