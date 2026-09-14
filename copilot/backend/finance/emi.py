"""
EMI (Equated Monthly Instalment) Calculator
============================================
All calculations are deterministic. No LLM involvement.

Formula:
    EMI = P × r × (1+r)^n / ((1+r)^n - 1)
    where:
        P = principal
        r = monthly interest rate (annual_rate / 12 / 100)
        n = tenure in months
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EMIResult:
    principal: float
    annual_rate_pct: float
    tenure_months: int
    emi: float
    total_payment: float
    total_interest: float
    processing_fee: float
    total_cost: float                # principal + interest + processing_fee
    effective_annual_cost_pct: float # IRR approximation
    monthly_schedule: list[dict] = field(default_factory=list)  # month-by-month breakdown

    def to_dict(self) -> dict:
        return {
            "principal": round(self.principal, 2),
            "annual_rate_pct": self.annual_rate_pct,
            "tenure_months": self.tenure_months,
            "emi": round(self.emi, 2),
            "total_payment": round(self.total_payment, 2),
            "total_interest": round(self.total_interest, 2),
            "processing_fee": round(self.processing_fee, 2),
            "total_cost": round(self.total_cost, 2),
            "effective_annual_cost_pct": round(self.effective_annual_cost_pct, 2),
        }


def calculate_emi(
    principal: float,
    annual_rate_pct: float,
    tenure_months: int,
    processing_fee_pct: float = 0.0,
    include_schedule: bool = False,
) -> EMIResult:
    """
    Calculates EMI and the full amortisation schedule.

    Args:
        principal:          Loan amount in ₹
        annual_rate_pct:    Annual interest rate in % (e.g. 12.0 for 12%)
        tenure_months:      Loan tenure in months
        processing_fee_pct: One-time processing fee as % of principal (e.g. 1.0)
        include_schedule:   If True, populate monthly_schedule

    Returns:
        EMIResult with full breakdown
    """
    if principal <= 0:
        raise ValueError("Principal must be positive")
    if tenure_months <= 0:
        raise ValueError("Tenure must be at least 1 month")

    processing_fee = round(principal * processing_fee_pct / 100.0, 2)

    # Zero-interest (No-Cost EMI)
    if annual_rate_pct == 0.0:
        emi = round(principal / tenure_months, 2)
        total_payment = emi * tenure_months
        total_interest = 0.0
        effective_rate = 0.0
        schedule = []
        if include_schedule:
            balance = principal
            for m in range(1, tenure_months + 1):
                principal_part = emi if m < tenure_months else balance
                balance -= principal_part
                schedule.append({
                    "month": m,
                    "emi": round(emi, 2),
                    "principal": round(principal_part, 2),
                    "interest": 0.0,
                    "balance": round(max(balance, 0), 2),
                })
        return EMIResult(
            principal=principal,
            annual_rate_pct=annual_rate_pct,
            tenure_months=tenure_months,
            emi=emi,
            total_payment=round(total_payment, 2),
            total_interest=0.0,
            processing_fee=processing_fee,
            total_cost=round(total_payment + processing_fee, 2),
            effective_annual_cost_pct=0.0,
            monthly_schedule=schedule,
        )

    # Standard EMI formula
    r = annual_rate_pct / 12.0 / 100.0
    factor = (1 + r) ** tenure_months
    emi = round(principal * r * factor / (factor - 1), 2)
    total_payment = round(emi * tenure_months, 2)
    total_interest = round(total_payment - principal, 2)

    # Effective annual cost (simple approximation via total cost / principal / years)
    total_cost = total_payment + processing_fee
    years = tenure_months / 12.0
    effective_annual_cost_pct = round(((total_cost / principal) - 1) / years * 100, 2) if years > 0 else annual_rate_pct

    schedule = []
    if include_schedule:
        balance = principal
        for m in range(1, tenure_months + 1):
            interest_part = round(balance * r, 2)
            principal_part = round(emi - interest_part, 2)
            balance = round(balance - principal_part, 2)
            schedule.append({
                "month": m,
                "emi": emi,
                "principal": principal_part,
                "interest": interest_part,
                "balance": max(balance, 0.0),
            })

    return EMIResult(
        principal=principal,
        annual_rate_pct=annual_rate_pct,
        tenure_months=tenure_months,
        emi=emi,
        total_payment=total_payment,
        total_interest=total_interest,
        processing_fee=processing_fee,
        total_cost=round(total_cost, 2),
        effective_annual_cost_pct=effective_annual_cost_pct,
        monthly_schedule=schedule,
    )


def emi_vs_cash_comparison(principal: float, emi_result: EMIResult) -> dict:
    """
    Compares paying cash now vs EMI.
    Returns the extra cost of EMI over paying cash.
    """
    extra_cost = emi_result.total_cost - principal
    extra_cost_pct = round(extra_cost / principal * 100, 2) if principal else 0
    return {
        "cash_outflow": round(principal, 2),
        "emi_total_outflow": round(emi_result.total_cost, 2),
        "extra_cost_via_emi": round(extra_cost, 2),
        "extra_cost_pct": extra_cost_pct,
        "monthly_emi": emi_result.emi,
        "cash_flow_relief_per_month": round(principal / emi_result.tenure_months - emi_result.emi, 2),
    }
