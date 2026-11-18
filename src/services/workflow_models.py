"""Data contracts for one synthetic medication-workflow session."""

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import StrEnum
from decimal import Decimal

import pandas as pd

DEMO_SCHEMA_VERSION = 3

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
    ON_ORDER = "on_order"
    SUPPLY_RECEIVED = "supply_received"
    
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
    fulfilled_by: str = "Demo user"
    fulfilled_by_role: Role = Role.WAREHOUSE
    
class OrderStatus(StrEnum):
    ORDERED = "ordered"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    CANCELLED = "cancelled"
    
@dataclass(frozen=True)
class CreateOrderInput:
    quantity: int
    unit: str
    expected_delivery: date | None = None
    expected_delivery_reason: str = ""

@dataclass(frozen=True)
class OrderEvent:
    sequence: int
    action: str
    from_status: OrderStatus | None
    to_status: OrderStatus
    reason: str
    actor_role: Role
    actor_name: str
    timestamp: str
    expected_delivery_before: str | None = None
    expected_delivery_after: str | None = None
    
@dataclass(frozen=True)
class SyntheticOrder:
    run_id: str
    order_id: str
    linked_request_id: str
    medication_id: str
    medication_name: str
    unit: str
    ordered_quantity: int
    supplier: str | None
    unit_cost: int | float | None
    order_value_cad: Decimal | None
    order_value_note: str
    lead_time_days: int | float | None
    order_date: str
    expected_delivery: str | None
    expected_delivery_note: str
    status: OrderStatus
    status_reason: str
    created_time: str
    updated_time: str
    order_key: str
    quantity_received: int = 0
    order_history: tuple[OrderEvent, ...] = ()
    ordered_by: str = "Demo user"
    ordered_by_role: Role = Role.PROCUREMENT
    provenance: str = (
        "Synthetic demonstration order. Not sent to any supplier."
    )

    @property
    def quantity_outstanding(self) -> int:
        return self.ordered_quantity - self.quantity_received
    
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
    order_ids: tuple[str, ...] = ()
    after_receipt: bool = False
    
@dataclass(frozen=True)
class ReceiptInput:
    quantity: int
    unit: str
    
@dataclass(frozen=True)
class ReceiptRecord:
    run_id: str
    receipt_id: str
    order_id: str
    linked_request_id: str
    medication_id: str
    unit: str
    received_quantity: int
    stock_before: int | float
    stock_after: int | float
    received_time: str
    receipt_key: str
    recorded_by: str = "Demo user"
    recorded_by_role: Role = Role.WAREHOUSE
    status: str = "posted"
    inventory_added: bool = True
    provenance: str = (
        "Synthetic demonstration receipt. No physical shipment is verified."
    )
    
    
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
    schema_version: int = DEMO_SCHEMA_VERSION
    orders: dict[str, SyntheticOrder] = field(default_factory=dict)
    next_order_number: int = 1
    receipts: dict[str, ReceiptRecord] = field(default_factory=dict)
    next_receipt_number: int = 1
    
@dataclass(frozen=True)
class WorkflowResult:
    state: DemoState
    request_id: str | None
    changed: bool
    message: str
    order_id: str | None = None
    receipt_id: str | None = None