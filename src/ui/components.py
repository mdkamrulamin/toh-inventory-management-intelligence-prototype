""" Reusable components for dashboard """

import pandas as pd
import streamlit as st
import plotly.express as px

from src.config import FIELD_LABELS
from src.data.schema import DATE_COLUMNS
from src.services.replenishment import build_replenishment_context
from src.ui.stock_indicators import (
    stock_review_cell_style,
    stock_review_style,
)
from src.ui.styles import style_stock_figure

def render_medication_table(
    medications: pd.DataFrame,
    title: str = "Sample medication inventory",
) -> None:
    """Format a display copy and color any inventory-review column."""
    
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
            
    # Display unavailable units explicitly without inventing a physical unit.
    if "stock_unit" in display_medications.columns:
        display_medications["stock_unit"] = (
            display_medications["stock_unit"].astype("string").str.strip()
            .replace("", pd.NA).fillna("N/A")
        )
    
    #Rename columns in the display copy
    display_medications = display_medications.rename(columns=FIELD_LABELS)
    table_content = display_medications
    review_column = FIELD_LABELS["ordering_review"]
    
    if review_column in display_medications.columns:
        table_content = display_medications.style.map(
            stock_review_cell_style,
            subset=[review_column],
        )
    
    #It provides an interactive table and these options hide the row index and fill the available width.
    st.dataframe(table_content, hide_index=True, width="stretch", row_height=40)
    
def render_stock_chart(medications: pd.DataFrame, key_prefix: str = "inventory") -> None:
    """Keep units separate and color quantities using shared review results."""
    """ Display the sample stock quantities, grouped by stock unit. """
    st.subheader("Sample stock quantities")
    st.caption(
        "Synthetic demonstration data. Quantities are shown separately for each stock unit."
    )
    
    # Reuse the same classification as the tables and selected-item badge.
    chart_context = build_replenishment_context(medications)
    units = chart_context["stock_unit"].astype("string").str.strip()
    has_unit = (units.notna() & units.ne("")).fillna(False)
    
    if (~has_unit).any():
        st.info(
            "Records without a stock unit remain in the tables but are omitted from stock charts."
            " No pysical unit is assumed."
        )
    chart_context = chart_context.loc[has_unit].copy()
    chart_context["stock_unit"] = units.loc[has_unit]
    
    if chart_context.empty:
        st.info("No stock units are available for charting.")
        return
    
    #Keep tablets, capsules, and vials in separate charts.
    for stock_unit, unit_data in chart_context.groupby("stock_unit", sort=False):
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
            hover_data=["medication_id", "ordering_review"],
            labels={
                "current_stock": f"Recorded stock ({stock_unit})",
                "medication_name": "Medication",
                "medication_id": "Medication ID",
                "ordering_review": "Inventory threshold review",
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
        # Apply shared typography first, then the stock-specific colors.
        style_stock_figure(figure)
        figure.update_traces(
            marker_color=[
                stock_review_style(label).foreground
                for label in chart_data["ordering_review"]
            ]
        )
        figure.update_layout(showlegend=False)
        
        # A zero-length bar cannot show its color, so add a visible red marker.
        zero_rows = chart_data.loc[
            chart_data["current_stock"].eq(0)
        ]
        if not zero_rows.empty:
            figure.add_scatter(
                x=[0] * len(zero_rows),
                y=zero_rows["medication_name"].to_list(),
                mode="markers",
                marker={
                    "size": 9,
                    "color": stock_review_style(
                        zero_rows["ordering_review"].iloc[0]
                    ).foreground,
                },
                customdata=zero_rows[
                    ["medication_id", "ordering_review"]
                ].to_numpy(),
                hovertemplate=(
                    "Medication: %{y}<br>"
                    "Medication ID: %{customdata[0]}<br>"
                    f"Recorded stock: 0 ({stock_unit})<br>"
                    "%{customdata[1]}<extra></extra>"
                ),
                cliponaxis=False,
                showlegend=False,
            )
        
        
        st.plotly_chart(
            figure, 
            width="stretch",
            key=f"{key_prefix}_stock_{stock_unit}",
        )
        
def render_feature_placeholder(title: str, description: str) -> None:
    """Display a clearly labelled section awaiting info or implementation"""
    st.subheader(title)
    st.info(f"N/A - illustrative placeholder. {description}")