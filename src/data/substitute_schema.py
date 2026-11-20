"""Contracts for illustrative, unvalidated relationship fixtures."""

from dataclasses import dataclass

RELATIONSHIP_LABEL = "Illustrative alternative"

RELATIONSHIP_VALIDATION_STATUS = "Unvalidated - synthetic demonstration only"

RELATIONSHIP_PROVENANCE = "Synthetic demo entry created by the project team. No TOH or clinical source"

SUBSTITUTE_INFORMATION_UNAVAILABLE = "Substitute information unavailable"

RELATIONSHIP_COLUMNS = (
    "relationship_id",
    "source_medication_id",
    "candidate_medication_id",
    "relationship_label",
    "relationship_validation_status",
    "provenance",
    "comparison_note",
    "fixture_version",
)

REQUIRED_RELATIONSHIP_COLUMNS = tuple(
    column
    for column in RELATIONSHIP_COLUMNS
    if column != "comparison_note"
)

@dataclass(frozen=True)
class SubstituteRelationship:
    relationship_id: str
    source_medication_id: str
    candidate_medication_id: str
    relationship_label: str
    relationship_validation_status: str
    provenance: str
    comparison_note: str
    fixture_version: str
    
@dataclass(frozen=True)
class SubstituteFixture:
    """An immutable result ready to retain within one demo run."""

    source_path: str
    source_fingerprint: str | None
    available: bool
    relationships: tuple[SubstituteRelationship, ...] = ()
    fixture_version: str | None = None
    ignored_row_count: int = 0
    issues: tuple[str, ...] = ()
    notice: str = ""