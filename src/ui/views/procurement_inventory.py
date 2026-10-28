"""Procurement and inventory/ordering dashboard view"""

import pandas as pd
import streamlit as st

from src.services.replenishment import build_replenishment_context
from src.ui.components import (
    render_feature_placeholder,
    render_medication_table, 
    render_stock_chart,
)
from src.ui.stock_indicators import render_stock_review_legend

def render_procurement_inventory_view(medications: pd.DataFrame) -> None:
    """Show synthetic inventory inputs and illustrative order-review context."""
    st.write("Review recorded stock, consumption, costs, suppliers and information relevant to ordering review.")
    
    #Retain stock units so quantities and costs have clear meaning.
    procurement_columns = [
        "medication_name",
        "current_stock",
        "stock_unit",
        "average_monthly_consumption",
        "expiry_date",
        "unit_cost",
        "supplier",
        "status",
    ]
    
    st.caption(
        "Consumption uses stock units per month; costs are CAD per stock unit. "
        "Expiry dates are fictional batch dates."     
    )
    
    render_medication_table(medications.reindex(columns=procurement_columns))
    context = build_replenishment_context(medications)
    
    # Format missing optional inputs for display only.
    # Their underlying numerical values remain missing, rather than zero.
    display_context = context.copy()
    for column in (
        "reorder_point",
        "safety_stock_level",
        "lead_time_days",
    ):
        display_context[column] = (context[column].astype("string").fillna("N/A"))
        
    st.caption(
        "Thresholds and lead times are synthetic, client-unvalidated examples. "
        "Positive stock at or below its supplied reorder point is flagged "
        "for review; zero recorded stock is shown separately. "
        "These flags do not trigger purchases."
    )
    
    render_medication_table(
        display_context,
        title="Illustrative replenishment context",
    )
    render_stock_review_legend()
    
    render_stock_chart(medications, key_prefix="procurement_inventory")
    
    # Classification methods and replenishment rules waiting for team findings.
    render_feature_placeholder(
        "ABC financial classification",
        "Financial ranking requires an agreed analysis period and method. "
        "The existing category field describes dosage form, not ABC class. "
        "No ABC ranking or clinical-criticality classification is assigned.",
    )
    
    render_feature_placeholder(
        "Replenishment-method selection",
        "Method selection remains subject to research and agreed assumptions. "
        "EOQ is not a universal ordering rule. "
        "No order quantity is calculated and no purchase order is created.",
    )
    