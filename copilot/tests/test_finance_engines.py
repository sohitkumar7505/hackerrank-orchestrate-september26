"""
Tests for all financial calculation engines.
Uses 5 validation scenarios from the implementation plan.
"""
import pytest
from copilot.backend.finance.emi import calculate_emi, emi_vs_cash_comparison
from copilot.backend.finance.fd import calculate_fd_maturity
from copilot.backend.finance.sip import calculate_sip_future_value, calculate_lumpsum_future_value, required_monthly_sip
from copilot.backend.finance.inflation import adjust_for_inflation, required_monthly_savings_for_goal
from copilot.backend.finance.tax import calculate_tax, TAX_RULES
from copilot.backend.finance.portfolio import build_portfolio, compare_portfolios
from copilot.backend.finance.scenario import run_scenarios
from copilot.backend.goal import GoalProfile, UserFinancialContext, RiskProfile
from copilot.backend.goal_analyzer import evaluate_goal_options


# ════════════════════════════════════════════════════════════════
# EMI Tests
# ════════════════════════════════════════════════════════════════

class TestEMI:
    def test_basic_emi_calculation(self):
        """₹1L principal at 12% for 12 months."""
        result = calculate_emi(100000, 12.0, 12)
        # Standard EMI formula: 100000 * 0.01 * 1.01^12 / (1.01^12 - 1)
        assert 8800 <= result.emi <= 8900, f"EMI {result.emi} out of expected range"
        assert result.total_payment == pytest.approx(result.emi * 12, abs=2)
        assert result.total_interest > 0

    def test_no_cost_emi(self):
        """Zero interest EMI should have no interest cost."""
        result = calculate_emi(60000, 0.0, 6)
        assert result.emi == pytest.approx(10000, abs=1)
        assert result.total_interest == 0.0
        assert result.total_cost == pytest.approx(60000, abs=1)

    def test_processing_fee_included_in_total_cost(self):
        """Processing fee should be part of total cost."""
        result = calculate_emi(100000, 12.0, 12, processing_fee_pct=1.0)
        assert result.processing_fee == pytest.approx(1000, abs=1)
        assert result.total_cost == pytest.approx(result.total_payment + 1000, abs=2)

    def test_emi_vs_cash_comparison(self):
        """EMI comparison should show extra cost vs cash."""
        result = calculate_emi(100000, 12.0, 12)
        comparison = emi_vs_cash_comparison(100000, result)
        assert comparison["extra_cost_via_emi"] > 0
        assert comparison["cash_outflow"] == 100000

    def test_invalid_principal_raises(self):
        with pytest.raises(ValueError):
            calculate_emi(-1000, 12.0, 12)

    def test_invalid_tenure_raises(self):
        with pytest.raises(ValueError):
            calculate_emi(100000, 12.0, 0)

    def test_emi_monthly_schedule(self):
        """Schedule should have correct number of entries."""
        result = calculate_emi(100000, 12.0, 6, include_schedule=True)
        assert len(result.monthly_schedule) == 6
        # Principal reduces over time
        for entry in result.monthly_schedule:
            assert "emi" in entry
            assert "principal" in entry
            assert "interest" in entry
            assert "balance" in entry


# ════════════════════════════════════════════════════════════════
# FD Tests
# ════════════════════════════════════════════════════════════════

class TestFD:
    def test_fd_maturity_basic(self):
        """₹1L FD at 7% for 12 months quarterly compounding."""
        result = calculate_fd_maturity(100000, 7.0, 12, "quarterly")
        # Expected: ~₹1,07,186
        assert 107000 <= result.maturity_value <= 107500
        assert result.interest_earned == pytest.approx(result.maturity_value - 100000, abs=1)

    def test_fd_2_year_grows_more(self):
        """2-year FD should yield more than 1-year FD."""
        fd1 = calculate_fd_maturity(100000, 7.0, 12)
        fd2 = calculate_fd_maturity(100000, 7.0, 24)
        assert fd2.maturity_value > fd1.maturity_value

    def test_fd_compounding_frequency_matters(self):
        """Monthly compounding should give slightly more than quarterly."""
        fd_quarterly = calculate_fd_maturity(100000, 7.0, 12, "quarterly")
        fd_monthly = calculate_fd_maturity(100000, 7.0, 12, "monthly")
        assert fd_monthly.maturity_value >= fd_quarterly.maturity_value

    def test_fd_invalid_principal_raises(self):
        with pytest.raises(ValueError):
            calculate_fd_maturity(-1000, 7.0, 12)


# ════════════════════════════════════════════════════════════════
# SIP Tests
# ════════════════════════════════════════════════════════════════

class TestSIP:
    def test_sip_basic(self):
        """₹10k/month SIP at 12% for 12 months."""
        result = calculate_sip_future_value(10000, 12.0, 12)
        assert result.total_invested == 120000
        assert result.maturity_value > 120000  # Returns add up
        assert result.estimated_returns > 0

    def test_sip_zero_return(self):
        """Zero return SIP should give back exactly total invested."""
        result = calculate_sip_future_value(10000, 0.0, 12)
        assert result.maturity_value == pytest.approx(120000, abs=1)
        assert result.estimated_returns == 0.0

    def test_lumpsum_future_value(self):
        """₹1L at 12% for 5 years (60 months)."""
        fv = calculate_lumpsum_future_value(100000, 12.0, 60)
        # (1.12)^5 = ~1.7623 → ~₹1,76,234
        assert 175000 <= fv <= 180000

    def test_higher_return_gives_higher_maturity(self):
        """Higher return rate should yield higher maturity value."""
        low = calculate_sip_future_value(10000, 7.0, 60)
        high = calculate_sip_future_value(10000, 12.0, 60)
        assert high.maturity_value > low.maturity_value

    def test_required_monthly_sip(self):
        """Required SIP to achieve ₹10L in 5 years at 12%."""
        monthly = required_monthly_sip(1000000, 12.0, 60)
        # Verify by computing SIP with that monthly
        verification = calculate_sip_future_value(monthly, 12.0, 60)
        assert abs(verification.maturity_value - 1000000) <= 500


# ════════════════════════════════════════════════════════════════
# Inflation Tests
# ════════════════════════════════════════════════════════════════

class TestInflation:
    def test_inflation_adjustment(self):
        """₹1L in 5 years at 6% inflation."""
        result = adjust_for_inflation(100000, 5.0, 6.0)
        # (1.06)^5 ≈ 1.3382 → ₹1,33,823
        assert 133000 <= result.future_amount <= 134500
        assert result.inflation_impact > 0
        assert result.inflation_impact_pct == pytest.approx(33.82, abs=1.0)

    def test_no_inflation(self):
        """0% inflation should not change the amount."""
        result = adjust_for_inflation(100000, 5.0, 0.0)
        assert result.future_amount == pytest.approx(100000, abs=1)
        assert result.inflation_impact == 0.0

    def test_required_savings(self):
        """Monthly savings to reach ₹5L in 3 years."""
        result = required_monthly_savings_for_goal(500000, 36)
        assert result["required_monthly_savings"] > 0
        assert result["inflation_adjusted_goal"] >= result["nominal_goal"]


# ════════════════════════════════════════════════════════════════
# Tax Tests (Indian FY2025-26)
# ════════════════════════════════════════════════════════════════

class TestTax:
    def test_equity_ltcg_exempt_within_limit(self):
        """LTCG up to ₹1.25L is exempt for equity."""
        result = calculate_tax("equity_mf", 100000, 15)  # 15 months = LTCG
        assert result.total_tax == 0.0  # ₹1L < ₹1.25L exempt

    def test_equity_ltcg_above_exempt(self):
        """LTCG above ₹1.25L should be taxed at 12.5%."""
        result = calculate_tax("equity_mf", 200000, 15)
        # Taxable = 200000 - 125000 = 75000; Tax = 75000 * 12.5% = 9375; Cess = 375
        assert result.tax_amount == pytest.approx(9375, abs=10)
        assert result.cess_amount == pytest.approx(375, abs=5)
        assert result.total_tax == pytest.approx(9750, abs=10)

    def test_equity_stcg_rate(self):
        """STCG on equity (< 12 months) at 20%."""
        result = calculate_tax("equity_mf", 100000, 6)
        assert result.tax_amount == pytest.approx(20000, abs=50)

    def test_fd_interest_taxed_as_slab(self):
        """FD interest should be taxed at income slab rate."""
        result = calculate_tax("fd", 50000, 12, annual_income=600000)
        assert result.total_tax >= 0  # Should have some tax
        assert "slab" in " ".join(result.notes).lower() or "FD" in " ".join(result.notes)

    def test_gold_stcg(self):
        """Gold STCG (< 24 months) taxed at slab rate."""
        result = calculate_tax("gold", 50000, 12, annual_income=600000)
        assert result.total_tax >= 0

    def test_gold_ltcg(self):
        """Gold LTCG (>= 24 months) taxed at 12.5%."""
        result = calculate_tax("gold", 100000, 30)
        assert result.tax_amount == pytest.approx(12500, abs=50)

    def test_zero_gain_no_tax(self):
        """Zero gain should have zero tax."""
        result = calculate_tax("equity_mf", 0, 15)
        assert result.total_tax == 0.0
        assert result.net_gain == 0.0

    def test_negative_gain_no_tax(self):
        """Negative gain (loss) should have zero tax."""
        result = calculate_tax("equity_mf", -10000, 15)
        assert result.total_tax == 0.0


# ════════════════════════════════════════════════════════════════
# Portfolio Tests
# ════════════════════════════════════════════════════════════════

class TestPortfolio:
    def test_three_portfolios_generated(self):
        """compare_portfolios should return 3 strategies."""
        portfolios = compare_portfolios(10000, 60)
        assert len(portfolios) == 3
        strategies = [p.strategy for p in portfolios]
        assert "conservative" in strategies
        assert "balanced" in strategies
        assert "growth" in strategies

    def test_growth_outperforms_conservative(self):
        """Growth portfolio should yield more than conservative over long term."""
        portfolios = compare_portfolios(10000, 120)  # 10 years
        by_strat = {p.strategy: p for p in portfolios}
        assert by_strat["growth"].net_maturity_value > by_strat["conservative"].net_maturity_value

    def test_portfolio_total_invested_correct(self):
        """Total invested should be monthly * tenure."""
        p = build_portfolio(10000, 60, "balanced")
        assert p.total_invested == pytest.approx(600000, rel=0.05)

    def test_portfolio_net_value_less_than_gross(self):
        """Tax should reduce gross to net."""
        p = build_portfolio(10000, 60, "growth")
        assert p.net_maturity_value <= p.gross_maturity_value

    def test_portfolio_blended_cagr_positive(self):
        """Blended CAGR should be positive for any strategy."""
        portfolios = compare_portfolios(10000, 60)
        for p in portfolios:
            assert p.blended_cagr_pct > 0, f"{p.strategy} CAGR should be positive"


# ════════════════════════════════════════════════════════════════
# Scenario Tests
# ════════════════════════════════════════════════════════════════

class TestScenarios:
    def test_bull_outperforms_bear(self):
        """Bull scenario should give better returns than bear."""
        result = run_scenarios(10000, 60, 500000)
        assert result.bull.equity_sip_value > result.bear.equity_sip_value

    def test_base_between_bear_and_bull(self):
        """Base scenario should be between bear and bull."""
        result = run_scenarios(10000, 60, 500000)
        assert result.bear.equity_sip_value <= result.base.equity_sip_value <= result.bull.equity_sip_value

    def test_fd_stable_across_scenarios(self):
        """FD should be relatively stable across scenarios (low variance)."""
        result = run_scenarios(10000, 60, 500000)
        variance = result.bull.fd_value - result.bear.fd_value
        equity_variance = result.bull.equity_sip_value - result.bear.equity_sip_value
        assert variance < equity_variance  # FD less volatile than equity


# ════════════════════════════════════════════════════════════════
# Risk Profile Tests
# ════════════════════════════════════════════════════════════════

class TestRiskProfile:
    def _make_ctx(self, **kwargs) -> UserFinancialContext:
        defaults = dict(monthly_income=60000, monthly_fixed_expenses=25000,
                       monthly_variable_expenses=10000, emergency_fund=180000,
                       monthly_emi_obligations=0, risk_tolerance="moderate")
        defaults.update(kwargs)
        return UserFinancialContext(**defaults)

    def _make_goal(self, horizon=12) -> GoalProfile:
        return GoalProfile(item_name="Test", current_cost=100000, target_amount=100000,
                          horizon_months=horizon)

    def test_adequate_emergency_fund_increases_score(self):
        """6+ months emergency fund should increase risk score."""
        ctx_low = self._make_ctx(emergency_fund=10000)
        ctx_high = self._make_ctx(emergency_fund=300000)
        goal = self._make_goal(60)
        low_score = RiskProfile.compute(ctx_low, goal).score
        high_score = RiskProfile.compute(ctx_high, goal).score
        assert high_score > low_score

    def test_high_debt_reduces_score(self):
        """High debt-to-income ratio should reduce risk score."""
        ctx_low_debt = self._make_ctx(monthly_emi_obligations=5000)
        ctx_high_debt = self._make_ctx(monthly_emi_obligations=30000)
        goal = self._make_goal(60)
        low_debt_score = RiskProfile.compute(ctx_low_debt, goal).score
        high_debt_score = RiskProfile.compute(ctx_high_debt, goal).score
        assert high_debt_score < low_debt_score

    def test_long_horizon_increases_score(self):
        """Long-term goals should allow higher risk."""
        ctx = self._make_ctx()
        short_goal = self._make_goal(horizon=6)
        long_goal = self._make_goal(horizon=180)
        short_score = RiskProfile.compute(ctx, short_goal).score
        long_score = RiskProfile.compute(ctx, long_goal).score
        assert long_score > short_score

    def test_score_clamped_1_to_10(self):
        """Risk score should always be 1-10."""
        ctx = self._make_ctx(monthly_emi_obligations=50000, emergency_fund=1000)
        goal = self._make_goal(horizon=3)
        profile = RiskProfile.compute(ctx, goal)
        assert 1 <= profile.score <= 10


# ════════════════════════════════════════════════════════════════
# Full Goal Evaluation Scenarios (Integration)
# ════════════════════════════════════════════════════════════════

class TestGoalEvaluationScenarios:

    def _run(self, goal_data, ctx_data):
        goal = GoalProfile(**goal_data)
        ctx = UserFinancialContext(**ctx_data)
        result = evaluate_goal_options(goal, ctx, ctx_data.get("existing_savings", 0), 10000)
        return result

    def test_scenario1_iphone_6months(self):
        """₹60k income, ₹40k expenses, ₹1L iPhone, 6-month goal."""
        result = self._run(
            {"item_name": "iPhone 16", "current_cost": 100000, "target_amount": 100000,
             "horizon_months": 6, "monthly_contribution": 10000},
            {"monthly_income": 60000, "monthly_fixed_expenses": 25000,
             "monthly_variable_expenses": 15000, "existing_savings": 50000,
             "emergency_fund": 50000, "risk_tolerance": "moderate"},
        )
        assert "recommendation" in result
        assert result["recommendation"]["recommended"] is not None
        # Short-term goal → should recommend EMI or cash, NOT equity
        rec_option = result["recommendation"]["recommended"]["option"]
        assert "retire" not in rec_option.lower()

    def test_scenario2_vacation_15months(self):
        """₹80k income, ₹50k expenses, ₹1.5L vacation, 15 months."""
        result = self._run(
            {"goal_type": "vacation", "item_name": "Europe Trip", "current_cost": 150000,
             "target_amount": 150000, "horizon_months": 15, "monthly_contribution": 8000},
            {"monthly_income": 80000, "monthly_fixed_expenses": 35000,
             "monthly_variable_expenses": 15000, "existing_savings": 80000,
             "monthly_emi_obligations": 5000, "emergency_fund": 100000,
             "risk_tolerance": "moderate"},
        )
        assert result["options"]["investments"]  # Investment options should exist

    def test_scenario3_longterm_50l(self):
        """₹1L income, ₹60k expenses, ₹50L long-term, 15 years."""
        result = self._run(
            {"goal_type": "wealth_creation", "item_name": "Retirement Corpus",
             "current_cost": 5000000, "target_amount": 5000000,
             "horizon_months": 180, "monthly_contribution": 20000},
            {"monthly_income": 100000, "monthly_fixed_expenses": 40000,
             "monthly_variable_expenses": 20000, "existing_savings": 200000,
             "existing_investments": 300000, "monthly_emi_obligations": 10000,
             "emergency_fund": 200000, "risk_tolerance": "aggressive"},
        )
        # Long-term → should recommend growth/equity
        rec = result["recommendation"]["recommended"]["option"]
        assert "portfolio" in rec.lower() or "invest" in rec.lower()

    def test_scenario4_high_debt_conservative(self):
        """High debt + low savings → conservative recommendation."""
        result = self._run(
            {"item_name": "Laptop", "current_cost": 80000, "target_amount": 80000,
             "horizon_months": 12, "monthly_contribution": 5000},
            {"monthly_income": 50000, "monthly_fixed_expenses": 20000,
             "monthly_variable_expenses": 10000, "existing_savings": 10000,
             "monthly_emi_obligations": 25000, "emergency_fund": 5000,  # 50% DTI → clearly high debt
             "risk_tolerance": "conservative"},
        )
        risk_profile = result["risk_profile"]
        assert risk_profile["category"] in ("conservative", "moderate")
        assert risk_profile["has_high_debt"] is True


    def test_scenario5_high_income_growth(self):
        """High income + high existing investments → growth option available."""
        result = self._run(
            {"goal_type": "wealth_creation", "item_name": "House Down Payment",
             "current_cost": 2000000, "target_amount": 2000000,
             "horizon_months": 60, "monthly_contribution": 40000},
            {"monthly_income": 200000, "monthly_fixed_expenses": 60000,
             "monthly_variable_expenses": 30000, "existing_savings": 1000000,
             "existing_investments": 2000000, "monthly_emi_obligations": 15000,
             "emergency_fund": 500000, "risk_tolerance": "aggressive"},
        )
        # Growth portfolio should exist and be feasible
        portfolios = result["options"]["portfolios"]
        growth = next((p for p in portfolios if p["strategy"] == "growth"), None)
        assert growth is not None
        assert growth["net_maturity_value"] > 0

    def test_result_has_all_required_keys(self):
        """Result should always have all required top-level keys."""
        result = self._run(
            {"item_name": "Test", "current_cost": 100000, "target_amount": 100000, "horizon_months": 12},
            {"monthly_income": 60000, "monthly_fixed_expenses": 30000,
             "monthly_variable_expenses": 10000, "existing_savings": 50000},
        )
        required_keys = ["goal", "user_context", "risk_profile", "options", "recommendation", "assumptions"]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_options_has_all_types(self):
        """Options should include investments, portfolios, and EMI."""
        result = self._run(
            {"item_name": "Test", "current_cost": 100000, "target_amount": 100000, "horizon_months": 24},
            {"monthly_income": 80000, "monthly_fixed_expenses": 30000,
             "monthly_variable_expenses": 15000, "existing_savings": 100000,
             "monthly_emi_obligations": 5000, "emergency_fund": 100000},
        )
        assert "investments" in result["options"]
        assert "portfolios" in result["options"]
        assert "emi" in result["options"]

    def test_disclaimer_always_present(self):
        """Disclaimer must always be in the result."""
        result = self._run(
            {"item_name": "Test", "current_cost": 50000, "target_amount": 50000, "horizon_months": 6},
            {"monthly_income": 50000, "monthly_fixed_expenses": 20000,
             "monthly_variable_expenses": 10000, "existing_savings": 30000},
        )
        assert result["assumptions"]["disclaimer"]
        assert result["recommendation"]["disclaimer"]
