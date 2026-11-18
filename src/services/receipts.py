"""Pure synthetic receipts against existing orders.

Preview does not create records. Confirmation publishes inventory,
receipt, order and linked-request changes as one new state.
"""

from copy import deepcopy
from dataclasses import replace
from numbers import Integral
import re

from src.services import orders
from src.services import workflow as wf
from src.services.workflow_models import (
    OrderStatus,
    ReceiptInput,
    ReceiptRecord,
    RequestStatus,
    Role,
    WorkflowError,
    WorkflowResult,
)

def _quantity(value):
    try:
        quantity = wf._quantity(value)
        wf._number(quantity, "Receipt quantity", "invalid_quantity")
    except WorkflowError as error:
        raise WorkflowError("invalid_quantity", "Enter a finite positive whole-number receipt quantity.") from error
    return quantity

def parse_receipt_quantity(text):
    """Reject invalid UI entries without rounding or defaulting to one."""
    if not isinstance(text, str):
        raise WorkflowError("invalid_quantity", "Enter a positive whole-number receipt quantity.")
    cleaned = text.strip()
    if not re.fullmatch(r"[0-9]+", cleaned):
        raise WorkflowError("invalid_quantity", "Enter a positive whole-number receipt quantity.")
    try:
        quantity = int(cleaned)
    except ValueError as error:
        raise WorkflowError("invalid_quantity", "Receipt quantity is outside the supported numeric range.") from error
    return _quantity(quantity)

def _prepare_receipt(state, order_id, inputs, context):
    stamp = wf._check_context(state, context, Role.WAREHOUSE)
    order_id = wf._text(order_id, "Order ID", "unknown_order")
    order = state.orders.get(order_id)
    
    if order is None:
        raise WorkflowError("unknown_order", "The order does not exist.")
    if order.run_id != state.run_id or order.order_id != order_id:
        raise WorkflowError("invalid_state", "Order identity is inconsistent.")
    if order.status not in orders.OPEN_ORDER_STATUSES:
        raise WorkflowError("invalid_transition", "Only Ordered or Partially received orders accept receipts.")
    
    request = wf._request(state, order.linked_request_id)
    
    if (order_id not in request.order_ids or order.medication_id != request.medication_id or order.unit != request.unit):
        raise WorkflowError("invalid_state", "Order and request links are inconsistent.")
    
    if stamp < order.updated_time or stamp < request.updated_time:
        raise WorkflowError("invalid_time", "Receipt time precedes the latest linked update.")
    
    allowed_request_statuses = {
        RequestStatus.ON_ORDER,
        RequestStatus.SUPPLY_RECEIVED,
        RequestStatus.UNDER_REVIEW,
        RequestStatus.APPROVED_FOR_RELEASE,
        RequestStatus.FULFILLED,
        RequestStatus.CLOSED,
    }
    if request.status not in allowed_request_statuses:
        raise WorkflowError("invalid_state", "The linked request is inconsistent with an open order.")
    if not isinstance(inputs, ReceiptInput):
        raise WorkflowError("invalid_input", "Use valid receipt inputs.")
    
    ordered = _quantity(order.ordered_quantity)
    received = order.quantity_received
    
    if (isinstance(received, bool) or not isinstance(received, Integral) or received < 0 or received >= ordered):
        raise WorkflowError("invalid_state", "The order's received quantity is inconsistent.")
    if (order.status == OrderStatus.ORDERED and received != 0) or (order.status == OrderStatus.PARTIALLY_RECEIVED and received == 0):
        raise WorkflowError("invalid_state", "The order status does not match its receipt progress.")
    
    # Recorded progress must agree with immutable posted receipts.
    posted_quantity = 0
    for receipt_id, receipt in state.receipts.items():
        if receipt.order_id != order_id:
            continue
        if (
            receipt.receipt_id != receipt_id
            or receipt.run_id != state.run_id
            or receipt.linked_request_id != request.request_id
            or receipt.medication_id != order.medication_id
            or receipt.unit != order.unit
            or receipt.status != "posted"
            or receipt.inventory_added is not True
        ):
            raise WorkflowError("invalid_state", "Existing receipt links are inconsistent.")
        
        posted_quantity += _quantity(receipt.received_quantity)
        
    if posted_quantity != received:
        raise WorkflowError("invalid_state", "Order progress does not match posted receipts.")
    
    quantity = _quantity(inputs.quantity)
    outstanding = ordered - received
    
    if quantity > outstanding:
        raise WorkflowError("over_receipt", "Receipt quantity exceeds the latest outstanding quantity.")
    
    row, requested, unit, stock = wf._available(state, request)
    receipt_unit = wf._text(inputs.unit, "Receipt unit", "invalid_unit")
    
    if receipt_unit != unit or receipt_unit != order.unit:
        raise WorkflowError("invalid_unit", "Receipt unit must match the order and current stock unit.")
    
    stock_after = stock + quantity
    wf._number(stock_after, "Updated stock", "invalid_stock")
    
    if stock_after <= stock or stock_after - stock != quantity:
        raise WorkflowError("invalid_stock", "The receipt cannot be added accurately within the numeric range.")
    
    inventory = state.inventory.copy(deep=True)
    target = inventory["medication_id"].eq(row["medication_id"])
    
    try:
        inventory.loc[target, "current_stock"] = stock_after
        inventory.loc[target, "status"] = ("In stock" if stock_after > 0 else "Out of stock")
    except (TypeError, ValueError, OverflowError) as error:
        raise WorkflowError("invalid_stock", "Updated stock is outside the inventory field's supported range.") from error
    
    stored_stock = wf._number(inventory.loc[target, "current_stock"].iloc[0], "Updated stock", "invalid_stock")
    if stored_stock != stock_after:
        raise WorkflowError("invalid_stock", "The inventory field cannot preserve the receipt quantity.")
    
    received_after = int(received) + quantity
    outstanding_after = ordered - received_after
    order_status = (
        OrderStatus.RECEIVED
        if outstanding_after == 0 else OrderStatus.PARTIALLY_RECEIVED
    )
    
    request_status = request.status
    if (request.status == RequestStatus.ON_ORDER and (stock_after >= requested or order_status == OrderStatus.RECEIVED)):
        request_status = RequestStatus.SUPPLY_RECEIVED
        
    preview = {
        "order_id": order_id,
        "linked_request_id": request.request_id,
        "medication_id": order.medication_id,
        "medication_name": order.medication_name,
        "unit": unit,
        "received_quantity": quantity,
        "stock_before": stock,
        "stock_after": stock_after,
        "quantity_outstanding_before": outstanding,
        "quantity_received_after": received_after,
        "quantity_outstanding_after": outstanding_after,
        "order_status_after": str(order_status),
        "request_status_before": str(request.status),
        "request_status_after": str(request_status),
    }
    
    return preview, order, request, inventory, stamp

def preview_receipt(state, order_id, inputs, context):
    """Show the latest projected receipt effect without creating an ID."""
    preview, _, _, _, _ = _prepare_receipt(state, order_id, inputs, context)
    return deepcopy(preview)

def confirm_receipt(state, order_id, inputs, receipt_key, context):
    """Post one receipt and its related changes atomically."""
    wf._check_context(state, context, Role.WAREHOUSE)
    receipt_key = wf._text(receipt_key, "Receipt confirmation key")
     
    if any(
        receipt.receipt_key == receipt_key
        for receipt in state.receipts.values()
    ):
        raise WorkflowError("duplicate_action", "This receipt confirmation key has already been used.")
     
    preview, order, request, inventory, stamp = _prepare_receipt(state, order_id, inputs, context)
    receipt_id = f"RCV-{state.next_receipt_number:04d}"
     
    if receipt_id in state.receipts:
        raise WorkflowError("invalid_state", "The next receipt ID is already present.")
     
    receipt = ReceiptRecord(
        run_id=state.run_id,
        receipt_id=receipt_id,
        order_id=order.order_id,
        linked_request_id=request.request_id,
        medication_id=order.medication_id,
        unit=preview["unit"],
        received_quantity=preview["received_quantity"],
        stock_before=preview["stock_before"],
        stock_after=preview["stock_after"],
        received_time=stamp,
        receipt_key=receipt_key,
    )
     
    updated_order = orders._order_event(
        order,
        OrderStatus(preview["order_status_after"]),
        "post_receipt",
        f"Synthetic receipt {receipt_id} posted.",
        Role.WAREHOUSE,
        stamp,
        quantity_received=preview["quantity_received_after"],
    )
     
    # Request history exposes identifiers, not order/receipt quantities.
    updated_request = wf._event(
        request,
        RequestStatus(preview["request_status_after"]),
        "post_receipt",
        f"Synthetic receipt {receipt_id} posted against "
        f"{order.order_id}; no release authorization.",
        Role.SYSTEM,
        stamp,
    )
     
    candidate = deepcopy(state)
    updated_orders = dict(candidate.orders)
    updated_requests = dict(candidate.requests)
    updated_receipts = dict(candidate.receipts)
     
    updated_orders[order.order_id] = deepcopy(updated_order)
    updated_requests[request.request_id] = deepcopy(updated_request)
    updated_receipts[receipt_id] = deepcopy(receipt)
     
    candidate = replace(
        candidate,
        inventory=inventory.copy(deep=True),
        orders=updated_orders,
        requests=updated_requests,
        receipts=updated_receipts,
        next_receipt_number=state.next_receipt_number + 1,
        revision=state.revision + 1,
    )
     
    return WorkflowResult(
        state=candidate,
        request_id=request.request_id,
        changed=True,
        message=(
            f"Synthetic receipt {receipt_id} posted once against "
            f"{order.order_id}. No release authorization."
        ),
        order_id=order.order_id,
        receipt_id=receipt_id,
    )
    
    