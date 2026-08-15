"""Ordered XBRL tag fallback chains per logical financial-statement concept.

Companies tag the same line item differently (and change tags across years),
so normalize.py walks each chain in order and takes the first tag that has a
value for a given (cik, fy) — the winning tag is recorded alongside the value
so the UI/writeup can show provenance.
"""

CONCEPT_CHAINS = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ],
    "net_income": [
        "NetIncomeLoss",
        "ProfitLoss",
    ],
    "eps_diluted": [
        "EarningsPerShareDiluted",
    ],
    "diluted_shares": [
        "WeightedAverageNumberOfDilutedSharesOutstanding",
    ],
    "gross_profit": [
        "GrossProfit",
    ],
    # Not a fundamentals column on its own — used only to derive gross_profit
    # (revenue - cost_of_revenue) when a company's income statement has no
    # GrossProfit subtotal line at all.
    "cost_of_revenue": [
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfServices",
    ],
    "operating_income": [
        "OperatingIncomeLoss",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "PaymentsForCapitalImprovements",
    ],
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    # Backs "Other Income Adjustments" / "Adjusted Net Income". Prefers the
    # aggregate "Other income (expense), net" income-statement subtotal
    # (NonoperatingIncomeExpense, falling back to OtherNonoperatingIncomeExpense
    # for filers that use that tag instead) over the narrower ASC 321
    # mark-to-market note tag EquitySecuritiesFvNiUnrealizedGainLoss. The
    # narrow tag looked more "precise" on paper but materially understates
    # the real swing for the tracked companies that report it: one company's
    # most recent fiscal year shows a multi-billion-dollar gap between the
    # narrow tag and the aggregate line (the real driver of that year's net
    # income), and another's aggregate line flips sign entirely versus the
    # narrow tag (driven by a real equity-method-investment swing not
    # captured by the narrow tag). The aggregate line is what actually
    # matches each company's reported story, so it wins even when the narrow
    # tag is also present.
    # The tradeoff is that the aggregate line also bundles in interest
    # income/expense for filers that don't tag it separately, so it isn't a
    # pure investment-marks isolate — a real precision gap, documented in
    # DESIGN.md rather than hidden.
    "nonoperating_income": [
        "NonoperatingIncomeExpense",
        "OtherNonoperatingIncomeExpense",
        "EquitySecuritiesFvNiUnrealizedGainLoss",
    ],
    # Near-universal single tag — used to tax-effect nonoperating_income in
    # adjusted_net_income() (see reported.py), since that line is pre-tax
    # while net_income is after-tax.
    "income_tax_expense": [
        "IncomeTaxExpenseBenefit",
    ],
}

# Maps logical concept -> (fundamentals column, fundamentals tag column)
FUNDAMENTALS_COLUMNS = {
    "revenue": ("revenue", "revenue_tag"),
    "net_income": ("net_income", "net_income_tag"),
    "eps_diluted": ("eps_diluted", "eps_diluted_tag"),
    "diluted_shares": ("diluted_shares", "diluted_shares_tag"),
    "gross_profit": ("gross_profit", "gross_profit_tag"),
    "operating_income": ("operating_income", "operating_income_tag"),
    "capex": ("capex", "capex_tag"),
    "operating_cash_flow": ("operating_cash_flow", "operating_cash_flow_tag"),
    "nonoperating_income": ("nonoperating_income", "nonoperating_income_tag"),
    "income_tax_expense": ("income_tax_expense", "income_tax_expense_tag"),
}
