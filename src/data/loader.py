""" Load representative medication data without coupling it to the UI."""

from math import isfinite
from pathlib import Path

import pandas as pd

from src.config import SAMPLE_MEDICATIONS_PATH
from src.data.schema import (
    COLUMN_MAPPING,
    DATE_COLUMNS,
    NUMERIC_COLUMNS,
    REQUIRED_COLUMNS,
)

def load_medications(path: str | Path = SAMPLE_MEDICATIONS_PATH) -> pd.DataFrame:
    """ Read the medication CSV, adapt to its field names and check basic validity """
    # Read as strings first to preserve identifiers such as leading-zero codes.
    try:
        medications = pd.read_csv(path, dtype="string")
    except pd.errors.EmptyDataError as error:
        raise ValueError(
            "The medication CSV has no headers or records."
        ) from error
    
    #Normalize header whitespace and apply source-field mappings.
    medications.columns = medications.columns.str.strip()
    medications = medications.rename(columns=COLUMN_MAPPING)
    
    if medications.columns.duplicated().any():
        raise ValueError("Header normalization or column mapping produced duplicate field names.")
    
    missing = set(REQUIRED_COLUMNS) - set(medications.columns)
    if missing:
        raise ValueError(f"Missing required medication fields: {sorted(missing)}")
    
    if medications.empty:
        raise ValueError("The medication dataset contains no records.")
    
    # Remove surrounding whitespace and treat blank cells as missing.
    # Extra columns remain available for future dashboard features.
    for column in medications.columns:
        medications[column] = (
            medications[column].str.strip().replace("", pd.NA)
        )
    
    #Requre identifiable medication records.
    for column in ("medication_id", "medication_name"):
        if medications[column].isna().any():
            raise ValueError(f"{column} contains missing or empty values.")
        
    if medications["medication_id"].duplicated().any():
        raise ValueError("Medication IDs must be unique in this single-record-per-medication dataset.")
    
    _parse_numeric_fields(medications)
    _parse_date_fields(medications)
    _check_recorded_availability(medications)
        
    return medications

def _parse_numeric_fields(medications: pd.DataFrame) -> None:
    """Parse present numeric fields and reject invalid values."""
    for column in NUMERIC_COLUMNS:
        if column not in medications.columns:
            continue
        
        try:
            values = pd.to_numeric(
                medications[column], errors="raise"
            )
        except (ValueError, TypeError) as error:
            raise ValueError(
                f"{column} must contain numeric values or blank optional cells."
            ) from error
        
        # Stock is required; optional numerical inputs may remain missing.
        if column == "current_stock" and values.isna().any():
            raise ValueError("current_stock contains missing values.")
        
        present_values = values.dropna()
        
        if not present_values.map(isfinite).all():
            raise ValueError(f"{column} must contain finite numbers; infinity is invalid.")
        
        if present_values.lt(0).any():
            raise ValueError(f"{column} must contain nonnegative values.")
        
        medications[column] = values

def _parse_date_fields(medications: pd.DataFrame) -> None:
    """Parse present date fields; optional blank dates remain missing."""
    for column in DATE_COLUMNS:
        if column not in medications.columns:
            continue
        
        values = medications[column]
        valid_format = values.str.fullmatch(r"\d{4}-\d{2}-\d{2}", na=False)
        
        if (values.notna() & ~valid_format).any():
            raise ValueError(f"{column} must use YYYY-MM-DD dates or blank optional cells.")
        
        try:
            medications[column] = pd.to_datetime(
                values,
                format="%Y-%m-%d",
                errors="raise",
            )
        except (ValueError, TypeError, OverflowError) as error:
            raise ValueError(f"{column} contains an invalid calendar date.") from error

def _check_recorded_availability(medications: pd.DataFrame) -> None:
    """Check basic availability against recorded stock quantities.
    This does not establish clinical suitability or account for expiry.
    Reorder alerts are separate from basic availability.
    """    
    expected_status = (
        medications["current_stock"].gt(0)
        .map({True: "In stock", False: "Out of stock"})
        .astype("string")
    )
    # Derive basic availability if the status column is absent.
    if "status" not in medications.columns:
        medications["status"] = expected_status
        return
    
    provided_status = medications["status"]
    inconsistent = (
        provided_status.notna() & provided_status.ne(expected_status)
    )
    if inconsistent.any():
        affected_ids = (
            medications.loc[inconsistent, "medication_id"].head(5).to_list()
        )
        
        raise ValueError(
            f"status conflicts with current_stock for medication IDs "
            f"{affected_ids}. "
            "Use 'In stock' for positive recorded stock and "
            "'Out of stock' for zero. "
            "Reorder/low-stock flags belong in separate fields."
        )
    
    # Fill missing labels without overwriting conflicting supplied values.
    medications["status"] = provided_status.fillna(expected_status)

    # counted_stock remains a historical sample observation.
    # It never replaces current_stock because later transactions are unknown.
        