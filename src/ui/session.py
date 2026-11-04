"""Streamlit session boundary for the synthetic workflow.
Business state lives under one key. Services create candidate states;
this adapter publishes successful changes in one assignment.

Public readers return detached data, not the canonical state object.
"""

from collections.abc import MutableMapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import streamlit as st

from src.config import SAMPLE_MEDICATIONS_PATH
from src.data.loader import load_medications
from src.services import workflow as wf
from src.services import workflow_queries as queries
from src.services.workflow_models import (
    ActionContext,
    DemoState,
    Role,
    WorkflowError,
    WorkflowResult,
)

STATE_KEY = "demo_state"
NOTICE_KEY = "workflow_notice"

# Reserve workflow_ui_ for resettable inputs/drafts. Action buttons should use a different prefix.
RESETTABLE_PREFIXES = (
    "clinical_request_quantity_",
    "workflow_ui_",
)

_ACTIONS = {
    "submit_request": wf.submit_request,
    "start_review": wf.start_review,
    "return_to_queue": wf.return_to_queue,
    "return_request": wf.return_request,
    "authorize_release": wf.authorize_release,
    "recall_release": wf.recall_release,
    "escalate_shortage": wf.escalate_shortage,
    "update_supply_feedback": wf.update_supply_feedback,
    "fulfill_request": wf.fulfill_request,
    "close_without_supply": wf.close_without_supply,
}

@dataclass(frozen=True)
class DemoSessionInfo:
    run_id: str
    revision: int
    dataset_path: str
    dataset_fingerprint: str
    request_count: int
    
def _store(state_store: MutableMapping | None = None) -> MutableMapping:
    # An explicitly supplied empty dictionary is a valid test store.
    return (st.session_state if state_store is None else state_store)

def _now(value: datetime | None) -> datetime:
    return (datetime.now(timezone.utc) if value is None else value)

def _current(store: MutableMapping) -> DemoState:
    state = store.get(STATE_KEY)
    
    if (not isinstance(state, DemoState) or state.schema_version != 1):
        raise WorkflowError("invalid_state", "No compatible active demo exists. Start a new demo with the configured dataset.")
    
    return state

def _info(state: DemoState) -> DemoSessionInfo:
    return DemoSessionInfo(
        run_id=state.run_id,
        revision=state.revision,
        dataset_path=state.dataset_path,
        dataset_fingerprint=state.dataset_fingerprint,
        request_count=len(state.requests),
    )
    
def _source_descriptor(source_path: str | Path) -> tuple[str, str]:
    path = Path(source_path).expanduser().resolve()
    
    return (str(path), sha256(path.read_bytes()).hexdigest())

def _check_source(state: DemoState, source_path: str | Path) -> None:
    path, fingerprint = _source_descriptor(source_path)
    
    if (path != state.dataset_path or fingerprint != state.dataset_fingerprint):
        raise WorkflowError("dataset_mismatch", "The configured dataset changed. Start a new demo explicitly before continuing.")
    
def _load_new_state(source_path: str | Path, now: datetime) -> DemoState:
    path, fingerprint = _source_descriptor(source_path)
    medications = load_medications(path)
    
    # Do not publish a state if its source changed during loading.
    after_path, after_fingerprint = _source_descriptor(path)
    
    if (path != after_path or fingerprint != after_fingerprint):
        raise WorkflowError("dataset_changed_during_load", "The dataset changed while loading. Retry when it is stable.")
    
    return wf.initialize_demo(medications, dataset_path=path, dataset_fingerprint=fingerprint, now=now)

def ensure_demo_session(
    source_path: str | Path = SAMPLE_MEDICATIONS_PATH,
    *,
    state_store: MutableMapping | None = None,
    now: datetime | None = None,
) -> DemoSessionInfo:
    """Initialize once; normal reruns retain active inventory/requests."""
    store = _store(state_store)
    
    if STATE_KEY not in store:
        candidate = _load_new_state(source_path, _now(now))
        store[STATE_KEY] = candidate
    else:
        _check_source(_current(store), source_path)
    
    return _info(_current(store))

def get_session_info(*, state_store: MutableMapping | None = None) -> DemoSessionInfo:
    return _info(_current(_store(state_store)))

def apply_workflow_action(
    action_name: str,
    *action_args,
    acting_role: Role,
    expected_run_id: str,
    expected_revision: int,
    source_path: str | Path = SAMPLE_MEDICATIONS_PATH,
    state_store: MutableMapping | None = None,
    now: datetime | None = None,
    **action_kwargs,
) -> WorkflowResult:
    """Apply an approved service action to the latest session state."""
    if action_name not in _ACTIONS:
        raise WorkflowError("invalid_action", "Unknown workflow action.")
    
    if "context" in action_kwargs:
        raise WorkflowError("invalid_action", "Action context is supplied by the session adapter.")
    
    store = _store(state_store)
    state = _current(store)
    
    # A callback can run before app.py reaches its initialization check. Therefore source consistency is checked here as well.
    _check_source(state, source_path)
    
    context = ActionContext(
        acting_role=acting_role,
        expected_run_id=expected_run_id,
        expected_revision=expected_revision,
        now=_now(now)
    )
    
    result = _ACTIONS[action_name](
        state,
        *action_args,
        context=context,
        **action_kwargs,
    )
    
    # Prepare the public copy before publishing anything. Callers must not receive a mutable reference to canonical state.
    public_result = deepcopy(result)
    
    if result.changed:
        store[STATE_KEY] = result.state
        
    return public_result

def _clear_demo_ui(store: MutableMapping, clinical_tab_label: str) -> None:
    if (not isinstance(clinical_tab_label, str) or not clinical_tab_label.strip()):
        raise WorkflowError("invalid_input", "A Clinical tab label is required for reset.")
    
    for key in list(store):
        if (isinstance(key, str) and key.startswith(RESETTABLE_PREFIXES)):
            del store[key]
            
    # Set the lookup explicitly; deleting a widget key alone can allow its old frontend value to return.
    store["clinical_medication_lookup"] = None
    store["dashboard_role_tabs"] = clinical_tab_label
    
    # Button trigger state is managed by Streamlit.
    # Do not manually assign clinical_preview_request.
    
def reset_demo_session(*, clinical_tab_label: str, state_store: MutableMapping | None = None, now: datetime | None = None) -> DemoSessionInfo:
    """Restore the stored baseline and clear workflow/UI state."""
    store = _store(state_store)
    state = _current(store)
    
    candidate = wf.reset_demo(state, now=_now(now))
    
    _clear_demo_ui(store, clinical_tab_label)
    store[STATE_KEY] = candidate
    
    return _info(candidate)

def replace_demo_dataset(
    source_path: str | Path,
    *,
    clinical_tab_label: str,
    state_store: MutableMapping | None = None,
    now: datetime | None = None,
) -> DemoSessionInfo:
    """Explicitly start a new run from a newly validated source."""
    store = _store(state_store)
    
    # Loading and validation finish before existing state/UI is cleared.
    candidate = _load_new_state(source_path, _now(now))
    
    _clear_demo_ui(store, clinical_tab_label)
    store[STATE_KEY] = candidate
    
    return _info(candidate)

def reset_demo_callback(*, clinical_tab_label: str, state_store: MutableMapping | None = None) -> None:
    """Safe callback used by the Reset demo button."""
    store = _store(state_store)
    
    try:
        reset_demo_session(clinical_tab_label=clinical_tab_label, state_store=store)
    except (OSError, ValueError) as error:
        store[NOTICE_KEY] = {
            "kind": "error",
            "message": str(error),
        }
    else:
        store[NOTICE_KEY] = {
            "kind": "success",
            "message": (
                "Demo reset. Starting stock restored and synthetic requests cleared."
            ),
        }
        
def replace_dataset_callback(
    *,
    source_path: str | Path,
    clinical_tab_label: str,
    state_store: MutableMapping | None = None,
) -> None:
    """Safe callback for deliberate dataset replacement."""
    store = _store(state_store)
    
    try:
        replace_demo_dataset(source_path, clinical_tab_label=clinical_tab_label, state_store=store)
    except (OSError, ValueError) as error:
        store[NOTICE_KEY] = {
            "kind": "error",
            "message": str(error),
        }
    else:
        store[NOTICE_KEY] = {
            "kind": "success",
            "message": (
                "A new demo started with the configured dataset."
            ),
        }
        
def take_notice(*, state_store: MutableMapping | None = None) -> dict | None:
    """Consume a temporary UI notice without changing business state."""
    return _store(state_store).pop(NOTICE_KEY, None)

def read_inventory(role: Role | str, *, state_store: MutableMapping | None = None):
    return queries.get_inventory_snapshot(_current(_store(state_store)), role)

def read_inventory_summary(*, state_store: MutableMapping | None = None) -> dict:
    return queries.get_inventory_summary(_current(_store(state_store)))

def read_requests(role: Role | str, *, actionable_only: bool = False, state_store: MutableMapping | None = None) -> list[dict]:
    return queries.list_requests(_current(_store(state_store)), role, actionable_only=actionable_only)

def read_request_details(request_id: str, role: Role | str, *, state_store: MutableMapping | None = None) -> list[dict]:
    return queries.get_request_details(_current(_store(state_store)), request_id, role)

def read_current_availability(request_id: str, *, state_store: MutableMapping | None = None) -> dict:
    return queries.get_current_availability(_current(_store(state_store)), request_id)


def read_request_summary(*, state_store: MutableMapping | None = None) -> dict:
    return queries.get_session_request_summary(_current(_store(state_store)))


def read_replenishment_review(*, state_store: MutableMapping | None = None):
    return queries.get_replenishment_review(_current(_store(state_store)))
 
        


