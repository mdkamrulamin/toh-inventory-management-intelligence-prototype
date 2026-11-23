"""Read-only Reporting dashboard for the active synthetic session."""

from numbers import Real

import pandas as pd
import streamlit as st

from src.config import FIELD_LABELS
from src.services.reporting import (
    REPORT_LABELS,
    REPORT_NOTES,
    REVIEW_LABELS,
    InventoryFilters,
    RequestFilters,
    build_inventory_report,
    build_request_report,
    build_request_summary,
    filter_inventory,
    inventory_filter_options,
    prepare_report_display,
)
from src.services.workflow_models import (
    RequestOutcome,
    RequestStatus,
    Role,
    Urgency,
)
from src.ui.components import render_medication_table
from src.ui.session import (
    read_demo_reference_date,
    read_orders,
    read_receipts,
    read_request_summary,
    read_requests,
)
from src.ui.workflow_components import (
    OUTCOME_LABELS,
    render_workflow_table,
    status_label,
)
from src.services.order_queries import ORDER_STATUS_LABELS
from src.services.transaction_reports import (
    DATE_FILTER_BASIS,
    TRANSACTION_REPORT_LABELS,
    TRANSACTION_REPORT_NOTES,
    TransactionFilters,
    build_transaction_report,
    prepare_transaction_report_display,
)


FILTER_KEYS = {
    "medication_ids": "workflow_ui_reporting_medications",
    "suppliers": "workflow_ui_reporting_suppliers",
    "stock_statuses": "workflow_ui_reporting_stock_statuses",
    "categories": "workflow_ui_reporting_categories",
    "ordering_reviews": "workflow_ui_reporting_reviews",
    "expiry_from": "workflow_ui_reporting_expiry_from",
    "expiry_to": "workflow_ui_reporting_expiry_to",
    "request_statuses": "workflow_ui_reporting_request_statuses",
    "request_urgencies": "workflow_ui_reporting_request_urgencies",
    "request_outcomes": "workflow_ui_reporting_request_outcomes",
}

VIEW_REPORT_LABELS = {
    **REPORT_LABELS,
    **TRANSACTION_REPORT_LABELS,
}

VIEW_REPORT_NOTES = {
    **REPORT_NOTES,
    **TRANSACTION_REPORT_NOTES,
}

# Separate keys prevent order and receipt filters from interfering
# with each other or with the existing inventory/request filters.
TRANSACTION_FILTER_KEYS = {
    report_id: {
        field: f"workflow_ui_reporting_{report_id}_{field}"
        for field in (
            "medication_ids",
            "order_ids",
            "request_ids",
            "statuses",
            "date_from",
            "date_to",
        )
    }
    for report_id in TRANSACTION_REPORT_LABELS
}

TRANSACTION_FIELD_LABELS = {
    "order_id": "Order ID",
    "receipt_id": "Receipt ID",
    "linked_request_id": "Linked request ID",
    "order_status": "Order status",
    "request_status": "Current linked request status",
    "receipt_status": "Receipt status",
    "ordered_quantity": "Ordered quantity",
    "quantity_received": "Total received quantity",
    "quantity_outstanding": "Outstanding quantity",
    "received_quantity": "Receipt quantity",
    "unit": "Stock unit",
    "order_date": "Recorded order date",
    "expected_delivery": "Illustrative expected delivery",
    "expected_delivery_note": "Expected delivery context",
    "created_time": "Order created time (UTC)",
    "updated_time": "Order updated time (UTC)",
    "received_time": "Receipt recorded time (UTC)",
    "stock_before": "Recorded stock before receipt",
    "stock_after": "Recorded stock after receipt",
    "recorded_by": "Demo actor",
    "recorded_by_role": "Demo actor role",
    "provenance": "Record provenance",
    "date_filter_basis": "Date filter basis",
    "report_scope": "Applied report filters",
}


def _clear_report_filters() -> None:
    """Clear presentation inputs without changing inventory or requests."""
    for name, key in FILTER_KEYS.items():
        st.session_state[key] = (
            None
            if name in {"expiry_from", "expiry_to"}
            else []
        )
        
    for keys in TRANSACTION_FILTER_KEYS.values():
        for name, key in keys.items():
            st.session_state[key] = (
                None
                if name in {"date_from", "date_to"}
                else []
            )


def _choice_label(value: str | None) -> str:
    return "Unavailable" if value is None else value


def _inventory_filters(medications: pd.DataFrame, *, disabled: bool = False) -> InventoryFilters:
    """Keep filter choices independent of the current filtered result."""
    options = inventory_filter_options(medications)
    medication_labels = (medications.set_index("medication_id")["medication_name"].to_dict())

    with st.expander("Inventory filters", expanded=not disabled):
        if disabled:
            st.caption(
                "Inactive for this whole-population or whole-session report. Stored inventory filters are not applied."
            )
        else:
            st.caption(
                "Empty selections mean all values. Filters apply to current inventory, not historical hospital activity."
            )

        medication_column, supplier_column, status_column = st.columns(3)

        with medication_column:
            medication_ids = st.multiselect(
                "Medication",
                options=options["medication_id"],
                key=FILTER_KEYS["medication_ids"],
                disabled=disabled,
                format_func=lambda medication_id: (
                    f"{medication_labels.get(medication_id, medication_id)} "
                    f"({medication_id})"
                ),
            )

        with supplier_column:
            suppliers = st.multiselect(
                "Demo supplier",
                options=options["supplier"],
                format_func=_choice_label,
                key=FILTER_KEYS["suppliers"],
                disabled=disabled,
            )

        with status_column:
            stock_statuses = st.multiselect(
                "Recorded availability",
                options=["In stock", "Out of stock"],
                key=FILTER_KEYS["stock_statuses"],
                disabled=disabled,
            )

        category_column, review_column = st.columns(2)

        with category_column:
            categories = st.multiselect(
                "Dosage form",
                options=options["category"],
                format_func=_choice_label,
                key=FILTER_KEYS["categories"],
                disabled=disabled,
            )

        with review_column:
            # Stable options preserve a selected classification even
            # when fulfillment leaves no records in that classification.
            ordering_reviews = st.multiselect(
                "Inventory threshold review",
                options=list(REVIEW_LABELS),
                key=FILTER_KEYS["ordering_reviews"],
                disabled=disabled,
            )

        start_column, end_column = st.columns(2)

        with start_column:
            expiry_from = st.date_input(
                "Expiry on or after — optional",
                value=None,
                key=FILTER_KEYS["expiry_from"],
                disabled=disabled,
            )

        with end_column:
            expiry_to = st.date_input(
                "Expiry on or before — optional",
                value=None,
                key=FILTER_KEYS["expiry_to"],
                disabled=disabled,
            )

        st.caption(
            "Expiry bounds are inclusive. Records without an expiry "
            "date are excluded when a date bound is applied. "
            "These filters do not refer to request submission dates."
        )

    return InventoryFilters(
        medication_ids=tuple(medication_ids),
        suppliers=tuple(suppliers),
        stock_statuses=tuple(stock_statuses),
        categories=tuple(categories),
        ordering_reviews=tuple(ordering_reviews),
        expiry_from=expiry_from,
        expiry_to=expiry_to,
    )


def _request_filters() -> RequestFilters:
    """Filter current request states separately from retained outcomes."""
    st.caption(
        "Inventory filters above select medications. These additional filters select their session requests."
    )

    status_column, urgency_column, outcome_column = st.columns(3)

    with status_column:
        statuses = st.multiselect(
            "Request status",
            options=[status.value for status in RequestStatus],
            format_func=status_label,
            key=FILTER_KEYS["request_statuses"],
        )

    with urgency_column:
        urgencies = st.multiselect(
            "Demo urgency",
            options=[urgency.value for urgency in Urgency],
            format_func=str.capitalize,
            key=FILTER_KEYS["request_urgencies"],
        )

    with outcome_column:
        outcomes = st.multiselect(
            "Request outcome",
            options=[
                None,
                *[outcome.value for outcome in RequestOutcome],
            ],
            format_func=lambda outcome: (
                "No final outcome"
                if outcome is None
                else OUTCOME_LABELS[outcome]
            ),
            key=FILTER_KEYS["request_outcomes"],
        )

    st.caption(
        "Successful synthetic fulfillment closes the request while retaining its fulfilled outcome. Closed does not always mean fulfilled."
    )

    return RequestFilters(
        statuses=tuple(statuses),
        urgencies=tuple(urgencies),
        outcomes=tuple(outcomes),
    )

def _transaction_filters(records: list[dict], medications: pd.DataFrame, report_id: str) -> TransactionFilters:
    """Filter session transactions independently of inventory filters."""
    keys = TRANSACTION_FILTER_KEYS[report_id]
    medication_labels = (medications.set_index("medication_id")["medication_name"].to_dict())

    def choose(field, label, options, format_func=str):
        # Remove stale choices before creating the widget.
        current = list(st.session_state.get(keys[field], []))
        retained = [
            value for value in current
            if value in options
        ]

        if retained != current:
            st.session_state[keys[field]] = retained

        return st.multiselect(
            label,
            options=options,
            format_func=format_func,
            key=keys[field],
        )

    with st.expander("Transaction filters", expanded=True):
        st.caption(
            "Empty selections mean all values. These filters apply "
            "to recorded transactions in the active demo session."
        )

        medication_column, order_column, request_column = st.columns(3)

        with medication_column:
            medication_ids = choose(
                "medication_ids",
                "Medication",
                sorted(medication_labels),
                format_func=lambda medication_id: (
                    f"{medication_labels[medication_id]} "
                    f"({medication_id})"
                ),
            )

        with order_column:
            order_ids = choose(
                "order_ids",
                "Order ID",
                sorted({
                    record["order_id"]
                    for record in records
                }),
            )

        with request_column:
            request_ids = choose(
                "request_ids",
                "Linked request ID",
                sorted({
                    record["linked_request_id"]
                    for record in records
                }),
            )

        if report_id == "session_orders":
            statuses = choose(
                "statuses",
                "Order status",
                list(ORDER_STATUS_LABELS),
                format_func=ORDER_STATUS_LABELS.__getitem__,
            )
            date_label = "Order date"
        else:
            statuses = choose(
                "statuses",
                "Receipt status",
                ["posted"],
                format_func=lambda value: "Posted",
            )
            date_label = "Receipt recorded date (UTC)"

        start_column, end_column = st.columns(2)

        with start_column:
            date_from = st.date_input(
                f"{date_label} on or after — optional",
                value=None,
                key=keys["date_from"],
            )

        with end_column:
            date_to = st.date_input(
                f"{date_label} on or before — optional",
                value=None,
                key=keys["date_to"],
            )

        st.caption(
            f"Date basis: {DATE_FILTER_BASIS[report_id]}. "
            "Bounds are inclusive. Records without the relevant "
            "date are excluded when a date bound is applied."
        )

    return TransactionFilters(
        medication_ids=tuple(medication_ids),
        order_ids=tuple(order_ids),
        request_ids=tuple(request_ids),
        statuses=tuple(statuses),
        date_from=date_from,
        date_to=date_to,
    )

def _render_report_table(report: pd.DataFrame, report_id: str) -> None:
    """Use existing table components and their native CSV controls."""
    is_transaction = report_id in TRANSACTION_REPORT_LABELS

    display = (
        prepare_transaction_report_display(report)
        if is_transaction
        else prepare_report_display(report)
    )

    # Keep mixed numeric/N/A columns compatible with Arrow transport.
    for column in display.columns:
        values = display[column]
        has_text = values.map(lambda value: isinstance(value, str)).any()
        has_number = values.map(lambda value: isinstance(value, Real)).any()

        if has_text and has_number:
            display[column] = values.astype("string")

    if report.empty:
        st.info("No records match this report and its filters.")

    st.caption(VIEW_REPORT_NOTES[report_id])
    st.caption(
        f"Report rows: {len(report)}. "
        "Use the table toolbar to download the current report."
    )

    if is_transaction:
        labels = {
            **FIELD_LABELS,
            **TRANSACTION_FIELD_LABELS,
        }

        if report_id == "session_receipts":
            labels["order_status"] = "Current linked order status"

        st.subheader(VIEW_REPORT_LABELS[report_id])
        render_workflow_table(display.rename(columns=labels), table_key=f"reporting_{report_id}")

    elif report_id in {"inventory_summary", "request_statuses", "request_summary", "abc_summary"}:
        st.subheader(VIEW_REPORT_LABELS[report_id])
        render_workflow_table(display.rename(columns=FIELD_LABELS), table_key=f"reporting_{report_id}")

    else:
        render_medication_table(
            display,
            title=VIEW_REPORT_LABELS[report_id],
            export_key=f"reporting_{report_id}",
        )


def render_reporting_view(medications: pd.DataFrame) -> None:
    """Render supported reports from current shared-session readers."""
    st.write(
        "Select a report, filter its supported content and download "
        "the displayed report table."
    )
    st.caption(
        "Synthetic demonstration data based on project assumptions. "
        "Reporting is open demo navigation and does not enforce "
        "authenticated access restrictions."
    )

    report_id = st.selectbox(
        "Report",
        options=list(VIEW_REPORT_LABELS),
        format_func=VIEW_REPORT_LABELS.__getitem__,
        key="workflow_ui_reporting_report",
    )

    st.button(
        "Clear report filters",
        key="workflow_action_reporting_clear_filters",
        on_click=_clear_report_filters,
    )

    try:
        if report_id in TRANSACTION_REPORT_LABELS:
            records = (
                read_orders(Role.REPORTING)
                if report_id == "session_orders"
                else read_receipts(Role.REPORTING)
            )

            transaction_filters = _transaction_filters(
                records,
                medications,
                report_id,
            )

            report = build_transaction_report(
                records,
                report_id,
                filters=transaction_filters,
            )

            st.caption(
                "Scope: recorded transactions in the active demo "
                "session matching the transaction filters. "
                "Only transaction filters apply."
            )

        else:
            whole_session = report_id == "request_summary"
            whole_population = report_id == "abc_summary"

            inventory_filters = _inventory_filters(
                medications,
                disabled=whole_session or whole_population,
            )

            if whole_session:
                st.info(
                    "Scope: every request in the active demo session. "
                    "Inventory and request filters are not applied."
                )
                report = build_request_summary(
                    read_request_summary()
                )

            elif whole_population:
                st.info(
                    "Scope: every medication in the loaded session "
                    "dataset. Inventory filters are not applied "
                    "to ABC category totals."
                )
                report = build_inventory_report(
                    medications,
                    "abc_summary",
                )

            elif report_id == "request_statuses":
                request_filters = _request_filters()
                selected_inventory = filter_inventory(
                    medications,
                    inventory_filters,
                )

                report = build_request_report(
                    read_requests(Role.REPORTING),
                    filters=request_filters,
                    allowed_medication_ids=tuple(
                        selected_inventory["medication_id"]
                    ),
                )

                st.caption(
                    "Scope: requests matching the selected "
                    "medications and request filters."
                )

            else:
                report = build_inventory_report(
                    medications,
                    report_id,
                    filters=inventory_filters,
                    as_of=(
                        read_demo_reference_date()
                        if report_id == "expiry_overview"
                        else None
                    ),
                )

                if report_id == "stock_analytics":
                    st.caption(
                        "Scope: displayed rows follow the inventory "
                        "filters. ABC classes and percentages retain "
                        "the complete loaded-population denominator."
                    )
                else:
                    st.caption(
                        "Scope: the selected inventory report and "
                        "filters. Inventory summary figures "
                        "describe that selection."
                    )

    except ValueError as error:
        st.error(str(error))
        return

    _render_report_table(report, report_id)

    st.info(
        "N/A: forecasting, optimized replenishment, clinical VEN "
        "classification and historical performance/trend measures. "
        "Required historical records, model inputs and governed "
        "definitions are unavailable."
    )