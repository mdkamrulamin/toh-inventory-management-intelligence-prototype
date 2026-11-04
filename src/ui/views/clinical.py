"""Clinical dashboard view for doctors and nurses."""

import pandas as pd
import streamlit as st

from src.services.clinical import build_clinical_request_preview
from src.services.replenishment import build_replenishment_context
from src.services.workflow_models import Role
from src.ui.components import (
    render_feature_placeholder,
    render_medication_table,
)
from src.ui.session import (
    get_session_info,
    read_request_details,
    read_requests,
)
from src.ui.stock_indicators import render_stock_review_badge
from src.ui.workflow_actions import (
    clinical_input_keys,
    new_clinical_draft_callback,
    prepare_clinical_draft,
    submit_clinical_request_callback,
)
from src.ui.workflow_components import (
    render_request_details,
    render_request_table,
    select_request,
)

def _render_submission(medication: pd.Series, quantity: int, stock_unit: str, *, has_unit: bool) -> None:
    """Render explicit submission independently of the temporary preview."""
    medication_id = medication["medication_id"]
    draft = prepare_clinical_draft(medication_id)
    info = get_session_info()
    
    st.subheader("Submit a synthetic medication request")
    st.caption(
        "Demo unit/ward stock requisition based on project assumptions. Do not enter patient information."
    )
    submitted_id = draft["submitted_request_id"]
    if submitted_id is not None:
        st.success(
            f"This draft was submitted as {submitted_id}. "
            "Its original quantity and request information are retained."
        )
        st.button(
            "Start another request for this medication",
            key=f"workflow_action_new_clinical_{medication_id}",
            on_click=new_clinical_draft_callback,
            args=(medication_id,),
        )
        return
    
    st.write(
        f"**Request to submit:** {medication['medication_name']} "
        f"({medication_id}), {quantity:,} {stock_unit}."
    )
    st.caption(
        "Submission creates a session request for Pharmacist review. "
        "It does not reserve stock, deduct stock or provide clinical approval."
    )
    
    if not has_unit:
        st.warning("A recorded stock unit is required before submission.")
        
    keys = clinical_input_keys(medication_id)
    with st.form(key=f"clinical_submission_form_{medication_id}", clear_on_submit=False):
        st.text_input(
            "Requesting location",
            placeholder="For example: Demo Ward",
            key=keys["location"],
        )
        st.text_area(
            "Reason for the synthetic request",
            placeholder="Describe this demonstration stock request",
            key=keys["reason"],
        )
        st.selectbox(
            "Demo urgency",
            options=["routine", "urgent"],
            format_func=str.capitalize,
            key=keys["urgency"],
            help=("Illustrative queue categories only. Hospital urgency definitions are not established."),
        )
        st.checkbox(
            "Allow consideration of substitutes during future review",
            key=keys["substitution"],
            help=("Preference only. This demo does not recommend, offer or approve substitutes."),
        )
        st.form_submit_button(
            "Submit synthetic request",
            disabled=not has_unit,
            on_click=submit_clinical_request_callback,
            kwargs={
                "medication_id": medication_id,
                "quantity": quantity,
                "unit": stock_unit if has_unit else "",
                "submission_key": draft["submission_key"],
                "expected_run_id": info.run_id,
                "expected_revision": info.revision,
            },
        )

def _render_session_requests() -> None:
    """Keep submitted requests visible independently of medication lookup."""
    st.subheader("Submitted requests — this demo session")
    st.caption(
        "Statuses and reasons come from the shared workflow. "
        "Changing tabs or clearing Preview does not delete these requests."
    )
    requests = read_requests(Role.CLINICAL)
    
    if not requests:
        st.info("No synthetic requests have been submitted.")
        return

    render_request_table(requests, table_key="clinical_requests")
    selected_request_id = select_request(requests, label="Inspect a submitted request", widget_key="workflow_ui_clinical_request_lookup")
    if selected_request_id is not None:
        request = read_request_details(selected_request_id, Role.CLINICAL)
        render_request_details(request, key_prefix="clinical_request")

def render_clinical_view(medications: pd.DataFrame) -> None:
    """Show availability, temporary Preview and explicit demo submission."""
    st.write(
        "Check recorded medication availability, preview a quantity or submit a synthetic request for review."
    )
    
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
    stock_unit = "N/A"
    has_unit = False
    
    if selected_id is not None:
        visible_medications = medications.loc[
            medications["medication_id"].eq(selected_id)
        ]
        selected_medication = visible_medications.iloc[0]
        
        selected_unit = selected_medication.get("stock_unit")
        has_unit = (isinstance(selected_unit, str) and bool(selected_unit.strip()))
        if has_unit:
            stock_unit = selected_unit.strip()
        
        st.write(
            f"**Selected medication:** "
            f"{selected_medication['medication_name']} ({selected_id})"
        )
        
        stock_column, unit_column, status_column = st.columns(3)
        
        stock_column.metric("Recorded stock", f"{float(selected_medication['current_stock']):g}")
        unit_column.metric("Stock unit", stock_unit)
        status_column.metric("Recorded availability", selected_medication["status"])
        
        st.caption("Recorded availability is not a physical stock confirmation or a clinical suitability assessment.")

        st.caption("Inventory threshold context - separate from the request preview.")
        selected_review = build_replenishment_context(visible_medications).iloc[0]["ordering_review"]
        render_stock_review_badge(selected_review)
        
    render_medication_table(
        visible_medications.reindex(columns=availability_columns),
        export_key="clinical_inventory",
    )
    
    st.subheader("Temporary request preview")
    st.caption("Preview only. No request is saved or sent, and no stock is reserved, deducted or approved.")
    
    if selected_medication is None:
        st.info("Select a medication above to preview or submit a request.")
    else:
        # Remains outside the submission form. Quantity changes rerun the page and clear the previous temporary preview.
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
                preview = build_clinical_request_preview(selected_medication, quantity)
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

        _render_submission(selected_medication, quantity, stock_unit, has_unit=has_unit)
        
    _render_session_requests()
    
    
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
    