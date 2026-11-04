"""Data contracts for one synthetic medication-workflow session."""

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import StrEnum

import pandas as pd

class Role(StrEnum):
    CLINICAL = "clinical"
    PHARMACIST = "pharmacist"
    PROCUREMENT = "procurement_inventory"
    WAREHOUSE = "warehouse"
    EXECUTIVE = "executive"
    REPORTING = "reporting"
    SYSTEM = "system"
    
class RequestStatus(StrEnum):
    RECEIVED = "received"
    UNDER_REVIEW = "under_review"
    RETURNED = "returned"
    APPROVED_FOR_RELEASE = "approved_for_release"
    FULFILLED = "fulfilled"
    ESCALATED = "escalated"
    AWAITING_SUPPLY = "awaiting_supply"
    CLOSED = "closed"
    
class Urgency(StrEnum):
    ROUTINE = "routine"
    URGENT = "urgent"
    
class RequestOutcome(StrEnum):
    RETURNED = "returned"
    FULFILLED = "fulfilled"
    CLOSED_WITHOUT_SUPPLY = "closed_without_supply"
    

class WorkflowError(ValueError):
    """An expected invalid action that must not change shared state."""
    
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)
        

@dataclass(frozen=True)
class ActionContext:
    acting_role: Role
    expected_run_id: str
    expected_revision: int
    now: datetime
    
@dataclass(frozen=True)
class SubmitRequestInput:
    medication_id: str
    quantity: int
    unit: str
    requesting_location: str
    reason: str
    urgency: Urgency = Urgency.ROUTINE
    substitution_allowed: bool = False
    
@dataclass(frozen=True)
class SupplyFeedbackInput:
    feedback: str
    expected_delivery: date | None = None
    
@dataclass(frozen=True)
class StatusEvent:
    sequence: int
    action: str
    from_status: RequestStatus | None
    to_status: RequestStatus | None
    reason: str
    actor_role: Role
    actor_name: str
    timestamp: str
    
    
@dataclass(frozen=True)
class SupplyFeedback:
    feedback: str
    supplier: str | None
    lead_time_days: int | float | None
    expected_delivery: str | None
    lead_time_demand: float | None
    updated_time: str
    updated_by: str = "Demo user"
    
@dataclass(frozen=True)
class FulfillmentRecord:
    fulfillment_id: str
    medication_id: str
    quantity: int
    unit: str
    stock_before: int | float
    stock_after: int | float
    fulfilled_time: str
    filfilled_by: str = "Demo user"
    fulfilled_by_role: Role = Role.WAREHOUSE
    
@dataclass(frozen=True)
class SyntheticRequest:
    run_id: str
    request_id: str
    submission_key: str
    sequence: int
    medication_id: str
    medication_name: str
    quantity: int
    unit: str
    requesting_location: str
    urgency: Urgency
    substitution_allowed: bool
    reason: str
    status: RequestStatus
    status_reason: str
    received_time: str
    updated_time: str
    decided_by: str | None = None
    shortfall: int | float | None = None
    priority_class: str | None = None
    supply_feedback: SupplyFeedback | None = None
    fulfillment: FulfillmentRecord | None = None
    outcome: RequestOutcome | None = None
    status_history: list[StatusEvent] = field(default_factory=list)
    
@dataclass(frozen=True)
class DemoState:
    run_id: str
    revision: int
    dataset_path: str
    dataset_fingerprint: str
    initial_inventory: pd.DataFrame
    inventory: pd.DataFrame
    requests: dict[str, SyntheticRequest]
    next_request_number: int
    started_time: str
    schema_version: int = 1
    
@dataclass(frozen=True)
class WorkflowResult:
    state: DemoState
    request_id: str | None
    changed: bool
    message: str