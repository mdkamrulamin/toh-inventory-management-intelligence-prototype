""" Reusable components for dashboard """

import pandas as pd
import streamlit as st

def render_medication_table(medications: pd.DataFrame) -> None:
    """ Display the synthetic medication inventory """
    st.subheader("Sample medication inventory")
    st.caption(
        "Synthetic demonstration data. Stock quntities use the unit shown in each row."
    )
    
    #It provides an interactive table and these options hide the row index and fill the available width.
    st.dataframe(medications, hide_index=True, width="stretch")