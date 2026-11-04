"""Clinical and Pharmacist callbacks for the synthetic workflow.
Drafts and notices are presentation state. Submitted requests and inventory
remain owned by the shared session adapter and workflow services.
"""

from collections.abc import MutableMapping
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import streamlit as st

from src.config import SAMPLE_MEDICATIONS_PATH
from src.services.workflow_models import (
    Role,
    SubmitRequestInput,
    SupplyFeedbackInput,
    WorkflowError,
)
from src.ui.session import (
    NOTICE_KEY,
    apply_workflow_action,
    get_session_info,
)

PHARMACIST_ACTIONS = {
    "start_review",
    "return_to_queue",
    "return_request",
    "authorize_release",
    "recall_release",
    "escalate_shortage",
    "close_without_supply",
}

def _store(state_store: MutableMapping | None = None) -> MutableMapping:
    """Allow callbacks to use Streamlit or an isolated test store."""
    return st.session_state if state_store is None else state_store

def _draft_key(medication_id: str) -> str:
    return f"workflow_ui_clinical_draft_{medication_id}"

def clinical_input_keys(medication_id: str) -> dict[str, str]:
    """Keep submission inputs separate from the existing preview controls."""
    prefix = f"workflow_ui_clinical_{medication_id}"
    
    return {
        "location": f"{prefix}_location",
        "reason": f"{prefix}_reason",
        "urgency": f"{prefix}_urgency",
        "substitution": f"{prefix}_substitution",
    }
    
def _new_draft(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "submission_key": uuid4().hex,
        "submitted_request_id": None
    }
    
def _notice(store: MutableMapping, kind: str, message: str) -> None:
    store[NOTICE_KEY] = {
        "kind": kind,
        "message": message,
    }

def prepare_clinical_draft(medication_id: str, *, state_store: MutableMapping | None = None) -> dict:
    """Reuse one submission identity across normal reruns.
    This creates UI state only. It does not create a request, advance the
    workflow revision, reserve inventory, or deduct stock.
    """
    store = _store(state_store)
    info = get_session_info(state_store=store)
    key = _draft_key(medication_id)
    draft = store.get(key)
    
    if (not isinstance(draft, dict) or draft.get("run_id") != info.run_id):
        draft = _new_draft(info.run_id)
        store[key] = draft
    return deepcopy(draft)

def new_clinical_draft_callback(medication_id: str, *, state_store: MutableMapping | None = None) -> None:
    """Explicitly begin another request without deleting submitted ones."""
    store = _store(state_store)
    
    try:
        info = get_session_info(state_store=store)
    except WorkflowError as error:
        _notice(store, "error", str(error))
        return
    
    store[_draft_key(medication_id)] = _new_draft(info.run_id)
    
    keys = clinical_input_keys(medication_id)
    store[keys["location"]] = ""
    store[keys["reason"]] = ""
    store[keys["urgency"]] = "routine"
    store[keys["substitution"]] = False
    store[f"clinical_request_quantity_{medication_id}"] = 1
    
def submit_clinical_request_callback(
    medication_id: str,
    quantity: int,
    unit: str,
    submission_key: str,
    expected_run_id: str,
    expected_revision: int,
    *,
    source_path: str | Path = SAMPLE_MEDICATIONS_PATH,
    state_store: MutableMapping | None = None,
    now: datetime | None = None,
) -> None:
    """Submit only after an explicit Clinical action.

    Form values are read when the callback runs. Medication, quantity,
    unit and revision identify the controls that produced the action.
    """
    store = _store(state_store)
    
    try:
        info = get_session_info(state_store=store)
        
        if info.run_id != expected_run_id:
            raise WorkflowError("stale_run", "The demo was reset. Select the medication again.")
        
        draft = store.get(_draft_key(medication_id))
        
        if (not isinstance(draft, dict) or draft.get("run_id") != expected_run_id or draft.get("submission_key") != submission_key):
            raise WorkflowError("stale_draft", "This draft changed. Review the current form and retry.")
        
        # Repeated callbacks for the completed draft cannot create another request. A new request requires the explicit new-draft action.
        submitted_id = draft.get("submitted_request_id")
        if submitted_id is not None:
            _notice(store, "success", f"This draft was already submitted as {submitted_id}.")
            return
        keys = clinical_input_keys(medication_id)
        inputs = SubmitRequestInput(
            medication_id=medication_id,
            quantity=quantity,
            unit=unit,
            requesting_location=store.get(keys["location"], ""),
            reason=store.get(keys["reason"], ""),
            urgency=store.get(keys["urgency"], "routine"),
            substitution_allowed=store.get(keys["substitution"], False),
        )
        
        result = apply_workflow_action(
            "submit_request",
            inputs,
            submission_key,
            acting_role=Role.CLINICAL,
            expected_run_id=expected_run_id,
            expected_revision=expected_revision,
            source_path=source_path,
            state_store=store,
            now=now,
        )
    except (OSError, ValueError) as error:
        _notice(store, "error", str(error))
        return
    
    # Retain a UI receipt. The canonical request is held by the adapter.
    store[_draft_key(medication_id)] = {**draft, "submitted_request_id": result.request_id}
    _notice(store, "success", f"{result.message} No stock was reserved or deducted.")
    
def pharmacist_action_callback(
    action_name: str,
    request_id: str,
    reason_key: str | None,
    expected_run_id: str,
    expected_revision: int,
    *,
    source_path: str | Path = SAMPLE_MEDICATIONS_PATH,
    state_store: MutableMapping | None = None,
    now: datetime | None = None,
) -> None:
    """Dispatch only Pharmacist actions through the shared adapter.
    The workflow service checks role, status, revision, reason and
    availability. Hiding or disabling buttons is not the validation layer.
    """
    store = _store(state_store)
    
    try:
        if action_name not in PHARMACIST_ACTIONS:
            raise WorkflowError("invalid_action", "This action is not a Pharmacist demo action.")
        
        action_args = [request_id]
        if action_name != "start_review":
            reason = ("" if reason_key is None else store.get(reason_key, ""))
            action_args.append(reason)
            
        result = apply_workflow_action(
            action_name,
            *action_args,
            acting_role=Role.PHARMACIST,
            expected_run_id=expected_run_id,
            expected_revision=expected_revision,
            source_path=source_path,
            state_store=store,
            now=now,
        )
    
    except (OSError, ValueError) as error:
        _notice(store, "error", str(error))
        return
    
    # Callbacks run before widgets are rendered again, so clearing a successfully used reason here is safe.
    if reason_key is not None:
        store[reason_key] = ""
        
    _notice(store, "success", result.message)
    
def warehouse_fulfillment_callback(
    request_id: str,
    confirmation_key: str,
    expected_run_id: str,
    expected_revision: int,
    *,
    source_path: str | Path = SAMPLE_MEDICATIONS_PATH,
    state_store: MutableMapping | None = None,
    now: datetime | None = None,
) -> None:
    """Confirm one full synthetic fulfillment through the shared service.
    The confirmation records deliberate user intent. The service still
    checks release status, latest stock, matching units, duplicate
    fulfillment and the session revision.
    """
    store = _store(state_store)
    
    try:
        if store.get(confirmation_key) is not True:
            raise WorkflowError("confirmation_required", "Confirm full-quantity synthetic fulfillment first.")
        
        result = apply_workflow_action(
            "fulfill_request",
            request_id,
            acting_role=Role.WAREHOUSE,
            expected_run_id=expected_run_id,
            expected_revision=expected_revision,
            source_path=source_path,
            state_store=store,
            now=now,
        )
    except (OSError, ValueError) as error:
        _notice(store, "error", str(error))
        return
    
    # This callback runs before the checkbox is rendered again.
    store[confirmation_key] = False
    _notice(store, "success", f"{result.message} This is synthetic fulfillment only.")
    
def procurement_feedback_callback(
    request_id: str,
    feedback_key: str,
    expected_date_key: str | None,
    expected_run_id: str,
    expected_revision: int,
    *,
    source_path: str | Path = SAMPLE_MEDICATIONS_PATH,
    state_store: MutableMapping | None = None,
    now: datetime | None = None,
) -> None:
    """Record request-linked synthetic feedback without changing stock.
    Form values are read when the callback runs. An omitted expected date
    lets the existing service use its supported lead-time illustration,
    or retain an unavailable date when the source lacks that context.
    """
    store = _store(state_store)
    
    try:
        inputs = SupplyFeedbackInput(
            feedback=store.get(feedback_key, ""),
            expected_delivery=(
                None
                if expected_date_key is None
                else store.get(expected_date_key)
            ),
        )
        result = apply_workflow_action(
            "update_supply_feedback",
            request_id,
            inputs,
            acting_role=Role.PROCUREMENT,
            expected_run_id=expected_run_id,
            expected_revision=expected_revision,
            source_path=source_path,
            state_store=store,
            now=now,
        )
    except (OSError, ValueError) as error:
        _notice(store, "error", str(error))
        return

    # Keep entered feedback available for deliberate editing.
    # An identical repeat is rejected by the shared service.
    _notice(store, "success", result.message)
    