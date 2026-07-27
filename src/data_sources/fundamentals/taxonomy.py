"""Standardized account-code taxonomy for ``financial_statement_items``
(spec section 3.3/8). Provider-agnostic: which ``statement_section`` each
``account_code`` belongs to, independent of any single adapter's raw field
names. Deliberately a small, high-value subset -- enough for spec section
8's core ratios (margins, ROE/ROA, current ratio, DER, EPS/PER/PBV inputs)
-- extend as more line items prove useful, never by fabricating a value
for a code a company doesn't actually report.
"""
from __future__ import annotations

CORE_ACCOUNT_CODE_SECTIONS: dict[str, str] = {
    # income_statement
    "revenue": "income_statement",
    "cost_of_revenue": "income_statement",
    "gross_profit": "income_statement",
    "operating_income": "income_statement",
    "operating_expense": "income_statement",
    "net_interest_income": "income_statement",
    "interest_income": "income_statement",
    "interest_expense": "income_statement",
    "ebitda": "income_statement",
    "pretax_income": "income_statement",
    "tax_expense": "income_statement",
    "net_income": "income_statement",
    "eps_basic": "income_statement",
    "eps_diluted": "income_statement",
    "shares_basic": "income_statement",
    "shares_diluted": "income_statement",
    # balance_sheet
    "total_assets": "balance_sheet",
    "total_liabilities": "balance_sheet",
    "total_equity": "balance_sheet",
    "current_assets": "balance_sheet",
    "current_liabilities": "balance_sheet",
    "total_debt": "balance_sheet",
    "cash_and_equivalents": "balance_sheet",
    "shares_outstanding": "balance_sheet",
    # cash_flow
    "operating_cash_flow": "cash_flow",
    "investing_cash_flow": "cash_flow",
    "financing_cash_flow": "cash_flow",
    "free_cash_flow": "cash_flow",
    "capital_expenditure": "cash_flow",
    "dividends_paid": "cash_flow",
}

# Disclosed industry-specific facts.  These are deliberately separate
# from the core completeness denominator: a normal industrial company is
# not an incomplete filing merely because it does not publish banking or
# mining facts.
INDUSTRY_ACCOUNT_CODE_SECTIONS: dict[str, str] = {
    # banking prudential / operating disclosures
    "gross_loans": "notes",
    "non_performing_loans_gross": "notes",
    "non_performing_loans_net": "notes",
    "earning_assets": "notes",
    "regulatory_capital": "notes",
    "risk_weighted_assets": "notes",
    "customer_deposits": "notes",
    "current_accounts": "notes",
    "savings_accounts": "notes",
    "npl_gross_ratio_reported": "notes",
    "npl_net_ratio_reported": "notes",
    "net_interest_margin_reported": "notes",
    "capital_adequacy_ratio_reported": "notes",
    # mining operational disclosures
    "proven_probable_reserves": "notes",
    "annual_production": "notes",
    "cash_cost_per_unit_reported": "notes",
    "stripping_ratio_reported": "notes",
}

ACCOUNT_CODE_SECTIONS: dict[str, str] = {
    **CORE_ACCOUNT_CODE_SECTIONS,
    **INDUSTRY_ACCOUNT_CODE_SECTIONS,
}

CORE_ACCOUNT_CODES = frozenset(CORE_ACCOUNT_CODE_SECTIONS)
