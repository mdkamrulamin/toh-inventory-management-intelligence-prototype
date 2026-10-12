""" Provisional medication schema with optional demo fields from research. """

#Keeping existing required fields for backward compatibility.
REQUIRED_COLUMNS = (
    "medication_id",
    "medication_name",
    "current_stock",
)

# Values must be finite and nonnegative; optional cells may be blank.
NUMERIC_COLUMNS = (
    "current_stock",
    "unit_cost",
    "average_monthly_consumption",
    "reorder_point",
    "safety_stock_level",
    "lead_time_days",
    "counted_stock",
)

DATE_COLUMNS = (
    "expiry_date",
    "last_count_date",
)

# These are proposed synthetic inputs from research, not confirmed TOH fields.
OPTIONAL_EXTENSION_COLUMNS = (
    "primary_location",
    "reorder_point",
    "safety_stock_level",
    "lead_time_days",
    "last_count_date",
    "counted_stock",
)

# Add confirmed mappings here when the final field names are set
COLUMN_MAPPING: dict[str, str] = {}

