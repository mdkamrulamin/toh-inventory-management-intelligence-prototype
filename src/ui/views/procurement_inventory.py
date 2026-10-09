"""Procurement and inventory/ordering dashboard view"""

import pandas as pd
import streamlit as st

from src.ui.components import (
    render_feature_placeholder,
    render_medication_table, 
    render_stock_chart,
)

def render_procurement_inventory_view(medications: pd.DataFrame) -> None:
    """Show sample inventory info and planned procurement sections."""
    st.write("Review stock, consumption, unit costs, and suppliers to support inventory and ordering decisions.")
    
    #Retain stock units so quantities and unit costs have clear meaning.
    procurement_columns = [
        "medication_name",
        "current_stock",
        "stock_unit",
        "average_monthly_consumption",
        "unit_cost",
        "supplier",
        "status",
    ]
    
    st.caption("Demo consumption is measured in stock units per month. Demo unit costs are in CAD per stock unit.")
    
    render_medication_table(medications[procurement_columns])
    render_stock_chart(medications, key_prefix="procurement_inventory")
    
    # Classification methods and replenishment rules waiting for team findings.
    render_feature_placeholder(
        "ABC classification",
        "Group medications using the team's agreed classification method "
        "and thresholds.",
    )
    
    render_feature_placeholder(
        "Replenishment and ordering",
        "Display safety-stock levels, reorder points, and ordering "
        "information once the required data and rules are confirmed.",
    )
    