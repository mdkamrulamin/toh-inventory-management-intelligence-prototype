"""Detached, role-projected readers for synthetic orders."""
from copy import deepcopy

from src.services import workflow as wf
from src.services.orders import OPEN_ORDER_STATUSES
from src.services.workflow_models import Role, WorkflowError
from src.services.receipt_queries import list_receipts

ORDER_READER_ROLES = {
    Role.CLINICAL,
    Role.PHARMACIST,
    Role.PROCUREMENT,
    Role.WAREHOUSE,
    Role.REPORTING,
}

ORDER_STATUS_LABELS = {
    "ordered": "Ordered",
    "partially_received": "Partially received",
    "received": "Received",
    "cancelled": "Cancelled",
}

PUBLIC_EVENT_REASONS = {
    "confirm_order": "Simulated order confirmed.",
    "update_order_delivery": "Illustrative expected delivery updated.",
    "cancel_order": "Simulated order cancelled.",
    "post_receipt": "Synthetic receipt posted.",
}

PROGRESS_NOTES = {
    "ordered": "Simulated order recorded. No receipt has been posted against this order.",
    "partially_received": "A partial synthetic receipt is recorded.",
    "received": "The synthetic order is fully received.",
    "cancelled": "The simulated order is cancelled.",
}

def _reader_role(role):
    try:
        role = Role(role)
    except (ValueError, TypeError) as error:
        raise WorkflowError("wrong_role", "Unknown order-reader role.") from error
    
    if role not in ORDER_READER_ROLES:
        raise WorkflowError("wrong_role", "This view does not receive individual order records.")
    return role

def get_order_details(state, order_id, role, *, include_history=True) -> dict:
    """Return only fields appropriate for the selected demo role."""
    role = _reader_role(role)
    order_id = wf._text(order_id, "Order ID", "unknown_order")
    order = state.orders.get(order_id)
    
    if order is None:
        raise WorkflowError("unknown_order", "The order does not exist in this demo.")
    if order.run_id != state.run_id or order.order_id != order_id:
        raise WorkflowError("invalid_state", "Order identity is inconsistent.")
    request = wf._request(state, order.linked_request_id)
    
    # Reporting receives an explicit operational projection.
    # Commercial details, free-text order history and internal keys
    # are excluded, including when include_history=True.
    if role == Role.REPORTING:
        if (
            order.order_id not in request.order_ids 
            or order.medication_id != request.medication_id
            or order.unit != request.unit
        ):
            raise WorkflowError("invalid_state", "The order and request links are inconsistent.")
        
        return deepcopy(
            {
                "run_id": order.run_id,
                "order_id": order.order_id,
                "linked_request_id": order.linked_request_id,
                "medication_id": order.medication_id,
                "medication_name": order.medication_name,
                "order_status": str(order.status),
                "request_status": str(request.status),
                "ordered_quantity": order.ordered_quantity,
                "quantity_received": order.quantity_received,
                "quantity_outstanding": order.quantity_outstanding,
                "unit": order.unit,
                "order_date": order.order_date,
                "expected_delivery": order.expected_delivery,
                "expected_delivery_note": order.expected_delivery_note,
                "created_time": order.created_time,
                "updated_time": order.updated_time,
                "provenance": order.provenance,
            }
        )
    
    result = {
        "run_id": order.run_id,
        "order_id": order.order_id,
        "linked_request_id": order.linked_request_id,
        "medication_id": order.medication_id,
        "medication_name": order.medication_name,
        "order_status": str(order.status),
        "expected_delivery": order.expected_delivery,
        "request_status": str(request.status),
        "updated_time": order.updated_time,
        "progress_note": PROGRESS_NOTES.get(str(order.status), "Recorded synthetic order progress."),
    }
    
    # Clinical receives identifiers and progress, without order quantities.
    if role != Role.CLINICAL:
        result.update(
            {
                "unit": order.unit,
                "ordered_quantity": order.ordered_quantity,
                "quantity_received": order.quantity_received,
                "quantity_outstanding": order.quantity_outstanding,
                "order_date": order.order_date,
                "created_time": order.created_time,
                "ordered_by": order.ordered_by,
                "ordered_by_role": str(order.ordered_by_role),
                "expected_delivery_note": order.expected_delivery_note,
                "provenance": order.provenance,
            }
        )
        
    if role in {Role.PHARMACIST, Role.PROCUREMENT}:
        result["supplier"] = order.supplier
        result["lead_time_days"] = order.lead_time_days
        
    if role == Role.PROCUREMENT:
        result.update(
            {
                "unit_cost": order.unit_cost,
                "order_value_cad": order.order_value_cad,
                "order_value_note": order.order_value_note,
                "status_reason": order.status_reason,
            }
        )
        
    if include_history and role != Role.CLINICAL:
        result["order_history"] = [
            {
                "sequence": event.sequence,
                "action": event.action,
                "from_status": (
                    None
                    if event.from_status is None else str(event.from_status)
                ),
                "to_status": str(event.to_status),
                # Free-text Procurement reasons may contain commercial
                # details. Other roles receive a generic event explanation.
                "reason": (
                    event.reason
                    if role == Role.PROCUREMENT
                    else PUBLIC_EVENT_REASONS.get(event.action, "Recorded synthetic order update.")
                ),
                "actor_role": str(event.actor_role),
                "actor_name": event.actor_name,
                "timestamp": event.timestamp,
                "expected_delivery_before": event.expected_delivery_before,
                "expected_delivery_after": event.expected_delivery_after,
            }
            for event in order.order_history
        ]
        
    receipts = list_receipts(state, role, order_id=order.order_id)
    result["receipt_ids"] = [
        receipt["receipt_id"]
        for receipt in receipts
    ]
    
    if include_history:
        result["receipts"] = receipts
        
    if request.status == "supply_received":
        result["progress_note"] = "Synthetic supply received. An explicit Pharmacist review is required before any release or fulfillment."
    elif (request.status == "under_review" and request.after_receipt):
        result["progress_note"] = "An explicit synthetic post-receipt review is in progress. No stock has been reserved by that review."
        
    # Never expose the internal confirmation key.
    return deepcopy(result)

def list_orders(state, role, *, open_only=False) -> list[dict]:
    """Keep completed/cancelled history available separately from open orders."""
    role = _reader_role(role)
    selected = [
        order
        for order in state.orders.values()
        if not open_only or order.status in OPEN_ORDER_STATUSES
    ]
    selected.sort(
        key=lambda order: (
            order.created_time,
            order.order_id,
        )
    )
    
    return [
        get_order_details(state, order.order_id, role, include_history=False)
        for order in selected
    ]