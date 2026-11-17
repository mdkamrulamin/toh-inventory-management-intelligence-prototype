"""Procurement UI callbacks for synthetic order previews and actions."""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import streamlit as st

from src.config import SAMPLE_MEDICATIONS_PATH
from src.services.orders import parse_order_quantity
from src.services.workflow_models import (
    CreateOrderInput,
    Role,
    WorkflowError,
)
from src.ui.session import (
    NOTICE_KEY,
    apply_workflow_action,
    get_session_info,
    preview_simulated_order,
)

def _store(state_store):
    return st.session_state if state_store is None else state_store

def _draft_key(request_id):
    return f"workflow_ui_order_draft_{request_id}"

def _new_draft(run_id):
    return {
        "run_id": run_id,
        "order_key": uuid4().hex,
        "preview": None,
        "preview_inputs": None,
        "confirmed_order_id": None,
    }
    
def _notice(store, kind, message):
    store[NOTICE_KEY] = {"kind": kind, "message": message}
    
def _check_info(store, expected_run_id, expected_revision):
    info = get_session_info(state_store=store)
    if info.run_id != expected_run_id:
        raise WorkflowError("wrong_run", "This control belongs to an earlier demo run.")
    if info.revision != expected_revision:
        raise WorkflowError("stale_state", "The demo changed. Refresh and preview again.")
    return info

def prepare_order_draft(request_id, *, state_store=None):
    """Create only temporary UI state, never a business order."""
    store = _store(state_store)
    info = get_session_info(state_store=store)
    draft = store.get(_draft_key(request_id))
    
    if not isinstance(draft, dict) or draft.get("run_id") != info.run_id:
        draft = _new_draft(info.run_id)
        store[_draft_key(request_id)] = draft
        
    return deepcopy(draft)

def order_input_keys(request_id, draft):
    prefix = (
        f"workflow_ui_order_{draft['run_id']}_"
        f"{request_id}_{draft['order_key']}"
    )
    return {
        "quantity": f"{prefix}_quantity",
        "date": f"{prefix}_date",
        "reason": f"{prefix}_date_reason",
        "confirmation": f"{prefix}_confirmation",
    }
    
def new_order_draft_callback(request_id, expected_run_id, order_key, *, state_store=None):
    """Start another draft without deleting previously recorded orders."""
    store = _store(state_store)
    
    try:
        info = get_session_info(state_store=store)
        draft = store.get(_draft_key(request_id))
        
        if info.run_id != expected_run_id:
            raise WorkflowError("wrong_run", "Start from the current demo.")
        if (not isinstance(draft, dict) or draft.get("order_key") != order_key):
            raise WorkflowError("draft_changed", "The order draft changed.")
        
        for key in order_input_keys(request_id, draft).values():
            store.pop(key, None)
            
        store[_draft_key(request_id)] = _new_draft(info.run_id)
    except (OSError, ValueError) as error:
        _notice(store, "error", str(error))
        
def order_creation_callback(
    action_name,
    request_id,
    unit,
    order_key,
    expected_run_id,
    expected_revision,
    *,
    source_path: str | Path = SAMPLE_MEDICATIONS_PATH,
    state_store=None,
    now=None,
):
    """Preview or confirm the exact submitted form values."""
    store = _store(state_store)
    try:
        if action_name not in {"preview_order", "confirm_order"}:
            raise WorkflowError("invalid_action", "Unknown order action.")
        _check_info(store, expected_run_id, expected_revision)
        draft = deepcopy(store.get(_draft_key(request_id)))
        
        if (not isinstance(draft, dict) or draft.get("run_id") != expected_run_id or draft.get("order_key") != order_key):
            raise WorkflowError("draft_changed", "The order draft changed. Preview the current draft.")
        if draft["confirmed_order_id"] is not None:
            raise WorkflowError("duplicate_action", "This draft has already produced an order.")
        
        keys = order_input_keys(request_id, draft)
        inputs = CreateOrderInput(
            quantity=parse_order_quantity(store.get(keys["quantity"], "")),
            unit=unit,
            expected_delivery=store.get(keys["date"]),
            expected_delivery_reason=store.get(keys["reason"], ""),
        )
        action_time = (now if now is not None else datetime.now(timezone.utc))
        
        if action_name == "preview_order":
            preview = preview_simulated_order(
                request_id,
                inputs,
                expected_run_id=expected_run_id,
                expected_revision=expected_revision,
                source_path=source_path,
                state_store=store,
                now=action_time,
            )
            draft["preview"] = preview
            draft["preview_inputs"] = inputs
            store[_draft_key(request_id)] = draft
            store[keys["confirmation"]] = False
            _notice(store, "success", "Preview ready. No order was created and stock is unchanged.")
            return
        
        preview = draft.get("preview")
        if (preview is None or preview.get("run_id") != expected_run_id or preview.get("revision") != expected_revision or inputs != draft.get("preview_inputs")):
            raise WorkflowError("preview_changed", "Inputs or session state changed. Preview again first.")
        
        if store.get(keys["confirmation"]) is not True:
            raise WorkflowError("confirmation_required", "Tick the synthetic-order confirmation first.")
        
        # Recheck time-dependent defaults as well as the business revision.
        fresh_preview = preview_simulated_order(
            request_id,
            inputs,
            expected_run_id=expected_run_id,
            expected_revision=expected_revision,
            source_path=source_path,
            state_store=store,
            now=action_time,
        )
        if fresh_preview != preview:
            raise WorkflowError("preview_changed", "The order preview changed. Review a fresh preview.")
        
        result = apply_workflow_action(
            "confirm_order",
            request_id,
            inputs,
            order_key,
            acting_role=Role.PROCUREMENT,
            expected_run_id=expected_run_id,
            expected_revision=expected_revision,
            source_path=source_path,
            state_store=store,
            now=action_time,
        )
        draft["confirmed_order_id"] = result.order_id
        draft["preview"] = None
        draft["preview_inputs"] = None
        store[_draft_key(request_id)] = draft
        store[keys["confirmation"]] = False
        _notice(store, "success", result.message)
        
    except (OSError, ValueError) as error:
        # An unchecked confirmation can be corrected without losing a
        # valid preview. Other failures require a fresh preview.
        if getattr(error, "code", None) != "confirmation_required":
            current = store.get(_draft_key(request_id))
            if (isinstance(current, dict) and current.get("run_id") == expected_run_id and current.get("order_key") == order_key):
                current = deepcopy(current)
                current["preview"] = None
                current["preview_inputs"] = None
                store[_draft_key(request_id)] = current
                
        _notice(store, "error", str(error))
        
def order_management_callback(
    action_name,
    order_id,
    reason_key,
    expected_run_id,
    expected_revision,
    *,
    expected_date_key=None,
    confirmation_key=None,
    source_path: str | Path = SAMPLE_MEDICATIONS_PATH,
    state_store=None,
    now=None,
):
    """Manage an order using current submitted form values."""
    store = _store(state_store)

    try:
        _check_info(store, expected_run_id, expected_revision)
        reason = store.get(reason_key, "")
        if action_name == "update_order_delivery":
            args = (order_id, store.get(expected_date_key), reason)
        elif action_name == "cancel_order":
            if store.get(confirmation_key) is not True:
                raise WorkflowError("confirmation_required", "Confirm the simulated-order cancellation first.")
            args = (order_id, reason)
        else:
            raise WorkflowError("invalid_action", "Unknown order action.")
        result = apply_workflow_action(
            action_name,
            *args,
            acting_role=Role.PROCUREMENT,
            expected_run_id=expected_run_id,
            expected_revision=expected_revision,
            source_path=source_path,
            state_store=store,
            now=now,
        )
        
        if confirmation_key is not None:
            store[confirmation_key] = False
            
        _notice(store, "success", result.message)
        
    except (OSError, ValueError) as error:
        _notice(store, "error", str(error))