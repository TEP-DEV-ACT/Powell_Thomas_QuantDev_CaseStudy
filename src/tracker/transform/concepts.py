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
    # GrossProfit subtotal line at all (e.g. GOOGL, ETN).
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
}
