"""Synthetic order creation, management and expected-delivery panels."""

from datetime import date

import pandas as pd
import streamlit as st

from src.services.order_queries import ORDER_STATUS_LABELS
from src.services.reporting import prepare_report_display
from src.services.workflow_models import Role
from src.ui.order_actions import (
    new_order_draft_callback,
    order_creation_callback,
    order_input_keys,
    order_management_callback,
    prepare_order_draft,
)
from src.ui.session import (
    get_session_info,
    read_order_details,
    read_orders,
)
from src.ui.workflow_components import (
    display_value,
    render_order_progress,
    render_workflow_table,
)
from src.ui.receipt_panels import render_receipt_creation

def _money(value):
    return "N/A" if value is None else f"{value:,.2f}"

def render_order_creation(request: dict) -> None:
    """Keep order preview and explicit confirmation in the same form."""
    if request["status"] != "awaiting_supply":
        return
    request_id = request["request_id"]
    info = get_session_info()
    draft = prepare_order_draft(request_id)
    
    st.subheader("Create a simulated order")
    st.caption(
        "Enter a human-selected quantity. Shortfall, threshold gap and lead-time demand "
        "are reference information, not order quantities. Nothing is sent to a supplier."
    )
    
    if draft["confirmed_order_id"] is not None:
        st.info(
            f"This draft created {draft['confirmed_order_id']}. "
            "Previous orders remain in the order history."
        )
        st.button(
            "Start another simulated order draft",
            key=(
                f"workflow_action_new_order_{info.run_id}_"
                f"{request_id}_{draft['order_key']}"
            ),
            on_click=new_order_draft_callback,
            kwargs={
                "request_id": request_id,
                "expected_run_id": info.run_id,
                "order_key": draft["order_key"],
            },
        )
        return
    
    keys = order_input_keys(request_id, draft)
    preview = draft.get("preview")
    fresh = (preview is not None and preview["run_id"] == info.run_id and preview["revision"] == info.revision)
    callback_args = {
        "request_id": request_id,
        "unit": request["unit"],
        "order_key": draft["order_key"],
        "expected_run_id": info.run_id,
        "expected_revision": info.revision,
    }
    with st.form(
        key=(
            f"order_creation_form_{info.run_id}_"
            f"{request_id}_{draft['order_key']}"
        )
    ):
        st.text_input(
            f"Order quantity — positive whole {request['unit']} units",
            key=keys["quantity"],
            placeholder="Enter a whole number",
        )
        st.date_input(
            "Override expected delivery — optional",
            value=None,
            key=keys["date"],
        )
        st.text_input(
            "Reason for overriding the default expected date",
            key=keys["reason"],
        )
        st.caption(
            "Leave the override blank to use order date plus supplied "
            "whole-day lead time where available. Dates are illustrative."
        )
        
        st.form_submit_button(
            "Preview simulated order",
            on_click=order_creation_callback,
            kwargs={
                **callback_args,
                "action_name": "preview_order",
            },
        )
        
        if preview is not None and not fresh:
            st.warning("The session changed. Preview again before confirmation.")
            
        if fresh:
            st.write(
                f"**Preview:** {preview['quantity']:,} "
                f"{preview['unit']} of {preview['medication_name']}."
            )
            st.write(
                f"**Demo supplier:** {display_value(preview['supplier'])}"
            )
            st.write(
                f"**Supplied unit cost (CAD/unit):** "
                f"{_money(preview['unit_cost'])}"
            )
            st.write(
                f"**Synthetic order value (CAD):** "
                f"{_money(preview['order_value_cad'])}"
            )
            st.caption(preview["order_value_note"])
            st.write(
                f"**Order date (UTC):** {preview['order_date']} | "
                f"**Illustrative expected delivery:** "
                f"{display_value(preview['expected_delivery'])}"
            )
            st.caption(preview["expected_delivery_note"])
            
            st.write(
                f"**Current request shortfall:** "
                f"{preview['current_shortfall']:g} {preview['unit']}"
            )
            st.write(
                f"**Gap below supplied ROP:** "
                f"{display_value(preview['reorder_gap'])} "
                f"{preview['unit']}"
            )
            st.write(
                f"**Illustrative lead-time demand:** "
                f"{display_value(preview['lead_time_demand'])} "
                f"{preview['unit']}"
            )
            st.caption(
                "Lead-time demand uses a 30-day month. "
                "No reference value automatically selects the order quantity."
            )
            
            for warning in preview["warnings"]:
                st.warning(warning)
                
        st.checkbox(
            "I confirm this synthetic order. No supplier transmission or inventory increase will occur.",
            key=keys["confirmation"],
            disabled=not fresh,
        )
        
        st.form_submit_button(
            "Confirm simulated order",
            disabled=not fresh,
            on_click=order_creation_callback,
            kwargs={
                **callback_args,
                "action_name": "confirm_order",
            },
        )
    st.caption(
        "Both buttons submit the current form values. "
        "If inputs change after preview, confirmation requires a new preview."
    )
    
def _select_order(role: Role, prefix: str):
    include_history = st.checkbox(
        "Include received and cancelled orders",
        key=f"workflow_ui_{prefix}_include_order_history",
    )   
    records = read_orders(role, open_only=not include_history)
    
    if not records:
        st.info("No simulated orders match this filter.")
        return None
    
    columns = [
        "order_id",
        "linked_request_id",
        "medication_name",
        "ordered_quantity",
        "unit",
        "quantity_received",
        "quantity_outstanding",
        "order_status",
        "expected_delivery",
        "expected_delivery_note",
    ]
    
    if role == Role.PROCUREMENT:
        columns.extend(
            [
                "supplier",
                "unit_cost",
                "order_value_cad",
                "order_value_note",
            ]
        )
    columns.extend(["run_id", "provenance"])
    table = pd.DataFrame(records).reindex(columns=columns)
    table["order_status"] = table["order_status"].map(ORDER_STATUS_LABELS)
    table = prepare_report_display(table).rename(
        columns={
            "order_id": "Order ID",
            "linked_request_id": "Linked request ID",
            "medication_name": "Medication",
            "ordered_quantity": "Ordered quantity",
            "unit": "Stock unit",
            "quantity_received": "Received quantity",
            "quantity_outstanding": "Outstanding quantity",
            "order_status": "Order status",
            "expected_delivery": "Illustrative expected delivery",
            "expected_delivery_note": "Expected-date context",
            "supplier": "Demo supplier",
            "unit_cost": "Supplied unit cost (CAD/unit)",
            "order_value_cad": "Synthetic order value (CAD)",
            "order_value_note": "Value context",
            "run_id": "Demo run ID",
            "provenance": "Synthetic provenance",
        }
    )
    render_workflow_table(table, table_key=f"{prefix}_orders")
    by_id = {order["order_id"]: order for order in records}
    selection_key = f"workflow_ui_{prefix}_order_lookup"
    
    if (st.session_state.get(selection_key) is not None and st.session_state[selection_key] not in by_id):
        st.session_state[selection_key] = None
        
    order_id = st.selectbox(
        "Inspect a simulated order",
        options=list(by_id),
        index=None,
        placeholder="Choose an order",
        key=selection_key,
        format_func=lambda value: (
            f"{value} | {by_id[value]['medication_name']}"
        ),
    )
    
    return (
        None
        if order_id is None else read_order_details(order_id, role)
    )
    
def render_procurement_orders() -> None:
    """Manage orders independently of the linked request's current status."""
    st.subheader("Simulated order management")
    st.caption(
        "Order records are session-only. Confirmation, date updates and cancellation do not change recorded stock."
    )
    order = _select_order(Role.PROCUREMENT, "procurement_order")
    if order is None:
        return
    render_order_progress([order], key_prefix="procurement_order_management")
    
    if order["order_status"] not in {"ordered", "partially_received"}:
        st.info("Read-only terminal order history.")
        return
    
    info = get_session_info()
    prefix = f"workflow_ui_order_manage_{info.run_id}_{order['order_id']}"
    reason_key = f"{prefix}_date_reason"
    date_key = f"{prefix}_date"
    
    current_date = (
        None
        if order["expected_delivery"] is None else date.fromisoformat(order["expected_delivery"])
    )
    with st.form(key=f"order_date_form_{info.run_id}_{order['order_id']}"):
        st.date_input(
            "Revised illustrative expected delivery",
            value=current_date,
            key=date_key,
        )
        st.text_input(
            "Reason for changing or clearing the date",
            key=reason_key,
        )
        
        st.form_submit_button(
            "Update illustrative delivery",
            on_click=order_management_callback,
            kwargs={
                "action_name": "update_order_delivery",
                "order_id": order["order_id"],
                "reason_key": reason_key,
                "expected_date_key": date_key,
                "expected_run_id": info.run_id,
                "expected_revision": info.revision,
            },
        )
    
    if (order["order_status"] != "ordered" or order["quantity_received"] != 0):
        st.caption("Cancellation is unavailable after any receipt.")
        return
    
    cancel_reason_key = f"{prefix}_cancel_reason"
    confirmation_key = f"{prefix}_cancel_confirmation"
    
    with st.form(key=f"order_cancel_form_{info.run_id}_{order['order_id']}"):
        st.text_input("Reason for cancelling the simulated order", key=cancel_reason_key)
        st.checkbox("Confirm cancellation before any receipt", key=confirmation_key)
        st.form_submit_button(
            "Cancel simulated order",
            on_click=order_management_callback,
            kwargs={
                "action_name": "cancel_order",
                "order_id": order["order_id"],
                "reason_key": cancel_reason_key,
                "confirmation_key": confirmation_key,
                "expected_run_id": info.run_id,
                "expected_revision": info.revision,
            },
        )
        
def render_warehouse_orders() -> None:
    """Show expected supply, receipt history and eligible receipt controls."""
    st.subheader("Expected synthetic deliveries")
    st.caption(
        "Expected dates are illustrative. Creating an order does not increase stock. "
        "Only an explicitly confirmed synthetic receipt adds to active session inventory."
    )
    
    order = _select_order(Role.WAREHOUSE, "warehouse_order")
    
    if order is None:
        st.caption(
            "Select an order above. Enable 'Include received and cancelled orders'" 
            " to inspect completed order and receipt history."
        )
        return
        
    
    render_order_progress([order], key_prefix="warehouse_expected_order")
    render_receipt_creation(order)
    
        
    
        
    
    