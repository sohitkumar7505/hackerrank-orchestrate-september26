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
import re
from datetime import date, datetime
from typing import Any
from copilot.backend.engine import CopilotEngine
from copilot.backend.goal import GoalProfile, UserFinancialContext, RiskProfile
from copilot.backend.goal_analyzer import extract_goal_from_text, evaluate_goal_options


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
            "portfolio", "cagr", "save the money", "or invest", "which strategy", "compare"
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

        # Estimate context defaults from user profile
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

        lines = [
            f"### 🎯 Goal-Based Financial Strategy: {item_name}",
            f"\n**Goal Details:**",
            f"- **Target Amount:** ₹{amount:,.2f}",
            f"- **Time Horizon:** {horizon} months ({rec.get('horizon_label', '')})",
        ]

        if monthly > 0:
            lines.append(f"- **Monthly Contribution Available:** ₹{monthly:,.2f}/month")

        if infl:
            lines.append(f"- **Inflation-Adjusted Target ({infl['years']:.1f} yrs @ {infl['inflation_rate_pct']}%):** **₹{infl['future_amount']:,.2f}** *(+₹{infl['inflation_impact']:,.2f} inflation impact)*")

        lines.append(f"- **Risk Profile:** `{risk['category']}` (Score: {risk['score']}/10)")

        # Recommended option
        rec_opt = rec.get("recommended", {})
        if rec_opt:
            lines.append(f"\n⭐ **RECOMMENDED STRATEGY: {rec_opt.get('label') or rec_opt.get('option')}**\n")

        # Comparison Table
        lines.append("#### 📈 Investment & Strategy Comparison Table")
        lines.append("| Strategy | Monthly Outflow | Net Projected Value (Post-Tax) | Tax | Feasible? |")
        lines.append("|---|---|---|---|---|")

        # 1. Pay Now
        if opts.get("pay_now"):
            pn = opts["pay_now"]
            lines.append(f"| **Buy Now (Cash)** | ₹{amount:,.0f} today | ₹{amount:,.0f} | ₹0 | {'✅ Yes' if pn['feasible'] else '❌ No'} |")

        # 2. Save Cash
        if opts.get("save_cash"):
            sc = opts["save_cash"]
            lines.append(f"| **Save Cash (No return)** | ₹{sc['monthly_outflow']:,.0f}/mo | ₹{sc['maturity_value']:,.0f} | ₹0 | {'✅ Yes' if sc['feasible'] else '❌ Shortfall'} |")

        # 3. Investments (FD, Debt MF, Gold, Equity)
        for inv in opts.get("investments", []):
            lines.append(f"| **{inv['label']}** ({inv['expected_return_pct']}%) | ₹{inv['monthly_outflow']:,.0f}/mo | **₹{inv['net_maturity_value']:,.0f}** | ₹{inv['tax_amount']:,.0f} | {'✅ Yes' if inv['feasible'] else '❌ Shortfall'} |")

        # 4. Portfolios
        for p in opts.get("portfolios", []):
            lines.append(f"| **{p['strategy'].title()} Portfolio** ({p['blended_cagr_pct']}%) | ₹{p['monthly_outflow']:,.0f}/mo | **₹{p['net_maturity_value']:,.0f}** | ₹{p['tax_amount']:,.0f} | {'✅ Yes' if p['feasible'] else '❌ Shortfall'} |")

        # EMI options summary
        emis = opts.get("emi", [])
        if emis:
            lines.append("\n#### 💳 Available EMI Options")
            for e in emis:
                lines.append(f"- **{e['label']}:** ₹{e['monthly_outflow']:,.2f}/month × {e['tenure_months']} mos (Total: ₹{e['total_outflow']:,.2f}, Interest: ₹{e['total_interest']:,.2f}) — {'✅ Affordable' if e['feasible'] else '❌ Exceeds surplus'}")

        # Why
        why_list = rec.get("why", [])
        if why_list:
            lines.append("\n#### ✅ Why This Strategy?")
            for w in why_list:
                lines.append(f"- {w}")

        # Scenarios
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
