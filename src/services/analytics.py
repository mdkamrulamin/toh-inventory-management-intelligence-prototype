"""Read-only analytics for synthetic medication inventory.

ABC uses supplied average monthly consumption and CAD unit costs.
Stock-dependent calculations use the inventory snapshot passed by the caller.
No source data, workflow state or historical feedback is modified.
"""

from dataclasses import dataclass
from decimal import Decimal, DecimalException, localcontext
from sys import float_info

import pandas as pd

from src.services.replenishment import build_replenishment_context

ANALYSIS_BASIS = (
    "Illustrative average month; supplied usage in stock units/month "
    "and supplied cost in CAD/stock unit. No observed calendar period."
)

ABC_SCOPE = "Complete loaded medication population, before display filters."

LEAD_TIME_BASIS = (
    "Illustrative lead-time demand assumes a 30-day month; it is not a purchase quantity or validated forecast."
)

NUMERIC_INPUTS = (
    "current_stock",
    "unit_cost",
    "average_monthly_consumption",
    "reorder_point",
    "safety_stock_level",
    "lead_time_days",
)

CALCULATED_COLUMNS = (
    "monthly_consumption_value_cad",
    "recorded_inventory_value_cad",
    "stock_coverage_months",
    "reorder_gap",
    "lead_time_demand",
    "abc_share_percent",
    "abc_cumulative_share_percent",
    "abc_class",
    "analytics_note",
    "abc_note",
    "analysis_basis",
    "abc_scope",
    "lead_time_basis",
)

MAX_NUMBER = Decimal(str(float_info.max))

@dataclass(frozen=True)
class StockAnalytics:
    """Detached row calculations and population-level aggregates."""
    rows: pd.DataFrame
    summary: dict
    
def _number(row: pd.Series, column: str) -> Decimal | None:
    """Preserve missing inputs and reject invalid supplied numbers."""
    raw = row.get(column)
    if raw is None or pd.isna(raw):
        return None
    if isinstance(raw, str) and not raw.strip():
        return None
    
    try:
        value = Decimal(str(raw))
    except (DecimalException, ValueError, TypeError) as error:
        raise ValueError(f"{column} must contain finite nonnegative numbers.") from error
    
    if (not value.is_finite() or value < 0 or value > MAX_NUMBER):
        raise ValueError(f"{column} must contain finite nonnegative numbers.")
    
    return value

def _calculate(operation) -> Decimal | None:
    """Withhold results outside the dashboard's finite numeric range."""
    try:
        value = operation()
    except (DecimalException, OverflowError, ZeroDivisionError):
        return None
    
    if not value.is_finite() or abs(value) > MAX_NUMBER:
        return None
    
    return value

def build_stock_analytics(medications: pd.DataFrame) -> StockAnalytics:
    """Calculate against a complete, validated inventory population.

    Call before display filtering. Decimal arithmetic and unrounded cumulative values determine ABC classes.
    """
    
    required = {"medication_id", "medication_name", "current_stock"}
    missing = required - set(medications.columns)
    if missing:
        raise ValueError(f"Missing analytics fields: {sorted(missing)}")
    
    rows = medications.copy(deep=True).reset_index(drop=True)
    
    for column in ("medication_id", "medication_name"):
        valid = all(
            isinstance(value, str) and bool(value.strip())
            for value in rows[column]
        )
        if not valid:
            raise ValueError(f"{column} must contain nonempty text.")
    
    normalized_ids = rows["medication_id"].str.strip()
    if normalized_ids.duplicated().any():
        raise ValueError("Medication IDs must be unique.")
    
    for column in NUMERIC_INPUTS:
        if column not in rows.columns:
            rows[column] = pd.Series(pd.NA, index=rows.index, dtype="Float64")
    if "stock_unit" not in rows.columns:
        rows["stock_unit"] = pd.Series(pd.NA, index=rows.index, dtype="string")
            
    inputs = []
    for _, row in rows.iterrows():
        values = {
            column: _number(row, column)
            for column in NUMERIC_INPUTS
        }
        if values["current_stock"] is None:
            raise ValueError("current_stock is required for inventory analytics.")
        inputs.append(values)
        
    for column in CALCULATED_COLUMNS:
        rows[column] = pd.Series([None] * len(rows), index=rows.index, dtype="object")
        
    # Reuse the established zero-stock and threshold rules.
    rows["ordering_review"] = (build_replenishment_context(rows)["ordering_review"])
    rows["analysis_basis"] = ANALYSIS_BASIS
    rows["abc_scope"] = ABC_SCOPE
    rows["lead_time_basis"] = LEAD_TIME_BASIS
    
    # Input floats have already been parsed by the loader. Converting their decimal text avoids binary floating-point cutoff decisions.
    with localcontext() as context:
        context.prec = 64
        monthly_values = []
        for index, values in enumerate(inputs):
            stock = values["current_stock"]
            cost = values["unit_cost"]
            usage = values["average_monthly_consumption"]
            reorder = values["reorder_point"]
            safety = values["safety_stock_level"]
            lead = values["lead_time_days"]
            unit = rows.at[index, "stock_unit"]
            has_unit = (isinstance(unit, str) and bool(unit.strip()))
            
            notes = []
            if cost == 0:
                notes.append("Supplied unit cost is zero.")
            if usage == 0:
                notes.append("Supplied monthly usage is zero.")
            if safety is None:
                notes.append("Supplied illustrative safety stock is unavailable.")
                
            calculations = (
                (
                    "monthly_consumption_value_cad",
                    has_unit and cost is not None and usage is not None,
                    lambda: usage * cost,
                    "Monthly value requires a stock unit, cost and usage.",
                ),
                (
                    "recorded_inventory_value_cad",
                    has_unit and cost is not None,
                    lambda: stock * cost,
                    "Inventory value requires a stock unit and cost.",
                ),
                (
                    "stock_coverage_months",
                    has_unit and usage is not None and usage > 0,
                    lambda: stock / usage,
                    "Coverage requires a stock unit and positive usage.",
                ),
                (
                    "reorder_gap",
                    has_unit and reorder is not None,
                    lambda: max(reorder - stock, Decimal(0)),
                    "Threshold gap requires a stock unit and supplied ROP.",
                ),
                (
                    "lead_time_demand",
                    has_unit and usage is not None and lead is not None,
                    lambda: usage / Decimal(30) * lead,
                    "Lead-time demand requires a stock unit, usage and lead time.",
                ),
            )
            
            for column, available, operation, explanation in calculations:
                if not available:
                    notes.append(f"N/A: {explanation}")
                    continue
                result = _calculate(operation)
                rows.at[index, column] = result
                
                if result is None:
                    notes.append(f"N/A: {column} exceeds the finite calculation range.")
            
            monthly_values.append(rows.at[index, "monthly_consumption_value_cad"])
            rows.at[index, "analytics_note"] = (
                " ".join(notes)
                if notes else "Required row inputs are available."
            )
            
        population_count = len(rows)
        complete_count = sum(
            value is not None
            for value in monthly_values
        )
        total = None
        if population_count and complete_count == population_count:
            total = _calculate(lambda: sum(monthly_values, Decimal(0)))
            
        if not population_count:
            abc_note = "N/A: no medication records."
        elif complete_count != population_count:
            abc_note = (
                f"N/A: {complete_count} of {population_count} records "
                "have complete, finite ABC inputs. Complete-population shares and classes are withheld."
            )
        elif total is None:
            abc_note = "N/A: total monthly consumption value exceeds the finite calculation range."
        elif total == 0:
            abc_note = "N/A: complete-population monthly consumption value is zero."
        else:
            abc_note = (
                "Complete-population ABC; cumulative share after inclusion; "
                "80% belongs to A and 95% belongs to B. "
                "The highest positive-value item remains A."
            )
        
        abc_available = total is not None and total > 0
        if abc_available:
            order = sorted(
                range(population_count),
                key=lambda index: (
                    -monthly_values[index],
                    normalized_ids.iloc[index],
                ),
            )
            cumulative = Decimal(0)
            
            for rank, index in enumerate(order):
                value = monthly_values[index]
                cumulative += value
                rows.at[index, "abc_share_percent"] = (value / total * Decimal(100))
                rows.at[index, "abc_cumulative_share_percent"] = (cumulative / total * Decimal(100))
                # Compare unrounded cumulative values
                if value == 0:
                    classification = "C"
                elif rank == 0 or cumulative * Decimal(100) <= total * Decimal(80):
                    classification = "A"
                elif cumulative * Decimal(100) <= total * Decimal(95):
                    classification = "B"
                else:
                    classification = "C"
                    
                rows.at[index, "abc_class"] = classification
                
        rows["abc_note"] = abc_note
        class_totals = []
        for classification in ("A", "B", "C"):
            count = None
            value = None
            share = None
            
            if abc_available:
                selected = rows["abc_class"].eq(classification)
                count = int(selected.sum())
                value = sum(rows.loc[selected, "monthly_consumption_value_cad"], Decimal(0))
                share = value / total * 100
                
            class_totals.append(
                {
                    "abc_class": classification,
                    "sku_count": count,
                    "monthly_consumption_value_cad": value,
                    "abc_share_percent": share,
                }
            )
    
    return StockAnalytics(
        rows=rows,
        summary={
            "population_count": population_count,
            "complete_abc_count": complete_count,
            "total_monthly_consumption_value_cad": total,
            "abc_available": abc_available,
            "abc_note": abc_note,
            "class_totals": class_totals,
            "analysis_basis": ANALYSIS_BASIS,
            "abc_scope": ABC_SCOPE,
        }
    )
            