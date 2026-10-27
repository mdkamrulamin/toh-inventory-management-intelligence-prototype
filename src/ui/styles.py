"""Shared visual presentation for the existing four-view dashboard."""

from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from src.config import (
    APP_SUBTITLE,
    APP_TITLE,
    PROJECT_ROOT,
    ROLE_CONTEXT,
    ROLE_LABELS,
)
from src.ui.icons import role_icon_data_uri

STYLESHEET_PATH = Path(__file__).with_name("styles.css")

def apply_dashboard_styles() -> None:
    """Load the shared stylesheet without JavaScript or external assets."""
    st.html(STYLESHEET_PATH)
    
def render_brand_header() -> None:
    """Display institutional logos around the project title and subtitle."""
    logo_directory = PROJECT_ROOT / "assets" / "logos"
    
    with st.container(key="brand_header"):
        hospital_column, title_column, uni_column = st.columns(
            [1.25, 5.5, 1.25],
            gap="medium",
            vertical_alignment="center",
        )
        with hospital_column:
            st.image(
                logo_directory / "toh.png",
                width="stretch",
                alt="The Ottawa Hospital",
            )
        with title_column:
            st.title(APP_TITLE, anchor=False)
            st.caption(APP_SUBTITLE)
        with uni_column:
            st.image(
                logo_directory / "uottawa.png",
                width="stretch",
                alt="University of Ottawa",
            )
            
    
    
def render_role_heading(role_id: str) -> None:
    """Display a recognizable role banner with its full audience label."""
    # This explicit key provides the stable class used by styles.css.
    with st.container(key=f"role_header_{role_id}"):
        st.header(
            f"![]({role_icon_data_uri(role_id)}) "
            f"{ROLE_LABELS[role_id]}",
            anchor=False,
        )
        st.write(ROLE_CONTEXT[role_id])
        
def style_stock_figure(figure: go.Figure) -> None:
    """Improve chart readability without changing quantities or grouping."""
    figure.update_layout(
        font={
            "family": "Arial, sans-serif",
            "size": 15,
            "color": "#1F2937",
        },
        title_font={
            "size": 18,
            "color": "#1F2937",
        },
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        margin={"l": 20, "r": 65, "t": 50, "b": 45},   
    )
    # Use one neutral bar color. #Change later
    figure.update_traces(marker_color="#4B6584")
    
    figure.update_xaxes(
        tickfont={"size": 14},
        title_font={"size": 15},
        gridcolor="#E5E7EB",
        automargin=True,
    )
    figure.update_yaxes(
        tickfont={"size": 15},
        title_font={"size": 15},
        automargin=True,
    )
    