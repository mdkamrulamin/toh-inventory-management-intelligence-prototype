"""Executive dashboard view."""

import pandas as pd

from src.ui.components import render_medication_table, render_stock_chart

def render_executive_view(medications: pd.DataFrame) -> None:
    """Render the initial executive view using shared demo components."""
    render_medication_table(medications)
    render_stock_chart(medications, key_prefix="executive")