""" Shared application settings and client-confirmed labels """
from pathlib import Path

APP_TITLE = "(TOH) Inventory Management & Intelligence Prototype"
APP_SUBTITLE = "ELG 5902 | Group 5 | TOH Project"

PROTOTYPE_NOTICE = (
    "Literature-informed educational prototype. "
    "All medication inventory values are synthetic and do not represent "
    "TOH operations. Illustrative features are not validated clinical "
    "or purchasing decisions."
)

# Stable role IDS, we will change displayed labels later
ROLE_LABELS: dict[str, str] = {
    "clinical": "Clinical - Doctor + Nurse",
    "procurement_inventory": "Procurement + Inventory/Ordering",
    "warehouse": "Warehouse",
    "executive": "Executive",
}

#Audience context
ROLE_CONTEXT: dict[str, str] = {
    "clinical": (
        "Process context: medication request and availability review. "
        "Alternative products require clinical/pharmacy approval."
    ),
    "procurement_inventory": (
        "Process context: inventory verification and monitoring; "
        "replenishment and supplier-order review."
    ),
    "warehouse": (
        "Process context: receiving and storage; distribution; "
        "physical count and reconciliation."
    ),
    "executive": (
        "Process context: overall inventory performance monitoring "
        "and policy review."
    ),
}

# Display labels are separate from the internal data-field names.
FIELD_LABELS: dict[str, str] = {
    "medication_id": "Medication ID",
    "medication_name": "Medication name",
    "category": "Dosage form",
    "stock_unit": "Stock unit",
    "current_stock": "Recorded stock",
    "unit_cost": "Unit cost (CAD/unit)",
    "average_monthly_consumption": "Average monthly use",
    "expiry_date": "Expiry date",
    "supplier": "Demo supplier",
    "status": "Recorded availability",
    "primary_location": "Representative location",
    "reorder_point": "Reorder point (demo)",
    "safety_stock_level": "Safety stock (demo)",
    "lead_time_days": "Lead time (days)",
    "last_count_date": "Last count date",
    "counted_stock": "Past counted stock",
    "ordering_review": "Illustrative ordering review",
}

# Resolve data paths from project loc
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_MEDICATIONS_PATH = PROJECT_ROOT / "data" / "sample_medications_extended.csv"
