"""Warehouse presentation of recorded synthetic stock movements."""

import pandas as pd
import streamlit as st

from src.services.workflow_models import Role
from src.ui.session import read_stock_movements
from src.ui.workflow_components import render_workflow_table


MOVEMENT_LABELS = {
    "run_id": "Demo run ID",
    "movement_id": "Movement ID",
    "movement_type": "Movement type",
    "receipt_id": "Receipt ID",
    "fulfillment_id": "Fulfillment ID",
    "order_id": "Linked order ID",
    "linked_request_id": "Linked request ID",
    "medication_id": "Medication ID",
    "medication_name": "Medication",
    "quantity_change": "Stock change",
    "stock_unit": "Stock unit",
    "stock_before": "Recorded stock before",
    "stock_after": "Recorded stock after",
    "recorded_time": "Recorded time (UTC)",
    "recorded_by": "Demo actor",
    "recorded_by_role": "Demo actor role",
    "provenance": "Synthetic record context",
}


def render_stock_movements() -> None:
    """Display each recorded receipt and fulfillment once."""
    st.subheader("Session stock movements")
    st.caption(
        "Synthetic session transactions. Positive quantities are "
        "posted receipts; negative quantities are completed "
        "fulfillments. Each quantity retains its stock unit."
    )

    movements = read_stock_movements(Role.WAREHOUSE)
    display = movements.copy(deep=True)

    display["movement_type"] = display["movement_type"].map(
        {
            "receipt": "Receipt",
            "fulfillment": "Fulfillment",
        }
    )
    display["quantity_change"] = display["quantity_change"].map(
        lambda value: f"{int(value):+d}"
    )

    display = display.astype("object").where(pd.notna(display), "N/A")

    if movements.empty:
        st.info("No receipts or fulfillments have been posted in this demo session.")

    render_workflow_table(
        display.rename(columns=MOVEMENT_LABELS),
        table_key="warehouse_stock_movements",
    )

    st.caption(
        "Before/after quantities describe each transaction's recorded "
        "time. This is not a complete historical ledger or physical "
        "count reconciliation. Transfers, loss and shrinkage are "
        "not established by these records."
    )