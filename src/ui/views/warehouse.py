"""Warehouse dashboard view."""

import pandas as pd
import streamlit as st

from src.services.replenishment import build_replenishment_context
from src.ui.components import (
    render_feature_placeholder,
    render_medication_table, 
    render_stock_chart,
)
from src.ui.stock_indicators import render_stock_review_legend

def render_warehouse_view(medications: pd.DataFrame) -> None:
        """Show respresentative stock locations, expiry, and past count observations."""
        st.write("Review recorded stock, representative storage locations, expiry dates, and historical count observations.")
        
        warehouse_columns = [
            "medication_id",
            "medication_name",
            "current_stock",
            "stock_unit",
            "primary_location",
            "expiry_date",
            "status",
        ]
        
        # Reindex adds missing optional columns without changing source data.
        warehouse_data = medications.reindex(columns=warehouse_columns).copy()
        
        # Reuse the same medication-level review result as Procurement.
        review_by_id = (
            build_replenishment_context(medications)
            .set_index("medication_id")["ordering_review"]
        )
        warehouse_data["ordering_review"] = (
            warehouse_data["medication_id"].map(review_by_id)
        )
        
        warehouse_data["primary_location"] = (
            warehouse_data["primary_location"].astype("string").fillna("N/A")
        )
        
        # Format dates for display only; loader output remains datetime data.
        if "expiry_date" in medications.columns:
            warehouse_data["expiry_date"] = (
                medications["expiry_date"].dt.strftime("%Y-%m-%d").fillna("N/A")
            )
        else:
            warehouse_data["expiry_date"] = "N/A"
        
        st.caption(
            "Locations and expiry dates are synthetic. Each medication record "
            "has one representative location and expiry date; "
            "multiple lots and batch-level FEFO are not represented."      
        )
        
        render_medication_table(
            warehouse_data, 
            title="Representative warehouse stock",
            export_key="warehouse_stock",
        )
        
        render_stock_review_legend()
        count_columns = [
            "medication_id",
            "medication_name",
            "current_stock",
            "stock_unit",
            "last_count_date",
            "counted_stock",
        ]
        
        count_data = medications.reindex(columns=count_columns).copy()
        
        if "last_count_date" in medications.columns:
            count_data["last_count_date"] = (
                medications["last_count_date"].dt.strftime("%Y-%m-%d").fillna("N/A")
            )
        else:
            count_data["last_count_date"] = "N/A"
        
        count_data["counted_stock"] = (
            count_data["counted_stock"].astype("string").fillna("N/A")
        )
        
        # Historical counts are displayed without replacing current recorded stock.
        st.caption(
            "Counted quantities are past synthetic observations. Transactions since each "
            "count are not modeled, so this comparison cannot establish current stock accuracy, loss, or shrinkage."
        )
        
        render_medication_table(
            count_data, 
            title="Historical count observations",
            export_key="warehouse_counts",
        )
        render_stock_chart(medications, key_prefix="warehouse")
        
        
        render_feature_placeholder(
            "Expiry monitoring",
            "The warning period and supporting lot-level information remain "
            "to be confirmed. No batch-specific expiry or FEFO decision is made.",
        )
        
        render_feature_placeholder(
            "Receiving and picking",
            "Receiving checks, picking information, and dispatch status "
            "await the agreed workflow and supporting records."
        )
        
        render_feature_placeholder(
            "Stock movement and reconciliation",
            "Receipts, issues, and transfers are not recorded in this demo. "
            "Transaction history and count-time balances are needed "
            "before a reconciliation result can be established.",
        )
        