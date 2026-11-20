"""Pharmacist callbacks for informational substitute-review decisions."""

from pathlib import Path

import streamlit as st

from src.config import SAMPLE_MEDICATIONS_PATH
from src.services.workflow_models import (
    Role,
    SubstituteReviewInput,
)
from src.ui.session import (
    NOTICE_KEY,
    apply_workflow_action,
)

def substitute_reason_key(run_id, request_id, relationship_id):
    return (
        f"workflow_ui_substitute_reason_{run_id}_"
        f"{request_id}_{relationship_id}"
    )
    
def substitute_review_callback(
    request_id,
    relationship_id,
    decision,
    expected_run_id,
    expected_revision,
    *,
    source_path: str | Path = SAMPLE_MEDICATIONS_PATH,
    state_store=None,
    now=None,
):
    """Record only through the canonical session action."""
    store = (
        st.session_state
        if state_store is None
        else state_store
    )
    reason_key = substitute_reason_key(expected_run_id, request_id, relationship_id)

    try:
        inputs = SubstituteReviewInput(
            relationship_id=relationship_id,
            decision=decision,
            reason=store.get(reason_key, ""),
        )

        result = apply_workflow_action(
            "record_substitute_review",
            request_id,
            inputs,
            acting_role=Role.PHARMACIST,
            expected_run_id=expected_run_id,
            expected_revision=expected_revision,
            source_path=source_path,
            state_store=store,
            now=now,
        )

    except (OSError, ValueError) as error:
        store[NOTICE_KEY] = {
            "kind": "error",
            "message": str(error),
        }
        return

    # Clear only a successfully recorded reason.
    store[reason_key] = ""
    store[NOTICE_KEY] = {
        "kind": "success",
        "message": result.message,
    }