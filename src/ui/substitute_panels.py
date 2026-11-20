"""Read-only alternatives displays and human-led demo review controls."""

import pandas as pd
import streamlit as st

from src.services.substitute_queries import (
    ALTERNATIVES_COLUMN,
    ALTERNATIVES_HELP,
    NOT_ASSESSED_LINE,
)
from src.services.workflow_models import (
    Role,
    SubstituteDecision,
)
from src.ui.components import render_medication_table
from src.ui.session import (
    get_session_info,
    read_inventory_alternatives,
    read_request_alternatives,
    read_substitute_fixture_info,
    read_substitute_reviews,
    take_notice,
)
from src.ui.stock_indicators import render_stock_review_badge
from src.ui.substitute_actions import (
    substitute_reason_key,
    substitute_review_callback,
)
from src.ui.workflow_components import (
    display_value,
    render_workflow_table,
)

HISTORY_LABELS = {
    "review_id": "Demo review ID",
    "request_id": "Request ID",
    "source_medication_id": "Requested medication ID",
    "source_medication_name": "Requested medication",
    "candidate_medication_id": "Candidate medication ID",
    "candidate_medication_name": "Illustrative candidate",
    "relationship_id": "Relationship ID",
    "decision_label": "Informational demo decision",
    "reason": "Demo reason",
    "candidate_stock_at_review": "Candidate stock at review",
    "candidate_unit_at_review": "Candidate unit at review",
    "candidate_indicator_at_review": "Candidate indicator at review",
    "candidate_indicator_text_at_review": "Indicator meaning at review",
    "recorded_by": "Demo actor",
    "recorded_by_role": "Demo role",
    "recorded_time": "Recorded time (UTC)",
    "fixture_version": "Fixture version",
    "fixture_fingerprint": "Fixture fingerprint",
    "run_id": "Demo run ID",
}

def render_substitute_notice():
    """Keep availability and ignored-row diagnostics visible."""
    info = read_substitute_fixture_info()

    if not info["available"]:
        st.warning("Substitute information unavailable")
        st.caption("Existing inventory and medication-request functions remain available.")
    elif info["ignored_row_count"]:
        st.warning(info["notice"])
        with st.expander("Relationship fixture validation details"):
            for issue in info["issues"]:
                st.write(issue)

    st.caption(ALTERNATIVES_HELP)
    st.caption(
        "Relationships remain fixed during this demo run. "
        "Reset demo reloads the fixture and clears review records."
    )
    
def attach_inventory_alternatives(medications, role):
    """Add display text to a copy without changing inventory fields."""
    alternatives = read_inventory_alternatives(role).set_index("medication_id")

    display = medications.copy(deep=True)
    display[ALTERNATIVES_COLUMN] = (
        display["medication_id"]
        .map(alternatives[ALTERNATIVES_COLUMN])
        .fillna("Substitute information unavailable")
    )
    return display

def render_pharmacist_inventory():
    """Always show the full inventory independently of request selection."""
    render_substitute_notice()

    inventory = read_inventory_alternatives(Role.PHARMACIST)

    render_medication_table(
        inventory,
        title="Inventory and illustrative alternatives",
        export_key="pharmacist_inventory_alternatives",
    )
    st.caption(
        "A dash means this inventory column is filled only for red/yellow stock rows. "
        "It does not establish whether a clinical alternative exists."
    )
    
def build_candidate_comparison(context, candidate):
    """Prepare explicit, cost-free comparison rows for display/export."""
    source = context["source"]
    other = candidate["inventory"]

    def stock_text(item):
        return (
            f"{item['recorded_stock']:,g} "
            f"{item['stock_unit'] or 'N/A'}"
        )

    def indicator_text(item):
        return f"{item['indicator']} — {item['indicator_text']}"

    def shelf_life_text(item):
        days = item["days_to_representative_expiry"]
        return (
            "N/A"
            if days is None
            else f"{days} days; as of {item['shelf_life_as_of']}"
        )

    rows = [
        (
            "Medication",
            (
                f"{source['medication_name']} "
                f"({source['medication_id']})"
            ),
            (
                f"{other['medication_name']} "
                f"({other['medication_id']})"
            ),
        ),
        ("Dosage form", source["category"], other["category"]),
        ("Stock unit", source["stock_unit"], other["stock_unit"]),
        (
            "Recorded stock (synthetic)",
            stock_text(source),
            stock_text(other),
        ),
        (
            "Inventory indicator",
            indicator_text(source),
            indicator_text(other),
        ),
        (
            "Representative expiry",
            source["expiry_date"],
            other["expiry_date"],
        ),
        (
            "Days to representative expiry",
            shelf_life_text(source),
            shelf_life_text(other),
        ),
        (
            "Representative location",
            source["primary_location"],
            other["primary_location"],
        ),
        ("Demo supplier", source["supplier"], other["supplier"]),
        (
            "Supplied lead time (days)",
            source["lead_time_days"],
            other["lead_time_days"],
        ),
        (
            "Supplier reliability",
            source["supplier_reliability"],
            other["supplier_reliability"],
        ),
        (
            "Substitute group / governance reference",
            "—",
            "N/A — no governed substitute group is recorded.",
        ),
        (
            "Strength / conversion context",
            "Strength is only part of the recorded medication name.",
            "No dose or unit conversion is modelled.",
        ),
        ("Recorded relationship", "—", candidate["relationship_label"]),
        (
            "Relationship validation",
            "—",
            candidate["relationship_validation_status"],
        ),
        ("Relationship provenance", "—", candidate["provenance"]),
        ("Comparison note", "—", candidate["comparison_note"]),
        ("Candidate demo status", "—", candidate["decision_status"]),
        ("Assessment scope", NOT_ASSESSED_LINE, NOT_ASSESSED_LINE),
        ("Demonstration boundary", context["banner"], context["banner"]),
    ]

    return pd.DataFrame(
        [
            {
                "Information": label,
                "Requested medication": display_value(source_value),
                "Illustrative candidate": display_value(candidate_value),
            }
            for label, source_value, candidate_value in rows
        ]
    )
    
@st.fragment
def render_alternative_review(request_id, expected_run_id, expected_revision):
    """Keep reason typing local; business changes refresh the full app."""
    info = get_session_info()

    if (info.run_id != expected_run_id or info.revision != expected_revision):
        st.rerun()

    notice = take_notice()
    if notice is not None:
        st.toast(
            notice["message"],
            icon=(
                "✅"
                if notice["kind"] == "success"
                else "⚠️"
            ),
        )

    context = read_request_alternatives(request_id, Role.PHARMACIST)

    if context["request_status"] != "under_review":
        return

    st.subheader("Alternatives (illustrative, information only)")
    st.info(context["banner"])
    st.caption(context["not_assessed_line"])

    if context["shortage"] is False:
        st.info(context["message"])
        return

    st.caption(context["candidate_order_note"])
    st.info(context["message"])

    if not context["candidates"]:
        return

    for candidate in context["candidates"]:
        relationship_id = candidate["relationship_id"]
        inventory = candidate["inventory"]

        st.write(
            f"**Illustrative candidate: "
            f"{inventory['medication_name']} "
            f"({inventory['medication_id']})**"
        )
        st.write(f"**Demo review status:** {candidate['decision_status']}")
        render_stock_review_badge(inventory["indicator_text"])

        comparison = build_candidate_comparison(context, candidate)
        render_workflow_table(
            comparison,
            table_key=(
                f"pharmacist_candidate_{info.run_id}_"
                f"{request_id}_{relationship_id}"
            ),
        )

        st.caption(
            "Representative expiry is information only. "
            "It does not establish usable stock or clinical suitability."
        )

        if candidate["unit_difference_note"]:
            st.caption(candidate["unit_difference_note"])

        reason_key = substitute_reason_key(info.run_id, request_id, relationship_id)
        reason = st.text_input(
            "Illustrative review reason",
            key=reason_key,
            live="0ms",
            disabled=not context["decisions_enabled"],
            placeholder="Enter a reason for this demo decision",
            help=(
                "Required for every informational decision. "
                "Do not enter patient information."
            ),
        )
        has_reason = bool((reason or "").strip())

        callback_args = {
            "request_id": request_id,
            "relationship_id": relationship_id,
            "expected_run_id": info.run_id,
            "expected_revision": info.revision,
        }

        keep_column, no_column, more_column = st.columns(3)

        with keep_column:
            st.button(
                "Keep for pharmacist consideration (demo)",
                key=(
                    f"workflow_action_substitute_keep_{info.run_id}_"
                    f"{request_id}_{relationship_id}"
                ),
                disabled=not (
                    has_reason and candidate["can_keep"]
                ),
                help=(
                    "The candidate has no recorded stock."
                    if inventory["recorded_stock"] == 0
                    else "Records consideration only; no substitute is applied."
                ),
                on_click=substitute_review_callback,
                kwargs={
                    **callback_args,
                    "decision": (
                        SubstituteDecision.KEPT_FOR_CONSIDERATION
                    ),
                },
            )

        with no_column:
            st.button(
                "Do not pursue in demo",
                key=(
                    f"workflow_action_substitute_no_{info.run_id}_"
                    f"{request_id}_{relationship_id}"
                ),
                disabled=not (
                    has_reason
                    and candidate["can_do_not_pursue"]
                ),
                on_click=substitute_review_callback,
                kwargs={
                    **callback_args,
                    "decision": SubstituteDecision.DO_NOT_PURSUE,
                },
            )

        with more_column:
            st.button(
                "Needs more review (demo)",
                key=(
                    f"workflow_action_substitute_more_{info.run_id}_"
                    f"{request_id}_{relationship_id}"
                ),
                disabled=not (
                    has_reason and candidate["can_more_review"]
                ),
                on_click=substitute_review_callback,
                kwargs={
                    **callback_args,
                    "decision": SubstituteDecision.NEEDS_MORE_REVIEW,
                },
            )

        st.caption(
            "These decisions do not change the requested medication, quantity, urgency, status or stock. "
            "Continue the normal request workflow separately."
        )


def render_substitute_history(*, title, table_key, request_id=None):
    """Render history independently of the actionable queue."""
    st.subheader(title)

    records = read_substitute_reviews(Role.PHARMACIST, request_id=request_id)

    if not records:
        st.info("No illustrative alternative reviews recorded.")
        return

    table = pd.DataFrame(records).reindex(
        columns=list(HISTORY_LABELS)
    )

    # Keep optional values explicit and table transport consistent.
    for column in table.columns:
        table[column] = table[column].map(display_value)

    table = table.rename(columns=HISTORY_LABELS)
    table["Review scope"] = (
        "Informational synthetic review only. No substitute was applied or clinically authorized."
    )

    render_workflow_table(table, table_key=table_key)
    st.caption(
        "Stock and indicators are snapshots from the recording time. "
        "Later receipts or fulfillment do not rewrite these records."
    )