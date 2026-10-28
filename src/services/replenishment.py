"""Illustrative replenishment context derive from synthetic inventory inputs"""

import pandas as pd

# Shared labels keep service results and presentation consistent.
ZERO_STOCK_LABEL = "Recorded stock = 0 — availability/order review"
REVIEW_STOCK_LABEL = "At/below illustrative reorder threshold — review"
ABOVE_STOCK_LABEL = "Above illustrative reorder threshold"
MISSING_REORDER_LABEL = "N/A — reorder point unavailable"
MISSING_UNIT_LABEL = "N/A — stock unit unavailable"

def build_replenishment_context(medications: pd.DataFrame) -> pd.DataFrame:
    """Return display context without changing inventory or placing orders.
    Numeric validity is checked by the CSV loader before dashboard rendering.
    Missing units prevent positive-stock threshold comparisons."""
    
    context = medications[
        [
            "medication_id",
            "medication_name",
            "current_stock",
        ]
    ].copy()
    
    if "stock_unit" in medications.columns:
        context["stock_unit"] = medications["stock_unit"]
    else:
        context["stock_unit"] = pd.Series(pd.NA, index=context.index, dtype="string")
    
    # Optional columns remain missing when the original CSV is used.
    for column in (
        "reorder_point",
        "safety_stock_level",
        "lead_time_days",
    ):
        if column in medications.columns:
            context[column] = medications[column]
        else:
            context[column] = pd.Series(pd.NA, index=context.index, dtype="Float64")
    
    stock = context["current_stock"]
    reorder_point = context["reorder_point"]
    
    units = context["stock_unit"].astype("string").str.strip()
    has_unit = (units.notna() & units.ne("")).fillna(False)
    positive_stock = stock.gt(0)
    
    # Unknown thresholds never become an artificial numerical zero.
    context["ordering_review"] = MISSING_REORDER_LABEL
    
    missing_unit = (positive_stock & reorder_point.notna() & ~has_unit)
    context.loc[missing_unit, "ordering_review"] = MISSING_UNIT_LABEL
    
    # A threshold uses the same stock unit as its medication record.
    comparable = (positive_stock & reorder_point.notna() & has_unit)
    context.loc[comparable, "ordering_review"] = ABOVE_STOCK_LABEL
    
    at_or_below = (comparable & stock.le(reorder_point)).fillna(False)
    context.loc[at_or_below, "ordering_review"] = REVIEW_STOCK_LABEL
    
    # Zero recorded stock takes precedence, even without threshold/unit data.
    context.loc[stock.eq(0), "ordering_review"] = ZERO_STOCK_LABEL
    
    return context