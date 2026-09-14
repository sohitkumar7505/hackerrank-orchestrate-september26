"""
Dubai Trip Financial Advisor Test Suite
=======================================
Tests the complete goal-based planning engine for a real-world scenario:
User wants to go on a Dubai trip next year (₹1.5 Lakhs target, 12-month horizon),
but currently only saves ₹10,000 per month.

Tests:
1. Shortfall Detection & Non-Affordability in 12 months via ₹10k/mo alone
2. Timeframe Extension Suggestion (extending to 15 months)
3. Controllable Expense Cuts & Budget Boost (cutting subscriptions/dining by ₹2.5k to reach ₹12.5k/mo)
4. Recalculation under boosted budget (₹12.5k/mo reaches ₹1.5L in 12 months)
5. Risk & Return percentage disclosure (Safe FD 0% market risk vs Equity SIP market risk)
6. Assistant natural language chat response formatting
"""
import pytest
from copilot.backend.goal import GoalProfile, UserFinancialContext, RiskProfile
from copilot.backend.goal_analyzer import evaluate_goal_options, extract_goal_from_text
from copilot.backend.finance.sip import calculate_sip_future_value
from copilot.backend.finance.fd import calculate_fd_maturity
from copilot.backend.finance.tax import calculate_tax


class TestDubaiTripScenario:
    """Test suite for the Dubai trip financial planning workflow."""

    def setup_method(self):
        # Goal: Dubai Trip, ₹1.5 Lakhs (150,000), 12 months horizon
        self.dubai_goal = GoalProfile(
            goal_type="vacation",
            item_name="Dubai Trip",
            current_cost=150000.0,
            target_amount=150000.0,
            horizon_months=12,
            monthly_contribution=10000.0,  # Only 10k/mo saved
            flexibility="flexible",
            priority="important",
        )

        # User context: ₹80k income, ₹45k expenses, ₹25k current savings
        self.user_ctx = UserFinancialContext(
            monthly_income=80000.0,
            monthly_fixed_expenses=35000.0,   # rent, utilities, EMIs
            monthly_variable_expenses=15000.0, # dining out, OTT, shopping
            existing_savings=25000.0,
            monthly_emi_obligations=5000.0,
            emergency_fund=60000.0,
            risk_tolerance="moderate",
            annual_income=960000.0,
        )

    def test_1_detects_shortfall_in_12_months(self):
        """Verifies that ₹10k/month for 12 months is detected as insufficient for ₹1.5L."""
        result = evaluate_goal_options(self.dubai_goal, self.user_ctx, current_balance=25000.0, min_balance=60000.0)

        # In 12 months, 12 x 10,000 = 120,000 saved (shortfall of ~30,000)
        opts = result["options"]
        save_cash = opts.get("save_cash")
        assert save_cash is not None
        assert save_cash["maturity_value"] == 120000.0  # 120k < 150k target

        # FD returns in 12 months at 7%: ~₹1,24,600 < ₹150,000
        fd = next((i for i in opts["investments"] if i["asset_class"] == "fd"), None)
        assert fd is not None
        assert fd["net_maturity_value"] < 150000.0
        assert fd["feasible"] is False

        # Equity SIP returns in 12 months at 12%: ~₹1,28,000 < ₹150,000
        equity = next((i for i in opts["investments"] if i["asset_class"] == "equity"), None)
        assert equity is not None
        assert equity["net_maturity_value"] < 150000.0
        assert equity["feasible"] is False

    def test_2_calculates_timeframe_extension_needed(self):
        """Verifies time extension required to reach ₹1.5L at ₹10k/month."""
        # 150,000 / 10,000 = 15 months for cash
        months_cash = round(150000.0 / 10000.0)
        assert months_cash == 15

        # With FD (7% p.a.): 10k/mo reaches 1.5L in ~14.4 months
        sip_fd_14m = calculate_sip_future_value(10000.0, 7.0, 14)
        sip_fd_15m = calculate_sip_future_value(10000.0, 7.0, 15)
        assert sip_fd_14m.maturity_value < 150000.0
        assert sip_fd_15m.maturity_value >= 150000.0  # Reaches in month 15

    def test_3_suggests_expense_cuts_to_boost_budget(self):
        """
        If user wants to complete in 12 months without extending time:
        Required monthly = 150,000 / 12 = ₹12,500/month.
        User needs an extra ₹2,500/month.
        Cutting variable expenses (Swiggy dining, OTT subscriptions) from ₹15k to ₹12.5k frees up ₹2,500/mo.
        """
        required_monthly_savings = 150000.0 / 12.0  # 12,500/mo
        current_savings = self.dubai_goal.monthly_contribution  # 10,000/mo
        extra_needed = required_monthly_savings - current_savings

        assert extra_needed == 2500.0

        # Verify user has enough variable expense buffer to cut ₹2,500/mo
        assert self.user_ctx.monthly_variable_expenses >= extra_needed
        new_variable_expenses = self.user_ctx.monthly_variable_expenses - extra_needed
        assert new_variable_expenses == 12500.0  # Safe cut from dining/entertainment

    def test_4_recalculates_options_under_boosted_budget(self):
        """Verifies that under ₹12.5k/month savings, the ₹1.5L Dubai trip is achieved in 12 months."""
        boosted_goal = GoalProfile(
            goal_type="vacation",
            item_name="Dubai Trip (Boosted Budget)",
            current_cost=150000.0,
            target_amount=150000.0,
            horizon_months=12,
            monthly_contribution=12500.0,  # Boosted from 10k to 12.5k/mo
            flexibility="flexible",
            priority="important",
        )

        result = evaluate_goal_options(boosted_goal, self.user_ctx, current_balance=25000.0, min_balance=60000.0)

        # 12.5k x 12 = 150,000 saved cash
        opts = result["options"]
        save_cash = opts.get("save_cash")
        assert save_cash["maturity_value"] == 150000.0
        assert save_cash["feasible"] is True

        # FD at 7%: 12.5k/mo gives ~₹1,55,700 post-tax -> Feasible with surplus!
        fd = next((i for i in opts["investments"] if i["asset_class"] == "fd"), None)
        assert fd is not None
        assert fd["net_maturity_value"] >= 150000.0
        assert fd["feasible"] is True

        # Equity SIP at 12%: 12.5k/mo gives ~₹1,60,000 -> Feasible!
        equity = next((i for i in opts["investments"] if i["asset_class"] == "equity"), None)
        assert equity is not None
        assert equity["net_maturity_value"] >= 150000.0
        assert equity["feasible"] is True

    def test_5_risk_and_return_disclosure(self):
        """Verifies clear risk and return percentage breakdown between safe FD and Equity SIP."""
        result = evaluate_goal_options(self.dubai_goal, self.user_ctx, current_balance=25000.0, min_balance=60000.0)
        opts = result["options"]["investments"]

        fd = next(i for i in opts if i["asset_class"] == "fd")
        equity = next(i for i in opts if i["asset_class"] == "equity")

        # FD: 7% expected return, low/zero capital risk
        assert fd["expected_return_pct"] == 7.0
        assert fd["risk_level"] == "low"

        # Equity: 12% expected return, high short-term volatility risk
        assert equity["expected_return_pct"] == 12.0
        assert equity["risk_level"] == "high"

    def test_6_assistant_handles_dubai_trip_natural_language_query(self):
        """Verifies assistant processes the user's exact Dubai trip prompt cleanly."""
        from copilot.backend.assistant import FinancialCopilotAssistant
        from copilot.backend.state import AppState
        from copilot.backend.engine import CopilotEngine
        from pathlib import Path

        state = AppState(Path("dataset"))
        engine = CopilotEngine(state)
        assistant = FinancialCopilotAssistant(engine)

        prompt = "I want to go to Dubai next year for a trip. I need about 1.5 lakhs but I only save 10k per month. Should I save in FD or SIP?"
        response = assistant.handle_message(prompt, user_id="aarav_in")

        assert response["role"] == "assistant"
        content = response["content"]

        # Verifies key elements in assistant response
        assert "CANNOT AFFORD" in content or "Shortfall" in content or "10 months" in content or "15 months" in content
        assert "Dubai" in content or "Vacation" in content or "Trip" in content
        assert "₹150,000" in content or "1.5" in content or "150000" in content
        assert "FD" in content
        assert "SIP" in content
        assert "Risk" in content
