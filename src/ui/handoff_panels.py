"""Warehouse fulfillment and Procurement feedback panels."""

import pandas as pd
import streamlit as st

from src.services.workflow_models import Role
from src.ui.session import (
    get_session_info,
    read_current_availability,
    read_request_details,
    read_requests,
)
from src.ui.workflow_actions import (
    procurement_feedback_callback,
    warehouse_fulfillment_callback,
)
from src.ui.workflow_components import (
    display_value,
    render_request_details,
    render_request_table,
    select_request,
)

def render_warehouse_handoffs() -> None:
    """Show released requests and deliberate full-quantity fulfillment."""
    st.subheader("Warehouse demo handoffs")
    st.caption(
        "Only released requests are eligible for fulfillment. "
        "Confirmation deducts the full requested quantity once from "
        "session inventory. Physical dispensing is not performed."
    )
    include_history = st.checkbox("Include previous Warehouse handoffs", key="workflow_ui_warehouse_include_history")
    
    requests = read_requests(Role.WAREHOUSE, actionable_only=not include_history)
    
    if not requests:
        st.info("No Warehouse requests match the current filter.")
        return
    
    render_request_table(requests, table_key="warehouse_requests")
    request_id = select_request(requests, label="Inspect a Warehouse handoff", widget_key="workflow_ui_warehouse_request_lookup")
    
    if request_id is None:
        return
    
    request = read_request_details(request_id, Role.WAREHOUSE)
    render_request_details(request, key_prefix="warehouse_request")
    
    if request["status"] != "approved_for_release":
        st.info("Read-only handoff history. This request is not currently eligible for Warehouse fulfillment.")
        return
    
    availability = read_current_availability(request_id)
    if not availability["comparable"]:
        st.warning(availability["message"])
        return
    
    stock_column, unit_column = st.columns(2)
    stock_column.metric("Latest recorded stock", f"{availability['recorded_stock']:g}")
    unit_column.metric("Current stock unit", availability["stock_unit"])
    
    can_fulfill = availability["available"] is True
    if not can_fulfill:
        st.warning(
            "Latest recorded stock does not cover the full request. "
            "No partial fulfillment or deduction is permitted. "
            "Pharmacist can recall the release for re-review and explicit shortage escalation."
        )
    else:
        projected_stock = (availability["recorded_stock"] - request["quantity"])
        st.write(
            "**Projected recorded stock after confirmation:** "
            f"{projected_stock:g} {request['unit']}."
        )
        
    info = get_session_info()
    
    # Require a fresh confirmation after the business revision changes.
    confirmation_key = (
       f"workflow_ui_warehouse_confirm_{info.run_id}_{request_id}_{info.revision}" 
    )
    confirmed = st.checkbox(
        f"Confirm synthetic fulfillment of the full "
        f"{request['quantity']:,} {request['unit']} "
        f"for {request_id}",
        key=confirmation_key,
        disabled=not can_fulfill,
    )
    
    st.button(
        "Confirm full demo fulfillment",
        key=(
            f"workflow_action_warehouse_fulfill_{info.run_id}_{request_id}"
        ),
        disabled=not (can_fulfill and confirmed),
        on_click=warehouse_fulfillment_callback,
        kwargs={
            "request_id": request_id,
            "confirmation_key": confirmation_key,
            "expected_run_id": info.run_id,
            "expected_revision": info.revision,
        },
    )
    
    st.caption("The shared service rechecks current stock, units, release status and previous fulfillment before changing anything.")
    
def render_procurement_handoffs(medications: pd.DataFrame) -> None:
    """Show request-linked shortages and informational supply updates."""
    st.subheader("Linked shortage reviews")
    st.caption(
        "These items come from explicit Pharmacist escalation. "
        "Routine stock monitoring below works independently. "
        "Neither route creates a purchase order."
    )
    include_history = st.checkbox("Include previous Procurement handoffs", key="workflow_ui_procurement_include_history")
    
    requests = read_requests(Role.PROCUREMENT, actionable_only=not include_history)
    if not requests:
        st.info("No linked shortages match the current filter.")
        return
    
    render_request_table(requests, table_key="procurement_requests")
    request_id = select_request(requests, label="Inspect a linked shortage", widget_key="workflow_ui_procurement_request_lookup")
    
    if request_id is None:
        return
    
    request = read_request_details(request_id, Role.PROCUREMENT)
    render_request_details(request, key_prefix="procurement_request")
    selected = medications.loc[medications["medication_id"].eq(request["medication_id"])]
    
    if len(selected) == 1:
        medication = selected.iloc[0]
        st.write("**Recorded synthetic supply context**")
        st.write(
            "**Demo supplier:** "
            f"{display_value(medication.get('supplier'))}"
        )
        st.write(
            "**Lead time (days):** "
            f"{display_value(medication.get('lead_time_days'))}"
        )
        st.write(
            "**Current recorded stock:** "
            f"{display_value(medication.get('current_stock'))} "
            f"{display_value(medication.get('stock_unit'))}"
        )
    
    st.caption(
        "Supplier and lead-time fields are demonstration context, "
        "not evidence of an open order or confirmed delivery."
    )
    
    if request["status"] not in {"escalated", "awaiting_supply"}:
        st.info("Read-only handoff history. Supply feedback cannot be changed in this request status.")
        return
    
    info = get_session_info()
    feedback_key = (f"workflow_ui_procurement_feedback_{info.run_id}_{request_id}")
    expected_date_key = (f"workflow_ui_procurement_expected_date_{info.run_id}_{request_id}")

    st.subheader("Record a synthetic supply update")
    st.caption(
        "The update is visible to Clinical and Pharmacist. "
        "It does not receive stock, fulfill the request, or create a supplier transaction."
    )
    
    with st.form(
        key=(
            f"procurement_feedback_form_"
            f"{info.run_id}_{request_id}"
        ),
        clear_on_submit=False,
    ):
        st.text_area(
            "Synthetic supply-review update",
            key=feedback_key,
            placeholder=(
                "For example: Synthetic supplier review recorded; delivery remains unconfirmed."
            ),
            help=(
                "Visible to Clinical and Pharmacist. "
                "Use an operational demo update; do not enter patient information or commercial pricing."
            ),
        )
        
        st.date_input(
            "Optional illustrative expected date",
            value=None,
            key=expected_date_key,
            help=(
                "If blank, the service uses a synthetic lead-time "
                "illustration where supported; otherwise the date "
                "remains unavailable. This is not a delivery promise."
            ),
        )
        
        st.form_submit_button(
            "Record synthetic supply update",
            on_click=procurement_feedback_callback,
            kwargs={
                "request_id": request_id,
                "feedback_key": feedback_key,
                "expected_date_key": expected_date_key,
                "expected_run_id": info.run_id,
                "expected_revision": info.revision,
            },
        )