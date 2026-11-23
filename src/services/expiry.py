"""Informational context for representative synthetic expiry dates."""

from datetime import date, datetime, timezone
import re

import pandas as pd

BEFORE_REFERENCE = "Before demo reference date"
ON_REFERENCE = "On demo reference date"
AFTER_REFERENCE = "After demo reference date"
MISSING_EXPIRY = "N/A — representative expiry unavailable"
MISSING_REFERENCE = "N/A — reference date unavailable"

EXPIRY_CONTEXT_COLUMNS = (
    "days_to_representative_expiry",
    "shelf_life_as_of",
    "representative_expiry_context",
    "expiry_context_note",
)

EXPIRY_LIMITATION = (
    "Representative calendar-date comparison only. "
    "No near-expiry threshold, batch-level FEFO or clinical usability assessment is made."
)

def demo_reference_date(started_time: str) -> date:
    """Use the demo's recorded UTC start date, never the current clock."""
    if not isinstance(started_time, str):
        raise ValueError("The demo start timestamp must be timezone-aware.")
    
    try:
        stamp = datetime.fromisoformat(started_time)

        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("Missing timezone.")

        return stamp.astimezone(timezone.utc).date()
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError("The demo start timestamp must be valid and timezone-aware.") from error
    
def _check_reference_date(as_of: date | None) -> None:
    if as_of is not None and (not isinstance(as_of, date) or isinstance(as_of, datetime)):
        raise ValueError("The expiry reference must be a calendar date or None.")
    
def _representative_date(value) -> date | None:
    """Read a calendar date without interpreting numbers as timestamps."""
    if isinstance(value, (datetime, date)):
        if pd.isna(value):
            return None

        return (
            value.date()
            if isinstance(value, datetime) else value
        )

    if isinstance(value, str):
        text = value.strip()

        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            try:
                return date.fromisoformat(text)
            except ValueError:
                pass

    return None

def describe_representative_expiry(value, *, as_of: date | None) -> dict:
    """Describe before/on/after-date context without deciding usability."""
    _check_reference_date(as_of)
    expiry = _representative_date(value)

    days = None

    if expiry is None:
        context = MISSING_EXPIRY
        note = ("The representative expiry date is missing or invalid. " + EXPIRY_LIMITATION)
    elif as_of is None:
        context = MISSING_REFERENCE
        note = ("A reference date was not supplied. " + EXPIRY_LIMITATION)
    else:
        days = (expiry - as_of).days
        context = (
            BEFORE_REFERENCE
            if days < 0
            else ON_REFERENCE
            if days == 0
            else AFTER_REFERENCE
        )
        note = EXPIRY_LIMITATION

    return {
        "expiry_date": (None if expiry is None else expiry.isoformat()),
        "days_to_representative_expiry": days,
        "shelf_life_as_of": (None if as_of is None else as_of.isoformat()),
        "representative_expiry_context": context,
        "expiry_context_note": note,
    }
    
def add_representative_expiry_context(medications: pd.DataFrame, *, as_of: date | None) -> pd.DataFrame:
    """Attach context to a copy while preserving existing source fields."""
    _check_reference_date(as_of)
    result = medications.copy(deep=True)

    if "expiry_date" not in result.columns:
        result["expiry_date"] = pd.Series(pd.NaT, index=result.index, dtype="datetime64[ns]")

    descriptions = [
        describe_representative_expiry(value, as_of=as_of)
        for value in result["expiry_date"]
    ]

    for column in EXPIRY_CONTEXT_COLUMNS:
        result[column] = pd.Series(
            [item[column] for item in descriptions],
            index=result.index,
            dtype=(
                "Int64"
                if column == "days_to_representative_expiry"
                else "string"
            ),
        )

    return result