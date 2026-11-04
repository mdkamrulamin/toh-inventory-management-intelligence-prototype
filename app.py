""" Streamlit entry point for dashboard. """

import streamlit as st

from src.config import (
    APP_TITLE,
    PROTOTYPE_NOTICE,
    ROLE_LABELS,
    SAMPLE_MEDICATIONS_PATH,
)
from src.services.workflow_models import Role, WorkflowError
from src.ui.icons import role_icon_data_uri
from src.ui.navigation import render_role_tabs
from src.ui.session import (
    ensure_demo_session,
    read_inventory,
    read_inventory_summary,
    replace_dataset_callback,
    reset_demo_callback,
    take_notice,
)
from src.ui.styles import (
    apply_dashboard_styles,
    render_brand_header,
    render_role_heading,
)
from src.ui.views import ROLE_RENDERERS

def main() -> None:
    """Configure presentation and render roles from the shared demo session."""
    
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
        
        clinical_tab_label = (
            f"![]({role_icon_data_uri('clinical')}) "
            f"{ROLE_LABELS['clinical']}"
        )
        
        notice = take_notice()
        if notice is not None:
            if notice["kind"] == "success":
                st.success(notice["message"])
            else:
                st.error(notice["message"])
                
        try:
            ensure_demo_session(SAMPLE_MEDICATIONS_PATH)
        except WorkflowError as error:
            if error.code == "dataset_mismatch":
                st.warning(str(error))
            else:
                st.error(f"Unable to start the demo: {error}")
                
            st.caption(
                "Starting a new demo clears existing synthetic "
                "requests and restores stock from the configured dataset."
            )
            st.button(
                "Start new demo with configured dataset",
                key="workflow_start_configured_demo",
                on_click=replace_dataset_callback,
                kwargs={
                    "source_path": SAMPLE_MEDICATIONS_PATH,
                    "clinical_tab_label": clinical_tab_label,
                },
            )
            return
        except (OSError, ValueError) as error:
            st.error(f"Unable to load medication data: {error}")
            return
        
        st.button(
            "Reset demo",
            key="workflow_reset_demo",
            on_click=reset_demo_callback,
            kwargs={
                "clinical_tab_label": clinical_tab_label,
            },
            help=(
                "Restore starting stock and clear synthetic requests and selections."
            ),
        )
        st.caption(
            "Demo data is temporary. Reset restores starting stock and clears synthetic requests."
        )
            
        role_tabs = render_role_tabs()
        
        for role_id, role_tab in zip(ROLE_LABELS, role_tabs, strict=True):
            with role_tab:
                render_role_heading(role_id)
                
                if role_id == "executive":
                    # Executive receives aggregate data only.
                    ROLE_RENDERERS[role_id](summary=read_inventory_summary())
                else:
                    # Every role reads a detached projection of the same active session inventory.
                    ROLE_RENDERERS[role_id](read_inventory(Role(role_id)))
            
  
if __name__ == "__main__":
    main()
    