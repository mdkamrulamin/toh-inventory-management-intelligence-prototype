"""Pure synthetic medication-workflow operations.

Functions return a new state without mutating their input.
The session adapter will publish successful results in one assignment.
No operation reads or writes a source CSV.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from math import isfinite
from numbers import Integral, Real
from uuid import uuid4

import pandas as pd

from src.services.workflow_models import (
    ActionContext,
    DemoState,
    FulfillmentRecord,
    RequestOutcome,
    RequestStatus,
    Role,
    StatusEvent,
    SubmitRequestInput,
    SupplyFeedback,
    SupplyFeedbackInput,
    SyntheticRequest,
    Urgency,
    WorkflowError,
    WorkflowResult,
)

def _text(value, field: str, code: str = "invalid_input") -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkflowError(code, f"{field} must contain a nonblank value.")
    return value.strip()

def _timestamp(now: datetime) -> str:
    if (not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None):
        raise WorkflowError("invalid_time", "Use a timezon-aware action time.")
    return now.astimezone(timezone.utc).isoformat(timespec="seconds")

def _quantity(value) -> int:
    # Preserve the existing integer-input preview convention.
    # Never round or truncate a fractional request.
    if (isinstance(value, bool) or not isinstance(value, Integral) or value <= 0):
        raise WorkflowError("invalid_quantity", "Enter a postive whole-number request quantity.")
    
    return int(value)

def _number(value, field: str, code: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise WorkflowError(code, f"{field} must be a finite nonnegative number.")
    try:
        finite = isfinite(value)
    except (ValueError, TypeError, OverflowError):
        finite = False
        
    if not finite or value < 0:
        raise WorkflowError(code, f"{field} must be a finite nonnegative number.")
    
    return int(value) if isinstance(value, Integral) else float(value)

def _optional_number(row: pd.Series, field: str) -> int | float | None:
    value = row.get(field, pd.NA)
    
    if pd.isna(value):
        return None
    return _number(value, field, "invalid_supply")

def _reason(value: str) -> str:
    return _text(value, "Reason", "reason_required")

def _check_context(state: DemoState, context: ActionContext, role: Role, *, check_revision: bool = True) -> str:
    if context.expected_run_id != state.run_id:
        raise WorkflowError("wrong_run", "This action belongs to an earlier demo run.")
    
    if context.acting_role != role:
        raise WorkflowError("wrong_role", f"This action requires the {role.value} role.")
    
    if check_revision and context.expected_revision != state.revision:
        raise WorkflowError("stale_state", "The demo changed. Refresh and retry the action.")
    
    stamp = _timestamp(context.now)
    
    if stamp < state.started_time:
        raise WorkflowError("invalid_time", "The action cannot predate this demo run.")
    
    return stamp 

def _medication(state: DemoState, medication_id: str) -> pd.Series:
    medication_id = _text(medication_id, "Medication ID", "unknown_medication")
    rows = state.inventory.loc[state.inventory["medication_id"].eq(medication_id)]
    if len(rows) != 1:
        raise WorkflowError("unknown_medication", "Medication ID must identify one record.")
    
    return rows.iloc[0]

def _request(state: DemoState, request_id: str) -> SyntheticRequest:
    request = state.requests.get(request_id)
    if request is None:
        raise WorkflowError("unknown_request", "The request does not exist in this demo.")
    if (request.run_id != state.run_id or request.request_id != request_id):
        raise WorkflowError("invalid_state", "The request identity is inconsistent.")
    return request

def _available(state: DemoState, request: SyntheticRequest):
    row = _medication(state, request.medication_id)
    quantity = _quantity(request.quantity)
    unit = _text(row.get("stock_unit"), "Stock unit", "invalid_unit")
    request_unit = _text(request.unit, "Request unit", "invalid_unit")
    
    if request_unit != unit:
        raise WorkflowError("invalid_unit", "Request unit does not match the stock unit.")
    
    stock = _number(row["current_stock"], "Recorded stock", "invalid_stock")
    
    return row, quantity, unit, stock

def _prepare(state, request_id, context, role, statuses):
    stamp = _check_context(state, context, role)
    request = _request(state, request_id)
    if request.status not in statuses:
        raise WorkflowError("invalid_transition", f"The action is not allowed while the request is {request.status}.")
    if stamp < request.updated_time:
        raise WorkflowError("invalid_time", "Action time precedes the last request update.")
    return request, stamp

def _event(
    request: SyntheticRequest,
    status: RequestStatus,
    action: str,
    reason: str,
    role: Role,
    stamp: str,
    **changes,
) -> SyntheticRequest:
    event = StatusEvent(
        sequence=len(request.status_history) + 1,
        action=action,
        from_status=request.status,
        to_status=status,
        reason=reason,
        actor_role=role,
        actor_name=("System" if role == Role.SYSTEM else "Demo user"),
        timestamp=stamp,
    )
    
    return replace(
        request,
        status=status,
        status_reason=reason,
        updated_time=stamp,
        decided_by=(request.decided_by if role == Role.SYSTEM else "Demo user"),
        status_history=[*request.status_history, event],
        **changes,
    )
    
def _publish(
    state: DemoState,
    request: SyntheticRequest,
    message: str,
    *,
    inventory: pd.DataFrame | None = None,
    next_request_number: int | None = None,
) -> WorkflowResult:
    # Copy the entire candidate, including nested history and baseline.
    # No object owned by the input state is modified.
    candidate = deepcopy(state)
    requests = dict(candidate.requests)
    requests[request.request_id] = deepcopy(request)
    
    candidate = replace(
        candidate,
        requests=requests,
        inventory=(candidate.inventory if inventory is None else inventory.copy(deep=True)),
        revision=state.revision + 1,
        next_request_number=(state.next_request_number if next_request_number is None else next_request_number),
    )
    
    return WorkflowResult(candidate, request.request_id, True, message)

def initialize_demo(
    validated_inventory: pd.DataFrame,
    *,
    dataset_path: str,
    dataset_fingerprint: str,
    now: datetime,
) -> DemoState:
    """Initialize from loader output using independent inventory copies."""
    stamp = _timestamp(now)
    dataset_path = _text(dataset_path, "Dataset path")
    dataset_fingerprint = _text(dataset_fingerprint, "Dataset fingerprint")
    required = {
        "medication_id",
        "medication_name",
        "current_stock",
    }
    
    if (
        not isinstance(validated_inventory, pd.DataFrame)
        or not required.issubset(validated_inventory.columns)
        or validated_inventory.empty
        or validated_inventory.columns.duplicated().any()
    ):
        raise WorkflowError("invalid_state", "Initialize with a nonempty validated inventory.")
    
    baseline = (validated_inventory.copy(deep=True).reset_index(drop=True))
    for field in ("medication_id", "medication_name"):
        for value in baseline[field]:
            if (not isinstance(value, str) or not value.strip() or value != value.strip()):
                raise WorkflowError("invalid_state", f"{field} must contain normalized text.")
            
    if baseline["medication_id"].duplicated().any():
        raise WorkflowError("invalid_state", "Medication IDs must be unique.")
    
    for value in baseline["current_stock"]:
        _number(value, "Recorded stock", "invalid_stock")
        
    expected = (baseline["current_stock"].gt(0).map({True: "In stock", False: "Out of stock"}).astype("string"))
    
    if "status" in baseline:
        supplied = baseline["status"].astype("string")
        conflicts = supplied.notna() & supplied.ne(expected)
        if conflicts.any():
            raise WorkflowError("invalid_state", "Availability conflicts with recorded stock.")
        baseline["status"] = supplied.fillna(expected)
    else:
        baseline["status"] = expected
        
    return DemoState(
        run_id=uuid4().hex,
        revision=0,
        dataset_path=dataset_path,
        dataset_fingerprint=dataset_fingerprint,
        initial_inventory=baseline.copy(deep=True),
        inventory=baseline.copy(deep=True),
        requests={},
        next_request_number=1,
        started_time=stamp,
    )
    
def make_context(state: DemoState, role: Role, *, now: datetime | None = None) -> ActionContext:
    """Build action metadata; services still validate every guard."""
    return ActionContext(
        acting_role=role,
        expected_run_id=state.run_id,
        expected_revision=state.revision,
        now=(datetime.now(timezone.utc) if now is None else now),
    )
    
def submit_request(state: DemoState, inputs: SubmitRequestInput, submission_key: str, context: ActionContext) -> WorkflowResult:
    stamp = _check_context(state, context, Role.CLINICAL, check_revision=False)
    submission_key = _text(submission_key, "Submission key")
    medication_id = _text(inputs.medication_id, "Medication ID", "unknown_medication")
    quantity = _quantity(inputs.quantity)
    unit = _text(inputs.unit, "Request unit", "invalid_unit")
    location = _text(inputs.requesting_location, "Requesting location")
    reason = _reason(inputs.reason)
    
    try:
        urgency = Urgency(inputs.urgency)
    except (ValueError, TypeError) as error:
        raise WorkflowError("invalid_input", "Select Routine or Urgent.") from error
    
    if not isinstance(inputs.substitution_allowed, bool):
        raise WorkflowError("invalid_input", "Substitution preference must be boolean.")
    
    payload = (
        medication_id,
        quantity,
        unit,
        location,
        urgency,
        inputs.substitution_allowed,
        reason,
    )
    # The original successful submission already advanced revision.
    # A retry with its original token must not create a second request.
    for existing in state.requests.values():
        if existing.submission_key == submission_key:
            previous = (
                existing.medication_id,
                existing.quantity,
                existing.unit,
                existing.requesting_location,
                existing.urgency,
                existing.substitution_allowed,
                existing.reason,
            )
            if payload != previous:
                raise WorkflowError("submission_key_conflict", "This submission key has a different payload.")
            return WorkflowResult(state, existing.request_id, False, "This request was already submitted.")
    
    _check_context(state, context, Role.CLINICAL)
    row = _medication(state, medication_id)
    current_unit = _text(row.get("stock_unit"), "Stock unit", "invalid_unit")
    if current_unit != unit:
        raise WorkflowError("invalid_unit", "Request unit does not match the stock unit.")
    
    # Submission may represent a shortage. Do not require enough
    # stock here; availability is checked at release and fulfillment.
    request_id = f"REQ-{state.next_request_number:04d}"
    
    if request_id in state.requests:
        raise WorkflowError("invalid_state", "The next request identity is already used.")
    
    event = StatusEvent(
        sequence=1,
        action="submit_request",
        from_status=None,
        to_status=RequestStatus.RECEIVED,
        reason=("Synthetic request submitted; no stock reserved or deducted."),
        actor_role=Role.CLINICAL,
        actor_name="Demo user",
        timestamp=stamp,
    )
    request = SyntheticRequest(
        run_id=state.run_id,
        request_id=request_id,
        submission_key=submission_key,
        sequence=state.next_request_number,
        medication_id=medication_id,
        medication_name=row["medication_name"],
        quantity=quantity,
        unit=unit,
        requesting_location=location,
        urgency=urgency,
        substitution_allowed=inputs.substitution_allowed,
        reason=reason,
        status=RequestStatus.RECEIVED,
        status_reason=event.reason,
        received_time=stamp,
        updated_time=stamp,
        status_history=[event],
    )
    
    return _publish(
        state,
        request,
        f"Synthetic request {request_id} submitted.",
        next_request_number=state.next_request_number + 1,
    )
    
def start_review(state, request_id, context) -> WorkflowResult:
    request, stamp = _prepare(state, request_id, context, Role.PHARMACIST, {RequestStatus.RECEIVED})
    updated = _event(request, RequestStatus.UNDER_REVIEW, "start_review", "Synthetic review started.", Role.PHARMACIST, stamp)
    return _publish(state, updated, "Review started.")

def return_to_queue(state, request_id, note, context) -> WorkflowResult:
    request, stamp = _prepare(state, request_id, context, Role.PHARMACIST, {RequestStatus.UNDER_REVIEW})
    reason = (
        "Returned to review queue."
        if note is None
        or (isinstance(note, str) and not note.strip())
        else _reason(note)
    )
    updated = _event(request, RequestStatus.RECEIVED, "return_to_queue", reason, Role.PHARMACIST, stamp)
    return _publish(state, updated, "Request returned to the queue.")

def return_request(state, request_id, reason, context) -> WorkflowResult:
    request, stamp = _prepare(state, request_id, context, Role.PHARMACIST, {RequestStatus.UNDER_REVIEW})
    updated = _event(
        request, 
        RequestStatus.RETURNED, 
        "return_request", 
        _reason(reason), 
        Role.PHARMACIST, 
        stamp, 
        outcome=RequestOutcome.RETURNED,
    )
    return _publish(state, updated, "Request returned with a reason.")

def authorize_release(state, request_id, reason, context) -> WorkflowResult:
    request, stamp = _prepare(state, request_id, context, Role.PHARMACIST, {RequestStatus.UNDER_REVIEW})
    reason = _reason(reason)
    _, quantity, unit, stock = _available(state, request)
    if quantity > stock:
        raise WorkflowError("insufficient_stock", f"Requested {quantity} {unit}; recorded stock {stock:g}. Full release is unavailable.")
    updated = _event(request, RequestStatus.APPROVED_FOR_RELEASE, "authorize_release", reason, Role.PHARMACIST, stamp)
    return _publish(state, updated, "Synthetic release authorized; stock is unchanged.")

def recall_release(state, request_id, reason, context) -> WorkflowResult:
    request, stamp = _prepare(state, request_id, context, Role.PHARMACIST, {RequestStatus.APPROVED_FOR_RELEASE})
    reason = _reason(reason)
    updated = _event(request, RequestStatus.UNDER_REVIEW, "recall_release", reason, Role.PHARMACIST, stamp)
    return _publish(state, updated, "Release recalled for Pharmacist review.")

def escalate_shortage(state, request_id, reason, context) -> WorkflowResult:
    request, stamp = _prepare(state, request_id, context, Role.PHARMACIST, {RequestStatus.UNDER_REVIEW})
    reason = _reason(reason)
    _, quantity, _, stock = _available(state, request)
    
    if quantity <= stock:
            raise WorkflowError("invalid_transition", "Current stock covers the full request.")
    updated = _event(
        request, 
        RequestStatus.ESCALATED, 
        "escalate_shortage", 
        reason, 
        Role.PHARMACIST, 
        stamp, 
        shortfall=quantity - stock,
    )
    return _publish(state, updated, "Shortage linked to Procurement; no stock change.")

def update_supply_feedback(state, request_id, inputs: SupplyFeedbackInput, context) -> WorkflowResult:
    request, stamp = _prepare(
        state, 
        request_id, 
        context, Role.PROCUREMENT, 
        {
            RequestStatus.ESCALATED,
            RequestStatus.AWAITING_SUPPLY,
        },
    )
    feedback = _reason(inputs.feedback)
    row = _medication(state, request.medication_id)
    supplier_value = row.get("supplier")
    supplier = (supplier_value.strip() if isinstance(supplier_value, str) and supplier_value.strip() else None)
    lead = _optional_number(row, "lead_time_days")
    consumption = _optional_number(row, "average_monthly_consumption")
    expected_delivery = None
    if inputs.expected_delivery is not None:
        if (isinstance(inputs.expected_delivery, datetime) or not isinstance(inputs.expected_delivery, date)):
            raise WorkflowError("invalid_supply", "Expected delivery must be a date.")
        expected_delivery = inputs.expected_delivery.isoformat()
    elif lead is not None and float(lead).is_integer():
        escalations = [event for event in request.status_history if event.to_status == RequestStatus.ESCALATED]
        if not escalations:
            raise WorkflowError("invalid_state", "The escalation event is missing.")
        origin = datetime.fromisoformat(escalations[-1].timestamp).date()
        
        try:
            expected_delivery = (origin + timedelta(days=int(lead))).isoformat()
        except OverflowError:
            expected_delivery = None
    # Demonstration context only: a 30-day month is assumed.
    # This is not a calculated purchase quantity.
    demand = None
    if lead is not None and consumption is not None:
        try:
            value = float(consumption) / 30 * float(lead)
            if isfinite(value):
                demand = value
        except OverflowError:
            demand = None
            
    response = SupplyFeedback(
        feedback=feedback,
        supplier=supplier,
        lead_time_days=lead,
        expected_delivery=expected_delivery,
        lead_time_demand=demand,
        updated_time=stamp,
    )
    
    previous = request.supply_feedback
    
    if previous is not None and (
        previous.feedback,
        previous.supplier,
        previous.lead_time_days,
        previous.expected_delivery,
        previous.lead_time_demand,
    ) == (
        response.feedback,
        response.supplier,
        response.lead_time_days,
        response.expected_delivery,
        response.lead_time_demand,
    ): 
        raise WorkflowError("duplicate_action", "This supply feedback is unchanged.")
    updated = _event(
        request,
        RequestStatus.AWAITING_SUPPLY,
        "update_supply_feedback",
        feedback,
        Role.PROCUREMENT,
        stamp,
        supply_feedback=response,
    )
    
    return _publish(state, updated, "Synthetic supply feedback recorded; no stock change.")

def fulfill_request(state, request_id, context) -> WorkflowResult:
    # Duplicate protection must exist below the UI layer.
    stamp = _check_context(state, context, Role.WAREHOUSE)
    request = _request(state, request_id)

    if (request.fulfillment is not None or request.outcome == RequestOutcome.FULFILLED):
        raise WorkflowError("already_fulfilled", "This request was already fulfilled.")

    request, stamp = _prepare(state, request_id, context, Role.WAREHOUSE, {RequestStatus.APPROVED_FOR_RELEASE})
    row, quantity, unit, stock = _available(state, request)

    if quantity > stock:
        raise WorkflowError("insufficient_stock", f"Requested {quantity} {unit}; latest stock {stock:g}. No deduction. Pharmacist re-review is required.")

    remaining = stock - quantity

    # Build a separate inventory candidate.
    # Input state remains intact if any later step fails.
    inventory = state.inventory.copy(deep=True)
    target = inventory["medication_id"].eq(row["medication_id"])

    inventory.loc[target, "current_stock"] = remaining
    inventory.loc[target, "status"] = ("In stock" if remaining > 0 else "Out of stock")

    fulfillment = FulfillmentRecord(
        fulfillment_id=f"FUL-{state.run_id}-{request_id}",
        medication_id=request.medication_id,
        quantity=quantity,
        unit=unit,
        stock_before=stock,
        stock_after=remaining,
        fulfilled_time=stamp,
    )

    fulfilled = _event(
        request,
        RequestStatus.FULFILLED,
        "fulfill_request",
        "Full synthetic fulfillment confirmed.",
        Role.WAREHOUSE,
        stamp,
        fulfillment=fulfillment,
        outcome=RequestOutcome.FULFILLED,
    )

    closed = _event(
        fulfilled,
        RequestStatus.CLOSED,
        "auto_close_fulfilled",
        "Closed after successful synthetic fulfillment.",
        Role.SYSTEM,
        stamp,
    )

    # Inventory, fulfillment, outcome, and history are returned together.
    return _publish(state, closed, f"{request_id} fulfilled once; recorded stock is {remaining:g} {unit}.", inventory=inventory)


def close_without_supply(state, request_id, reason, context) -> WorkflowResult:
    request, stamp = _prepare(state, request_id, context, Role.PHARMACIST, {RequestStatus.AWAITING_SUPPLY})

    updated = _event(
        request,
        RequestStatus.CLOSED,
        "close_without_supply",
        _reason(reason),
        Role.PHARMACIST,
        stamp,
        outcome=RequestOutcome.CLOSED_WITHOUT_SUPPLY,
    )

    return _publish(state, updated, "Closed without supply; stock is unchanged.")


def reset_demo(state: DemoState, *, now: datetime,) -> DemoState:
    """Restore the baseline and clear requests in a new demo run."""
    stamp = _timestamp(now)

    if stamp < state.started_time:
        raise WorkflowError("invalid_time", "Reset cannot predate the active demo.",)

    return initialize_demo(
        state.initial_inventory,
        dataset_path=state.dataset_path,
        dataset_fingerprint=state.dataset_fingerprint,
        now=now,
    )