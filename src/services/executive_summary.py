"""Aggregate-only Executive summaries from existing inventory services."""

from copy import deepcopy

import pandas as pd

from src.services.analytics import build_stock_analytics
from src.services.replenishment import (
    ABOVE_STOCK_LABEL,
    REVIEW_STOCK_LABEL,
    ZERO_STOCK_LABEL,
)
from src.services.summary import summarize_inventory

def build_executive_summary(medications: pd.DataFrame) -> dict:
    """Reuse existing calculations without returning medication records."""
    snapshot = summarize_inventory(medications)
    analytics = build_stock_analytics(medications)
    calculated = analytics.summary
    reviews = analytics.rows["ordering_review"]

    known_labels = {
        ZERO_STOCK_LABEL,
        REVIEW_STOCK_LABEL,
        ABOVE_STOCK_LABEL,
    }
    
    stock_review_counts = {
        "at_or_below_rop": int(reviews.eq(REVIEW_STOCK_LABEL).sum()),
        "above_rop": int(reviews.eq(ABOVE_STOCK_LABEL).sum()),
        "unavailable": int((~reviews.isin(known_labels)).sum()),
    }
    
    # Explicit aggregate fields prevent item-level inventory or
    # unrelated future analytics fields from reaching Executive.
    aggregate_analytics = {
        "population_count": calculated["population_count"],
        "complete_abc_count": calculated["complete_abc_count"],
        "total_monthly_consumption_value_cad": calculated["total_monthly_consumption_value_cad"],
        "abc_available": calculated["abc_available"],
        "abc_note": calculated["abc_note"],
        "analysis_basis": calculated["analysis_basis"],
        "abc_scope": calculated["abc_scope"],
        "class_totals": [
            {
                "abc_class": item["abc_class"],
                "sku_count": item["sku_count"],
                "monthly_consumption_value_cad": item["monthly_consumption_value_cad"],
                "abc_share_percent": item["abc_share_percent"],
            }
            for item in calculated["class_totals"]
        ],
    }

    return deepcopy(
        {
            **snapshot,
            "stock_review_counts": stock_review_counts,
            "analytics": aggregate_analytics,
        }
    )
    
    
    