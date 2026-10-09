""" Load reprenstative medication data without coupling it to the UI."""

from pathlib import Path

import pandas as pd

from src.config import SAMPLE_MEDICATIONS_PATH
from src.data.schema import (
    COLUMN_MAPPING,
    NUMERIC_COLUMNS,
    REQUIRED_COLUMNS,
)

def load_medications(path: str | Path = SAMPLE_MEDICATIONS_PATH) -> pd.DataFrame:
    """ Read the medication CSV, adapt to its field names and check basic validity """
    # Read as strings first to preserve identifiers such as leading-zero codes.
    medications = pd.read_csv(path, dtype="string")
    #Normalize header whitespace and apply source-field mappings.
    medications.columns = medications.columns.str.strip()
    medications = medications.rename(columns=COLUMN_MAPPING)
    
    if medications.columns.duplicated().any():
        raise ValueError("Column mapping produced duplicate field names.")
    
    missing = set(REQUIRED_COLUMNS) - set(medications.columns)
    if missing:
        raise ValueError(f"Missing required medication fields: {sorted(missing)}")
    
    if medications.empty:
        raise ValueError("The medication dataset contains no records.")
    
    #Requre identifiable medication records.
    for column in ("medication_id", "medication_name"):
        medications[column] = medications[column].str.strip()
        if medications[column].isna().any() or medications[column].eq("").any():
            raise ValueError(f"{column} contains missing or empty values.")
        
    if medications["medication_id"].duplicated().any():
        raise ValueError("Medication IDs must be unique.")
    
    # Convert known numeric fields and preserve additional column
    for column in NUMERIC_COLUMNS:
        if column in medications.columns:
            medications[column] = pd.to_numeric(
                medications[column], errors="raise"
            )
    if medications["current_stock"].isna().any():
        raise ValueError("current_stock contains missing values.")
    
    if "expiry_date" in medications.columns:
        medications["expiry_date"] = pd.to_datetime(
            medications["expiry_date"],
            format="%Y-%m-%d",
            errors="raise",
        )
        
    return medications
    