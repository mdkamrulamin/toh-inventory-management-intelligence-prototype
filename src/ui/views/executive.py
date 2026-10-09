"""Executive dashboard view."""

import pandas as pd
import streamlit as st

from src.ui.components import (
    render_feature_placeholder,
    render_stock_chart,
)

def render_executive_view(medications: pd.DataFrame) -> None:
    """Show descriptive sample counts and planned executive sections."""
    st.write("Review a summary of the demo medication inventory.")
    st.caption("These counts describe synthetic sample data.")
    
    #Count records and suppliers without combining different stock units.
    record_count = len(medications)
    zero_stock_count = int(medications["current_stock"].eq(0).sum())
    supplier_count = int(medications["supplier"].nunique())
    
    records_column, zero_stock_column, suppliers_column = st.columns(3)
    
    with records_column:
        st.metric("Sample medication records", record_count)
    
    with zero_stock_column:
        st.metric("Records with zero stock", zero_stock_count)
        
    with suppliers_column:
        st.metric("Demo suppliers", supplier_count)
        
    render_stock_chart(medications, key_prefix="executive")
    
    #Executive indicators that will follow team's requirements
    render_feature_placeholder(
        "Inventory performance KPIs",
        "Display agreed performance indicators once their definitions, "
        "reporting periods, and required data are confirmed.",
    )

    render_feature_placeholder(
        "Risk and cost overview",
        "Summarize availability risks, expiry exposure, and inventory costs "
        "once the supporting data and calculation rules are confirmed.",
    )
