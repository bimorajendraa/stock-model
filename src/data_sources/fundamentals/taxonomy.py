"""Standardized account-code taxonomy for ``financial_statement_items``
(spec section 3.3/8). Provider-agnostic: which ``statement_section`` each
``account_code`` belongs to, independent of any single adapter's raw field
names. Deliberately a small, high-value subset -- enough for spec section
8's core ratios (margins, ROE/ROA, current ratio, DER, EPS/PER/PBV inputs)
-- extend as more line items prove useful, never by fabricating a value
for a code a company doesn't actually report.
"""
from __future__ import annotations

ACCOUNT_CODE_SECTIONS: dict[str, str] = {
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
