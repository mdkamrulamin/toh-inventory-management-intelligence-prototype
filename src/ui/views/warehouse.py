"""Warehouse dashboard view."""

import pandas as pd
import streamlit as st

from src.ui.components import (
    render_feature_placeholder,
    render_medication_table, 
    render_stock_chart,
)

def render_warehouse_view(medications: pd.DataFrame) -> None:
        """Show sample warehouse stock and planned operational sections."""
        st.write("Review medication stock quantities and recorded expiry dates.")
        
        warehouse_columns = [
            "medication_id",
            "medication_name",
            "current_stock",
            "stock_unit",
            "expiry_date",
            "status",
        ]
        
        #Each sample medication represents one illustrative batch.
        # This does not yet support multiple batches or storage locations.
        st.caption("Each sample record represents one illustrative medication batch. Expiry dates are frictional.")
        
        render_medication_table(medications[warehouse_columns])
        render_stock_chart(medications, key_prefix="warehouse")
        
        # Operational details will follow confirmed warehouse requirements.
        render_feature_placeholder(
            "Expiry monitoring",
            "Highlight approaching expiry dates using an agreed warning period "
            "and batch-level data.",
        )
        
        render_feature_placeholder(
            "Storage locations and stock movements",
            "Show where medications are stored and track receipts, issues, "
            "and transfers once the required fields and workflow are confirmed.",
        )
        