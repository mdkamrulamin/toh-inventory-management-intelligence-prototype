""" Provisional medication schema. Will refine when dataset is finalized """

# Minimum fields required for now
REQUIRED_COLUMNS = (
    "medication_id",
    "medication_name",
    "current_stock",
)

NUMERIC_COLUMNS = (
    "current_stock",
    "unit_cost",
    "average_monthly_consumption",
)

# Add confirmed mappings here when the final field names are set
COLUMN_MAPPING: dict[str, str] = {}

