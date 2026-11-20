"""Load illustrative relationships without inventing clinical alternatives."""

from collections.abc import Iterable
import csv
from hashlib import sha256
from io import StringIO
from pathlib import Path
import re

from src.config import SUBSTITUTE_RELATIONSHIPS_PATH
from src.data.substitute_schema import (
    RELATIONSHIP_COLUMNS,
    RELATIONSHIP_LABEL,
    RELATIONSHIP_PROVENANCE,
    RELATIONSHIP_VALIDATION_STATUS,
    REQUIRED_RELATIONSHIP_COLUMNS,
    SUBSTITUTE_INFORMATION_UNAVAILABLE,
    SubstituteFixture,
    SubstituteRelationship,
)

def _unavailable(path: Path, explanation: str, *, fingerprint: str | None = None) -> SubstituteFixture:
    """Represent unavailable fixture data without stopping the dashboard."""
    return SubstituteFixture(
        source_path=str(path),
        source_fingerprint=fingerprint,
        available=False,
        issues=(explanation,),
        notice=SUBSTITUTE_INFORMATION_UNAVAILABLE,
    )
    
def _known_medication_ids(values: Iterable[str]) -> frozenset[str]:
    """Require identifiers from an already validated medication dataset."""
    if isinstance(values, (str, bytes)):
        raise ValueError("Provide the medication IDs from the validated dataset.")
    
    identifiers = tuple(values)
    
    if not identifiers or any(
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        for value in identifiers
    ):
        raise ValueError("Medication IDs must be nonblank, normalized strings.")
    
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Medication IDs must be unique.")
    
    return frozenset(identifiers)

def load_substitute_relationships(path: str | Path = SUBSTITUTE_RELATIONSHIPS_PATH, *, medication_ids: Iterable[str]) -> SubstituteFixture:
    """Validate a fixture and return an immutable snapshot.

    Surrounding field whitespace is normalized before validation.
    Fixed labels and provenance must then match the accepted wording.

    Invalid records are ignored with diagnostics. File-level failures
    return unavailable information rather than fabricated relationships.
    """
    known_ids = _known_medication_ids(medication_ids)
    path = Path(path).expanduser().resolve()
    
    try:
        source = path.read_bytes()
    except OSError:
        return _unavailable(path, "The relationship fixture could not be read.")
    
    fingerprint = sha256(source).hexdigest()
    
    try:
        text = source.decode("utf-8-sig")
        records = list(csv.reader(StringIO(text, newline=""), strict=True))
    except (UnicodeError, csv.Error):
        return _unavailable(path, "The relationship fixture is not a readable UTF-8 CSV.", fingerprint=fingerprint)
    
    # Empty lines carry no relationship information.
    records = [
        record
        for record in records
        if record and any(value.strip() for value in record)
    ]
    
    if not records:
        return _unavailable(path, "The relationship fixture has no header.", fingerprint=fingerprint)
    
    header = tuple(value.strip() for value in records[0])
    
    if len(set(header)) != len(header):
        return _unavailable(path, "The relationship fixture contains duplicate headers.", fingerprint=fingerprint)
    
    missing = set(REQUIRED_RELATIONSHIP_COLUMNS) - set(header)
    unexpected = set(header) - set(RELATIONSHIP_COLUMNS)

    if missing or unexpected:
        return _unavailable(path, "The relationship fixture has missing required or unsupported columns.", fingerprint=fingerprint)
    
    relationships = []
    issues = []
    ignored_count = 0
    seen_ids = set()
    seen_pairs = set()
    fixture_version = None
    
    fixed_values = {
        "relationship_label": RELATIONSHIP_LABEL,
        "relationship_validation_status": RELATIONSHIP_VALIDATION_STATUS,
        "provenance": RELATIONSHIP_PROVENANCE,
    }
    
    for record_number, values in enumerate(records[1:], start=2):
        if len(values) != len(header):
            ignored_count += 1
            issues.append(f"Record {record_number} ignored: field count does not match the header.")
            continue
        row = {
            column: value.strip()
            for column, value in zip(header, values, strict=True) 
        }
        row.setdefault("comparison_note", "")
        
        reasons = []
        
        for column in REQUIRED_RELATIONSHIP_COLUMNS:
            if not row[column]:
                reasons.append(f"{column} is required")
                
        relationship_id = row["relationship_id"]
        source_id = row["source_medication_id"]
        candidate_id = row["candidate_medication_id"]
        version = row["fixture_version"]
        pair = (source_id, candidate_id)
        
        if not re.fullmatch(r"SR-[0-9]{3}", relationship_id):
            reasons.append("relationship_id must use the SR-nnn format")
            
        if source_id not in known_ids:
            reasons.append("source_medication_id is not in the medication dataset")
            
        if candidate_id not in known_ids:
            reasons.append("candidate_medication_id is not in the medication dataset")

        if source_id == candidate_id:
            reasons.append("source and candidate must be different medications")
            
        for column, expected in fixed_values.items():
            if row[column] != expected:
                reasons.append(f"{column} must use the fixed demonstration wording")

        if not re.fullmatch(r"v[1-9][0-9]*", version):
            reasons.append("fixture_version must use a version such as v1")
            
        if len(row["comparison_note"].splitlines()) > 1:
            reasons.append("comparison_note must be a single factual line")

        if relationship_id in seen_ids:
            reasons.append("relationship_id repeats an earlier valid record")

        if pair in seen_pairs:
            reasons.append("directed pair repeats an earlier valid record")

        if (fixture_version is not None and version != fixture_version):
            reasons.append("fixture_version differs from the first valid record")

        if reasons:
            ignored_count += 1
            issues.append(
                f"Record {record_number} ignored: "
                + "; ".join(reasons)
                + "."
            )
            continue

        relationship = SubstituteRelationship(
            relationship_id=relationship_id,
            source_medication_id=source_id,
            candidate_medication_id=candidate_id,
            relationship_label=row["relationship_label"],
            relationship_validation_status=(
                row["relationship_validation_status"]
            ),
            provenance=row["provenance"],
            comparison_note=row["comparison_note"],
            fixture_version=version,
        )

        relationships.append(relationship)
        seen_ids.add(relationship_id)
        seen_pairs.add(pair)

        if fixture_version is None:
            fixture_version = version

    return SubstituteFixture(
        source_path=str(path),
        source_fingerprint=fingerprint,
        available=True,
        relationships=tuple(relationships),
        fixture_version=fixture_version,
        ignored_row_count=ignored_count,
        issues=tuple(issues),
        notice=(
            f"Illustrative relationships loaded: "
            f"{len(relationships)}. "
            f"Rows ignored: {ignored_count}."
        ),
    )
            
            
            
        
            
        
    
    