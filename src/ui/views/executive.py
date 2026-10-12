"""Executive dashboard view."""

import pandas as pd
import streamlit as st

from src.services.summary import summarize_inventory
from src.ui.components import (
    render_feature_placeholder,
    render_stock_chart,
)

def render_executive_view(medications: pd.DataFrame) -> None:
    """Show synthetic snapshot summaries and illustrative executive KPI areas."""
    st.write("Review aggregate inventory exposure and recorded availability.")
    st.caption(
        "All figures describe synthetic demonstration data. "
        "Each medication record represents one unique sample SKU."
    )
    
    summary = summarize_inventory(medications)
    
    share = summary["zero_stock_share_percent"]
    share_text = "N/A" if share is None else f"{share:.1f}%"
    
    inventory_value = summary["inventory_value_cad"]
    value_text = (
        "N/A"
        if inventory_value is None
        else f"{inventory_value:,.2f}"
    )
    
    supplier_count = summary["supplier_count"]
    supplier_text = (
        "N/A" if supplier_count is None else supplier_count
    )
    
    sku_column, zero_column, share_column = st.columns(3)
    
    with sku_column:
        st.metric("Sample SKUs", summary["sku_count"])
        
    with zero_column:
        st.metric("Recorded zero-stock SKUs", summary["zero_stock_count"])
    
    with share_column:
        st.metric("Zero-stock share - snapshot", share_text)
        
    value_column, suppliers_column, turnover_column = st.columns(3)
    
    with value_column:
        st.metric("Sample inventory value (CAD)", value_text)
        
    with suppliers_column:
        st.metric("Known demo suppliers", supplier_text)
        
    with turnover_column:
        st.metric("Inventory turnover - placeholder", "N/A")
        
    st.caption(
        "Zero-stock share is a snapshot, not a stockout rate over time. "
        "Inventory value sums recoreded stock x synthetic CAD unit cost; "
        "the total is N/A if any unit cost is missing."
    )
    
    st.caption(
        "Turnover is an illustrative KPI slot. Its definition, reporting period "
        ", and supporting historical records remain to be confirmed. "
        "No turnover value is calculated."
    )
    
    render_stock_chart(medications, key_prefix="executive")
    
    render_feature_placeholder(
        "Inventory performance KPIs",
        "Additional indicators require agreed definitions, reporting periods, and supporting data.",
    )
    
    render_feature_placeholder(
        "Risk, waste and cost trends",
        "Historical observations and agreed measures are needed "
        "before trends or validated risk indicators can be displayed.",
    )