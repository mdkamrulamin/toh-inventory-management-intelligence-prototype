"""Read-only substitute information and Pharmacist review history.

Queries use the frozen relationship fixture and current session inventory.
They do not record decisions, alter stock or change workflow status.
"""

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime

import pandas as pd

from src.data.substitute_schema import (
    SUBSTITUTE_INFORMATION_UNAVAILABLE,
    SubstituteFixture,
)
from src.services import substitute_reviews as reviews
from src.services import workflow as wf
from src.services.workflow_models import (
    RequestStatus,
    Role,
    WorkflowError,
)

ALTERNATIVES_COLUMN = "alternatives_illustrative"

ALTERNATIVES_HELP = (
    "Illustrative synthetic relationships for demonstration. Not clinically validated "
    "and not a recommendation. Indicators use recorded session stock."
)

INFORMATION_BANNER = (
    "Information only. No substitute has been recommended, offered or approved. "
    "Clinical suitability is decided by the pharmacist and prescriber, outside this demo."
)

NOT_ASSESSED_LINE = (
    "Suitability, dose conversion and fulfilment quantity "
    "have not been assessed."
)

DECISION_LABELS = {
    "kept_for_consideration": "Kept for consideration (demo)",
    "do_not_pursue": "Not pursued (demo)",
    "needs_more_review": "Needs more review (demo)",
}

INVENTORY_READER_ROLES = {
    Role.CLINICAL,
    Role.PHARMACIST,
    Role.PROCUREMENT,
}

def _reader_role(value, allowed):
    try:
        role = Role(value)
    except (ValueError, TypeError) as error:
        raise WorkflowError("wrong_role", "Unknown substitute-information reader role.") from error

    if role not in allowed:
        raise WorkflowError("wrong_role", "This role does not receive this substitute information.")

    return role

def get_fixture_info(state) -> dict:
    """Return display-safe diagnostics about the run's frozen fixture."""
    fixture = state.substitute_fixture

    if not isinstance(fixture, SubstituteFixture):
        return {
            "available": False,
            "fixture_version": None,
            "source_fingerprint": None,
            "relationship_count": 0,
            "ignored_row_count": 0,
            "issues": [],
            "notice": SUBSTITUTE_INFORMATION_UNAVAILABLE,
        }

    return deepcopy(
        {
            "available": fixture.available,
            "fixture_version": fixture.fixture_version,
            "source_fingerprint": fixture.source_fingerprint,
            "relationship_count": len(fixture.relationships),
            "ignored_row_count": fixture.ignored_row_count,
            "issues": list(fixture.issues),
            "notice": fixture.notice,
        }
    )
    
def _relationships(state, source_id):
    info = get_fixture_info(state)

    if not info["available"]:
        return ()

    selected = []

    for relationship in state.substitute_fixture.relationships:
        if relationship.source_medication_id != source_id:
            continue

        _, validated = reviews._fixture_relationship(state, source_id, relationship.relationship_id)
        selected.append(validated)

    return tuple(selected)

def _alternatives_text(state, source_id, source_indicator):
    """Keep inventory cells compact; details remain in Pharmacist review."""
    if not get_fixture_info(state)["available"]:
        return SUBSTITUTE_INFORMATION_UNAVAILABLE

    if source_indicator not in {"Red", "Yellow"}:
        return "—"

    relationships = _relationships(state, source_id)

    if not relationships:
        return "No relationship recorded"

    names = [
        str(
            wf._medication(
                state,
                relationship.candidate_medication_id,
            )["medication_name"]
        )
        for relationship in relationships[:2]
    ]

    text = "; ".join(names)

    if len(relationships) > 2:
        text += f"; +{len(relationships) - 2} more"

    return text

def get_inventory_alternatives(state, role) -> pd.DataFrame:
    """Provide a separate information table without changing inventory."""
    _reader_role(role, INVENTORY_READER_ROLES)
    rows = []

    for medication_id in state.inventory["medication_id"]:
        medication = wf._medication(state, medication_id)
        snapshot = reviews._candidate_snapshot(state, medication_id)

        rows.append(
            {
                "medication_id": medication_id,
                "medication_name": medication["medication_name"],
                "current_stock": snapshot.recorded_stock,
                "stock_unit": snapshot.stock_unit,
                "status": medication["status"],
                "ordering_review": snapshot.indicator_text,
                ALTERNATIVES_COLUMN: _alternatives_text(state, medication_id, snapshot.indicator),
            }
        )

    return pd.DataFrame(rows).copy(deep=True)

def _text_or_none(value):
    return (
        value.strip()
        if isinstance(value, str) and value.strip()
        else None
    )
    
def _stock_details(state, medication_id, as_of):
    """Explicit comparison fields; costs and valuation are excluded."""
    row = wf._medication(state, medication_id)
    snapshot = reviews._candidate_snapshot(state, medication_id)

    expiry_value = row.get("expiry_date")
    expiry = None

    if expiry_value is not None and not pd.isna(expiry_value):
        try:
            expiry = pd.Timestamp(expiry_value).date()
        except (TypeError, ValueError, OverflowError):
            expiry = None

    return {
        "medication_id": medication_id,
        "medication_name": row["medication_name"],
        "category": _text_or_none(row.get("category")),
        **asdict(snapshot),
        "expiry_date": None if expiry is None else expiry.isoformat(),
        "days_to_representative_expiry": None if expiry is None else (expiry - as_of).days,
        "shelf_life_as_of": as_of.isoformat(),
        "primary_location": _text_or_none(row.get("primary_location")),
        "supplier": _text_or_none(row.get("supplier")),
        "lead_time_days": wf._optional_number(row, "lead_time_days"),
        "supplier_reliability": "N/A — delivery history is unavailable.",
    }
    
def get_request_alternatives(state, request_id, role) -> dict:
    """Return live candidate facts and current decision eligibility."""
    _reader_role(role, {Role.PHARMACIST})
    request = wf._request(state, request_id)

    # A labelled session date keeps shelf-life context reproducible.
    as_of = datetime.fromisoformat(state.started_time).date()
    source = _stock_details(state, request.medication_id, as_of)
    fixture_info = get_fixture_info(state)

    shortage = None
    comparison_error = None

    try:
        _, quantity, _, stock = wf._available(state, request)
        shortage = quantity > stock
    except WorkflowError as error:
        comparison_error = str(error)

    relationships = _relationships(state, request.medication_id)

    decisions_enabled = (
        request.status == RequestStatus.UNDER_REVIEW
        and shortage is True
        and request.substitution_allowed is True
        and fixture_info["available"]
        and bool(relationships)
    )

    candidates = []

    for relationship in relationships:
        inventory = _stock_details(state, relationship.candidate_medication_id, as_of)
        latest = reviews._latest_review(state, request_id, relationship.relationship_id)

        unit_difference_note = ""
        if (source["stock_unit"] is not None and inventory["stock_unit"] is not None and source["stock_unit"] != inventory["stock_unit"]):
            unit_difference_note = (
                "Unit differs from the requested medication. "
                "No unit conversion is modelled."
            )

        latest_decision = None if latest is None else str(latest.decision)

        candidates.append(
            {
                "relationship_id": relationship.relationship_id,
                "relationship_label": relationship.relationship_label,
                "relationship_validation_status": relationship.relationship_validation_status,
                "provenance": relationship.provenance,
                "comparison_note": relationship.comparison_note,
                "fixture_version": relationship.fixture_version,
                "inventory": inventory,
                "unit_difference_note": unit_difference_note,
                "latest_review_id": None if latest is None else latest.review_id,
                "latest_decision": latest_decision,
                "decision_status": (
                    "Candidate - pending pharmacist review"
                    if latest is None
                    else DECISION_LABELS[latest_decision]
                ),
                "can_keep": (decisions_enabled and inventory["recorded_stock"] > 0),
                "can_do_not_pursue": decisions_enabled,
                "can_more_review": decisions_enabled,
            }
        )

    if not fixture_info["available"]:
        message = SUBSTITUTE_INFORMATION_UNAVAILABLE
    elif comparison_error is not None:
        message = comparison_error
    elif shortage is False:
        message = "Recorded stock covers this request, so alternatives are not needed here."
    elif not relationships:
        message = (
            "No relationship recorded for "
            f"{request.medication_name} "
            f"({request.medication_id}). "
            "No alternative is suggested."
        )
    elif request.substitution_allowed is not True:
        message = reviews.PREFERENCE_DISABLED_MESSAGE
    elif request.status != RequestStatus.UNDER_REVIEW:
        message = "Review decisions are available only while the request is Under review."
    else:
        message = "Inspect the recorded information and enter a reason for any informational demo decision."

    return deepcopy(
        {
            "run_id": state.run_id,
            "revision": state.revision,
            "request_id": request_id,
            "request_status": str(request.status),
            "request_quantity": request.quantity,
            "request_unit": request.unit,
            "substitution_allowed": request.substitution_allowed,
            "source": source,
            "shortage": shortage,
            "decisions_enabled": decisions_enabled,
            "fixture_available": fixture_info["available"],
            "as_of_date": as_of.isoformat(),
            "message": message,
            "banner": INFORMATION_BANNER,
            "not_assessed_line": NOT_ASSESSED_LINE,
            "candidate_order_note": "Candidates appear in fixture order. The order is not a ranking.",
            "candidates": candidates,
        }
    )
    
def list_substitute_reviews(state, role, *, request_id=None) -> list[dict]:
    """Keep Pharmacist history readable independently of request status."""
    _reader_role(role, {Role.PHARMACIST})

    if request_id is not None:
        wf._request(state, request_id)

    rows = []

    for record in state.substitute_reviews.values():
        if request_id is not None and record.request_id != request_id:
            continue

        if record.run_id != state.run_id:
            raise WorkflowError("invalid_state", "A review belongs to a different demo run.")

        wf._request(state, record.request_id)
        source = wf._medication(state, record.source_medication_id)
        candidate = wf._medication(state, record.candidate_medication_id)
        snapshot = record.inventory_at_review

        rows.append(
            {
                "review_id": record.review_id,
                "run_id": record.run_id,
                "request_id": record.request_id,
                "source_medication_id": record.source_medication_id,
                "source_medication_name": source["medication_name"],
                "candidate_medication_id": record.candidate_medication_id,
                "candidate_medication_name": candidate["medication_name"],
                "relationship_id": record.relationship_id,
                "decision": str(record.decision),
                "decision_label": DECISION_LABELS[str(record.decision)],
                "reason": record.reason,
                "recorded_time": record.recorded_time,
                "recorded_by": record.recorded_by,
                "recorded_by_role": str(record.recorded_by_role),
                "candidate_stock_at_review": snapshot.recorded_stock,
                "candidate_unit_at_review": snapshot.stock_unit,
                "candidate_indicator_at_review": snapshot.indicator,
                "candidate_indicator_text_at_review": snapshot.indicator_text,
                "fixture_version": record.fixture_version,
                "fixture_fingerprint": record.fixture_fingerprint,
            }
        )

    return deepcopy(rows)