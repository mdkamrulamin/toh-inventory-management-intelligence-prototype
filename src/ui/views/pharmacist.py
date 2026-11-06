"""Pharmacist dashboard for synthetic request review and routing."""

import pandas as pd
import streamlit as st

from src.services.replenishment import build_replenishment_context
from src.services.workflow_models import Role
from src.ui.components import render_medication_table
from src.ui.session import (
    get_session_info,
    read_current_availability,
    read_request_details,
    read_requests,
    take_notice,
)
from src.ui.stock_indicators import render_stock_review_badge
from src.ui.workflow_actions import pharmacist_action_callback
from src.ui.workflow_components import (
    display_value,
    render_request_details,
    render_request_table,
    select_request,
)

def _render_stock_context(medications: pd.DataFrame, request: dict) -> dict:
    """Display current role-permitted inventory and availability context."""
    selected = medications.loc[medications["medication_id"].eq(request["medication_id"])].copy()
    availability = read_current_availability(request["request_id"])
    
    st.subheader("Current recorded availability")
    if availability["comparable"]:
        stock_column, unit_column = st.columns(2)
        stock_column.metric("Current recorded stock", f"{availability['recorded_stock']:g}")
        unit_column.metric("Current stock unit", availability["stock_unit"])
        if availability["available"]:
            st.info("Current recorded stock covers the full request. Release still requires an explicit demo review action.")
        else:
            st.warning("Current recorded stock does not cover the full request. This demo does not support partial release.")
    else:
        st.warning(availability["message"])
        
    if not selected.empty:
        review = build_replenishment_context(selected).iloc[0]["ordering_review"]
        render_stock_review_badge(review)
        
        context_columns = [
            "medication_id",
            "medication_name",
            "current_stock",
            "stock_unit",
            "primary_location",
            "expiry_date",
            "supplier",
            "lead_time_days",
            "average_monthly_consumption",
            "reorder_point",
            "safety_stock_level",
            "last_count_date",
            "counted_stock",
        ]
        context = selected.reindex(columns=context_columns).copy()
        
        # Presentation-only missing labels. Source/session fields are neither invented nor changed.
        for column in context.columns:
            context[column] = context[column].astype("object")
            context[column] = context[column].where(context[column].notna(), "N/A")
            
        render_medication_table(context, title="Representative stock and supply context", export_key="pharmacist_stock_context")
        
    st.caption(
        "Location, expiry and supply fields are synthetic. "
        "One representative location/expiry is shown per medication. "
        "Historical counts do not replace current recorded stock."
    )
    st.caption(
        "Threshold indicators provide inventory context. "
        "They do not establish clinical suitability or reserve stock."
    )
    st.write(
        "**Governed ABC/VEN priority:** "
        f"{display_value(request.get('priority_class'))}"
    )
    
    return availability

@st.fragment
def _render_review_actions(request: dict, availability: dict) -> None:
    """Offer only actions relevant to the request's current status."""
    info = get_session_info()
    # A successful workflow action changes the business revision.
    # Refresh the full app then, so queues, details and other views
    # receive the updated state. Typing alone does not change revision.
    if (info.run_id != request["run_id"] or info.revision != availability["revision"]):
        st.rerun()
        
    notice = take_notice()
    if notice is not None:
        st.toast(
            notice["message"],
            icon=(
                "✅"
                if notice["kind"] == "success"
                else "⚠️"
            ),
        )
    
    
    status = request["status"]
    request_id = request["request_id"]
    
    st.subheader("Synthetic review actions")
    st.caption("Actions are recorded as Demo user. They are not real pharmacist authorization.")
    
    if status == "received":
        st.button(
            "Start demo review",
            key=(
                f"workflow_action_start_review_"
                f"{info.run_id}_{request_id}"
            ),
            on_click=pharmacist_action_callback,
            kwargs={
                "action_name": "start_review",
                "request_id": request_id,
                "reason_key": None,
                "expected_run_id": info.run_id,
                "expected_revision": info.revision,
            },
        )
        return
    
    if status not in {"under_review", "approved_for_release", "awaiting_supply"}:
        if status == "escalated":
            st.info("Shortage routed to Procurement. The shared request will show any later supply feedback.")
        else:
            st.info("No Pharmacist action is available for this status.")
        return
    
    reason_key = (f"workflow_ui_pharmacist_reason_{info.run_id}_{request_id}")
    reason = st.text_input(
        "Demo decision reason",
        key=reason_key,
        live="0ms",
        placeholder="Enter a reason for this demo decision",
        help=(
            "Required for release, final return, shortage escalation, "
            "recall and closure. Optional when returning to the queue. "
            "Do not enter patient information."
        ),
    )
    has_reason = bool((reason or "").strip())
    
    def action_button(label: str, action_name: str, *, disabled: bool = False) -> None:
        st.button(
            label,
            key=(
                f"workflow_action_{action_name}_"
                f"{info.run_id}_{request_id}"
            ),
            disabled=disabled,
            on_click=pharmacist_action_callback,
            kwargs={
                "action_name": action_name,
                "request_id": request_id,
                "reason_key": reason_key,
                "expected_run_id": info.run_id,
                "expected_revision": info.revision,
            },
        )
    
    if status == "under_review":
        can_release = (availability["comparable"] and availability["available"] is True)
        can_escalate = (availability["comparable"] and availability["available"] is False)
        release_column, shortage_column = st.columns(2)
        with release_column:
            action_button(
                "Authorize demo release to Warehouse",
                "authorize_release",
                disabled=not (has_reason and can_release),
            )
        with shortage_column:
            action_button(
                "Confirm shortage and route to Procurement",
                "escalate_shortage",
                disabled=not (has_reason and can_escalate),
            )
            
        return_column, queue_column = st.columns(2)
        with return_column:
            action_button(
                "Return request with reason — final",
                "return_request",
                disabled=not has_reason,
            )
        with queue_column:
            action_button("Return to review queue", "return_to_queue")
            
        st.caption("Release and escalation recheck current stock in the shared service. Neither action changes inventory quantities.")
        
    elif status == "approved_for_release":
        st.info("Eligible for Warehouse demo fulfillment. Release authorization has not deducted or reserved stock.")
        action_button(
            "Recall demo release for review",
            "recall_release",
            disabled=not has_reason,
        )
    elif status == "awaiting_supply":
        st.warning("Supply feedback is informational. Closing here records closure without supply.")
        action_button(
            "Close demo request without supply",
            "close_without_supply",
            disabled=not has_reason,
        )
        
def render_pharmacist_view(medications: pd.DataFrame) -> None:
    """Connect submitted requests to deliberate synthetic review actions."""
    st.write("Review synthetic requests and route them using recorded availability and the agreed demonstration workflow.")
    st.warning("Synthetic workflow only. Demo user is not authenticated, and these actions do not constitute real clinical authorization.")
    st.caption("Queue order: demo urgency, then original arrival time.Review deadlines and governed ABC/VEN values are unavailable.")
    st.caption("Redistribution and substitute selection remain conceptual. This demo does not execute or automatically recommend them.")
    st.subheader("Synthetic request queue")
    
    include_completed = st.checkbox("Include returned and closed requests", key="workflow_ui_pharmacist_include_completed")
    requests = read_requests(Role.PHARMACIST)
    if not include_completed:
        requests = [
            request
            for request in requests
            if request["status"] not in {"returned", "fulfilled", "closed"}
        ]
        
    if not requests:
        st.info("No requests match the current queue filter.")
        return
    
    render_request_table(requests, table_key="pharmacist_requests")
    selected_request_id = select_request(requests, label="Open a request for inspection", widget_key="workflow_ui_pharmacist_request_lookup")
    if selected_request_id is None:
        st.info("Select a request to inspect it. Opening a request does not start its review.")
        return
    
    request = read_request_details(selected_request_id, Role.PHARMACIST)
    render_request_details(request, key_prefix="pharmacist_request")
    availability = _render_stock_context(medications, request)
    _render_review_actions(request, availability)
    