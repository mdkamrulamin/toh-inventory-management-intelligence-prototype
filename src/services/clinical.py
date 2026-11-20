"""Compare a demo request with recorded stock, without changing inventory"""

from dataclasses import dataclass
from math import isfinite
from numbers import Integral, Real
import re

import pandas as pd

QUANTITY_ERROR = "Enter a positive whole-number request quantity."

def validate_request_quantity(value) -> int:
    """Validate runtime quantities without rounding or substitution."""
    if (isinstance(value, bool) or not isinstance(value, Integral) or value <= 0):
        raise ValueError(QUANTITY_ERROR)
    try:
        finite = isfinite(value)
    except (TypeError, ValueError, OverflowError):
        finite = False
    
    if not finite:
        raise ValueError("Request quantity is outside the supported numeric range.")
    
    return int(value)

def parse_clinical_quantity(text) -> int:
    """Parse current form text without falling back to another quantity."""
    if not isinstance(text, str):
        raise ValueError(QUANTITY_ERROR)
    
    cleaned = text.strip()

    if not re.fullmatch(r"[0-9]+", cleaned):
        raise ValueError(QUANTITY_ERROR)
    
    try:
        quantity = int(cleaned)
    except ValueError as error:
        raise ValueError("Request quantity is outside the supported numeric range.") from error

    return validate_request_quantity(quantity)
    

@dataclass(frozen=True)
class ClinicalRequestPreview:
    """A temporary stock comparison, not a submitted or approved request."""
    medication_id: str
    medication_name: str
    requested_quantity: int
    recorded_stock: float
    stock_unit: str
    outcome: str
    message: str
    
def build_clinical_request_preview(medication: pd.Series, requested_quantity: int | None) -> ClinicalRequestPreview:
    """Comapre a positive integer quantity with current recoreded stock."""
    quantity = validate_request_quantity(requested_quantity)
    recorded_stock = medication.get("current_stock")
    
    # Reject missing, fractional, boolean, or nonpositive quantities.
    if (
        isinstance(recorded_stock, bool) 
        or not isinstance(recorded_stock, Real) 
        or not isfinite(recorded_stock)
        or recorded_stock < 0
    ):
        raise ValueError("Recorded stock is unavailable or invalid; a preview cannot be evaluated.")
    
    labels = {}
    
    for field in ("medication_id", "medication_name", "stock_unit"):
        value = medication.get(field)

        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} is missing; a preview cannot be evaluated.")

        labels[field] = value.strip()
    
    stock = float(recorded_stock)
    
    recorded_stock = medication.get("current_stock")
    
    # Historical counted_stock is deliberately not used.
    if stock == 0:
        outcome = "out_of_stock"
        message = (
            "Unable to fulfill from recorded stock. Pharmacy review is required; the proposed process "
            "may consider internal redistribution, clinically authorized alternatives or procurement escalation."
        )
    elif stock >= quantity:
        outcome = "sufficient"
        message = (
            "Sufficient recorded stock for this requested quantity. This is a synthetic record, not a physical "
            "stock confirmation; proposed next step is pharmacist verification."
        )
    else:
        outcome = "insufficient"
        message = ("Requested quantity exceeds recorded stock; review is needed before fulfillment.")
        
    return ClinicalRequestPreview(
        medication_id=labels["medication_id"],
        medication_name=labels["medication_name"],
        requested_quantity=quantity,
        recorded_stock=stock,
        stock_unit=labels["stock_unit"],
        outcome=outcome,
        message=message,
    )