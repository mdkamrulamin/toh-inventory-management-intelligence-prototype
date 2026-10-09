"""Clinical dashboard view for doctors and nurses."""

import pandas as pd

from src.ui.components import render_medication_table, render_stock_chart

def render_clinical_view(medications: pd.DataFrame) -> None:
    """REnder the initial clinical view using shared demo components."""
    render_medication_table(medications)
    render_stock_chart(medications, key_prefix="clinical")
    