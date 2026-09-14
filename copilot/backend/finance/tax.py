"""
Indian Tax Engine — FY 2025-26
================================
Deterministic tax calculation for investment gains.

IMPORTANT: Tax rules are versioned in TAX_RULES dict.
Update this file when Indian tax laws change (Budget etc.).

Sources:
- Income Tax Act, 1961 (as amended by Finance Act 2024)
- LTCG on equity/equity MF: 12.5% above ₹1.25L per year (Budget 2024)
- STCG on equity/equity MF: 20% (Budget 2024, earlier 15%)
- FD interest: Taxed as income at slab rate
- Debt MF: Taxed at income slab rate (after Finance Act 2023)
- Gold STCG (<36 months): Slab rate
- Gold LTCG (>=36 months): 20% with indexation (pre-Budget 2024) or 12.5% without
"""
from dataclasses import dataclass
from typing import Optional


# ─── Versioned Tax Rules FY 2025-26 ────────────────────────────────────────
TAX_RULES = {
    "version": "FY2025-26",
    "cess_pct": 4.0,  # Health & Education Cess on income tax

    # Equity & Equity-oriented MF (holding >= 12 months = LTCG)
    "equity_ltcg": {
        "holding_months_threshold": 12,
        "exempt_limit": 125000.0,   # ₹1.25 lakh exempt per FY (Budget 2024)
        "rate_pct": 12.5,            # on gains above exempt limit
        "cess_pct": 4.0,
        "stt_required": True,
    },
    "equity_stcg": {
        "holding_months_threshold": 12,
        "rate_pct": 20.0,            # Budget 2024: raised from 15%
        "cess_pct": 4.0,
        "stt_required": True,
    },

    # Debt MF (post Finance Act 2023: taxed at slab rate regardless of holding)
    "debt_mf": {
        "tax_as": "income_slab",
        "note": "Post Apr 2023: No LTCG benefit for debt MF. Taxed at slab.",
    },

    # Fixed Deposit interest (taxed as income)
    "fd": {
        "tax_as": "income_slab",
        "tds_threshold": 40000.0,    # TDS deducted by bank above ₹40k interest
        "tds_rate_pct": 10.0,
    },

    # Gold (physical / Gold ETF / Sovereign Gold Bond)
    "gold_physical_ltcg": {
        "holding_months_threshold": 24,  # Budget 2024: changed from 36 to 24
        "rate_pct": 12.5,                # Budget 2024: 12.5% without indexation
        "cess_pct": 4.0,
    },
    "gold_physical_stcg": {
        "holding_months_threshold": 24,
        "tax_as": "income_slab",
    },
    "sgb": {
        "note": "SGB held to maturity: capital gains tax exempt. Interest taxed at slab.",
        "maturity_exempt": True,
        "interest_tax": "income_slab",
    },

    # Income slab rates FY 2025-26 (New Tax Regime — default)
    "income_slabs_new_regime": [
        {"limit": 300000,   "rate_pct": 0.0},
        {"limit": 700000,   "rate_pct": 5.0},
        {"limit": 1000000,  "rate_pct": 10.0},
        {"limit": 1200000,  "rate_pct": 15.0},
        {"limit": 1500000,  "rate_pct": 20.0},
        {"limit": None,     "rate_pct": 30.0},
    ],

    # Standard deduction (new regime FY2025-26)
    "standard_deduction": 75000,
    "rebate_87a_limit": 700000,     # Tax rebate if total income <= ₹7L (new regime)
    "rebate_87a_amount": "full",    # Full tax rebate
}


@dataclass
class TaxResult:
    asset_class: str
    gross_gain: float
    holding_months: int
    taxable_gain: float
    tax_amount: float
    cess_amount: float
    total_tax: float
    net_gain: float
    effective_rate_pct: float
    regime: str
    notes: list[str]

    def to_dict(self) -> dict:
        return {
            "asset_class": self.asset_class,
            "gross_gain": round(self.gross_gain, 2),
            "holding_months": self.holding_months,
            "taxable_gain": round(self.taxable_gain, 2),
            "tax_amount": round(self.tax_amount, 2),
            "cess_amount": round(self.cess_amount, 2),
            "total_tax": round(self.total_tax, 2),
            "net_gain": round(self.net_gain, 2),
            "effective_rate_pct": round(self.effective_rate_pct, 2),
            "regime": self.regime,
            "notes": self.notes,
        }


def _income_slab_tax(income: float, rules: dict = TAX_RULES) -> float:
    """Calculates income tax under new tax regime."""
    taxable = max(0, income - rules.get("standard_deduction", 0))
    if taxable <= rules.get("rebate_87a_limit", 700000):
        return 0.0  # Full rebate under 87A

    tax = 0.0
    prev_limit = 0
    for slab in rules["income_slabs_new_regime"]:
        rate = slab["rate_pct"] / 100.0
        limit = slab["limit"]
        if limit is None:
            tax += (taxable - prev_limit) * rate
            break
        if taxable <= limit:
            tax += (taxable - prev_limit) * rate
            break
        tax += (limit - prev_limit) * rate
        prev_limit = limit

    return round(tax, 2)


def calculate_tax(
    asset_class: str,
    gross_gain: float,
    holding_months: int,
    annual_income: float = 600000.0,  # for slab-rate assets
    rules: dict = TAX_RULES,
) -> TaxResult:
    """
    Calculates Indian income tax on investment gains.

    Args:
        asset_class:   'equity_mf' | 'debt_mf' | 'fd' | 'gold' | 'sgb' | 'savings'
        gross_gain:    Total gain/interest in ₹
        holding_months: How long the investment was held
        annual_income:  User's annual income (for slab-rate calculation)
        rules:         Tax rules dict (default: TAX_RULES FY2025-26)

    Returns:
        TaxResult with full breakdown
    """
    notes = []
    notes.append(f"Tax rules: {rules.get('version', 'FY2025-26')}")

    if gross_gain <= 0:
        return TaxResult(
            asset_class=asset_class,
            gross_gain=gross_gain,
            holding_months=holding_months,
            taxable_gain=0.0,
            tax_amount=0.0,
            cess_amount=0.0,
            total_tax=0.0,
            net_gain=gross_gain,
            effective_rate_pct=0.0,
            regime="new_regime",
            notes=["No gain — no tax applicable"],
        )

    cess_rate = rules["cess_pct"] / 100.0

    # ─── Equity / Equity MF ─────────────────────────────────────────────────
    if asset_class in ("equity_mf", "nifty50", "index_fund"):
        ltcg_threshold = rules["equity_ltcg"]["holding_months_threshold"]
        if holding_months >= ltcg_threshold:
            exempt = rules["equity_ltcg"]["exempt_limit"]
            taxable = max(0.0, gross_gain - exempt)
            rate = rules["equity_ltcg"]["rate_pct"] / 100.0
            tax = round(taxable * rate, 2)
            cess = round(tax * cess_rate, 2)
            total_tax = round(tax + cess, 2)
            notes.append(f"LTCG: ₹{exempt:,.0f} exempt, {rules['equity_ltcg']['rate_pct']}% on balance")
        else:
            taxable = gross_gain
            rate = rules["equity_stcg"]["rate_pct"] / 100.0
            tax = round(gross_gain * rate, 2)
            cess = round(tax * cess_rate, 2)
            total_tax = round(tax + cess, 2)
            notes.append(f"STCG: {rules['equity_stcg']['rate_pct']}% (held < {ltcg_threshold} months)")

    # ─── Debt MF (post Finance Act 2023) ────────────────────────────────────
    elif asset_class == "debt_mf":
        taxable = gross_gain
        slab_tax = _income_slab_tax(annual_income + gross_gain) - _income_slab_tax(annual_income)
        tax = round(slab_tax, 2)
        cess = round(tax * cess_rate, 2)
        total_tax = round(tax + cess, 2)
        notes.append("Debt MF: taxed at income slab rate (post Finance Act 2023)")

    # ─── Fixed Deposit interest ──────────────────────────────────────────────
    elif asset_class == "fd":
        taxable = gross_gain
        slab_tax = _income_slab_tax(annual_income + gross_gain) - _income_slab_tax(annual_income)
        tax = round(slab_tax, 2)
        cess = round(tax * cess_rate, 2)
        total_tax = round(tax + cess, 2)
        tds_threshold = rules["fd"]["tds_threshold"]
        notes.append(f"FD interest taxed at income slab rate. TDS deducted by bank if interest > ₹{tds_threshold:,.0f}")

    # ─── Gold ────────────────────────────────────────────────────────────────
    elif asset_class == "gold":
        ltcg_threshold = rules["gold_physical_ltcg"]["holding_months_threshold"]
        if holding_months >= ltcg_threshold:
            rate = rules["gold_physical_ltcg"]["rate_pct"] / 100.0
            taxable = gross_gain
            tax = round(gross_gain * rate, 2)
            cess = round(tax * cess_rate, 2)
            total_tax = round(tax + cess, 2)
            notes.append(f"Gold LTCG: {rules['gold_physical_ltcg']['rate_pct']}% (held >= {ltcg_threshold} months, Budget 2024)")
        else:
            taxable = gross_gain
            slab_tax = _income_slab_tax(annual_income + gross_gain) - _income_slab_tax(annual_income)
            tax = round(slab_tax, 2)
            cess = round(tax * cess_rate, 2)
            total_tax = round(tax + cess, 2)
            notes.append(f"Gold STCG: slab rate (held < {ltcg_threshold} months)")

    # ─── Savings / Cash / Liquid (treat as income) ───────────────────────────
    elif asset_class in ("savings", "liquid_fund", "rbi_bonds"):
        taxable = gross_gain
        slab_tax = _income_slab_tax(annual_income + gross_gain) - _income_slab_tax(annual_income)
        tax = round(slab_tax, 2)
        cess = round(tax * cess_rate, 2)
        total_tax = round(tax + cess, 2)
        notes.append("Interest taxed as income at slab rate")

    else:
        # Unknown asset — conservative: 30% slab
        taxable = gross_gain
        tax = round(gross_gain * 0.30, 2)
        cess = round(tax * cess_rate, 2)
        total_tax = round(tax + cess, 2)
        notes.append(f"Unknown asset class '{asset_class}': estimated at 30% slab")

    net_gain = round(gross_gain - total_tax, 2)
    effective_rate_pct = round((total_tax / gross_gain * 100) if gross_gain else 0, 2)

    return TaxResult(
        asset_class=asset_class,
        gross_gain=gross_gain,
        holding_months=holding_months,
        taxable_gain=round(taxable if 'taxable' in dir() else gross_gain, 2),
        tax_amount=tax,
        cess_amount=cess,
        total_tax=total_tax,
        net_gain=net_gain,
        effective_rate_pct=effective_rate_pct,
        regime="new_regime",
        notes=notes,
    )
