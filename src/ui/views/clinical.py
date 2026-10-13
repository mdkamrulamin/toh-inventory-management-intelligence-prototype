"""Clinical dashboard view for doctors and nurses."""

import pandas as pd
import streamlit as st

from src.services.clinical import build_clinical_request_preview
from src.ui.components import (
    render_feature_placeholder,
    render_medication_table,
)

def render_clinical_view(medications: pd.DataFrame) -> None:
    """Show medication availability and a stock-aware demo request preview."""
    st.write("Check a medication and review its recorded availability.")
    
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
    selected_medication = None
    
    if selected_id is not None:
        visible_medications = medications.loc[
            medications["medication_id"].eq(selected_id)
        ]
        selected_medication = visible_medications.iloc[0]
        
        st.write(
            f"**Selected medication:** "
            f"{selected_medication['medication_name']} ({selected_id})"
        )
        
        stock_column, unit_column, status_column = st.columns(3)
        
        stock_column.metric(
            "Recorded stock",
            f"{float(selected_medication['current_stock']):g}",
        )
        unit_column.metric(
            "Stock unit",
            selected_medication["stock_unit"],
        )
        status_column.metric(
            "Recorded availability",
            selected_medication["status"],
        )
        
        st.caption("Recorded availability is not a physical stock confirmation or a clinical suitability assessment.")
    
    render_medication_table(visible_medications[availability_columns])
    
    st.subheader("Demo medication request")
    st.caption("Demo only. Nothing is saved, sent, deducted or approved.")
    
    if selected_medication is None:
        st.info("Select a medication above to preview a request.")
    else:
        stock_unit = selected_medication["stock_unit"]
        
        # Keep this outside a form so quantity changes trigger a rerun.
        quantity = st.number_input(
            f"Requested quantity - stock unit: {stock_unit}",
            min_value=1,
            value=1,
            step=1,
            key=f"clinical_request_quantity_{selected_id}",
        )
        
        # Render a preview only on this button-click run.
        # Changing the selection or quantity clears the previous result.
        if st.button(
            "Preview demo request",
            key="clinical_preview_request",
        ):
            try:
                preview = build_clinical_request_preview(
                    selected_medication,
                    quantity,
                )
            except ValueError as error:
                st.error(str(error))
            else:
                st.write(
                    f"**Medication:** {preview.medication_name} "
                    f"({preview.medication_id})"
                )
                st.write(
                    f"**Stock comparison:** requested quantity "
                    f"{preview.requested_quantity:,}; recorded stock "
                    f"{preview.recorded_stock:g}; "
                    f"stock unit: {preview.stock_unit}."
                )
                
                if preview.outcome == "sufficient":
                    st.success(preview.message)
                else:
                    st.warning(preview.message)
                    
                st.caption("Preview only. No request was saved, sent or approved; recorded stock is unchanged.")
    
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
    