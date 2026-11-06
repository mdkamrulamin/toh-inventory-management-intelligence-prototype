"""Shared presentation for synthetic request queues and details."""

import pandas as pd
import streamlit as st

STATUS_LABELS = {
    "received": "Received",
    "under_review": "Under review",
    "returned": "Returned",
    "approved_for_release": "Approved for release",
    "fulfilled": "Fulfilled",
    "escalated": "Escalated",
    "awaiting_supply": "Awaiting supply",
    "closed": "Closed",
}

OUTCOME_LABELS = {
    "returned": "Returned without fulfillment",
    "fulfilled": "Synthetic fulfillment recorded",
    "closed_without_supply": "Closed without supply",
}

ROLE_LABELS = {
    "clinical": "Clinical",
    "pharmacist": "Pharmacist",
    "procurement_inventory": "Procurement",
    "warehouse": "Warehouse",
    "executive": "Executive",
    "reporting": "Reporting",
    "system": "System",
}


def display_value(value) -> str:
    """Display unavailable scalar values without inventing information."""
    if value is None or pd.isna(value):
        return "N/A"
    if isinstance(value, str):
        return value.strip() or "N/A"
    return str(value)

def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)

def render_workflow_table(data: pd.DataFrame, *, table_key: str) -> None:
    """Reuse the existing persistent native-toolbar styling."""
    with st.container(key=f"table_{table_key}"):
        st.dataframe(data, hide_index=True, width="stretch", row_height=40)
        
def render_request_table(requests: list[dict], *, table_key: str) -> None:
    """Show explicit request fields, preserving query-service queue order."""
    rows = [
        {
            "Request ID": request["request_id"],
            "Medication ID": request["medication_id"],
            "Medication": request["medication_name"],
            "Quantity": request["quantity"],
            "Unit": request["unit"],
            "Requesting location": request["requesting_location"],
            "Demo urgency": request["urgency"].capitalize(),
            "Status": status_label(request["status"]),
            "Outcome": OUTCOME_LABELS.get(request.get("outcome"), "—"),
            "Received time (UTC)": request["received_time"],
        }
        for request in requests
    ]
    
    if not rows:
        st.info("No synthetic requests to display.")
        return
        
    st.caption("Synthetic requests from this demo session. Request IDs apply within the current session.")
    render_workflow_table(pd.DataFrame(rows), table_key=table_key)
    
def select_request(requests: list[dict], *, label: str, widget_key: str) -> str | None:
    """Select a request without changing its workflow status."""
    by_id = {
        request["request_id"]: request
        for request in requests
    }
    request_ids = list(by_id)
    
    # A terminal request may disappear from an open-request filter.
    # Clear an invalid selection before creating the widget.
    current_selection = st.session_state.get(widget_key)
    if (current_selection is not None and current_selection not in by_id):
        st.session_state[widget_key] = None
    return st.selectbox(
        label,
        options=request_ids,
        index=None,
        placeholder="Choose a synthetic request",
        key=widget_key,
        format_func=lambda request_id: (
            f"{request_id} | "
            f"{by_id[request_id]['medication_name']} | "
            f"{by_id[request_id]['quantity']} "
            f"{by_id[request_id]['unit']}"
        ),
    )
    
def render_request_details(request: dict, *, key_prefix: str) -> None:
    """Render an already role-projected request without hidden fields."""
    st.subheader(f"Request {request['request_id']}")
    st.write(
        f"**Medication:** {request['medication_name']} "
        f"({request['medication_id']})"
    )
    quantity_column, unit_column, status_column = st.columns(3)
    quantity_column.metric("Requested quantity", f"{request['quantity']:,}")
    unit_column.metric("Request unit", request["unit"])
    status_column.metric("Request status", status_label(request["status"]))
    st.write(
        f"**Requesting location:** "
        f"{request['requesting_location']}"
    )
    st.write(f"**Demo urgency:** {request['urgency'].capitalize()}")
    st.write("**Original request reason**")
    st.text(request["reason"])

    st.write("**Latest status reason**")
    st.text(request["status_reason"])
    
    st.write(
        f"**Recorded demo actor:** "
        f"{display_value(request.get('decided_by'))}"
    )
    st.caption(
        f"Received: {request['received_time']} | "
        f"Updated: {request['updated_time']} | Times are UTC."
    )
    
    substitution_preference = ("Yes" if request["substitution_allowed"] else "No")
    st.write(
        "**Substitution review preference:** "
        f"{substitution_preference}"
    )
    st.caption(
        "This records a request preference only. No substitute has been recommended, offered or approved."
    )
    
    outcome = request.get("outcome")
    if outcome is not None:
        st.info(OUTCOME_LABELS.get(outcome, outcome))
        
    shortfall = request.get("shortfall_at_escalation")
    if shortfall is not None:
        st.write(
            f"**Recorded shortfall at escalation:** "
            f"{shortfall:g} {request['unit']}"
        )
        st.caption("This is the shortfall recorded when escalation occurred.")
        
    feedback = request.get("supply_feedback")
    if feedback is not None:
        st.write("**Synthetic supply feedback**")
        st.text(feedback["feedback"])
        st.write(
            "**Illustrative expected date:** "
            f"{display_value(feedback.get('expected_delivery'))}"
        )
        st.caption("Supply feedback and expected dates do not record an order, receipt or inventory increase.")
        
        # These fields exist only in projections permitted to see them.
        commercial_context = {
            "supplier": "Demo supplier",
            "lead_time_days": "Lead time (days)",
            "lead_time_demand": "Illustrative lead-time demand",
        }
        
        for field, label in commercial_context.items():
            if field in feedback:
                st.write(
                    f"**{label}:** "
                    f"{display_value(feedback[field])}"
                )
        if "lead_time_demand" in feedback:
            st.caption("Lead-time demand uses synthetic monthly use and a 30-day month assumption. It is not an order quantity.")
            
    fulfillment = request.get("fulfillment")
    if fulfillment is not None:
        st.write("**Synthetic fulfillment record**")
        st.write(
            f"Quantity: {fulfillment['quantity']} "
            f"{fulfillment['unit']} | "
            f"Recorded stock before: "
            f"{fulfillment['stock_before']:g} | "
            f"Recorded stock after: "
            f"{fulfillment['stock_after']:g}"
        )
        st.caption(
            f"Demo actor: {fulfillment['fulfilled_by']} | "
            f"Time (UTC): {fulfillment['fulfilled_time']}"
        )
        
    history = request.get("status_history", [])
    with st.expander("Synthetic status history"):
        history_rows = [
            {
                "Sequence": event["sequence"],
                "From": (
                    "—"
                    if event["from_status"] is None
                    else status_label(event["from_status"])
                ),
                "To": status_label(event["to_status"]),
                "Reason": event["reason"],
                "Demo role": ROLE_LABELS.get(
                    event["actor_role"],
                    event["actor_role"],
                ),
                "Actor": event["actor_name"],
                "Time (UTC)": event["timestamp"],
            }
            for event in history
        ]
        
        if history_rows:
            render_workflow_table(pd.DataFrame(history_rows), table_key=f"{key_prefix}_history")
        else:
            st.info("No status history is available.")
            
        st.caption("Session-only demonstration history. Actors are not authenticated professionals.")
            
    