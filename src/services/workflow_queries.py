"""Read-only, role-specific queries for the synthetic workflow.

Returned DataFrames and dictionaries are detached from shared state.
Queries do not submit requests, change statuses, or modify inventory.
"""

from copy import deepcopy
from dataclasses import asdict

import pandas as pd

from src.services.clinical import build_clinical_request_preview
from src.services.replenishment import build_replenishment_context
from src.services.summary import summarize_inventory
from src.services.workflow_models import (
    DemoState,
    RequestOutcome,
    RequestStatus,
    Role,
    SyntheticRequest,
    Urgency,
    WorkflowError,
)

INVENTORY_COLUMNS = (
    "medication_id",
    "medication_name",
    "category",
    "stock_unit",
    "current_stock",
    "unit_cost",
    "average_monthly_consumption",
    "expiry_date",
    "supplier",
    "status",
    "primary_location",
    "reorder_point",
    "safety_stock_level",
    "lead_time_days",
    "last_count_date",
    "counted_stock",
)

ROLE_INVENTORY_COLUMNS = {
    Role.CLINICAL: (
        "medication_id",
        "medication_name",
        "current_stock",
        "stock_unit",
        "status",
        # Retained internally for the existing review badge.
        # The Clinical table does not display a raw threshold.
        "reorder_point",
    ),
    Role.PHARMACIST: (
        "medication_id",
        "medication_name",
        "category",
        "current_stock",
        "stock_unit",
        "status",
        "expiry_date",
        "primary_location",
        "average_monthly_consumption",
        "reorder_point",
        "safety_stock_level",
        "supplier",
        "lead_time_days",
        "last_count_date",
        "counted_stock",
    ),
    Role.WAREHOUSE: (
        "medication_id",
        "medication_name",
        "current_stock",
        "stock_unit",
        "status",
        "primary_location",
        "expiry_date",
        "last_count_date",
        "counted_stock",
        "reorder_point",
    ),
    Role.PROCUREMENT: INVENTORY_COLUMNS,
    Role.REPORTING: INVENTORY_COLUMNS,
}

ACTIONABLE_STATUSES = {
    Role.CLINICAL: set(),
    Role.PHARMACIST: {
        RequestStatus.RECEIVED,
        RequestStatus.UNDER_REVIEW,
        RequestStatus.APPROVED_FOR_RELEASE,
        RequestStatus.AWAITING_SUPPLY,
    },
    Role.WAREHOUSE: {
        RequestStatus.APPROVED_FOR_RELEASE,
    },
    Role.PROCUREMENT: {
        RequestStatus.ESCALATED,
        RequestStatus.AWAITING_SUPPLY,
    },
    Role.REPORTING: set(),
}

def _role(value: Role | str) -> Role:
    try:
        role = Role(value)
    except (ValueError, TypeError) as error:
        raise WorkflowError("wrong_role", "Unknown dashboard role.") from error
    
    if role == Role.SYSTEM:
        raise WorkflowError("wrong_role", "System is not a dashboard reader role.")
    return role

def _request(state: DemoState, request_id: str) -> SyntheticRequest:
    request = state.requests.get(request_id)
    
    if request is None:
        raise WorkflowError("unknown_request", "The request does not exist in this demo.")
    if (request.run_id != state.run_id or request.request_id != request_id):
        raise WorkflowError("invalid_state", "The request identity is inconsistent.")
    return request

def _visible(request: SyntheticRequest, role: Role) -> bool:
    if role in {Role.CLINICAL, Role.PHARMACIST, Role.REPORTING}:
        return True
    
    if role == Role.WAREHOUSE:
        # Retain read-only visibility after a release is recalled or a request has been fulfilled.
        return (
            request.status == RequestStatus.APPROVED_FOR_RELEASE
            or any(
                event.to_status == RequestStatus.APPROVED_FOR_RELEASE
                for event in request.status_history
            )
        )
    if role == Role.PROCUREMENT:
        return (
            request.status in {RequestStatus.ESCALATED, RequestStatus.AWAITING_SUPPLY}
            or any (
                event.to_status == RequestStatus.ESCALATED
                for event in request.status_history
            )
        )
    return False

def _project_request(request: SyntheticRequest, role: Role, *, include_history: bool) -> dict:
    # Explicit fields prevent internal submission tokens or unrelated future fields from leaking into role outputs.
    result = {
        "run_id": request.run_id,
        "request_id": request.request_id,
        "medication_id": request.medication_id,
        "medication_name": request.medication_name,
        "quantity": request.quantity,
        "unit": request.unit,
        "requesting_location": request.requesting_location,
        "urgency": str(request.urgency),
        "substitution_allowed": request.substitution_allowed,
        "reason": request.reason,
        "status": str(request.status),
        "status_reason": request.status_reason,
        "received_time": request.received_time,
        "updated_time": request.updated_time,
        "decided_by": request.decided_by,
        "outcome": (
            None
            if request.outcome is None
            else str(request.outcome)
        ),
        "shortfall_at_escalation": request.shortfall,
        "supply_feedback": None,
        "fulfillment": None,
    }
    
    if role in {Role.PHARMACIST, Role.PROCUREMENT, Role.REPORTING}:
        # Remains unavailable unless explicitly governed classification data is introduced later.
        result["priority_class"] = request.priority_class
    
    if request.supply_feedback is not None:
        feedback = asdict(request.supply_feedback)
            
        if role in {Role.CLINICAL, Role.WAREHOUSE}:
            # Preceding roles receive the operational update without supplier commercial context.
            feedback = {
                key: feedback[key]
                for key in (
                    "feedback",
                    "expected_delivery",
                    "updated_time",
                    "updated_by",
                )
            }
            
        result["supply_feedback"] = feedback
        
    if request.fulfillment is not None:
        fulfillment = asdict(request.fulfillment)
        fulfillment["fulfilled_by_role"] = str(request.fulfillment.fulfilled_by_role)
        result["fulfillment"] = fulfillment
        
    if include_history:
        result["status_history"] = [
            {
                "sequence": event.sequence,
                "action": event.action,
                "from_status": (
                    None
                    if event.from_status is None
                    else str(event.from_status)
                ),
                "to_status": str(event.to_status),
                "reason": event.reason,
                "actor_role": str(event.actor_role),
                "actor_name": event.actor_name,
                "timestamp": event.timestamp,
            }
            for event in request.status_history
        ]
    
    return deepcopy(result)

def get_inventory_snapshot(state: DemoState, role: Role | str) -> pd.DataFrame:
    """Return only the inventory fields supported for this role."""
    role = _role(role)
    
    if role == Role.EXECUTIVE:
        raise WorkflowError("aggregate_only", "Executive receives summaries, not item-level inventory.")
    
    columns = [
        column
        for column in ROLE_INVENTORY_COLUMNS[role]
        if column in state.inventory.columns
    ]
    # Missing optional source columns remain absent. Individual presentation components can display N/A.
    return state.inventory.loc[:, columns].copy(deep=True)

def list_requests(state: DemoState, role: Role | str, *, actionable_only: bool = False) -> list[dict]:
    """Return visible requests ordered by demo urgency and arrival."""
    role = _role(role)
    
    if role == Role.EXECUTIVE:
        raise WorkflowError("aggregate_only", "Executive receives aggregate workflow counts only.")
    requests = [
        request
        for request in state.requests.values()
        if _visible(request, role)
    ]
    
    if actionable_only:
        requests = [
            request
            for request in requests
            if request.status in ACTIONABLE_STATUSES[role]
        ]
        
    requests.sort(
        key=lambda request: (
            0 if request.urgency == Urgency.URGENT else 1,
            request.received_time,
            request.sequence,
        )
    )
    
    return [
        _project_request(request, role, include_history=False)
        for request in requests
    ]
    
def get_request_details(state: DemoState, request_id: str, role: Role | str) -> dict: 
    """Return projected details and history for one visible request."""
    role = _role(role)
    if role == Role.EXECUTIVE:
        raise WorkflowError("aggregate_only", "Executive does not receive individual request details.")
    request = _request(state, request_id)
    
    if not _visible(request, role):
        raise WorkflowError("request_not_visible", "This request has not been handed to this role.")
    
    return _project_request(request, role, include_history=True)

def get_current_availability(state: DemoState, request_id: str) -> dict: 
    """Compare with current stock without reserving or changing it."""
    request = _request(state, request_id)
    
    rows = state.inventory.loc[state.inventory["medication_id"].eq(request.medication_id)]
    if len(rows) != 1:
        raise WorkflowError("unknown_medication", "Medication ID must identify one current record.")
    
    result = {
        "run_id": state.run_id,
        "revision": state.revision,
        "request_id": request.request_id,
        "medication_id": request.medication_id,
        "requested_quantity": request.quantity,
        "request_unit": request.unit,
        "recorded_stock": None,
        "stock_unit": None,
        "comparable": False,
        "available": None,
        "outcome": "unavailable",
        "message": "", 
    }
    
    try:
        preview = build_clinical_request_preview(rows.iloc[0].copy(), request.quantity)
    except ValueError as error:
        result["message"] = str(error)
        return result
    
    result["recorded_stock"] = preview.recorded_stock
    result["stock_unit"] = preview.stock_unit
    
    if (not isinstance(request.unit, str) or request.unit.strip() != preview.stock_unit):
        result["outcome"] = "unit_mismatch"
        result["message"] = ("Request unit does not match the current stock unit.")
        return result
    
    result.update(comparable=True, available=preview.outcome == "sufficient", outcome=preview.outcome, message=preview.message)
    
    return result

def get_inventory_summary(state: DemoState) -> dict:
    """Reuse the existing Executive calculations on active inventory."""
    return deepcopy(summarize_inventory(state.inventory))

def get_replenishment_review(state: DemoState) -> pd.DataFrame:
    """Recalculate review context from current session stock."""
    return build_replenishment_context(state.inventory).copy(deep=True)

def get_session_request_summary(state: DemoState) -> dict:
    """Describe this demo session, not historical hospital activity."""
    by_status = {
        status.value: 0
        for status in RequestStatus
    }
    for request in state.requests.values():
        status = str(request.status)
        
        if status not in by_status:
            raise WorkflowError("invalid_state", "A request has an unknown workflow status.")
        by_status[status] += 1
        
    open_statuses = {
        RequestStatus.RECEIVED,
        RequestStatus.UNDER_REVIEW,
        RequestStatus.APPROVED_FOR_RELEASE,
        RequestStatus.ESCALATED,
        RequestStatus.AWAITING_SUPPLY,
    }
    return {
        "total_requests": len(state.requests),
        "open_requests": sum(
            request.status in open_statuses
            for request in state.requests.values()
        ),
        "returned_requests": sum(
            request.outcome == RequestOutcome.RETURNED
            for request in state.requests.values()
        ),
        "fulfilled_requests": sum(
            request.outcome == RequestOutcome.FULFILLED
            for request in state.requests.values()
        ),
        "closed_without_supply": sum(
            request.outcome
            == RequestOutcome.CLOSED_WITHOUT_SUPPLY
            for request in state.requests.values()
        ),
        "by_status": by_status,
    }
    
    
    
    
    