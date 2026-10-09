""" Reusable components for dashboard """

import pandas as pd
import streamlit as st
import plotly.express as px

def render_medication_table(medications: pd.DataFrame) -> None:
    """ Display the synthetic medication inventory """
    st.subheader("Sample medication inventory")
    st.caption(
        "Synthetic demonstration data. Stock quntities use the unit shown in each row."
    )
    
    #It provides an interactive table and these options hide the row index and fill the available width.
    st.dataframe(medications, hide_index=True, width="stretch")
    
def render_stock_chart(medications: pd.DataFrame, key_prefix: str = "inventory") -> None:
    """ Display the sample stock quantities, grouped by stock unit. """
    st.subheader("Sample stock quantities")
    st.caption(
        "Synthetic demonstration data. Quantities are shown separately for each stock unit."
    )
    
    #Keep tablets, capsules, and vials in separate charts.
    for stock_unit, unit_data in medications.groupby("stock_unit", sort=False):
        chart_data = unit_data.sort_values("current_stock")
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
            height=320,
        )
        
        # Show all values even medications with zero stock
        figure.update_traces(
            textposition="outside",
            cliponaxis=False,
        )
        figure.update_xaxes(rangemode="tozero")
        st.plotly_chart(
            figure, 
            width="stretch",
            key=f"{key_prefix}_stock_{stock_unit}",
        )