"""Pure synthetic order operations.

Preview creates no business records. Confirmation, delivery-date updates
and cancellation return a new state without changing inventory.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal, DecimalException, localcontext
import re
from sys import float_info

from src.services import workflow as wf
from src.services.analytics import build_stock_analytics
from src.services.workflow_models import (
    CreateOrderInput,
    OrderEvent,
    OrderStatus,
    RequestStatus,
    Role,
    SyntheticOrder,
    WorkflowError,
    WorkflowResult,
)

OPEN_ORDER_STATUSES = {
    OrderStatus.ORDERED,
    OrderStatus.PARTIALLY_RECEIVED,
}

def _quantity(value) -> int:
    try:
        quantity = wf._quantity(value)
        wf._number(quantity, "Order quantity", "invalid_quantity")
    except WorkflowError as error:
        raise WorkflowError("invalid_quantity", "Enter a finite positive whole-number order quantity.") from error
    return quantity

def parse_order_quantity(text: str) -> int:
    """Validate UI text without rounding or silently substituting one."""
    if not isinstance(text, str):
        raise WorkflowError("invalid_quantity", "Enter a positive whole-number order quantity.")
    cleaned = text.strip()
    if not re.fullmatch(r"[0-9]+", cleaned):
        raise WorkflowError("invalid_quantity", "Enter a positive whole-number order quantity.")
    
    try:
        value = int(cleaned)
    except ValueError as error:
        raise WorkflowError("invalid_quantity", "The order quantity is outside the supported numeric range.") from error
    return _quantity(value)

def _open_orders(state, request_id):
    return tuple(
        order
        for order in state.orders.values()
        if order.linked_request_id == request_id and order.status in OPEN_ORDER_STATUSES
    )

def _calendar_date(value, order_date):
    if value is None:
        return None
    if not isinstance(value, date) or isinstance(value, datetime):
        raise WorkflowError("invalid_order_date", "Expected delivery must be a calendar date.")
    if value < order_date:
        raise WorkflowError("invalid_order_date", "Expected delivery cannot predate the order date.")
    return value.isoformat()

def _default_delivery(order_date, lead):
    if lead is None or not float(lead).is_integer():
        return None
    try:
        return (order_date + timedelta(days=int(lead))).isoformat()
    except (OverflowError, ValueError):
        return None
    
def _order_value(quantity, cost):
    if cost is None:
        return None, "N/A: supplied unit cost is unavailable."
    
    try:
        with localcontext() as context:
            context.prec = 64
            value = Decimal(quantity) * Decimal(str(cost))
            
        if (not value.is_finite() or value > Decimal(str(float_info.max))):
            return None, "N/A: order value exceeds the finite numeric range."
    
    except (DecimalException, OverflowError):
        return None, "N/A: order value exceeds the finite numeric range."
    
    note = (
        "Supplied unit cost is zero."
        if cost == 0 else "Synthetic ordered quantity multiplied by supplied CAD unit cost."
    )
    return value, note

def preview_order(state, request_id, inputs, context) -> dict:
    """Return Procurement-only order context without creating an ID."""
    request, stamp = wf._prepare(state, request_id, context, Role.PROCUREMENT, {RequestStatus.AWAITING_SUPPLY})
    
    if request.outcome is not None:
        raise WorkflowError("invalid_transition", "A completed request cannot create an order.")
    if _open_orders(state, request_id):
        raise WorkflowError("open_order_exists", "This request already has an open simulated order.")
    if not isinstance(inputs, CreateOrderInput):
        raise WorkflowError("invalid_input", "Use valid order inputs.")
    
    row, requested, unit, stock = wf._available(state, request)
    quantity = _quantity(inputs.quantity)
    supplied_unit = wf._text(inputs.unit, "Order unit", "invalid_unit")
    
    if supplied_unit != unit:
        raise WorkflowError("invalid_unit", "Order unit must match the request and recorded stock unit.")
    supplier_value = row.get("supplier")
    supplier = (
        supplier_value.strip() or None
        if isinstance(supplier_value, str) else None
    )
    cost = wf._optional_number(row, "unit_cost")
    lead = wf._optional_number(row, "lead_time_days")
    order_date = datetime.fromisoformat(stamp).date()
    default_delivery = _default_delivery(order_date, lead)
    expected = default_delivery
    delivery_reason = ""
    delivery_note = (
        "Illustrative order date plus suppled whole-day lead time."
        if expected is not None else "N/A: a supported supplied whole-day lead time is unavailable."
    )
    
    if inputs.expected_delivery is not None:
        expected = _calendar_date(inputs.expected_delivery, order_date)
        if expected != default_delivery:
            delivery_reason = wf._reason(inputs.expected_delivery_reason)
            delivery_note = "Humer-entered illustrative expected date."
            
    value, value_note = _order_value(quantity, cost)
    shortfall = max(requested - stock, 0)
    
    analytics = build_stock_analytics(state.inventory).rows.set_index("medication_id")
    current = analytics.loc[request.medication_id]
    
    other_orders = [
        order.order_id
        for order in state.orders.values()
        if order.medication_id == request.medication_id
        and order.linked_request_id != request_id
        and order.status in OPEN_ORDER_STATUSES
    ]
    
    warnings = []
    if quantity < shortfall:
        warnings.append("The entered order quantity is below the current request shortfall.")
    if other_orders:
        warnings.append(
            "Other open orders exist for this medication: "
            + ", ".join(other_orders)
            + ". No consolidation is performed."
        )
    return {
        "linked_request_id": request_id,
        "medication_id": request.medication_id,
        "medication_name": request.medication_name,
        "quantity": quantity,
        "unit": unit,
        "supplier": supplier,
        "unit_cost": cost,
        "order_value_cad": value,
        "order_value_note": value_note,
        "lead_time_days": lead,
        "order_date": order_date.isoformat(),
        "expected_delivery": expected,
        "expected_delivery_reason": delivery_reason,
        "expected_delivery_note": delivery_note,
        "recorded_stock": stock,
        "current_shortfall": shortfall,
        "reorder_gap": current["reorder_gap"],
        "lead_time_demand": current["lead_time_demand"],
        "warnings": warnings,
    }
    
def _publish_order(state, order, request, message, *, new_order=False):
    """Publish order and request changes together in a detached candidate."""
    candidate = deepcopy(state)
    orders = dict(candidate.orders)
    requests = dict(candidate.requests)
    
    orders[order.order_id] = deepcopy(order)
    requests[request.request_id] = deepcopy(request)
    
    candidate = replace(
        candidate,
        orders=orders,
        requests=requests,
        revision=state.revision + 1,
        next_order_number=(
            state.next_order_number + 1
            if new_order else state.next_order_number
        ),
    )
    
    return WorkflowResult(
        state=candidate,
        request_id=request.request_id,
        changed=True,
        message=message,
        order_id=order.order_id,
    )
    
def confirm_order(state, request_id, inputs, order_key, context):
    """Create one linked order; never add or reserve inventory."""
    stamp = wf._check_context(state, context, Role.PROCUREMENT)
    order_key = wf._text(order_key, "Order confirmation key")
    
    if any(
        order.order_key == order_key
        for order in state.orders.values()
    ):
        raise WorkflowError("duplicate_action", "This order confirmation key has already been used.")
    
    preview = preview_order(state, request_id, inputs, context)
    request = wf._request(state, request_id)
    order_id = f"PO-{state.next_order_number:04d}"
    
    if order_id in state.orders:
        raise WorkflowError("invalid_state", "The next order ID is already present.")
    reason = (preview["expected_delivery_reason"] or "Synthetic order confirmed.")
    event = OrderEvent(
        sequence=1,
        action="confirm_order",
        from_status=None,
        to_status=OrderStatus.ORDERED,
        reason=reason,
        actor_role=Role.PROCUREMENT,
        actor_name="Demo user",
        timestamp=stamp,
        expected_delivery_after=preview["expected_delivery"],
    )
    order = SyntheticOrder(
        run_id=state.run_id,
        order_id=order_id,
        linked_request_id=request_id,
        medication_id=request.medication_id,
        medication_name=request.medication_name,
        unit=preview["unit"],
        ordered_quantity=preview["quantity"],
        supplier=preview["supplier"],
        unit_cost=preview["unit_cost"],
        order_value_cad=preview["order_value_cad"],
        order_value_note=preview["order_value_note"],
        lead_time_days=preview["lead_time_days"],
        order_date=preview["order_date"],
        expected_delivery=preview["expected_delivery"],
        expected_delivery_note=preview["expected_delivery_note"],
        status=OrderStatus.ORDERED,
        status_reason=reason,
        created_time=stamp,
        updated_time=stamp,
        order_key=order_key,
        order_history=(event,),
    )
    
    # Keep commercial details/reasons out of shared request-history text.
    updated_request = wf._event(
        request,
        RequestStatus.ON_ORDER,
        "confirm_order",
        f"Simulated order {order_id} confirmed; no stock change.",
        Role.PROCUREMENT,
        stamp,
        order_ids=(*request.order_ids, order_id),
    )
    
    return _publish_order(
        state,
        order,
        updated_request,
        f"{order_id} recorded. No supplier transmission or stock change.",
        new_order=True,
    )
    
def _existing_order(state, order_id, context):
    stamp = wf._check_context(state, context, Role.PROCUREMENT)
    order_id = wf._text(order_id, "Order ID", "unknown_order")
    order = state.orders.get(order_id)
    
    if order is None:
        raise WorkflowError("unknown_order", "The order does not exist.")
    if order.run_id != state.run_id or order.order_id != order_id:
        raise WorkflowError("invalid_state", "Order identity is inconsistent.")
    
    request = wf._request(state, order.linked_request_id)
    
    if stamp < order.updated_time or stamp < request.updated_time:
        raise WorkflowError("invalid_time", "Action time precedes the latest linked update.")
    return order, request, stamp

def _order_event(order, status, action, reason, role, stamp, **changes):
    event = OrderEvent(
        sequence=len(order.order_history) + 1,
        action=action,
        from_status=order.status,
        to_status=status,
        reason=reason,
        actor_role=role,
        actor_name="Demo user",
        timestamp=stamp,
        expected_delivery_before=order.expected_delivery,
        expected_delivery_after=changes.get("expected_delivery", order.expected_delivery),
    )
    return replace(order, status=status, status_reason=reason, updated_time=stamp, order_history=(*order.order_history, event), **changes)

def update_order_delivery(state, order_id, expected_delivery, reason, context):
    """Change an open order's illustrative date with a recorded reason."""
    order, request, stamp = _existing_order(state, order_id, context)
    if order.status not in OPEN_ORDER_STATUSES:
        raise WorkflowError("invalid_transition", "Only open orders can change expected delivery.")
    reason = wf._reason(reason)
    expected = _calendar_date(expected_delivery, date.fromisoformat(order.order_date))
    if expected == order.expected_delivery:
        raise WorkflowError("duplicate_action", "The illustrative expected date is unchanged.")
    updated_order = _order_event(
        order,
        order.status,
        "update_order_delivery",
        reason, 
        Role.PROCUREMENT,
        stamp,
        expected_delivery=expected,
        expected_delivery_note=(
            "Human-updated illustrative expected date."
            if expected is not None else "N/A: illustrative expected date cleared with a reason."
        )
    )
    updated_request = wf._event(
        request,
        request.status,
        "update_order_delivery",
        f"Illustrative expected delivery updated for {order.order_id}.",
        Role.PROCUREMENT,
        stamp,
    )
    return _publish_order(
        state,
        updated_order,
        updated_request,
        f"Illustrative expected delivery updated for {order.order_id}.",
    )
    
def cancel_order(state, order_id, reason, context):
    """Cancel before any receipt; never reopen a closed request."""
    order, request, stamp = _existing_order(state, order_id, context)
    if (order.status != OrderStatus.ORDERED or order.quantity_received != 0):
        raise WorkflowError("invalid_transition", "Cancellation requires an Ordered order with no receipts.")
    
    reason = wf._reason(reason)
    updated_order = _order_event(
        order,
        OrderStatus.CANCELLED,
        "cancel_order",
        reason,
        Role.PROCUREMENT,
        stamp,
    )
    target_status = (
        RequestStatus.AWAITING_SUPPLY
        if request.status == RequestStatus.ON_ORDER else request.status
    )
    updated_request = wf._event(
        request,
        target_status,
        "cancel_order",
        f"Simulated order {order.order_id} cancelled; no stock change.",
        Role.PROCUREMENT,
        stamp,
    )
    return _publish_order(
        state,
        updated_order,
        updated_request,
        f"{order.order_id} cancelled. Stock is unchanged.",
    )