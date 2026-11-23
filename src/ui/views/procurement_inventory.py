"""Procurement shortage feedback and independent inventory monitoring."""

import pandas as pd
import streamlit as st

from src.services.analytics import (
    ABC_SCOPE,
    ANALYSIS_BASIS,
    LEAD_TIME_BASIS,
    build_stock_analytics,
)
from src.services.reporting import prepare_report_display
from src.ui.components import (
    render_medication_table, 
    render_stock_chart,
)
from src.ui.handoff_panels import render_procurement_handoffs
from src.ui.stock_indicators import render_stock_review_legend
from src.ui.order_panels import render_procurement_orders
from src.services.substitute_queries import ALTERNATIVES_COLUMN
from src.services.workflow_models import Role
from src.ui.substitute_panels import (
    attach_inventory_alternatives,
    render_substitute_notice,
)

def render_procurement_inventory_view(medications: pd.DataFrame) -> None:
    """Show linked shortages and supported synthetic stock analytics."""
    st.write(
        "Review linked demo shortages, recorded stock, consumption, "
        "costs, suppliers and illustrative inventory analytics."
    )
    
    render_procurement_handoffs(medications)
    render_procurement_orders()
    
    st.subheader("Routine inventory monitoring")
    st.caption(
        "This monitoring is available without a Clinical request. "
        "Threshold flags do not submit requests or place orders."
    )
    
    #Retain stock units so quantities and costs have clear meaning.
    procurement_columns = [
        "medication_name",
        "current_stock",
        "stock_unit",
        "average_monthly_consumption",
        "expiry_date",
        "unit_cost",
        "supplier",
        "status",
        ALTERNATIVES_COLUMN,
    ]
    
    st.caption(
        "Consumption uses supplied stock units per illustrative month; costs are CAD per stock unit. Expiry dates are synthetic."  
    )
    
    render_substitute_notice()
    
    procurement_display = attach_inventory_alternatives(medications, Role.PROCUREMENT)
    
    render_medication_table(
        prepare_report_display(
            procurement_display.reindex(columns=procurement_columns)
        ),
        export_key="procurement_inventory",
    )
    analytics = build_stock_analytics(medications)
    replenishment_columns = [
        "medication_id",
        "medication_name",
        "current_stock",
        "stock_unit",
        "average_monthly_consumption",
        "reorder_point",
        "safety_stock_level",
        "lead_time_days",
        "stock_coverage_months",
        "reorder_gap",
        "lead_time_demand",
        "ordering_review",
        "analytics_note",
        "lead_time_basis",
    ]
    
    st.caption(
        "ROP, safety stock and lead time are supplied illustrative "
        "parameters. Coverage and threshold gaps use current session stock. "
        "Coverage is not a predicted stockout date; the gap is not an "
        "order recommendation. Safety stock does not replace the supplied ROP."
    )
    st.caption(LEAD_TIME_BASIS)
    
    render_medication_table(
        prepare_report_display(analytics.rows.reindex(columns=replenishment_columns)),
        title="Illustrative replenishment context",
        export_key="procurement_replenishment",
    )
    
    render_stock_review_legend()
    
    render_stock_chart(medications, key_prefix="procurement_inventory")
    
    st.caption(ANALYSIS_BASIS)
    st.caption(ABC_SCOPE)
    st.caption(
        "Financial ABC does not establish clinical priority. Dosage form remains separate from ABC class."
    )
    total = analytics.summary["total_monthly_consumption_value_cad"]
    st.metric(
        "Illustrative monthly consumption value (CAD/month)",
        "N/A" if total is None else f"{total:,.2f}",
    )
    
    st.caption(
        f"Complete ABC inputs: "
        f"{analytics.summary['complete_abc_count']} of "
        f"{analytics.summary['population_count']} records. "
        f"{analytics.summary['abc_note']}"
    )
    
    abc_columns = [
        "medication_id",
        "medication_name",
        "category",
        "stock_unit",
        "average_monthly_consumption",
        "unit_cost",
        "monthly_consumption_value_cad",
        "abc_share_percent",
        "abc_cumulative_share_percent",
        "abc_class",
        "analytics_note",
        "abc_note",
        "analysis_basis",
        "abc_scope",
    ]
    
    abc_rows = analytics.rows.sort_values(
        ["monthly_consumption_value_cad", "medication_id"],
        ascending=[False, True],
        na_position="last",
    )
    
    render_medication_table(
        prepare_report_display(abc_rows.reindex(columns=abc_columns)),
        title="Illustrative ABC — average monthly consumption value",
        export_key="procurement_abc",
    )
    
    
    
    st.caption(
        "N/A: calculated safety stock, optimized reorder points "
        "and EOQ/Newsvendor recommendations. Required demand history, "
        "ordering/holding costs and agreed model assumptions are "
        "unavailable. Synthetic orders use the explicit order "
        "controls above."
    )
    