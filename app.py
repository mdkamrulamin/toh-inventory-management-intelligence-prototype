""" Streamlit entry point for dashboard. """

import streamlit as st

from src.config import (
    APP_TITLE,
    PROTOTYPE_NOTICE,
    ROLE_LABELS,
)
from src.data.loader import load_medications
from src.ui.navigation import render_role_tabs
from src.ui.styles import (
    apply_dashboard_styles,
    render_brand_header,
    render_role_heading,
)
from src.ui.views import ROLE_RENDERERS

def main() -> None:
    """Configure shared presentation, load data, and render four roles."""
    
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="💊",
        layout="wide",
    )
    
    apply_dashboard_styles()
    
    # Scope custom presentation to this explicitly keyed container.
    with st.container(key="dashboard"):
        render_brand_header()
        
        # Keep one clear global notice
        st.info(PROTOTYPE_NOTICE)
        
        st.write(
            "A medication-focused dashboard for clinical availability, "
            "inventory operations, and executive oversight."
        )
        st.caption("Demo audience views - no sign-in or access control.")
        try:
            medications = load_medications()
        except (OSError, ValueError) as error:
            st.error(f"Unable to load medication data: {error}")
            return
    
        role_tabs = render_role_tabs()
        
        for role_id, role_tab in zip(ROLE_LABELS, role_tabs, strict=True):
            with role_tab:
                render_role_heading(role_id)
                ROLE_RENDERERS[role_id](medications)
            
  
if __name__ == "__main__":
    main()
    