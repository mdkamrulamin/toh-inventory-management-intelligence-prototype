"""Descriptive inventory summaries calculated from synthetic inputs."""

from math import isfinite

import pandas as pd

def summarize_inventory(medications: pd.DataFrame) -> dict[str, int | float | None]:
    """Summarize validated single-record-per-medication data."""
    sku_count = len(medications)
    zero_stock_count = int(medications["current_stock"].eq(0).sum())
    
    zero_stock_share = (
        zero_stock_count / sku_count * 100
        if sku_count
        else None
    )
    
    # Count known suppliers; missing supplier info stays unavailable.
    supplier_count = None
    if (
        "supplier" in medications.columns
        and medications["supplier"].notna().any()
    ):
        supplier_count = int(medications["supplier"].nunique())
        
    # Monetary values can be combined only when quantity/cost compatibility is established for every selected record.
    inventory_value = None
    
    has_units = False
    if "stock_unit" in medications.columns:
        units = medications["stock_unit"].astype("string").str.strip()
        has_units = bool((units.notna() & units.ne("")).fillna(False).all())
        
    if (sku_count and has_units and "unit_cost" in medications.columns and medications["unit_cost"].notna().all() and medications["current_stock"].notna().all()):
        row_values = (medications["current_stock"] * medications["unit_cost"])
        
        if (row_values.notna().all() and row_values.map(isfinite).all()):
            calculated_value = float(row_values.sum())
            
            if isfinite(calculated_value):
                inventory_value = calculated_value
            
    return {
        "sku_count": sku_count,
        "zero_stock_count": zero_stock_count,
        "zero_stock_share_percent": zero_stock_share,
        "supplier_count": supplier_count,
        "inventory_value_cad": inventory_value,
    }