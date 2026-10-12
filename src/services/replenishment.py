"""Illustrative replenishment context derive from synthetic inventory inputs"""

import pandas as pd

def build_replenishment_context(medications: pd.DataFrame) -> pd.DataFrame:
    """Return display context without changing inventory or placing orders."""
    context = medications[
        [
            "medication_id",
            "medication_name",
            "current_stock",
            "stock_unit",
        ]
    ].copy()
    
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
    context["ordering_review"] = "N/A - reorder threshold unavailable"
    
    #Only compare positive stock where a threshold has been supplied
    comparable = stock.gt(0) & reorder_point.notna()
    
    context.loc[comparable, "ordering_review"] = ("Above illustrative reorder threshold")
    
    at_or_below = (comparable & stock.le(reorder_point)).fillna(False)
    
    context.loc[at_or_below, "ordering_review"] = ("At/below illustrative reorder threshold - review")
    
    context.loc[stock.eq(0), "ordering_review"] = ("Recorded stock = 0 — availability/order review")
    
    return context