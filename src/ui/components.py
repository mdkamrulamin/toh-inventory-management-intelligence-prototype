""" Reusable components for dashboard """

import pandas as pd
import streamlit as st
import plotly.express as px

from src.config import FIELD_LABELS
from src.data.schema import DATE_COLUMNS
from src.ui.styles import style_stock_figure

def render_medication_table(
    medications: pd.DataFrame,
    title: str = "Sample medication inventory",
) -> None:
    """ Display readable medication labels while preserving internal field names."""
    st.subheader(title)
    st.caption(
        "Synthetic demonstration data. Stock quantities use the unit shown in each row."
    )
    
    display_medications = medications.copy()
    
    # Format dates only in the presentation copy.
    # Missing or unparseable display values become N/A, never NaT.
    for column in DATE_COLUMNS:
        if column in display_medications.columns:
            display_dates = pd.to_datetime(
                display_medications[column],
                format="%Y-%m-%d",
                errors="coerce",
            )
            display_medications[column] = (
                display_dates.dt.strftime("%Y-%m-%d").fillna("N/A")
            )
    
    #Rename columns in the display copy
    display_medications = display_medications.rename(columns=FIELD_LABELS)
    
    #It provides an interactive table and these options hide the row index and fill the available width.
    st.dataframe(display_medications, hide_index=True, width="stretch", row_height=40)
    
def render_stock_chart(medications: pd.DataFrame, key_prefix: str = "inventory") -> None:
    """ Display the sample stock quantities, grouped by stock unit. """
    st.subheader("Sample stock quantities")
    st.caption(
        "Synthetic demonstration data. Quantities are shown separately for each stock unit."
    )
    
    #Keep tablets, capsules, and vials in separate charts.
    for stock_unit, unit_data in medications.groupby("stock_unit", sort=False):
        # Retain zero-stock rows so their medication labels remain visible.
        chart_data = unit_data.sort_values("current_stock")
        row_count = len(chart_data)
        
        # Reserve room for titles/axes, then add space per medication.
        chart_height = max(190, 110 + 46 * row_count)
        
        figure = px.bar(
            chart_data,
            x="current_stock",
            y="medication_name",
            orientation="h",
            text="current_stock",
            labels={
                "current_stock": f"Current stock ({stock_unit})",
                "medication_name": "Medication",
            },
            title=f"Stock unit: {stock_unit}",
            height=chart_height,
        )
        
        # Show all values even medications with zero stock
        figure.update_traces(
            textposition="outside",
            cliponaxis=False,
            width=0.6,
        )
        figure.update_layout(
            margin=dict(l=20, r=60, t=45, b=40),
            title_font_size=16,
        )
        
        # Leave space for outside value labels, including zero-stock groups.
        maximum_stock = float(chart_data["current_stock"].max())
        
        figure.update_xaxes(
            range=[0, max(1.0, maximum_stock * 1.15)],
            automargin=True,
        )
        figure.update_yaxes(
            categoryorder="array",
            categoryarray=chart_data["medication_name"].to_list(),
            automargin=True,
        )
        style_stock_figure(figure)
        
        st.plotly_chart(
            figure, 
            width="stretch",
            key=f"{key_prefix}_stock_{stock_unit}",
        )
        
def render_feature_placeholder(title: str, description: str) -> None:
    """Display a clearly labelled section awaiting info or implementation"""
    st.subheader(title)
    st.info(f"N/A - illustrative placeholder. {description}")