""" Shared navigation for the demo dashboard """

import streamlit as st

from src.config import ROLE_LABELS
from src.ui.icons import role_icon_data_uri

def render_role_tabs():
    """Show an illustrated icon alongside each short role label."""
    tab_labels = [
        f"![]({role_icon_data_uri(role_id)}) {label}"
        for role_id, label in ROLE_LABELS.items()
    ]
    
    # Preserve the existing tab execution behavior for this styling ticket.
    # State-aware navigation for later
    return st.tabs(tab_labels)

