""" Shared navigation for the demo dashboard """

import streamlit as st

from src.config import ROLE_LABELS
from src.ui.icons import role_icon_data_uri

def _reset_clinical_lookup_on_role_change(clinical_tab_label: str) -> None:
    """Clear the Clinical selection when another role is chosen."""
    active_tab = st.session_state.get("dashboard_role_tabs")
    
    if active_tab != clinical_tab_label:
        st.session_state["clinical_medication_lookup"] = None

def render_role_tabs():
    """Show an illustrated icon alongside each short role label."""
    role_ids = list(ROLE_LABELS)
    
    tab_labels = [
        f"![]({role_icon_data_uri(role_id)}) {ROLE_LABELS[role_id]}"
        for role_id in role_ids
    ]
    
    clinical_tab_label = tab_labels[role_ids.index("clinical")]
    
    # Track the active tab and rerun after an actual tab change. The callback runs before the app reruns.
     # Clear only the Clinical lookup; other views keep their state.
    return st.tabs(
        tab_labels,
        key="dashboard_role_tabs",
        on_change=_reset_clinical_lookup_on_role_change,
        args=(clinical_tab_label,),
    )

