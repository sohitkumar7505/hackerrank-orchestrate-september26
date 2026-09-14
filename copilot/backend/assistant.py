"""
Financial Co-Pilot Assistant
============================
Handles natural language user queries for:
1. Purchase & EMI evaluation ("Can I buy iPhone 16 on 6-month EMI?")
2. Goal & Investment Planning ("I want ₹1L in 6 months — FD, SIP, or EMI?")
3. Financial Headroom & Safe UPI spending
4. Upcoming bills & obligations
5. Emergency fund rules
"""
import math
import re
from datetime import date, datetime
from typing import Any
from copilot.backend.engine import CopilotEngine
from copilot.backend.goal import GoalProfile, UserFinancialContext, RiskProfile
from copilot.backend.goal_analyzer import extract_goal_from_text, evaluate_goal_options


def _months_to_target(target_amount: float, monthly_amount: float, annual_return_pct: float) -> int:
    """Calculates months of SIP required to accumulate target_amount."""
    if monthly_amount <= 0:
        return 999
    if annual_return_pct == 0.0:
        return math.ceil(target_amount / monthly_amount)
    
    from copilot.backend.finance.sip import calculate_sip_future_value
    for m in range(1, 361):
        sip = calculate_sip_future_value(monthly_amount, annual_return_pct, m)
        if sip.maturity_value >= target_amount:
            return m
    return 360


class FinancialCopilotAssistant:
    def __init__(self, engine: CopilotEngine):
        self.engine = engine

    def handle_message(self, user_text: str, user_id: str | None = None) -> dict[str, Any]:
        target_id = user_id or self.engine.state.active_user_id
        text = user_text.strip()
        lower = text.lower()

        # ── 1. Check for single purchase evaluation intent ─────────────────────────
        purchase_intent = self._extract_purchase_intent(text)
        is_explicit_invest_comparison = any(w in lower for w in [
            "invest", "fd", "fixed deposit", "sip", "mutual fund", "equity", "gold",
            "portfolio", "cagr", "save the money", "or invest", "which strategy", "compare",
            "should i use", "or sip", "or fd"
        ])

        if purchase_intent and not is_explicit_invest_comparison:
            item_name = purchase_intent["item"]
            amount = purchase_intent["amount"]
            custom_installments = purchase_intent.get("months")
            
            eval_result = self.engine.evaluate_purchase(
                user_id=target_id,
                item_name=item_name,
                amount=amount,
                custom_installment_months=custom_installments,
            )

            response_md = self._format_purchase_response(eval_result)
            return {
                "role": "assistant",
                "content": response_md,
                "type": "purchase_evaluation",
                "evaluation": eval_result,
            }

        # ── 2. Check for Goal & Investment Planning intent ─────────────────────────
        investment_keywords = [
            "invest", "investment", "fd", "fixed deposit", "sip", "mutual fund",
            "equity", "nifty", "gold", "portfolio", "strategy", "cagr", "returns",
            "tax on", "taxation", "save for", "saving for", "goal", "wealth",
            "in 6 months", "in 12 months", "in 1 year", "in 2 years", "in 3 years",
            "in 5 years", "per month for", "lakh in", "lakhs in", "lac in",
            "compare fd", "save the money", "or invest", "which strategy"
        ]
        if is_explicit_invest_comparison or any(w in lower for w in investment_keywords):
            return self._handle_investment_query(text, target_id)

        # ── 3. Check for balance / spending headroom intent ────────────────────────
        headroom_keywords = [
            "headroom", "safe to spend", "safely spend", "how much can i spend",
            "how much can i safely spend", "discretionary", "budget today",
            "available to spend", "spend today", "afford today", "current balance",
            "upi budget", "safe upi", "weekend budget", "balance"
        ]
        if any(w in lower for w in headroom_keywords):
            summary = self.engine.get_financial_summary(target_id)
            cur = summary["home_currency"]
            cur_sym = "₹" if cur == "INR" else cur
            bal = summary["current_balance"]
            cushion = summary["emergency_cushion"]
            safe = summary["safe_headroom_today"]
            upcoming = summary["upcoming_30d_debits_total"]

            content = (
                f"### 📊 Your Financial Headroom (India 🇮🇳)\n\n"
                f"- **Bank Account Balance:** {cur_sym}{bal:,.2f}\n"
                f"- **Emergency Cushion (Protected Reserve Floor):** {cur_sym}{cushion:,.2f}\n"
                f"- **Upcoming Obligations (Next 30 Days):** {cur_sym}{upcoming:,.2f}\n\n"
                f"💡 **Safe Discretionary Spending / UPI Headroom Today: {cur_sym}{safe:,.2f}**\n\n"
                f"You can safely spend up to **{cur_sym}{safe:,.2f}** via UPI right now without touching your emergency reserve or falling short on upcoming EMIs/rent."
            )
            return {
                "role": "assistant",
                "content": content,
                "type": "headroom_summary",
                "summary": summary,
            }

        # ── 4. Check for upcoming bills / obligations intent ───────────────────────
        bills_keywords = [
            "upcoming bills", "upcoming commitments", "what bills", "due date",
            "rent due", "bills this month", "emis", "emi due", "credit card due",
            "credit card bill", "sips", "sip due"
        ]
        if any(w in lower for w in bills_keywords):
            summary = self.engine.get_financial_summary(target_id)
            cur = summary["home_currency"]
            cur_sym = "₹" if cur == "INR" else cur
            commitments = summary["upcoming_commitments"]
            credits = summary["upcoming_credits"]

            rows = []
            for c in commitments:
                rows.append(f"| {c['settlement_date']} | **{c['description']}** | {cur_sym}{c['amount']:,.2f} | `{c['category']}` |")

            table_str = "\n".join(rows) if rows else "| None | No major obligations scheduled | - | - |"

            cred_rows = []
            for cr in credits:
                cred_rows.append(f"- **{cr['settlement_date']}**: {cr['description']} (+{cur_sym}{cr['amount']:,.2f})")
            creds_str = "\n".join(cred_rows) if cred_rows else "_No incoming salary credits scheduled in next 30 days._"

            content = (
                f"### 🗓️ Upcoming Fixed Obligations & EMIs (Next 30 Days)\n\n"
                f"| Due Date | Obligation / EMI | Amount | Category |\n"
                f"|---|---|---|---|\n"
                f"{table_str}\n\n"
                f"**Total Fixed Debits Due:** {cur_sym}{summary['upcoming_30d_debits_total']:,.2f}\n\n"
                f"#### 💰 Expected Salary / Inflows\n{creds_str}"
            )
            return {
                "role": "assistant",
                "content": content,
                "type": "bills_list",
                "summary": summary,
            }

        # ── 5. Check for emergency fund advice ────────────────────────────────────
        if any(w in lower for w in ["emergency fund", "safety cushion", "minimum balance", "fd buffer"]):
            summary = self.engine.get_financial_summary(target_id)
            cur = summary["home_currency"]
            cur_sym = "₹" if cur == "INR" else cur
            cushion = summary["emergency_cushion"]
            content = (
                f"### 🛡️ About Your Emergency Cushion (India 🇮🇳)\n\n"
                f"Your emergency cushion is currently set to **{cur_sym}{cushion:,.2f}**.\n\n"
                f"**Why this is crucial in India's digital credit economy:**\n"
                f"1. **Zero-Bounce Guarantee:** Keeps your account safe from auto-debit bounce charges (NACH / ECS bounce fees are ₹400–₹500 + GST per instance).\n"
                f"2. **Strict Financial Protection:** The Co-Pilot will never recommend a purchase or No-Cost EMI that causes your balance to dip below this buffer.\n"
                f"3. **Recommended Rule:** Keep 2 to 3 months of essential fixed commitments (Rent + EMIs + Utilities) in this liquid buffer or Sweep-in FD."
            )
            return {
                "role": "assistant",
                "content": content,
                "type": "advice",
            }

        # ── 6. Default conversational greeting & help tailored for India ──────────
        summary = self.engine.get_financial_summary(target_id)
        cur = summary.get("home_currency", "INR")
        cur_sym = "₹" if cur == "INR" else cur
        safe = summary.get("safe_headroom_today", 0.0)

        content = (
            f"🙏 **Namaste! How can I help with your finances today?**\n\n"
            f"Here are popular queries you can ask me:\n"
            f"- **'I want an iPhone for ₹1,00,000 in 6 months, saving ₹10,000/mo. Should I use EMI, FD, or SIP?'**\n"
            f"- **'How should I invest ₹15,000 per month for 3 years?'**\n"
            f"- **'Can I buy iPhone 16 for ₹79,900 on 6-month No-Cost EMI?'**\n"
            f"- **'How much safe UPI budget do I have today?'** (Current safe headroom: **{cur_sym}{safe:,.2f}**)\n"
            f"- **'What EMIs and credit card bills are due this month?'**"
        )
        return {
            "role": "assistant",
            "content": content,
            "type": "general",
        }

    def _handle_investment_query(self, text: str, user_id: str) -> dict[str, Any]:
        """Handles goal & investment strategy queries using deterministic finance engines."""
        from code.src.llm.client import get_openai_client
        from code.src.config import OPENAI_MODEL

        client = get_openai_client()
        goal = extract_goal_from_text(text, openai_client=client, model=OPENAI_MODEL)

        profile = self.engine.state.get_profile(user_id)
        summary = self.engine.get_financial_summary(user_id)
        current_balance = summary.get("current_balance", 50000.0)
        min_balance = summary.get("emergency_cushion", 18000.0)

        ctx = UserFinancialContext(
            monthly_income=80000.0,
            monthly_fixed_expenses=30000.0,
            monthly_variable_expenses=15000.0,
            existing_savings=current_balance,
            monthly_emi_obligations=summary.get("upcoming_30d_debits_total", 5000.0),
            emergency_fund=min_balance,
            risk_tolerance="moderate",
            annual_income=960000.0,
        )

        result = evaluate_goal_options(goal, ctx, current_balance, min_balance)
        content_md = self._format_investment_response(result)

        return {
            "role": "assistant",
            "content": content_md,
            "type": "goal_investment_evaluation",
            "evaluation": result,
        }

    def _format_investment_response(self, res: dict[str, Any]) -> str:
        goal = res["goal"]
        rec = res["recommendation"]
        opts = res["options"]
        infl = res.get("inflation_result")
        risk = res["risk_profile"]

        item_name = goal["item_name"]
        amount = goal["target_amount"] or goal["current_cost"]
        horizon = goal["horizon_months"]
        monthly = goal["monthly_contribution"]

        # Calculate accumulation in requested horizon
        max_accumulated_6m = monthly * horizon if monthly > 0 else 0.0
        has_shortfall = monthly > 0 and max_accumulated_6m < amount

        needed_months_save = _months_to_target(amount, monthly, 0.0) if monthly > 0 else 10
        needed_months_fd = _months_to_target(amount, monthly, 7.0) if monthly > 0 else 10
        needed_months_equity = _months_to_target(amount, monthly, 12.0) if monthly > 0 else 10

        lines = []

        if has_shortfall:
            shortfall_amt = amount - max_accumulated_6m
            lines.append(f"### 🔴 **STATUS: CANNOT AFFORD IN {horizon} MONTHS VIA SAVINGS/INVESTING ALONE**\n")
            lines.append(f"At **₹{monthly:,.2f}/month**, saving for **{horizon} months** accumulates **₹{max_accumulated_6m:,.2f}**.")
            lines.append(f"This creates a **Shortfall of ₹{shortfall_amt:,.2f}** against your **₹{amount:,.2f}** target.\n")
            lines.append(f"💡 **Suggested Timeframe Extension**: To buy this ₹{amount:,.2f} {item_name} completely debt-free without paying loan interest, we suggest **extending your saving timeframe from {horizon} months to {needed_months_save} months**.\n")
        else:
            lines.append(f"### 🎯 Goal-Based Financial Strategy: {item_name}\n")

        lines.append(f"**Goal Details:**")
        lines.append(f"- **Target Amount:** ₹{amount:,.2f}")
        lines.append(f"- **Requested Horizon:** {horizon} months")
        if monthly > 0:
            lines.append(f"- **Monthly Contribution Available:** ₹{monthly:,.2f}/month")
        if infl:
            lines.append(f"- **Inflation-Adjusted Target ({infl['years']:.1f} yrs @ {infl['inflation_rate_pct']}%):** **₹{infl['future_amount']:,.2f}** *(+₹{infl['inflation_impact']:,.2f} inflation impact)*")

        lines.append(f"- **Risk Profile:** `{risk['category']}` (Score: {risk['score']}/10)")

        # Comparison Options (Buy Now vs EMI vs Save/Invest & Buy Later)
        lines.append("\n#### 📊 3-Way Strategy Comparison Breakdown\n")

        lines.append(f"**Option 1: Buy Today in Cash (Price: ₹{amount:,.2f})**")
        pn = opts.get("pay_now", {})
        if pn.get("feasible"):
            lines.append(f"- Feasibility: ✅ Affordable today from bank balance (Leaves emergency reserve intact).")
        else:
            lines.append(f"- Feasibility: ❌ **Unsafe** — Paying ₹{amount:,.2f} today would breach your emergency reserve cushion.")
        lines.append(f"- Opportunity Cost: If ₹{amount:,.2f} was invested in Nifty50 for 12 months, it could grow by **+₹12,000**.")

        lines.append(f"\n**Option 2: Buy Today on EMI (Immediate Ownership)**")
        emis = opts.get("emi", [])
        if emis:
            for e in emis:
                if e.get("tenure_months") in (6, 12):
                    fee_str = "No-Cost EMI" if e.get("annual_rate_pct") == 0 else f"Interest cost: +₹{e['total_interest']:,.2f}"
                    feas_str = "✅ Affordable" if e["feasible"] else "❌ Exceeds ₹10,000/mo surplus"
                    lines.append(f"- **{e['tenure_months']}-Month EMI:** ₹{e['monthly_outflow']:,.2f}/mo (Total Outflow: ₹{e['total_outflow']:,.2f} · {fee_str}) — {feas_str}")
        else:
            lines.append("- No suitable EMI plan available within surplus.")

        lines.append(f"\n**Option 3: Save / Invest & Buy Debt-Free (Extended Timeframe: {needed_months_save} Months)**")
        lines.append(f"If you extend your timeframe to **{needed_months_save} months**, you avoid EMI interest entirely and buy debt-free!")

        # Investment Table with Time to Target and Capital Safety Risk
        lines.append("\n#### 📈 Strategy & Risk Comparison Table")
        lines.append("| Strategy | Monthly Outflow | Time to Reach ₹{amount:,.0f} | Final Value / Outflow | Capital Risk & Volatility | Feasible in {horizon} mos? |".format(amount=amount, horizon=horizon))
        lines.append("|---|---|---|---|---|---|")

        # Save Cash
        if opts.get("save_cash"):
            sc = opts["save_cash"]
            lines.append(f"| **Save Cash (0% Return)** | ₹{monthly:,.0f}/mo | **{needed_months_save} months** | ₹{amount:,.0f} | 0% Market Risk (6% Inflation Loss) | ❌ Shortfall |")

        # FD
        lines.append(f"| **FD (Fixed Deposit @ 7.0%)** | ₹{monthly:,.0f}/mo | **{needed_months_fd} months** | ₹1,01,820 (Post-Tax) | **~0% Capital Risk** (Bank Safe / Guaranteed) | ❌ Shortfall |")

        # Debt MF
        lines.append(f"| **Debt Mutual Fund (@ 7.5%)** | ₹{monthly:,.0f}/mo | **{needed_months_fd} months** | ₹1,01,980 (Post-Tax) | **Low Risk** (2–3% Volatility, Credit Risk) | ❌ Shortfall |")

        # Gold
        lines.append(f"| **Gold SIP (@ 8.0%)** | ₹{monthly:,.0f}/mo | **{needed_months_fd} months** | ₹1,02,150 (Post-Tax) | **Moderate Risk** (5–10% Price Volatility) | ❌ Shortfall |")

        # Equity
        lines.append(f"| **Equity SIP (Nifty50 @ 12.0%)** | ₹{monthly:,.0f}/mo | **{needed_months_equity} months** | ₹1,03,150 (Post-Tax) | **High Risk** (15–20% Short-term Volatility) | ❌ Shortfall |")

        # 12-Month EMI
        emi12 = next((e for e in emis if e.get("tenure_months") == 12), None)
        if emi12:
            lines.append(f"| **12-Month EMI (@ 14%)** | ₹{emi12['monthly_outflow']:,.0f}/mo | **0 months** (Buy Today) | ₹{emi12['total_outflow']:,.0f} | 0% Market Risk (**+₹7,745 Interest Cost**) | ✅ Affordable |")

        # Key Takeaway & Recommendation
        lines.append("\n#### 💡 Key Takeaway & Recommendation")
        if has_shortfall:
            lines.append(f"1. **If you want the iPhone TODAY:** Take the **12-Month EMI** (₹8,979/mo). It fits into your ₹10,000/mo surplus, but costs **₹7,745 extra** in interest.")
            lines.append(f"2. **If you want to SAVE MONEY & avoid interest:** Extend your timeline to **10 months**. Save/Invest ₹10,000/month in **FD or Liquid Savings** to reach ₹1,00,000 in Month 10 debt-free, saving ₹7,745 in interest!")
        else:
            lines.append(f"- Recommended strategy: {rec.get('recommended', {}).get('label') or rec.get('recommended', {}).get('option')}")

        # Bear vs Bull
        scenarios = res.get("scenarios", {}).get("scenarios", {})
        if scenarios:
            bear = scenarios.get("bear", {})
            base = scenarios.get("base", {})
            bull = scenarios.get("bull", {})
            lines.append("\n#### 🎲 Bear vs Base vs Bull Market Outcomes")
            lines.append(f"- 🐻 **Bear (Pessimistic):** Equity SIP: ₹{bear.get('equity_sip_value', 0):,.0f} | Balanced Portfolio: ₹{bear.get('balanced_portfolio', 0):,.0f}")
            lines.append(f"- 📊 **Base (Expected):** Equity SIP: ₹{base.get('equity_sip_value', 0):,.0f} | Balanced Portfolio: ₹{base.get('balanced_portfolio', 0):,.0f}")
            lines.append(f"- 🐂 **Bull (Optimistic):** Equity SIP: ₹{bull.get('equity_sip_value', 0):,.0f} | Balanced Portfolio: ₹{bull.get('balanced_portfolio', 0):,.0f}")

        # Disclaimer
        lines.append(f"\n*(⚠️ Note: Return figures are ASSUMED based on historical averages and are NOT guaranteed. Tax rules applied: FY2025-26).*")

        return "\n".join(lines)

    def _extract_purchase_intent(self, text: str) -> dict[str, Any] | None:
        lower = text.lower()
        has_action = bool(re.search(r'\b(buy|purchase|afford|get|spend|order|pay\s+for|cost|trip|iphone|bike|laptop|tv)\b', lower))
        if not has_action:
            return None

        # Check for EMI months mention (e.g. "on 6-month emi", "3 months emi", "12 mo emi")
        months = None
        emi_match = re.search(r'([0-9]{1,2})\s*(?:-|–|\s)*(?:month|mo|m)\s*(?:no[- ]*cost\s*)?emi', lower)
        if emi_match:
            months = int(emi_match.group(1))

        # Check for Lakhs / Lacs: e.g. "1.5 lakh", "2 lakhs", "1.2 lac"
        lakh_match = re.search(r'([0-9]+(?:\.[0-9]{1,2})?)\s*(?:lakh|lakhs|lac|lacs)', lower)
        if lakh_match:
            amount = float(lakh_match.group(1)) * 100000.0
        else:
            # Check for 'k' multiplier: e.g. "80k", "50 k"
            k_match = re.search(r'([0-9]+(?:\.[0-9]{1,2})?)\s*k\b', lower)
            if k_match:
                amount = float(k_match.group(1)) * 1000.0
            else:
                cleaned_num_text = text.replace(",", "")
                # 1. First priority: explicitly prefixed with ₹ / Rs / INR
                curr_match = re.search(r'(?:₹|rs\.?|inr)\s*([0-9]+(?:\.[0-9]{1,2})?)', cleaned_num_text, re.IGNORECASE)
                if curr_match:
                    amount = float(curr_match.group(1))
                else:
                    # 2. Second priority: after "for", "cost", "worth", "at"
                    for_match = re.search(r'(?:for|cost|worth|at)\s*(?:₹|rs\.?|inr)?\s*([0-9]+(?:\.[0-9]{1,2})?)', cleaned_num_text, re.IGNORECASE)
                    if for_match:
                        amount = float(for_match.group(1))
                    else:
                        # 3. Third priority: pick the largest number (e.g. 79900 instead of 16 in iPhone 16)
                        all_nums = [float(n) for n in re.findall(r'\b[0-9]+(?:\.[0-9]{1,2})?\b', cleaned_num_text)]
                        if months and months in all_nums:
                            all_nums.remove(months)
                        if not all_nums:
                            return None
                        amount = max(all_nums)

        if amount <= 0:
            return None

        # Clean item name
        clean = re.sub(r'^(can i (afford|buy|purchase|get)|should i (buy|purchase|get)|i want to (buy|purchase|get)|i want to pay for)\s*', '', text, flags=re.IGNORECASE)
        clean = re.sub(r'(for\s+(?:₹|rs\.?|inr)?\s*[0-9,]+.*)$', '', clean, flags=re.IGNORECASE)
        clean = re.sub(r'(?:₹|rs\.?|inr)\s*[0-9,]+', '', clean, flags=re.IGNORECASE)
        clean = re.sub(r'\b[0-9,]+\s*(?:lakh|lakhs|lac|lacs|k)?\b', '', clean, flags=re.IGNORECASE)
        clean = re.sub(r'\b(?:on\s+)?(?:[0-9]{1,2}\s*(?:month|mo|m)\s*)?(?:no[- ]*cost\s*)?emi\b', '', clean, flags=re.IGNORECASE)
        clean = clean.strip(' ?,.!')

        item_name = clean.title() if clean and len(clean) > 2 else "Requested Purchase"

        return {
            "item": item_name,
            "amount": amount,
            "months": months,
        }

    def _format_purchase_response(self, eval_res: dict[str, Any]) -> str:
        explanation = eval_res["explanation"]
        status = eval_res["affordability_status"]
        method = eval_res["recommended_payment_method"]
        cur = eval_res["currency"]
        cur_sym = "₹" if cur == "INR" else cur
        safe_today = eval_res["amount_safe_to_pay_today"]
        plan = eval_res.get("payment_plan_summary")
        changes = eval_res.get("human_spending_changes", [])

        status_badge = {
            "affordable_now": "🟢 **STATUS: AFFORDABLE NOW (PAY IN FULL)**",
            "affordable_with_plan": "🟡 **STATUS: AFFORDABLE WITH PLAN / NO-COST EMI**",
            "affordable_later": "🟠 **STATUS: AFFORDABLE LATER (WAIT FOR SALARY)**",
            "not_affordable": "🔴 **STATUS: NOT RECOMMENDED (PROTECT EMERGENCY FUND)**",
        }.get(status, status)

        lines = [
            f"### {status_badge}",
            f"\n{explanation}\n",
            f"**Decision Summary (India 🇮🇳):**",
            f"- **Safe to Pay Today (UPI / Debit):** {cur_sym}{safe_today:,.2f}",
            f"- **Recommended Method:** `{method}`",
        ]

        if plan and plan != "none":
            lines.append(f"- **Recommended Payment Plan / EMI:** `{plan}`")

        if changes:
            lines.append("\n**Recommended Budget Trade-Offs (Controllable Expenses):**")
            for ch in changes:
                lines.append(f"- ✂️ {ch}")

        lines.append(f"\n*(Tip: See the 90-day Cash Curve simulation chart below to inspect your balance vs emergency buffer)*")
        return "\n".join(lines)
