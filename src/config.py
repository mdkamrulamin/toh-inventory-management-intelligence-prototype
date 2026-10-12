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

# Resolve data paths from project loc
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_MEDICATIONS_PATH = PROJECT_ROOT / "data" / "sample_medications_extended.csv"
