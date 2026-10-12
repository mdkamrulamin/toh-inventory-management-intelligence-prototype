"""Clinical dashboard view for doctors and nurses."""

import pandas as pd
import streamlit as st

from src.ui.components import (
    render_feature_placeholder,
    render_medication_table,
)

def render_clinical_view(medications: pd.DataFrame) -> None:
    """Show medication lookup, availability, and a demo request preview."""
    st.write("Check a medication and review its availability.")
    
    #Use stable IDs for selection while displaying medication names.
    medication_labels = (
        medications.set_index("medication_id")["medication_name"].to_dict()
    )
    
    st.subheader("Medication lookup")
    
    selected_id = st.selectbox(
        "Find a medication",
        options=medications["medication_id"].to_list(),
        format_func=lambda medication_id: (
            f"{medication_labels[medication_id]} ({medication_id})"
        ),
        index=None,
        placeholder="Choose or type a medication name",
        key="clinical_medication_lookup",
    )
    
    #Keep clinical table focus on availability
    #Quantities ratain their stock units to avoid misleading comparisons.
    availability_columns = [
        "medication_name",
        "current_stock",
        "stock_unit",
        "status",
    ]
    
    #Show all records initially, or the selected medication after lookup.
    visible_medications = medications
    if selected_id is not None:
        visible_medications = medications.loc[
            medications["medication_id"].eq(selected_id)
        ]
    
    render_medication_table(visible_medications[availability_columns])
    
    st.subheader("Demo medication request")
    st.caption("Preview only. Requests are not saved or sent, and stock quantities are not changed.")
    
    if selected_id is None:
        st.info("Select a medication above to preview a request.")
    else:
        selected_medication = visible_medications.iloc[0]
        medication_name = selected_medication["medication_name"]
        stock_unit = selected_medication["stock_unit"]
        # Keep quantity input specific to the selected medication and unit.
        with st.form("clinical_demo_request"):
            quantity = st.number_input(
                f"Requested quantity - stock unit: {stock_unit}",
                min_value=1,
                value=1,
                step=1,
                key=f"clinical_request_quantity_{selected_id}",
            )
            
            preview_requested = st.form_submit_button(
                "Preview demo request"
            )
            if preview_requested:
                st.info(
                    f"Demo request preview: {medication_name} - " 
                    f"{quantity} stock units ({stock_unit}). "
                    "No request was saved or sent; stock is unchanged."
                )
    
    #Detailed content and rules will follow confirmed requirements from team
    #Request previews do not create requests or clinical approvals.
    render_feature_placeholder(
        "Clinical/pharmacy review status",
        "Request preview only. No request has been submitted "
        "and no clinical/pharmacy approval is recorded.",
    )
    
    #Research describs substitue info, not validated equivalence.  
    render_feature_placeholder(
        "Approved substitute-product information",
        "No validated substitute data is available. "
        "Any candidate requires clinical/pharmacy review and approval. "
        "This demonstration does not rank or approve alternatives.",
    )
    
    render_feature_placeholder(
        "Availability alerts",
        "Alert thresholds remain to be confirmed. "
        "Displayed availability reflects recorded stock quantities only; "
        "it does not establish clinical suitability or usable expiry.",
    )
    