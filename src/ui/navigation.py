""" Shared navigation for the demo dashboard """

import streamlit as st

from src.config import ROLE_LABELS

# def render_role_selector() -> str:
#     """Display audience labels and return the selected stable role ID. """
#     with st.sidebar:
#         st.title("Dashboard navigation")
#         st.caption("Demo role selection - no sign-in or access control.")
        
#         #Store the stable ID while displaying readable label.
#         #format_func lets the dropdown display a readable label while returning its internal ID, such as "clinical"
#         selected_role = st.selectbox(
#             "Choose your role",
#             options=list(ROLE_LABELS),
#             format_func=lambda role_id: ROLE_LABELS[role_id],
#             key="selected_role",
#         )
    
#     return selected_role

def render_role_tabs():
    """Create tab containers in the same order as the configured role IDs."""
    return st.tabs(list(ROLE_LABELS.values()))