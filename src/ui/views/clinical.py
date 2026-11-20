"""Clinical dashboard view for doctors and nurses."""

import pandas as pd
import streamlit as st

from src.services.clinical import (
    build_clinical_request_preview,
    parse_clinical_quantity,
)
from src.services.replenishment import build_replenishment_context
from src.services.substitute_queries import ALTERNATIVES_COLUMN
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
from src.ui.substitute_panels import (
    attach_inventory_alternatives,
    render_substitute_notice,
)
from src.ui.workflow_actions import (
    clinical_input_keys,
    new_clinical_draft_callback,
    prepare_clinical_draft,
    submit_clinical_form_callback,
)
from src.ui.workflow_components import (
    render_request_details,
    render_request_table,
    select_request,
)


def _render_request_form(
    medication: pd.Series,
    stock_unit: str,
    *,
    has_unit: bool,
) -> None:
    """Keep current quantity, Preview and Submit within one form."""
    medication_id = medication["medication_id"]
    draft = prepare_clinical_draft(medication_id)
    info = get_session_info()
    keys = clinical_input_keys(medication_id)
    submitted_id = draft["submitted_request_id"]
    submitted = submitted_id is not None

    st.subheader("Medication request")
    st.caption(
        "Enter a positive whole quantity in the recorded stock unit. "
        "Click Preview or Submit to apply the current form values. "
        "Do not enter patient information."
    )

    if submitted:
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
        st.caption("Preview remains available. Changing its quantity does not edit the submitted request.")

    if not has_unit:
        st.warning("A recorded stock unit is required for Preview and submission.")

    with st.form(
        key=(
            f"clinical_request_form_{info.run_id}_"
            f"{medication_id}_{draft['submission_key']}"
        ),
        clear_on_submit=False,
        enter_to_submit=False,
    ):
        quantity_text = st.text_input(
            f"Requested quantity — stock unit: {stock_unit}",
            key=keys["quantity"],
            placeholder="Enter a positive whole number",
        )

        st.caption(
            "Preview checks recorded stock without creating a request. "
            "Submission creates a synthetic request for Pharmacist review "
            "without reserving or deducting stock."
        )

        st.text_input(
            "Requesting location",
            placeholder="For example: Demo Ward",
            key=keys["location"],
            disabled=submitted,
        )
        st.text_area(
            "Reason for the synthetic request",
            placeholder="Describe this demonstration stock request",
            key=keys["reason"],
            disabled=submitted,
        )
        st.selectbox(
            "Demo urgency",
            options=["routine", "urgent"],
            format_func=str.capitalize,
            key=keys["urgency"],
            disabled=submitted,
            help=(
                "Illustrative queue categories only. Hospital urgency definitions are not established."
            ),
        )
        st.checkbox(
            "Allow consideration of substitutes during demo review",
            key=keys["substitution"],
            disabled=submitted,
            help=(
                "Preference only. This demo does not recommend, offer or approve substitutes."
            ),
        )

        preview_clicked = st.form_submit_button(
            "Preview demo request",
            key="clinical_preview_request",
            disabled=not has_unit,
        )

        st.form_submit_button(
            "Submit synthetic request",
            key=(
                f"workflow_action_clinical_submit_{info.run_id}_"
                f"{medication_id}_{draft['submission_key']}"
            ),
            disabled=submitted or not has_unit,
            on_click=submit_clinical_form_callback,
            kwargs={
                "medication_id": medication_id,
                "unit": stock_unit if has_unit else "",
                "submission_key": draft["submission_key"],
                "expected_run_id": info.run_id,
                "expected_revision": info.revision,
            },
        )

    # Preview exists only for this button-click run.
    if preview_clicked:
        try:
            quantity = parse_clinical_quantity(quantity_text)
            preview = build_clinical_request_preview(
                medication,
                quantity,
            )
        except ValueError as error:
            st.session_state[keys["form_error"]] = str(error)
        else:
            st.session_state[keys["form_error"]] = ""

            st.subheader("Temporary request preview")
            st.write(
                f"**Medication:** {preview.medication_name} "
                f"({preview.medication_id})"
            )
            st.write(
                f"**Validated preview quantity:** "
                f"{preview.requested_quantity:,} "
                f"{preview.stock_unit}"
            )
            st.write(
                f"**Recorded stock:** "
                f"{preview.recorded_stock:g} "
                f"{preview.stock_unit}"
            )

            if preview.outcome == "sufficient":
                st.success(preview.message)
            else:
                st.warning(preview.message)

            st.caption(
                "Preview only. No request was saved, sent or approved; "
                "recorded stock is unchanged. This result describes "
                "the validated quantity shown above."
            )

    form_error = st.session_state.get(keys["form_error"], "")
    if form_error:
        st.error(form_error)


def _render_session_requests() -> None:
    """Keep submitted requests independent of lookup and Preview."""
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

    selected_request_id = select_request(
        requests,
        label="Inspect a submitted request",
        widget_key="workflow_ui_clinical_request_lookup",
    )

    if selected_request_id is not None:
        request = read_request_details(selected_request_id, Role.CLINICAL)
        render_request_details(request, key_prefix="clinical_request")


def render_clinical_view(medications: pd.DataFrame) -> None:
    """Show availability, temporary Preview and explicit submission."""
    st.write(
        "Check recorded medication availability, preview a quantity or submit a synthetic request for review."
    )

    medication_labels = (medications.set_index("medication_id")["medication_name"].to_dict())

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

    availability_columns = [
        "medication_name",
        "current_stock",
        "stock_unit",
        "status",
        ALTERNATIVES_COLUMN,
    ]

    visible_medications = medications
    selected_medication = None
    stock_unit = "N/A"
    has_unit = False

    if selected_id is not None:
        visible_medications = medications.loc[medications["medication_id"].eq(selected_id)]
        selected_medication = visible_medications.iloc[0]

        selected_unit = selected_medication.get("stock_unit")
        has_unit = (
            isinstance(selected_unit, str)
            and bool(selected_unit.strip())
        )
        if has_unit:
            stock_unit = selected_unit.strip()

        st.write(
            f"**Selected medication:** "
            f"{selected_medication['medication_name']} ({selected_id})"
        )

        stock_column, unit_column, status_column = st.columns(3)
        stock_column.metric(
            "Recorded stock",
            f"{float(selected_medication['current_stock']):g}",
        )
        unit_column.metric("Stock unit", stock_unit)
        status_column.metric(
            "Recorded availability",
            selected_medication["status"],
        )

        st.caption(
            "Recorded availability is not a physical stock confirmation or a clinical suitability assessment."
        )
        st.caption(
            "Inventory threshold context — separate from request Preview."
        )

        selected_review = build_replenishment_context(visible_medications).iloc[0]["ordering_review"]
        render_stock_review_badge(selected_review, prominent=True)

    render_substitute_notice()
    availability_display = attach_inventory_alternatives(visible_medications, Role.CLINICAL)
    render_medication_table(
        availability_display.reindex(columns=availability_columns),
        export_key="clinical_inventory",
    )

    if selected_medication is None:
        st.info("Select a medication above to preview or submit a request.")
    else:
        _render_request_form(selected_medication, stock_unit, has_unit=has_unit)

    _render_session_requests()

    st.subheader("Illustrative alternatives (information only)")
    st.caption(
        "Recorded relationships appear in the inventory table "
        "for red/yellow stock rows. They are synthetic and unvalidated. "
        "No substitute has been recommended, offered or approved."
    )
    
    render_feature_placeholder(
        "Availability alerts",
        "Alert thresholds remain to be confirmed. "
        "Displayed availability reflects recorded stock quantities only; "
        "it does not establish clinical suitability or usable expiry.",
    )