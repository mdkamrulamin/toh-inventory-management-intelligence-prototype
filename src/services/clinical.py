"""Compare a demo request with recorded stock, without changing inventory"""

from dataclasses import dataclass
from math import isfinite
from numbers import Integral, Real

import pandas as pd

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
    
    # Reject missing, fractional, boolean, or nonpositive quantities.
    if (isinstance(requested_quantity, bool) or not isinstance(requested_quantity, Integral) or requested_quantity <= 0):
        raise ValueError("Enter a positive whole-number request quantity.")
    
    recorded_stock = medication.get("current_stock")
    
    if (isinstance(recorded_stock, bool) or not isinstance(recorded_stock, Real) or not isfinite(recorded_stock) or recorded_stock < 0):
        raise ValueError("Recorded stock is unavailable or invalid; a preview cannot be evaluated.")
    
    # These identifiers and units must accompany every preview.
    labels: dict[str, str] = {}
    for field in ("medication_id", "medication_name", "stock_unit"):
        value = medication.get(field)
        
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} is missing; a preview cannot be evaluated.")
        
        labels[field] = value.strip()
        
    quantity = int(requested_quantity)
    stock = float(recorded_stock)
    
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