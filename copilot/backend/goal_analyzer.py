"""
Goal Analyzer
=============
Extracts GoalProfile from natural language using LLM with deterministic fallback.
Also provides the full goal-based financial evaluation combining all engines.
"""
from __future__ import annotations
import json
import re
from datetime import date, timedelta
from typing import Optional

from copilot.backend.goal import GoalProfile, UserFinancialContext, RiskProfile
from copilot.backend.finance.emi import calculate_emi, emi_vs_cash_comparison
from copilot.backend.finance.fd import calculate_fd_maturity
from copilot.backend.finance.sip import calculate_sip_future_value, required_monthly_sip
from copilot.backend.finance.inflation import adjust_for_inflation, required_monthly_savings_for_goal
from copilot.backend.finance.tax import calculate_tax
from copilot.backend.finance.portfolio import compare_portfolios, build_portfolio, INVESTMENT_ASSUMPTIONS
from copilot.backend.finance.scenario import run_scenarios


# ─── LLM-based extraction ─────────────────────────────────────────────────────

GOAL_EXTRACTION_PROMPT = """You are a financial assistant. Extract the user's financial goal from their message.

User message: "{message}"

Extract and return ONLY a JSON object with these fields:
{{
  "goal_type": "purchase|vacation|education|car|house_down_payment|emergency_fund|retirement|wealth_creation|other",
  "item_name": "string (what they want to buy/achieve)",
  "current_cost": number (amount in ₹, 0 if unknown),
  "target_date": "YYYY-MM-DD or null",
  "horizon_months": number (months until goal, estimate if not explicit),
  "flexibility": "fixed|flexible|aspirational",
  "priority": "essential|important|nice_to_have",
  "monthly_contribution": number (monthly savings available for this goal, 0 if unknown)
}}

Rules:
- Convert lakh/lac to number: 1 lakh = 100000
- Convert "k" to thousands: 50k = 50000
- If horizon is given in years, convert to months
- If no date given but months mentioned, calculate horizon_months
- If completely unknown, use reasonable defaults

Return ONLY the JSON, no explanation.
"""


def extract_goal_from_text(
    message: str,
    openai_client=None,
    model: str = "gpt-4o-mini",
) -> GoalProfile:
    """
    Extracts GoalProfile from user's natural language message.
    Falls back to heuristic extraction if LLM unavailable.
    """
    # Try LLM extraction
    if openai_client:
        try:
            response = openai_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a JSON-only financial goal extractor. Return only valid JSON."},
                    {"role": "user", "content": GOAL_EXTRACTION_PROMPT.format(message=message)},
                ],
                temperature=0.0,
                max_tokens=300,
            )
            raw = response.choices[0].message.content.strip()
            # Clean potential markdown fences
            raw = re.sub(r"```json\s*|\s*```", "", raw).strip()
            data = json.loads(raw)
            return GoalProfile(**{k: v for k, v in data.items() if v is not None})
        except Exception:
            pass  # Fall through to heuristic

    # ─── Heuristic extraction ─────────────────────────────────────────────────
    return _heuristic_extract(message)


def _heuristic_extract(message: str) -> GoalProfile:
    """Simple regex-based goal extraction as a fallback."""
    msg = message.lower()
    cleaned = msg.replace(",", "")

    # Extract amount
    amount = 0.0
    lakh_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:lakh|lakhs|lac|lacs|\bl\b)", cleaned)
    if lakh_match:
        amount = float(lakh_match.group(1)) * 100000.0

    if not amount:
        k_match = re.search(r"₹?\s*(\d+(?:\.\d+)?)\s*k\b", cleaned)
        if k_match:
            amount = float(k_match.group(1)) * 1000.0

    if not amount:
        # Match numbers 4 digits or longer
        num_matches = [float(x) for x in re.findall(r"\b\d{4,}\b", cleaned)]
        if num_matches:
            amount = max(num_matches)

    # Extract horizon
    months = 12
    year_match = re.search(r"(\d+)\s*(?:year|yr|years|yrs)", cleaned)
    month_match = re.search(r"(\d+)\s*(?:month|mo|months|mos)", cleaned)
    if year_match:
        months = int(year_match.group(1)) * 12
    elif month_match:
        months = int(month_match.group(1))

    # Goal type heuristics
    goal_type = "purchase"
    item_name = "Goal"
    if any(w in cleaned for w in ["iphone", "phone", "laptop", "macbook", "tv", "camera", "gadget"]):
        goal_type = "purchase"
        item_name = "Electronics / Gadget"
    elif any(w in cleaned for w in ["trip", "vacation", "holiday", "travel", "tour"]):
        goal_type = "vacation"
        item_name = "Vacation / Travel"
    elif any(w in cleaned for w in ["car", "bike", "vehicle", "scooter"]):
        goal_type = "car"
        item_name = "Vehicle"
    elif any(w in cleaned for w in ["education", "course", "mba", "degree", "school", "college"]):
        goal_type = "education"
        item_name = "Education"
    elif any(w in cleaned for w in ["wedding", "marriage"]):
        goal_type = "wedding"
        item_name = "Wedding"
    elif any(w in cleaned for w in ["house", "flat", "apartment", "down payment", "home"]):
        goal_type = "house_down_payment"
        item_name = "Home / Down Payment"
    elif any(w in cleaned for w in ["emergency", "medical", "fund"]):
        goal_type = "emergency_fund"
        item_name = "Emergency Fund"
    elif any(w in cleaned for w in ["retire", "retirement"]):
        goal_type = "retirement"
        item_name = "Retirement"

    # Monthly savings
    monthly = 0.0
    save_match = re.search(r"(?:save|saving|invest|investing)\s*(?:₹|rs\.?|inr)?\s*(\d+)", cleaned)
    if save_match:
        monthly = float(save_match.group(1))

    return GoalProfile(
        goal_type=goal_type,
        item_name=item_name,
        current_cost=amount,
        target_amount=amount,
        horizon_months=months,
        monthly_contribution=monthly,
    )



# ─── Full Goal Evaluation ─────────────────────────────────────────────────────

def evaluate_goal_options(
    goal: GoalProfile,
    ctx: UserFinancialContext,
    current_balance: float = 0.0,
    min_balance: float = 0.0,
) -> dict:
    """
    Evaluates all financial strategies for a goal and returns a structured comparison.

    Strategies compared:
        1. Pay now (cash)
        2. EMI (3, 6, 12 month options)
        3. Save cash (no-return savings)
        4. FD (fixed deposit)
        5. Debt MF (debt mutual fund)
        6. Equity SIP (Nifty50 / equity MF)
        7. Gold SIP
        8. Portfolio (conservative / balanced / growth)
        9. Wait and buy later

    Returns:
        Dict with all options ranked + recommendation + scenarios
    """
    amount = goal.target_amount or goal.current_cost
    horizon = goal.horizon_months
    monthly = min(goal.monthly_contribution or ctx.monthly_surplus, ctx.monthly_surplus)
    annual_income = ctx.annual_income or ctx.monthly_income * 12

    # ── Inflation adjustment ───────────────────────────────────────────────
    inflation_result = None
    if horizon > 6:
        infl = adjust_for_inflation(amount, horizon / 12.0)
        inflation_result = infl.to_dict()
        inflation_adjusted_amount = infl.future_amount
    else:
        inflation_adjusted_amount = amount

    # ── Risk profile ──────────────────────────────────────────────────────
    risk_profile = RiskProfile.compute(ctx, goal)

    # ── Option 1: Pay cash now ─────────────────────────────────────────────
    can_pay_now = current_balance - amount >= min_balance
    pay_now = {
        "option": "pay_now",
        "label": "Buy Now (Cash)",
        "feasible": can_pay_now,
        "cost": round(amount, 2),
        "total_outflow": round(amount, 2),
        "monthly_outflow": 0.0,
        "time_to_goal_months": 0,
        "opportunity_cost": _opportunity_cost(amount, 12.0, horizon),
        "pros": ["No interest cost", "Immediate ownership"],
        "cons": ["Depletes liquid savings", f"Opportunity cost: ₹{_opportunity_cost(amount, 12.0, horizon):,.0f} if invested"],
    }

    # ── Options 2: EMI ─────────────────────────────────────────────────────
    emi_options = []
    for tenure, rate in [(3, 0.0), (6, 14.0), (12, 14.0), (18, 15.0), (24, 15.0)]:
        if monthly * tenure < amount * 0.5:
            continue  # Skip if monthly is too low to service
        try:
            emi_res = calculate_emi(amount, rate, tenure)
            emi_options.append({
                "option": f"emi_{tenure}m",
                "label": f"EMI — {tenure} months {'(No-Cost)' if rate == 0 else f'@ {rate}%'}",
                "feasible": emi_res.emi <= monthly,
                "monthly_outflow": emi_res.emi,
                "total_outflow": emi_res.total_cost,
                "total_interest": emi_res.total_interest,
                "processing_fee": emi_res.processing_fee,
                "time_to_goal_months": 0,  # Own it immediately
                "tenure_months": tenure,
                "annual_rate_pct": rate,
                "pros": ["Immediate ownership", f"Split into {tenure} manageable payments"],
                "cons": [f"Extra cost: ₹{emi_res.total_interest:,.0f}" if rate > 0 else "No extra cost (No-Cost EMI)"],
            })
        except Exception:
            pass

    # ── Option 3: Save and buy later ──────────────────────────────────────
    if monthly > 0:
        months_to_save = max(1, round(amount / monthly))
        save_option = {
            "option": "save_cash",
            "label": "Save Cash (No investment return)",
            "feasible": True,
            "monthly_outflow": monthly,
            "total_invested": monthly * months_to_save,
            "maturity_value": monthly * months_to_save,
            "time_to_goal_months": months_to_save,
            "return_pct": 0.0,
            "pros": ["No risk", "No debt"],
            "cons": [f"Takes {months_to_save} months", "Inflation erodes purchasing power"],
        }
    else:
        save_option = None

    # ── Options 4-7: Investment options ─────────────────────────────────────
    investment_options = []
    if monthly > 0:
        for asset, label, return_pct, tax_class in [
            ("fd",      "FD (Fixed Deposit)",           7.0,  "fd"),
            ("debt_mf", "Debt Mutual Fund",              7.5,  "debt_mf"),
            ("gold",    "Gold SIP (Gold ETF/Fund)",      8.0,  "gold"),
            ("equity",  "Equity SIP (Nifty50 Index Fund)", 12.0, "equity_mf"),
        ]:
            sip = calculate_sip_future_value(monthly, return_pct, horizon)
            gain = sip.estimated_returns
            tax_res = calculate_tax(tax_class, gain, horizon, annual_income)
            net_value = round(sip.maturity_value - tax_res.total_tax, 2)
            surplus = round(net_value - amount, 2)
            feasible = net_value >= amount

            # Required monthly to hit goal
            req_monthly = required_monthly_sip(inflation_adjusted_amount, return_pct, horizon)

            investment_options.append({
                "option": f"invest_{asset}",
                "label": label,
                "asset_class": asset,
                "feasible": feasible,
                "monthly_outflow": round(monthly, 2),
                "required_monthly_for_goal": round(req_monthly, 2),
                "total_invested": round(sip.total_invested, 2),
                "gross_maturity_value": round(sip.maturity_value, 2),
                "tax_amount": round(tax_res.total_tax, 2),
                "net_maturity_value": net_value,
                "surplus_or_shortfall": surplus,
                "expected_return_pct": return_pct,
                "time_to_goal_months": horizon,
                "risk_level": INVESTMENT_ASSUMPTIONS.get(asset, {}).get("risk", "unknown"),
                "disclaimer": "Expected return based on historical data. NOT guaranteed.",
                "pros": [f"Potentially ₹{net_value:,.0f} after {horizon} months"],
                "cons": [
                    f"Tax: ₹{tax_res.total_tax:,.0f}",
                    "Returns not guaranteed" if asset in ("equity", "gold") else "Lower growth potential",
                ],
            })

    # ── Option 8: Portfolios ───────────────────────────────────────────────
    portfolio_options = []
    if monthly > 0:
        portfolios = compare_portfolios(monthly, horizon, annual_income)
        for p in portfolios:
            surplus = round(p.net_maturity_value - amount, 2)
            portfolio_options.append({
                "option": f"portfolio_{p.strategy}",
                "label": f"{p.strategy.title()} Portfolio",
                "strategy": p.strategy,
                "feasible": p.net_maturity_value >= amount,
                "monthly_outflow": round(monthly, 2),
                "total_invested": round(p.total_invested, 2),
                "gross_maturity_value": round(p.gross_maturity_value, 2),
                "tax_amount": round(p.total_tax, 2),
                "net_maturity_value": round(p.net_maturity_value, 2),
                "blended_cagr_pct": p.blended_cagr_pct,
                "surplus_or_shortfall": surplus,
                "allocations": [a.__dict__ for a in p.allocations],
                "description": p.description,
                "disclaimer": p.disclaimer,
            })

    # ── Scenario analysis ──────────────────────────────────────────────────
    scenarios = None
    if monthly > 0:
        scenario_set = run_scenarios(monthly, horizon, amount, annual_income)
        scenarios = scenario_set.to_dict()

    # ── Recommendation ────────────────────────────────────────────────────
    recommendation = _generate_recommendation(
        goal=goal,
        ctx=ctx,
        risk_profile=risk_profile,
        can_pay_now=can_pay_now,
        emi_options=emi_options,
        investment_options=investment_options,
        portfolio_options=portfolio_options,
        amount=amount,
        monthly=monthly,
        horizon=horizon,
    )

    return {
        "goal": goal.model_dump(),
        "user_context": {
            "monthly_surplus": round(ctx.monthly_surplus, 2),
            "debt_to_income_ratio": ctx.debt_to_income_ratio,
            "emergency_fund_months": ctx.emergency_fund_months,
        },
        "risk_profile": risk_profile.model_dump(),
        "inflation_result": inflation_result,
        "inflation_adjusted_goal": round(inflation_adjusted_amount, 2),
        "options": {
            "pay_now": pay_now,
            "emi": emi_options,
            "save_cash": save_option,
            "investments": investment_options,
            "portfolios": portfolio_options,
        },
        "scenarios": scenarios,
        "recommendation": recommendation,
        "assumptions": {
            "inflation_rate_pct": 6.0,
            "fd_return_pct": 7.0,
            "debt_mf_return_pct": 7.5,
            "gold_return_pct": 8.0,
            "equity_return_pct": 12.0,
            "tax_rules_version": "FY2025-26",
            "disclaimer": (
                "All investment return figures are ASSUMPTIONS based on historical data. "
                "They are NOT guaranteed future returns. "
                "This tool provides financial education, not regulated investment advice. "
                "Please consult a SEBI-registered financial advisor before investing."
            ),
        },
    }


def _opportunity_cost(amount: float, return_pct: float, horizon_months: int) -> float:
    """What amount could become if invested for the horizon period."""
    from copilot.backend.finance.sip import calculate_lumpsum_future_value
    fv = calculate_lumpsum_future_value(amount, return_pct, horizon_months)
    return round(fv - amount, 2)


def _generate_recommendation(
    goal: GoalProfile,
    ctx: UserFinancialContext,
    risk_profile: RiskProfile,
    can_pay_now: bool,
    emi_options: list[dict],
    investment_options: list[dict],
    portfolio_options: list[dict],
    amount: float,
    monthly: float,
    horizon: int,
) -> dict:
    """
    Generates a structured, explainable recommendation.
    Logic is deterministic — LLM is used only for natural language explanation.
    """
    strategy = risk_profile.recommended_strategy()

    # ── Decision logic ────────────────────────────────────────────────────
    recommended_option = None
    why = []
    why_not = {}
    risks = []
    alternatives = []

    # Case 1: Short-term purchase — can pay now
    if goal.is_short_term() and can_pay_now and goal.goal_type == "purchase":
        # Check if no-cost EMI is available
        no_cost_emi = next((e for e in emi_options if e.get("annual_rate_pct", 1) == 0 and e["feasible"]), None)
        if no_cost_emi:
            recommended_option = no_cost_emi
            why = [
                "No-Cost EMI is available — you pay the same amount as cash with zero extra cost.",
                "Preserves liquid savings for emergencies.",
                f"Monthly outflow of ₹{no_cost_emi['monthly_outflow']:,.0f} is within your monthly surplus of ₹{ctx.monthly_surplus:,.0f}.",
            ]
            why_not["pay_now"] = "No-Cost EMI gives same cost with better cash flow management."
            alternatives = ["pay_now", "invest_fd"]
            risks = ["Ensure EMI payments don't cause cash flow issues."]
        else:
            recommended_option = {"option": "pay_now", "label": "Buy Now (Cash)"}
            why = [
                "You have sufficient balance to cover this purchase.",
                f"Remaining balance stays above your minimum of ₹{ctx.monthly_surplus:,.0f}.",
                "Avoids debt and interest costs.",
            ]
            why_not["emi_12m"] = "EMI adds extra interest cost when you can pay cash."
            alternatives = ["invest_fd", "emi_3m"]
            risks = ["Opportunity cost: the same amount invested could grow."]

    # Case 2: Short-term goal — need to save
    elif goal.is_short_term() and not can_pay_now:
        # Check feasible EMI
        feasible_emi = next((e for e in emi_options if e["feasible"]), None)
        if feasible_emi:
            recommended_option = feasible_emi
            why = [
                f"You can't pay ₹{amount:,.0f} from current balance without breaching minimum.",
                f"EMI of ₹{feasible_emi['monthly_outflow']:,.0f}/month is within your surplus.",
                "Allows you to own the item now while spreading cost.",
            ]
            why_not["pay_now"] = "Insufficient liquid balance."
            alternatives = ["save_cash", "invest_fd"]
            risks = ["EMI payment must be maintained for full tenure."]
        else:
            # Save first
            recommended_option = {"option": "save_cash", "label": "Save first, then buy"}
            why = [
                f"Monthly surplus of ₹{monthly:,.0f} is insufficient for EMI or immediate purchase.",
                "Saving first avoids debt and interest.",
            ]
            risks = ["Inflation may increase the cost before you save enough."]

    # Case 3: Medium-term goal
    elif goal.is_medium_term():
        # Recommend balanced portfolio or FD depending on risk
        if risk_profile.category == "conservative":
            best_portfolio = next((p for p in portfolio_options if p["strategy"] == "conservative"), None)
        elif risk_profile.category == "aggressive":
            best_portfolio = next((p for p in portfolio_options if p["strategy"] == "growth"), None)
        else:
            best_portfolio = next((p for p in portfolio_options if p["strategy"] == "balanced"), None)

        if best_portfolio and best_portfolio["feasible"]:
            recommended_option = best_portfolio
            why = [
                f"Your goal is {horizon} months away — medium-term horizon suits a {strategy} portfolio.",
                f"Expected corpus: ₹{best_portfolio['net_maturity_value']:,.0f} after tax.",
                f"Risk profile score: {risk_profile.score}/10 ({risk_profile.category}).",
            ] + risk_profile.reasoning
            risks = [
                "Investment returns are assumed, not guaranteed.",
                "Equity allocation may underperform in market downturns.",
            ]
            alternatives = ["invest_fd", "invest_equity"]
        else:
            recommended_option = {"option": "invest_fd", "label": "FD (Safe, Guaranteed)"}
            why = ["Goal is medium-term but monthly surplus is limited — FD is safest option."]
            risks = ["FD returns may not beat inflation."]

    # Case 4: Long-term goal
    else:
        best_portfolio = next((p for p in portfolio_options if p["strategy"] == strategy), None)
        if best_portfolio:
            recommended_option = best_portfolio
            why = [
                f"Long-term goal ({horizon} months) allows higher equity allocation.",
                f"Growth portfolio targets ₹{best_portfolio['net_maturity_value']:,.0f} after {horizon} months.",
                "Time in market reduces volatility risk for equity.",
            ] + risk_profile.reasoning
            risks = [
                "Equity can be volatile in the short term.",
                "Stay invested — don't panic during corrections.",
                "Review allocation annually.",
            ]
            why_not["invest_fd"] = "FD may not beat inflation over long periods."
            alternatives = ["portfolio_balanced", "invest_equity"]
        else:
            recommended_option = {"option": "invest_equity", "label": "Equity SIP (Nifty50)"}
            why = ["Long-term horizon makes equity most suitable."]
            risks = ["Short-term volatility can be significant."]

    return {
        "recommended": recommended_option,
        "strategy": strategy,
        "risk_profile": risk_profile.model_dump(),
        "why": why,
        "why_not": why_not,
        "risks": risks,
        "alternatives": alternatives,
        "horizon_label": goal.horizon_label(),
        "disclaimer": (
            "⚠️ This is financial education, not regulated investment advice. "
            "Returns shown are assumed based on historical data and are NOT guaranteed. "
            "Consult a SEBI-registered investment advisor before making decisions."
        ),
    }
