"""Clinical dashboard view for doctors and nurses."""

import pandas as pd
import streamlit as st

from src.ui.components import (
    render_feature_placeholder,
    render_medication_table,
)

def render_clinical_view(medications: pd.DataFrame) -> None:
    """Show sample availability and provisional clinical sections."""
    st.write("Check medication availability and stock quantities.")
    
    #Keep clinical table focus on availability
    #Quantities ratain their stock units to avoid misleading comparisons.
    availability_columns = [
        "medication_name",
        "current_stock",
        "stock_unit",
        "status",
    ]
    
    render_medication_table(medications[availability_columns])
    
    #Detailed content and rules will follow confirmed requirements from team
    render_feature_placeholder(
        "Substitute-product information",
        "Display reviewed alternative-product information. "
        "No substitute recommendations are implemented yet.",
    )
    
    render_feature_placeholder(
        "Availability alerts",
        "Highlight availability concerns using agreed inventory thresholds. "
        "Alert rules are still to be defined.",
    )
    