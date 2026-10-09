""" Shared application settings and client-confirmed labels """
from pathlib import Path

APP_TITLE = "(TOH) Inventory Management & Intelligence Prototype"
APP_SUBTITLE = "ELG 5902 | Group 5 | TOH Project"

PROTOTYPE_NOTICE = (
    "Academic decision-support prototype. "
    "Demo data and representative metrics will be clearly labelled."
)

# Stable role IDS, we will change displayed labels later
ROLE_LABELS: dict[str, str] = {
    "clinical": "Clinical - Doctor + Nurse",
    "procurement_inventory": "Procurement + Inventory/Ordering",
    "warehouse": "Warehouse",
    "executive": "Executive",
}

# Resolve data paths from project loc
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_MEDICATIONS_PATH = PROJECT_ROOT / "data" / "sample_medications.csv"
