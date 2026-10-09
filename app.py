""" Streamlit entry point for dashboard. """

import streamlit as st

from src.config import (
    APP_SUBTITLE,
    APP_TITLE,
    PROTOTYPE_NOTICE,
    ROLE_LABELS,
)
from src.data.loader import load_medications
from src.ui.views import ROLE_RENDERERS
from src.ui.navigation import render_role_tabs

def main() -> None:
    """ COnfigure the application and render the initial landing page. """
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="💊",
        layout="wide",
    )
    
    st.title(APP_TITLE)
    st.caption(APP_SUBTITLE)
    st.info(PROTOTYPE_NOTICE)
    
    st.write(
        "A medication-focused dashboard for clinical availability, "
        "inventory operations, and executive oversight."
    )
        
    try:
        medications = load_medications()
    except (OSError, ValueError) as error:
        st.error(f"Unable to load medication data: {error}")
        return
    
    st.caption("Demo audience views - no sign-in or access control.")
    role_tabs = render_role_tabs()
    
    # Match each stable role ID to its tab container.
    
    for role_id, role_tab in zip(ROLE_LABELS, role_tabs, strict=True):
        with role_tab:
            st.subheader(ROLE_LABELS[role_id])
            ROLE_RENDERERS[role_id](medications)
        
    
        
if __name__ == "__main__":
    main()
    