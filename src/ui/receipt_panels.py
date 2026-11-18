"""Warehouse controls for deliberate synthetic receipt posting."""

import streamlit as st

from src.ui.receipt_actions import (
    new_receipt_draft_callback,
    prepare_receipt_draft,
    receipt_action_callback,
    receipt_input_keys,
)
from src.ui.session import get_session_info

def render_receipt_creation(order: dict) -> None:
    """Offer receipt controls only for eligible outstanding orders."""
    if order["order_status"] not in {"ordered", "partially_received"}:
        st.info("This order is read-only. No further receipt can be posted.")
        return
    
    order_id = order["order_id"]
    info = get_session_info()
    draft = prepare_receipt_draft(order_id)
    
    st.subheader("Receive synthetic supply")
    st.caption(
        "The initial quantity is the order's outstanding quantity. Enter a smaller positive whole quantity "
        "for a partial receipt. This does not verify a physical shipment."
    )
    
    if draft["confirmed_receipt_id"] is not None:
        st.success(f"Receipt {draft['confirmed_receipt_id']} was recorded. This receipt draft is locked.")
        st.button(
            "Start another synthetic receipt",
            key=(
                f"workflow_action_new_receipt_{info.run_id}_"
                f"{order_id}_{draft['receipt_key']}"
            ),
            on_click=new_receipt_draft_callback,
            kwargs={
                "order_id": order_id,
                "expected_run_id": info.run_id,
                "receipt_key": draft["receipt_key"],
            },
        )
        return
    
    keys = receipt_input_keys(order_id, draft)
    preview = draft.get("preview")
    fresh = (preview is not None and preview["run_id"] == info.run_id and preview["revision"] == info.revision)
    
    callback_args = {
        "order_id": order_id,
        "unit": order["unit"],
        "receipt_key": draft["receipt_key"],
        "expected_run_id": info.run_id,
        "expected_revision": info.revision,
    }
    
    with st.form(
        key=(
            f"receipt_form_{info.run_id}_"
            f"{order_id}_{draft['receipt_key']}"
        )
    ):
        st.text_input(
            f"Received quantity — positive whole {order['unit']} units",
            key=keys["quantity"],
            placeholder="Enter a whole number",
        )
        st.caption(
            f"Current outstanding quantity: "
            f"{order['quantity_outstanding']:,} {order['unit']}."
        )
        st.form_submit_button(
            "Preview synthetic receipt",
            on_click=receipt_action_callback,
            kwargs={
                **callback_args,
                "action_name": "preview_receipt",
            },
        )
        
        if preview is not None and not fresh:
            st.warning("The session changed. Preview again before confirmation.")
            
        if fresh:
            inputs = draft["preview_inputs"]
            
            st.write(
                f"**Receipt preview:** {inputs.quantity:,} "
                f"{inputs.unit} of {order['medication_name']}."
            )
            
            before_column, after_column = st.columns(2)
            before_column.metric(
                "Recorded stock before",
                f"{preview['stock_before']:g}",
            )
            after_column.metric(
                "Recorded stock after confirmation",
                f"{preview['stock_after']:g}",
            )
            st.caption("Preview does not change stock. A confirmed receipt does not authorize release or fulfill the request.")
            
        st.checkbox(
            "I confirm this synthetic receipt and its one-time increase to active session stock.",
            key=keys["confirmation"],
            disabled=not fresh,
        )
        st.form_submit_button(
            "Confirm synthetic receipt",
            disabled=not fresh,
            on_click=receipt_action_callback,
            kwargs={
                **callback_args,
                "action_name": "confirm_receipt",
            },
        )
    st.caption(
        "Both buttons submit the current form values. Changing quantity after preview requires a new preview."
    )
        
             
        
    