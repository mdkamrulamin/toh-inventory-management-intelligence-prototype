"""Read-only reports for synthetic session orders and posted receipts."""

from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from src.services.order_queries import ORDER_STATUS_LABELS
from src.services.reporting import (
    SYNTHETIC_NOTICE,
    prepare_report_display,
)


TRANSACTION_REPORT_LABELS = {
    "session_orders": "Current-session synthetic orders",
    "session_receipts": "Current-session synthetic receipts",
}

TRANSACTION_REPORT_NOTES = {
    "session_orders": (
        "Synthetic orders from the active session, including completed "
        "and cancelled orders. Linked request statuses are current. "
        "Expected delivery dates are illustrative; creating an order "
        "does not add inventory."
    ),
    "session_receipts": (
        "Posted synthetic receipts from the active session. Stock before "
        "and after are recorded receipt observations. Linked order and "
        "request statuses are current. No physical shipment is verified."
    ),
}

TRANSACTION_COLUMNS = {
    "session_orders": (
        "run_id",
        "order_id",
        "linked_request_id",
        "medication_id",
        "medication_name",
        "order_status",
        "request_status",
        "ordered_quantity",
        "quantity_received",
        "quantity_outstanding",
        "unit",
        "order_date",
        "expected_delivery",
        "expected_delivery_note",
        "created_time",
        "updated_time",
        "provenance",
    ),
    "session_receipts": (
        "run_id",
        "receipt_id",
        "order_id",
        "linked_request_id",
        "medication_id",
        "medication_name",
        "receipt_status",
        "order_status",
        "request_status",
        "received_quantity",
        "unit",
        "stock_before",
        "stock_after",
        "received_time",
        "recorded_by",
        "recorded_by_role",
        "provenance",
    ),
}

DATE_FILTER_BASIS = {
    "session_orders": "Order date — calendar date",
    "session_receipts": "Receipt recorded date — UTC",
}


@dataclass(frozen=True)
class TransactionFilters:
    medication_ids: tuple[str, ...] = ()
    order_ids: tuple[str, ...] = ()
    request_ids: tuple[str, ...] = ()
    statuses: tuple[str, ...] = ()
    date_from: date | None = None
    date_to: date | None = None


def _validate_filters(filters: TransactionFilters, report_id: str) -> None:
    for value in (filters.date_from, filters.date_to):
        if value is not None and (not isinstance(value, date) or isinstance(value, datetime)):
            raise ValueError("Report date filters must use calendar dates.")

    if (
        filters.date_from is not None
        and filters.date_to is not None
        and filters.date_from > filters.date_to
    ):
        raise ValueError("Report start date must not be after the end date.")

    allowed_statuses = (
        set(ORDER_STATUS_LABELS)
        if report_id == "session_orders"
        else {"posted"}
    )

    if any(
        status not in allowed_statuses
        for status in filters.statuses
    ):
        raise ValueError("A selected status is not supported by this report.")


def _filter_scope(filters: TransactionFilters) -> str:
    def choices(values):
        return ", ".join(values) if values else "all"

    return (
        f"Medication IDs: {choices(filters.medication_ids)}; "
        f"Order IDs: {choices(filters.order_ids)}; "
        f"Request IDs: {choices(filters.request_ids)}; "
        f"Statuses: {choices(filters.statuses)}; "
        f"From: "
        f"{filters.date_from.isoformat() if filters.date_from else 'unbounded'}; "
        f"To: "
        f"{filters.date_to.isoformat() if filters.date_to else 'unbounded'}"
    )


def build_transaction_report(
    records: list[dict],
    report_id: str,
    *,
    filters: TransactionFilters | None = None,
) -> pd.DataFrame:
    """Prepare a detached report from explicit Reporting projections.

    Orders are filtered by their recorded order date.
    Receipts are filtered by their recorded receipt timestamp's UTC date.
    Date bounds are inclusive. Unavailable dates do not match date bounds.
    """
    if report_id not in TRANSACTION_COLUMNS:
        raise ValueError("Unsupported transaction report.")

    filters = filters or TransactionFilters()
    _validate_filters(filters, report_id)

    columns = TRANSACTION_COLUMNS[report_id]

    # Whitelist fields rather than exporting an unrestricted dictionary.
    # Explicit columns preserve headers when there are no records.
    report = pd.DataFrame(
        [
            {
                column: record.get(column)
                for column in columns
            }
            for record in records
        ],
        columns=columns,
    )

    status_column = (
        "order_status"
        if report_id == "session_orders"
        else "receipt_status"
    )

    for column, selected in (
        ("medication_id", filters.medication_ids),
        ("order_id", filters.order_ids),
        ("linked_request_id", filters.request_ids),
        (status_column, filters.statuses),
    ):
        if selected:
            report = report.loc[
                report[column].isin(selected)
            ].copy()

    if (
        filters.date_from is not None
        or filters.date_to is not None
    ):
        date_column = (
            "order_date"
            if report_id == "session_orders"
            else "received_time"
        )

        dates = pd.to_datetime(
            report[date_column],
            format="ISO8601",
            errors="coerce",
            utc=True,
        ).dt.normalize()

        mask = dates.notna()

        if filters.date_from is not None:
            mask = mask & dates.ge(
                pd.Timestamp(filters.date_from, tz="UTC")
            )

        if filters.date_to is not None:
            mask = mask & dates.le(
                pd.Timestamp(filters.date_to, tz="UTC")
            )

        report = report.loc[mask].copy()

    report["report_name"] = TRANSACTION_REPORT_LABELS[report_id]
    report["synthetic_data_notice"] = SYNTHETIC_NOTICE
    report["report_note"] = TRANSACTION_REPORT_NOTES[report_id]
    report["date_filter_basis"] = DATE_FILTER_BASIS[report_id]
    report["report_scope"] = _filter_scope(filters)

    return report.reset_index(drop=True)


def prepare_transaction_report_display(
    report: pd.DataFrame,
) -> pd.DataFrame:
    """Reuse existing display preparation for the native table exporter."""
    display = prepare_report_display(report)

    if "order_status" in display.columns:
        display["order_status"] = display["order_status"].map(
            lambda value: ORDER_STATUS_LABELS.get(value, value)
        )

    if "receipt_status" in display.columns:
        display["receipt_status"] = display["receipt_status"].map(
            lambda value: (
                "Posted" if value == "posted" else value
            )
        )

    return display