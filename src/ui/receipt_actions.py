"""Warehouse callbacks for synthetic receipt previews and confirmation."""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import streamlit as st

from src.config import SAMPLE_MEDICATIONS_PATH
from src.services.receipts import parse_receipt_quantity
from src.services.workflow_models import (
    ReceiptInput,
    Role,
    WorkflowError
)
from src.ui.session import (
    NOTICE_KEY,
    apply_workflow_action,
    get_session_info,
    preview_simulated_receipt,
    read_order_details,
)

def _store(state_store):
    return st.session_state if state_store is None else state_store

def _draft_key(order_id):
    return f"workflow_ui_receipt_draft_{order_id}"

def _new_draft(run_id, outstanding_quantity):
    return {
        "run_id": run_id,
        "receipt_key": uuid4().hex,
        "initial_quantity": str(outstanding_quantity),
        "preview": None,
        "preview_inputs": None,
        "confirmed_receipt_id": None,
    }
    
def _notice(store, kind, message):
    store[NOTICE_KEY] = {
        "kind": kind,
        "message": message,
    }
    
def receipt_input_keys(order_id, draft):
    prefix = (
        f"workflow_ui_receipt_{draft['run_id']}_"
        f"{order_id}_{draft['receipt_key']}"
    )
    return {
        "quantity": f"{prefix}_quantity",
        "confirmation": f"{prefix}_confirmation",
    }
    
def prepare_receipt_draft(order_id, *, state_store=None):
    """Create presentation state without recording or adding inventory."""
    store = _store(state_store)
    info = get_session_info(state_store=store)
    order = read_order_details(
        order_id,
        Role.WAREHOUSE,
        state_store=store,
    )
    
    key = _draft_key(order_id)
    draft = store.get(key)
    
    if (not isinstance(draft, dict) or draft.get("run_id") != info.run_id):
        draft = _new_draft(info.run_id, order["quantity_outstanding"])
        store[key] = draft
        
    keys = receipt_input_keys(order_id, draft)
    
    # Initialize once; never overwrite a quantity the user has entered.
    if (draft["confirmed_receipt_id"] is None and keys["quantity"] not in store):
        store[keys["quantity"]] = draft["initial_quantity"]
        
    return deepcopy(draft)

def new_receipt_draft_callback(order_id, expected_run_id, receipt_key, *, state_store=None):
    """Explicitly begin another receipt after a successful partial receipt."""
    store = _store(state_store)
    
    try:
        info = get_session_info(state_store=store)
        if info.run_id != expected_run_id:
            raise WorkflowError("wrong_run", "This control belongs to an earlier demo run.")
        
        draft = store.get(_draft_key(order_id))
        if (not isinstance(draft, dict) or draft.get("run_id") != expected_run_id or draft.get("receipt_key") != receipt_key):
            raise WorkflowError("draft_changed", "The receipt draft changed.")
        
        if draft.get("confirmed_receipt_id") is None:
            raise WorkflowError("invalid_action", "Complete the current receipt draft first.")
        
        order = read_order_details(order_id, Role.WAREHOUSE, state_store=store)
        
        if (order["order_status"] not in {"ordered", "partially_received"} or order["quantity_outstanding"] <= 0):
            raise WorkflowError("invalid_transition", "This order has no eligible outstanding receipt.")
        
        for key in receipt_input_keys(order_id, draft).values():
            store.pop(key, None)
            
        store[_draft_key(order_id)] = _new_draft(info.run_id, order["quantity_outstanding"])
        
        _notice(store, "success", "New receipt draft started. Recorded stock is unchanged.")
        
    except (OSError, ValueError) as error:
        _notice(store, "error", str(error))
        
def receipt_action_callback(
    action_name,
    order_id,
    unit,
    receipt_key,
    expected_run_id,
    expected_revision,
    *,
    source_path: str | Path = SAMPLE_MEDICATIONS_PATH,
    state_store=None,
    now=None,
):
    """Preview or confirm the exact quantity submitted by the form."""
    store = _store(state_store)
    
    try:
        if action_name not in {"preview_receipt", "confirm_receipt"}:
            raise WorkflowError("invalid_action", "Unknown receipt action.")
        
        info = get_session_info(state_store=store)
        
        if info.run_id != expected_run_id:
            raise WorkflowError("wrong_run", "This control belongs to an earlier demo run.")
        
        if info.revision != expected_revision:
            raise WorkflowError("stale_state", "The demo changed. Preview the receipt again.")
        
        draft = deepcopy(store.get(_draft_key(order_id)))
        
        if (not isinstance(draft, dict) or draft.get("run_id") != expected_run_id or draft.get("receipt_key") != receipt_key):
            raise WorkflowError("draft_changed", "The receipt draft changed. Use the current draft.")
        
        if draft["confirmed_receipt_id"] is not None:
            raise WorkflowError("duplicate_action", "This draft has already recorded a receipt. Start another receipt explicitly if supply remains.")
        
        keys = receipt_input_keys(order_id, draft)
        inputs = ReceiptInput(quantity=parse_receipt_quantity(store.get(keys["quantity"], "")), unit=unit)
        action_time = (
            datetime.now(timezone.utc)
            if now is None else now
        )
        
        if action_name == "preview_receipt":
            preview = preview_simulated_receipt(
                order_id,
                inputs,
                expected_run_id=expected_run_id,
                expected_revision=expected_revision,
                source_path=source_path,
                state_store=store,
                now=action_time,
            )
            draft["preview"] = preview
            draft["preview_inputs"] = inputs
            store[_draft_key(order_id)] = draft
            store[keys["confirmation"]] = False

            _notice(store, "success", "Receipt preview ready. No stock change was made.")
            return
        
        preview = draft.get("preview")
        if (
            preview is None 
            or preview.get("run_id") != expected_run_id 
            or preview.get("revision") != expected_revision 
            or inputs != draft.get("preview_inputs")
        ):
            raise WorkflowError("preview_changed", "Inputs or session state changed. Preview again first.")
        
        if store.get(keys["confirmation"]) is not True:
            raise WorkflowError("confirmation_required", "Tick the synthetic-receipt confirmation first.")
        
        # Revalidate the source, order, quantity, units and latest stock.
        preview_simulated_receipt(
            order_id,
            inputs,
            expected_run_id=expected_run_id,
            expected_revision=expected_revision,
            source_path=source_path,
            state_store=store,
            now=action_time,
        )
        
        result = apply_workflow_action(
            "confirm_receipt",
            order_id,
            inputs,
            receipt_key,
            acting_role=Role.WAREHOUSE,
            expected_run_id=expected_run_id,
            expected_revision=expected_revision,
            source_path=source_path,
            state_store=store,
            now=action_time,
        )
        
        # Keep this identity locked across reruns and repeated clicks.
        draft["confirmed_receipt_id"] = result.receipt_id
        draft["preview"] = None
        draft["preview_inputs"] = None
        store[_draft_key(order_id)] = draft
        store[keys["confirmation"]] = False

        _notice(store, "success", result.message)
        
    except (OSError, ValueError) as error:
        if getattr(error, "code", None) != "confirmation_required":
            current = store.get(_draft_key(order_id))
            
            # An old callback must not clear a newer run/draft.
            if (isinstance(current, dict) and current.get("run_id") == expected_run_id and current.get("receipt_key") == receipt_key):
                current = deepcopy(current)
                current["preview"] = None
                current["preview_inputs"] = None
                store[_draft_key(order_id)] = current
                
            _notice(store, "error", str(error))
        
        
            
            
        