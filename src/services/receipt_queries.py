"""Detached, role-specific readers for synthetic receipt records."""

from copy import deepcopy

from src.services import workflow as wf
from src.services.workflow_models import Role, WorkflowError

RECEIPT_READER_ROLES = {
    Role.CLINICAL,
    Role.PHARMACIST,
    Role.PROCUREMENT,
    Role.WAREHOUSE,
}

def _reader_role(value):
    try:
        role = Role(value)
    except (ValueError, TypeError) as error:
        raise WorkflowError("wrong_role", "Unknown receipt-reader role.") from error
    
    if role not in RECEIPT_READER_ROLES:
        raise WorkflowError("wrong_role", "This view does not receive individual receipt records.")
    
    return role

def _linked_order(state, order_id):
    order_id = wf._text(order_id, "Order ID", "unknown_order")
    order = state.orders.get(order_id)
    
    if order is None:
        raise WorkflowError("unknown_order", "The order does not exist in this demo.")
    
    if (order.run_id != state.run_id or order.order_id != order_id):
        raise WorkflowError("invalid_state", "Order identity is inconsistent.")
    
    request = wf._request(state, order.linked_request_id)
    
    if (order_id not in request.order_ids or order.medication_id != request.medication_id or order.unit != request.unit):
        raise WorkflowError("invalid_state", "The order and request links are inconsistent.")
    
    return order, request

def get_receipt_details(state, receipt_id, role) -> dict:
    """Project recorded receipt facts without exposing internal tokens."""
    role = _reader_role(role)
    receipt_id = wf._text(receipt_id, "Receipt ID", "unknown_receipt")
    receipt = state.receipts.get(receipt_id)
    
    if receipt is None:
        raise WorkflowError("unknown_receipt", "The receipt does not exist in this demo.")
    if (receipt.run_id != state.run_id or receipt.receipt_id != receipt_id):
        raise WorkflowError("invalid_state", "Receipt identity is inconsistent.")
    
    order, request = _linked_order(state, receipt.order_id)
    
    if (
        receipt.linked_request_id != request.request_id
        or receipt.medication_id != order.medication_id
        or receipt.unit != order.unit
        or receipt.status != "posted"
        or receipt.inventory_added is not True
    ):
        raise WorkflowError("invalid_state", "The receipt links or posting result are inconsistent.")
    
    result = {
        "run_id": receipt.run_id,
        "receipt_id": receipt.receipt_id,
        "order_id": receipt.order_id,
        "linked_request_id": receipt.linked_request_id,
        "medication_id": receipt.medication_id,
        "medication_name": order.medication_name,
        "receipt_status": str(receipt.status),
        "received_time": receipt.received_time,
    }
    
    # Clinical receives receipt identity/progress, not supply quantities.
    if role != Role.CLINICAL:
        result.update(
            {
                "unit": receipt.unit,
                "received_quantity": receipt.received_quantity,
                "stock_before": receipt.stock_before,
                "stock_after": receipt.stock_after,
                "recorded_by": receipt.recorded_by,
                "recorded_by_role": str(receipt.recorded_by_role),
                "inventory_added": receipt.inventory_added,
                "provenance": receipt.provenance,
            }
        )
    # Supplier/cost details belong to the existing role-specific order readers. Internal receipt confirmation keys are never exposed.
    return deepcopy(result)

def list_receipts(state, role, *, order_id=None) -> list[dict]:
    """Return recorded receipts, optionally limited to one known order."""
    role = _reader_role(role)
    
    if order_id is not None:
        order, _=_linked_order(state, order_id)
        order_id = order.order_id
        
    selected = [
        receipt
        for receipt in state.receipts.values()
        if order_id is None or receipt.order_id == order_id
    ]
    
    selected.sort(
        key=lambda receipt: (
            receipt.received_time,
            receipt.receipt_id,
        )
    )
    
    return [
        get_receipt_details(state, receipt.receipt_id, role)
        for receipt in selected
    ]
    
    