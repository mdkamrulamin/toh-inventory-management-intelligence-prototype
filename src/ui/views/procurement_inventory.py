"""Procurement and inventory/ordering dashboard view"""

import pandas as pd

from src.ui.components import render_medication_table, render_stock_chart

def render_procurement_inventory_view(medications: pd.DataFrame) -> None:
    """Render the initial procurement and inventory view."""
    render_medication_table(medications)
    render_stock_chart(medications, key_prefix="procurement_inventory")
    