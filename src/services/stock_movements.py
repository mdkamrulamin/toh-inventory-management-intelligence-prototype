"""Read-only stock movements from canonical synthetic transactions."""

import pandas as pd

from src.services import workflow as wf
from src.services.receipt_queries import list_receipts
from src.services.workflow_models import (
    DemoState,
    RequestOutcome,
    Role,
    WorkflowError,
)


MOVEMENT_COLUMNS = (
    "run_id",
    "movement_id",
    "movement_type",
    "receipt_id",
    "fulfillment_id",
    "order_id",
    "linked_request_id",
    "medication_id",
    "medication_name",
    "quantity_change",
    "stock_unit",
    "stock_before",
    "stock_after",
    "recorded_time",
    "recorded_by",
    "recorded_by_role",
    "provenance",
)


def get_stock_movements(state: DemoState, role: Role | str) -> pd.DataFrame:
    """Return one row per posted receipt or recorded fulfillment.

    Request status events are not movements. In particular, Fulfilled
    and Closed events refer to one canonical fulfillment record.

    Before/after stock values remain observations at transaction time.
    They are never replaced by the latest inventory balance.
    """
    try:
        role = Role(role)
    except (ValueError, TypeError) as error:
        raise WorkflowError("wrong_role", "Unknown stock-movement reader role.") from error

    if role != Role.WAREHOUSE:
        raise WorkflowError("wrong_role", "This stock-movement projection is for Warehouse.")

    rows = []

    # Reuse the validated, non-commercial Warehouse receipt projection.
    for receipt in list_receipts(state, Role.WAREHOUSE):
        rows.append(
            {
                "run_id": receipt["run_id"],
                "movement_id": receipt["receipt_id"],
                "movement_type": "receipt",
                "receipt_id": receipt["receipt_id"],
                "fulfillment_id": None,
                "order_id": receipt["order_id"],
                "linked_request_id": receipt["linked_request_id"],
                "medication_id": receipt["medication_id"],
                "medication_name": receipt["medication_name"],
                "quantity_change": receipt["received_quantity"],
                "stock_unit": receipt["unit"],
                "stock_before": receipt["stock_before"],
                "stock_after": receipt["stock_after"],
                "recorded_time": receipt["received_time"],
                "recorded_by": receipt["recorded_by"],
                "recorded_by_role": receipt["recorded_by_role"],
                "provenance": receipt["provenance"],
            }
        )

    for request_id in state.requests:
        request = wf._request(state, request_id)
        fulfillment = request.fulfillment

        if fulfillment is None:
            continue

        if (
            fulfillment.medication_id != request.medication_id
            or fulfillment.unit != request.unit
            or fulfillment.quantity != request.quantity
            or request.outcome != RequestOutcome.FULFILLED
        ):
            raise WorkflowError("invalid_state", "The fulfillment and request records are inconsistent.")

        rows.append(
            {
                "run_id": state.run_id,
                "movement_id": fulfillment.fulfillment_id,
                "movement_type": "fulfillment",
                "receipt_id": None,
                "fulfillment_id": fulfillment.fulfillment_id,
                # Fulfillment belongs to the request. It is not
                # attributed to an arbitrary linked purchase order.
                "order_id": None,
                "linked_request_id": request.request_id,
                "medication_id": fulfillment.medication_id,
                "medication_name": request.medication_name,
                "quantity_change": -fulfillment.quantity,
                "stock_unit": fulfillment.unit,
                "stock_before": fulfillment.stock_before,
                "stock_after": fulfillment.stock_after,
                "recorded_time": fulfillment.fulfilled_time,
                "recorded_by": fulfillment.fulfilled_by,
                "recorded_by_role": str(fulfillment.fulfilled_by_role),
                "provenance": (
                    "Synthetic demonstration fulfillment. "
                    "No physical dispatch is verified."
                ),
            }
        )

    movements = pd.DataFrame(rows, columns=MOVEMENT_COLUMNS)

    if movements.empty:
        return movements

    if movements.duplicated(subset=["run_id", "movement_type", "movement_id"]).any():
        raise WorkflowError("invalid_state", "A stock transaction has a duplicate movement identity.")

    # Tie-breaking provides a stable display, not an inferred
    # execution sequence for actions with identical timestamps.
    return movements.sort_values(
        ["recorded_time", "movement_type", "movement_id"],
        kind="stable",
    ).reset_index(drop=True)