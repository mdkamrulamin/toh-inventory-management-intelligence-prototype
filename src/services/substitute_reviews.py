"""Pure human-led review of illustrative substitute relationships.

Review records are informational. They do not change requests,
inventory, urgency, orders, receipts or handoff queues.
"""

from copy import deepcopy
from dataclasses import replace
import re

import pandas as pd

from src.data.substitute_schema import (
    RELATIONSHIP_LABEL,
    RELATIONSHIP_PROVENANCE,
    RELATIONSHIP_VALIDATION_STATUS,
    SUBSTITUTE_INFORMATION_UNAVAILABLE,
    SubstituteFixture,
)
from src.services import workflow as wf
from src.services.replenishment import (
    ABOVE_STOCK_LABEL,
    REVIEW_STOCK_LABEL,
    ZERO_STOCK_LABEL,
    build_replenishment_context,
)
from src.services.workflow_models import (
    CandidateInventorySnapshot,
    RequestStatus,
    Role,
    SubstituteDecision,
    SubstituteReviewInput,
    SubstituteReviewRecord,
    WorkflowError,
    WorkflowResult,
)

PREFERENCE_DISABLED_MESSAGE = (
    "The requester did not allow consideration of substitutes for this request. Review decisions are disabled."
)

def _require_fixture(state):
    fixture = state.substitute_fixture
    if (not isinstance(fixture, SubstituteFixture) or not fixture.available):
        raise WorkflowError("substitute_information_unavailable", SUBSTITUTE_INFORMATION_UNAVAILABLE)
    
    if (not isinstance(fixture.source_fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fixture.source_fingerprint)):
        raise WorkflowError("invalid_state", "The relationship fixture fingerprint is inconsistent.")
    
    return fixture

def _fixture_relationship(state, source_medication_id, relationship_id):
    """Resolve one valid directed relationship from the frozen fixture."""
    fixture = _require_fixture(state)
    relationship_id = wf._text(relationship_id, "Relationship ID", "unknown_relationship")
    
    matches = [
        relationship
        for relationship in fixture.relationships
        if relationship.relationship_id == relationship_id
    ]

    if len(matches) != 1:
        raise WorkflowError("unknown_relationship", "The relationship does not identify one recorded candidate.")

    relationship = matches[0]
    
    if relationship.source_medication_id != source_medication_id:
        raise WorkflowError("invalid_relationship", "The relationship does not belong to this request's medication.")

    same_pair = [
        row
        for row in fixture.relationships
        if (row.source_medication_id == relationship.source_medication_id
            and row.candidate_medication_id == relationship.candidate_medication_id)
    ]
    
    if (
        len(same_pair) != 1
        or relationship.source_medication_id
        == relationship.candidate_medication_id
        or relationship.relationship_label != RELATIONSHIP_LABEL
        or relationship.relationship_validation_status
        != RELATIONSHIP_VALIDATION_STATUS
        or relationship.provenance != RELATIONSHIP_PROVENANCE
        or relationship.fixture_version != fixture.fixture_version
        or not re.fullmatch(r"v[1-9][0-9]*", relationship.fixture_version)
    ):
        raise WorkflowError("invalid_relationship", "The recorded relationship is inconsistent with the fixture.")
    
    wf._medication(state, relationship.source_medication_id)
    wf._medication(state, relationship.candidate_medication_id)

    return fixture, relationship

def _candidate_snapshot(state, medication_id):
    """Use candidate stock and its own threshold without conversion."""
    row = wf._medication(state, medication_id)
    stock = wf._number(row["current_stock"], "Candidate recorded stock", "invalid_stock")

    unit_value = row.get("stock_unit")
    unit = (
        unit_value.strip()
        if isinstance(unit_value, str) and unit_value.strip() else None
    )
    reorder_point = wf._optional_number(row, "reorder_point")
    context = pd.DataFrame(
        [
            {
                "medication_id": row["medication_id"],
                "medication_name": row["medication_name"],
                "current_stock": stock,
                "stock_unit": (
                    pd.NA if unit is None else unit
                ),
            }
        ]
    )
    # Explicit nullable numeric dtype keeps missing thresholds comparable without treating them as zero.
    context["reorder_point"] = pd.Series(
        [reorder_point],
        index=context.index,
        dtype="Float64",
    )
    
    indicator_text = str(build_replenishment_context(context).iloc[0]["ordering_review"])
    indicator = {
        ZERO_STOCK_LABEL: "Red",
        REVIEW_STOCK_LABEL: "Yellow",
        ABOVE_STOCK_LABEL: "Green",
    }.get(indicator_text, "Neutral")
    
    return CandidateInventorySnapshot(
        recorded_stock=stock,
        stock_unit=unit,
        indicator=indicator,
        indicator_text=indicator_text,
    )
    
def _latest_review(state, request_id, relationship_id):
    """Canonical records retain successful append order."""
    for record in reversed(tuple(state.substitute_reviews.values())):
        if (record.request_id == request_id and record.relationship_id == relationship_id):
            return record

    return None

def _check_review_time(state, stamp):
    """A current-inventory snapshot cannot predate recorded changes."""
    recorded_times = [
        state.started_time,
        *[
            request.updated_time
            for request in state.requests.values()
        ],
        *[
            order.updated_time
            for order in state.orders.values()
        ],
        *[
            receipt.received_time
            for receipt in state.receipts.values()
        ],
        *[
            review.recorded_time
            for review in state.substitute_reviews.values()
        ],
    ]

    if stamp < max(recorded_times):
        raise WorkflowError("invalid_time", "Review time precedes a recorded session update.")
    
def record_substitute_review(state, request_id, inputs, context) -> WorkflowResult:
    """Append one guarded informational decision, without routing changes."""
    # Context/revision checks happen before duplicate detection.
    request, stamp = wf._prepare(state, request_id, context, Role.PHARMACIST, {RequestStatus.UNDER_REVIEW})
    _check_review_time(state, stamp)
    
    if not isinstance(inputs, SubstituteReviewInput):
        raise WorkflowError("invalid_input", "Use valid substitute-review inputs.")

    try:
        decision = SubstituteDecision(inputs.decision)
    except (ValueError, TypeError) as error:
        raise WorkflowError("invalid_input", "Select one of the three informational demo decisions.") from error

    reason = wf._reason(inputs.reason)
    
    if request.substitution_allowed is not True:
        raise WorkflowError("substitution_not_allowed", PREFERENCE_DISABLED_MESSAGE)

    fixture, relationship = _fixture_relationship(state, request.medication_id, inputs.relationship_id)
    
    latest = _latest_review(state, request_id, relationship.relationship_id)
    if (latest is not None and latest.decision == decision and latest.reason == reason):
        raise WorkflowError("duplicate_action", "This demo decision and reason were already recorded.")
    
    _, requested_quantity, _, source_stock = wf._available(state, request)

    if requested_quantity <= source_stock:
        raise WorkflowError("alternatives_not_needed", "Recorded stock covers this request, so alternatives are not needed here.")
    
    snapshot = _candidate_snapshot(state, relationship.candidate_medication_id)

    if (decision == SubstituteDecision.KEPT_FOR_CONSIDERATION and snapshot.recorded_stock <= 0):
        raise WorkflowError("candidate_out_of_stock", "The candidate has no recorded stock.")
    
    number = wf._quantity(state.next_substitute_review_number)
    review_id = f"SUB-REV-{number:04d}"

    if review_id in state.substitute_reviews:
        raise WorkflowError("invalid_state", "The next substitute-review ID is already present.")
    
    record = SubstituteReviewRecord(
        review_id=review_id,
        run_id=state.run_id,
        request_id=request_id,
        source_medication_id=request.medication_id,
        candidate_medication_id=(
            relationship.candidate_medication_id
        ),
        relationship_id=relationship.relationship_id,
        decision=decision,
        reason=reason,
        recorded_time=stamp,
        inventory_at_review=snapshot,
        fixture_version=relationship.fixture_version,
        fixture_fingerprint=fixture.source_fingerprint,
    )
    
    # Build the complete result before the session adapter publishes it.
    candidate = deepcopy(state)
    records = dict(candidate.substitute_reviews)
    records[review_id] = record

    candidate = replace(
        candidate,
        substitute_reviews=records,
        next_substitute_review_number=number + 1,
        revision=state.revision + 1,
    )
    
    return WorkflowResult(
        state=candidate,
        request_id=request_id,
        changed=True,
        message=(
            f"Demo review {review_id} recorded. "
            "No substitute was applied; request and stock are unchanged."
        ),
        substitute_review_id=review_id,
    )
    
    