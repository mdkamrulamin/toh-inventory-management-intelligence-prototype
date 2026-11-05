"""Read-only reports built from existing synthetic inventory services.

These functions do not submit requests, change inventory or write files.
The UI supplies current session projections and uses its existing table
renderer/export controls.
"""

from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from src.services.replenishment import (
    ABOVE_STOCK_LABEL,
    MISSING_REORDER_LABEL,
    MISSING_UNIT_LABEL,
    REVIEW_STOCK_LABEL,
    ZERO_STOCK_LABEL,
    build_replenishment_context,
)
from src.services.summary import summarize_inventory
from src.services.workflow_models import RequestStatus

REPORT_LABELS = {
    "inventory_snapshot": "Inventory snapshot",
    "zero_stock": "Zero-stock report",
    "replenishment_review": "Replenishment review",
    "supplier_cost": "Supplier and cost report",
    "expiry_overview": "Expiry overview",
    "inventory_summary": "Inventory summary",
    "historical_counts": "Historical count observations",
    "request_statuses": "Current synthetic requests",
    "request_summary": "Whole-session request summary",
}

INVENTORY_COLUMNS = {
    "inventory_snapshot": (
        "medication_id",
        "medication_name",
        "category",
        "current_stock",
        "stock_unit",
        "status",
        "expiry_date",
        "supplier",
        "primary_location",
    ),
    "zero_stock": (
        "medication_id",
        "medication_name",
        "current_stock",
        "stock_unit",
        "status",
        "supplier",
        "primary_location",
    ),
    "replenishment_review": (
        "medication_id",
        "medication_name",
        "current_stock",
        "stock_unit",
        "average_monthly_consumption",
        "reorder_point",
        "safety_stock_level",
        "lead_time_days",
        "supplier",
        "ordering_review",
    ),
    "supplier_cost": (
        "medication_id",
        "medication_name",
        "current_stock",
        "stock_unit",
        "unit_cost",
        "supplier",
    ),
    "expiry_overview": (
        "medication_id",
        "medication_name",
        "current_stock",
        "stock_unit",
        "expiry_date",
        "primary_location",
    ),
    "historical_counts": (
        "medication_id",
        "medication_name",
        "current_stock",
        "stock_unit",
        "last_count_date",
        "counted_stock",
        "primary_location",
    ),
}

INVENTORY_REPORT_IDS = (
    "inventory_snapshot",
    "zero_stock",
    "replenishment_review",
    "supplier_cost",
    "expiry_overview",
    "inventory_summary",
    "historical_counts",
)

REPORT_NOTES = {
    "inventory_snapshot": (
        "Current report selection. Recorded quantities are synthetic."
    ),
    "zero_stock": (
        "Current recorded stock equals zero; this is not a historical hospital stockout measure."
    ),
    "replenishment_review": (
        "Thresholds and lead times are synthetic, unvalidated examples. No order quantity or purchase order is generated."
    ),
    "supplier_cost": (
        "Synthetic suppliers and CAD unit costs; no supplier transaction or hospital cost-saving claim."
    ),
    "expiry_overview": (
        "One representative expiry/location per medication. No batch-level FEFO or clinical usability decision."
    ),
    "inventory_summary": (
        "Current filtered inventory selection. Physical stock units are not combined into one quantity."
    ),
    "historical_counts": (
        "Past count observations. Intervening transactions are incomplete; no confirmed discrepancy, loss or reconciliation result."
    ),
    "request_statuses": (
        "Current filtered requests from this synthetic session. Closed status is distinguished by its retained outcome."
    ),
    "request_summary": (
        "Whole demo session. Current states and final outcomes are separate: fulfilled requests close with a fulfilled outcome."
    ),
}

SYNTHETIC_NOTICE = ("Synthetic demonstration only; not verified TOH operational data.")

REQUEST_COLUMNS = (
    "run_id",
    "request_id",
    "medication_id",
    "medication_name",
    "requested_quantity",
    "request_unit",
    "requesting_location",
    "request_urgency",
    "request_status",
    "request_outcome",
    "request_reason",
    "status_reason",
    "received_time",
    "updated_time",
    "supply_update",
    "expected_delivery",
    "fulfillment_quantity",
    "fulfilled_time",
)

REVIEW_LABELS = (
    ZERO_STOCK_LABEL,
    REVIEW_STOCK_LABEL,
    ABOVE_STOCK_LABEL,
    MISSING_REORDER_LABEL,
    MISSING_UNIT_LABEL,
)

@dataclass(frozen=True)
class InventoryFilters:
    medication_ids: tuple[str, ...] = ()
    suppliers: tuple[str | None, ...] = ()
    stock_statuses: tuple[str, ...] = ()
    categories: tuple[str | None, ...] = ()
    ordering_reviews: tuple[str, ...] = ()
    expiry_from: date | None = None
    expiry_to: date | None = None
    
@dataclass(frozen=True)
class RequestFilters:
    statuses: tuple[str, ...] = ()
    urgencies: tuple[str, ...] = ()
    outcomes: tuple[str | None, ...] = ()
    
def _text_values(frame: pd.DataFrame, column: str) -> pd.Series:
    """Normalize filter text without replacing unavailable values."""
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="string")
    
    return (frame[column].astype("string").str.strip().replace("", pd.NA))

def _pick(frame: pd.DataFrame, column: str, selected: tuple) -> pd.DataFrame:
    """An empty selection means no restriction; None selects missing."""
    if not selected:
        return frame
    
    values = _text_values(frame, column)
    known = [value for value in selected if value is not None]
    mask = values.isin(known)
    
    if any(value is None for value in selected):
        mask = mask | values.isna()
        
    return frame.loc[mask].copy()

def _check_date(value: date | None) -> None:
    if value is not None and (
        not isinstance(value, date) 
        or isinstance(value, datetime)
    ):
        raise ValueError("Expiry filters must use calendar dates.")
    
def filter_inventory(medications: pd.DataFrame, filters: InventoryFilters | None = None) -> pd.DataFrame:
    """Return a detached selection with the shared review classification."""
    filters = filters or InventoryFilters()
    _check_date(filters.expiry_from)
    _check_date(filters.expiry_to)
    
    if (
        filters.expiry_from is not None 
        and filters.expiry_to is not None
        and filters.expiry_from > filters.expiry_to
    ):
        raise ValueError("Expiry start date must not be after the end date.")
    selected = medications.copy(deep=True)
    selected["ordering_review"] = build_replenishment_context(selected)["ordering_review"]
    
    for column, choices in (
        ("medication_id", filters.medication_ids),
        ("supplier", filters.suppliers),
        ("status", filters.stock_statuses),
        ("category", filters.categories),
        ("ordering_review", filters.ordering_reviews),
    ):
        selected = _pick(selected, column, choices)
        
    if (filters.expiry_from is not None or filters.expiry_to is not None):
        dates = pd.to_datetime(
            _text_values(selected, "expiry_date"),
            errors="coerce",
        )
        mask = dates.notna()
        
        if filters.expiry_from is not None:
            mask = mask & dates.ge(pd.Timestamp(filters.expiry_from))
            
        if filters.expiry_to is not None:
            mask = mask & dates.le(pd.Timestamp(filters.expiry_to))
            
        selected = selected.loc[mask].copy()
        
    return selected.copy(deep=True)

def inventory_filter_options(medications: pd.DataFrame) -> dict[str, list]:
    """Return supported choices, retaining an explicit missing option."""
    selected = filter_inventory(medications)
    result = {}
    
    for column in ("medication_id", "supplier", "status", "category", "ordering_review"):
        values = _text_values(selected, column)
        choices = sorted(values.dropna().unique().tolist())
        
        if values.isna().any():
            choices.append(None)
            
        result[column] = choices
        
    return result

def _annotate(frame: pd.DataFrame, report_id: str) -> pd.DataFrame:
    result = frame.copy(deep=True)
    result["report_name"] = REPORT_LABELS[report_id]
    result["synthetic_data_notice"] = SYNTHETIC_NOTICE
    result["report_note"] = REPORT_NOTES[report_id]
    return result

def build_inventory_report(medications: pd.DataFrame, report_id: str, *, filters: InventoryFilters | None = None) -> pd.DataFrame:
    """Build a supported report from the current inventory selection."""
    if report_id not in INVENTORY_REPORT_IDS:
        raise ValueError("Unsupported inventory report.")
    
    selected = filter_inventory(medications, filters)
    
    if report_id == "inventory_summary":
        summary = summarize_inventory(selected)
        rows = [
            (
                "Medication SKUs",
                summary["sku_count"],
                "SKUs",
            ),
            (
                "Recorded zero-stock SKUs",
                summary["zero_stock_count"],
                "SKUs",
            ),
            (
                "Recorded zero-stock share",
                summary["zero_stock_share_percent"],
                "%",
            ),
            (
                "Synthetic inventory value",
                summary["inventory_value_cad"],
                "CAD",
            ),
            (
                "Known demo suppliers",
                summary["supplier_count"],
                "suppliers",
            ),
        ]
        
        counts = selected["ordering_review"].value_counts()
        rows.extend(
            (
                label,
                int(counts.get(label, 0)),
                "SKUs",
            )
            for label in REVIEW_LABELS
        )
        
        report = pd.DataFrame(rows, columns=["measure", "value", "measure_unit"])
    else:
        if report_id == "zero_stock":
            selected = selected.loc[selected["current_stock"].eq(0)].copy()
            
        # Missing optional fields become missing report cells.
        # They do not become zero or invented source values.
        report = selected.reindex(columns=INVENTORY_COLUMNS[report_id]).copy()
    
    return _annotate(report, report_id)

def build_request_report(
    requests: list[dict],
    *,
    filters: RequestFilters | None = None,
    allowed_medication_ids: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Flatten role-projected requests without internal submission tokens.

    None allows all medication IDs. An explicitly empty tuple allows none.
    """
    filters = filters or RequestFilters()
    rows = []

    for request in requests:
        feedback = request.get("supply_feedback") or {}
        fulfillment = request.get("fulfillment") or {}

        rows.append({
            "run_id": request["run_id"],
            "request_id": request["request_id"],
            "medication_id": request["medication_id"],
            "medication_name": request["medication_name"],
            "requested_quantity": request["quantity"],
            "request_unit": request["unit"],
            "requesting_location": request["requesting_location"],
            "request_urgency": request["urgency"],
            "request_status": request["status"],
            "request_outcome": request.get("outcome"),
            "request_reason": request["reason"],
            "status_reason": request["status_reason"],
            "received_time": request["received_time"],
            "updated_time": request["updated_time"],
            "supply_update": feedback.get("feedback"),
            "expected_delivery": feedback.get("expected_delivery"),
            "fulfillment_quantity": fulfillment.get("quantity"),
            "fulfilled_time": fulfillment.get("fulfilled_time"),
        })

    # Build and filter once, after collecting every request.
    # Explicit columns also preserve a valid empty report.
    report = pd.DataFrame(
        rows,
        columns=REQUEST_COLUMNS,
    )

    if allowed_medication_ids is not None:
        report = report.loc[
            report["medication_id"].isin(
                allowed_medication_ids
            )
        ].copy()

    for column, choices in (
        ("request_status", filters.statuses),
        ("request_urgency", filters.urgencies),
        ("request_outcome", filters.outcomes),
    ):
        report = _pick(report, column, choices)

    return _annotate(report, "request_statuses")
    
def build_request_summary(summary: dict) -> pd.DataFrame:
    """Format the existing whole-session query result; do not recalculate."""
    rows = [
        ("Submitted requests", summary["total_requests"]),
        ("Open requests", summary["open_requests"]),
        ("Fulfilled outcomes", summary["fulfilled_requests"]),
        ("Returned outcomes", summary["returned_requests"]),
        ("Closed without supply", summary["closed_without_supply"]),
    ]
    rows.extend(
        (
            f"Current state: {status.value.replace('_', ' ').capitalize()}",
            summary["by_status"][status.value],
        )
        for status in RequestStatus
    )

    report = pd.DataFrame(rows, columns=["measure", "value"])
    report["measure_unit"] = "requests"

    return _annotate(report, "request_summary")


def prepare_report_display(report: pd.DataFrame) -> pd.DataFrame:
    """Format a detached table for the existing renderer/native CSV tool."""
    display = report.copy(deep=True)

    for column in ("expiry_date", "last_count_date", "expected_delivery"):
        if column in display.columns:
            dates = pd.to_datetime(
                display[column],
                format="%Y-%m-%d",
                errors="coerce",
            )
            display[column] = dates.dt.strftime("%Y-%m-%d")

    if "request_status" in display.columns:
        display["request_status"] = display["request_status"].map(
            lambda value: value.replace("_", " ").capitalize()
            if isinstance(value, str)
            else value
        )

    if "request_urgency" in display.columns:
        display["request_urgency"] = (display["request_urgency"].str.capitalize())

    if "request_outcome" in display.columns:
        outcome_labels = {
            "fulfilled": "Synthetic fulfillment recorded",
            "returned": "Returned without fulfillment",
            "closed_without_supply": "Closed without supply",
        }
        display["request_outcome"] = display["request_outcome"].map(
            lambda value: outcome_labels.get(value, value)
            if isinstance(value, str)
            else value
        )

    if {"measure", "value", "measure_unit"}.issubset(display.columns):
        formatted_values = []

        for value, unit in zip(display["value"], display["measure_unit"], strict=True):
            if pd.isna(value):
                formatted_values.append("N/A")
            elif unit == "CAD":
                formatted_values.append(f"{float(value):.2f}")
            elif unit == "%":
                formatted_values.append(f"{float(value):.1f}")
            else:
                formatted_values.append(f"{float(value):g}")

        display["value"] = formatted_values

    # Convert only the display copy before inserting string missing labels.
    return display.astype("object").where(pd.notna(display), "N/A")
    
        