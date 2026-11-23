"""Executive dashboard using prepared synthetic aggregates only."""

import pandas as pd
import streamlit as st

from src.ui.workflow_components import render_workflow_table

def _money(value) -> str:
    return "N/A" if value is None else f"{value:,.2f}"

def render_executive_view(*, summary: dict) -> None:
    """Display supported aggregate inventory and financial ABC context."""
    st.write("Review aggregate inventory exposure, recorded availability and illustrative financial ABC context.")
    st.caption(
        "All figures describe synthetic demonstration data. "
        "Each medication record represents one unique sample SKU."
    )
    
    analytics = summary["analytics"]
    review_counts = summary["stock_review_counts"]

    share = summary["zero_stock_share_percent"]
    share_text = ("N/A" if share is None else f"{share:.1f}%")
    supplier_count = summary["supplier_count"]

    sku_column, zero_column, share_column = st.columns(3)
    
    with sku_column:
        st.metric("Sample SKUs", summary["sku_count"])

    with zero_column:
        st.metric("Recorded zero-stock SKUs", summary["zero_stock_count"])

    with share_column:
        st.metric("Zero-stock share — snapshot", share_text)
        
    value_column, suppliers_column, monthly_column = st.columns(3)
    
    with value_column:
        st.metric(
            "Sample inventory value (CAD)",
            _money(summary["inventory_value_cad"]),
        )

    with suppliers_column:
        st.metric(
            "Known demo suppliers",
            "N/A" if supplier_count is None else supplier_count,
        )

    with monthly_column:
        st.metric(
            "Illustrative monthly consumption value (CAD/month)",
            _money(analytics["total_monthly_consumption_value_cad"]),
        )
        
    st.caption(
        "Inventory value uses current session stock and supplied synthetic CAD unit costs. "
        "Monthly consumption value uses supplied average monthly usage and costs; "
        "it describes an illustrative average month."
    )
    st.caption(
        "Zero-stock share is a current snapshot. It does not measure historical stockouts. "
        "Whole-population monetary totals remain N/A when required inputs or finite results are unavailable."
    )

    st.subheader("Illustrative stock-threshold context")
    
    review_column, above_column, unavailable_column = st.columns(3)

    with review_column:
        st.metric(
            "Positive-stock SKUs at/below supplied ROP",
            review_counts["at_or_below_rop"],
        )

    with above_column:
        st.metric(
            "Positive-stock SKUs above supplied ROP",
            review_counts["above_rop"],
        )

    with unavailable_column:
        st.metric(
            "Positive-stock SKUs without threshold context",
            review_counts["unavailable"],
        )
        
    st.caption(
        "These counts reuse the shared stock indicators and each medication's supplied illustrative "
        "reorder point and stock unit. Zero-stock SKUs are counted separately above. "
        "Missing threshold or unit context remains unavailable."
    )

    st.subheader("Illustrative financial ABC summary")
    st.caption(analytics["analysis_basis"])
    st.caption(analytics["abc_scope"])
    st.caption(
        f"Monthly-value inputs available: "
        f"{analytics['complete_abc_count']} of "
        f"{analytics['population_count']} SKUs. "
        "Financial ABC classes do not assign clinical urgency or VEN priority."
    )
    
    if not analytics["abc_available"]:
        st.info(analytics["abc_note"])

    category_table = pd.DataFrame(
        analytics["class_totals"],
        columns=[
            "abc_class",
            "sku_count",
            "monthly_consumption_value_cad",
            "abc_share_percent",
        ],
    )
    
    category_table["monthly_consumption_value_cad"] = (
        category_table["monthly_consumption_value_cad"].map(_money)
    )
    category_table["abc_share_percent"] = (
        category_table["abc_share_percent"].map(
            lambda value: ("N/A" if value is None else f"{value:.2f}")
        )
    )
    
    category_table = category_table.astype("object").where(pd.notna(category_table), "N/A")
    
    render_workflow_table(
        category_table.rename(
            columns={
                "abc_class": "Illustrative financial ABC class",
                "sku_count": "Sample SKUs",
                "monthly_consumption_value_cad": ("Monthly consumption value (CAD/month)"),
                "abc_share_percent": ("Full-population monthly value share (%)"),
            }
        ),
        table_key="executive_abc_summary",
    )
    
    st.caption(
        "N/A: inventory turnover, historical waste, supplier performance, cost trends and validated risk measures. "
        "Supporting historical records and agreed definitions are unavailable."
    )