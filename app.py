""" Streamlit entry point for dashboard. """

import streamlit as st

from src.config import (
    APP_SUBTITLE,
    APP_TITLE,
    PROTOTYPE_NOTICE,
    ROLE_LABELS,
)

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
    
    # Display the confirmed labels while we build the foundation.
    st.subheader("Planned dashboard audiences")
    
    for label in ROLE_LABELS.values():
        st.markdown(f"- {label}")
        
if __name__ == "__main__":
    main()
    