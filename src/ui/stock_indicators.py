"""Shared inventory-review colors, badges, and explanatory legend."""

from dataclasses import dataclass

import streamlit as st

from src.services.replenishment import (
    ABOVE_STOCK_LABEL,
    MISSING_REORDER_LABEL,
    MISSING_UNIT_LABEL,
    REVIEW_STOCK_LABEL,
    ZERO_STOCK_LABEL,
)

@dataclass(frozen=True)
class ReviewStyle:
    """One reusable visual representation for an inventory-review result."""
    name: str
    badge_color: str
    foreground: str
    background: str
    
_NEUTRAL_STYLE = ReviewStyle(
    "Neutral",
    "gray",
    "#4B5563",
    "#F3F4F6",
)

_REVIEW_STYLES = {
    ZERO_STOCK_LABEL: ReviewStyle(
        "Red",
        "red",
        "#991B1B",
        "#FEE2E2",
    ),
    REVIEW_STOCK_LABEL: ReviewStyle(
        "Yellow",
        "yellow",
        "#92400E",
        "#FEF3C7",
    ),
    ABOVE_STOCK_LABEL: ReviewStyle(
        "Green",
        "green",
        "#166534",
        "#DCFCE7",
    ),
    MISSING_REORDER_LABEL: _NEUTRAL_STYLE,
    MISSING_UNIT_LABEL: _NEUTRAL_STYLE,
}

def stock_review_style(label: object) -> ReviewStyle:
    """Return a neutral presentation for any unrecognized display value."""
    if not isinstance(label, str):
        return _NEUTRAL_STYLE
    
    return _REVIEW_STYLES.get(label, _NEUTRAL_STYLE)

def stock_review_cell_style(label: object) -> str:
    """Provide centrally defined cell styling for native Streamlit tables."""
    style = stock_review_style(label)
    
    return (
        f"background-color: {style.background}; "
        f"color: {style.foreground}; "
        "font-weight: 600;" 
    )
    
def render_stock_review_badge(label: str) -> None:
    """Pair the inventory-review label with its color name and badge."""
    style = stock_review_style(label)
    
    st.badge(
        f"{style.name} — {label}",
        color=style.badge_color,
    )

def render_stock_review_legend() -> None:
    """Explain colors without presenting them as clinical classifications."""
    st.markdown("**Recorded-stock review legend**")
    
    examples = (
        ("Zero recorded stock", ZERO_STOCK_LABEL),
        ("At/below reorder point", REVIEW_STOCK_LABEL),
        ("Above reorder point", ABOVE_STOCK_LABEL),
        ("Information unavailable", MISSING_REORDER_LABEL),
    )
    
    for column, (title, label) in zip(st.columns(4), examples, strict=True):
        with column:
            style = stock_review_style(label)
            st.badge(
                f"{style.name} — {title}",
                color=style.badge_color,
            )
            
            if label == MISSING_REORDER_LABEL:
                st.caption("No threshold comparison when the reorder point or stock unit is unavailable.")
            else:
                st.caption(label)
                
    st.caption(
        "Flags describe recorded synthetic stock against illustrative "
        "reorder points. They do not establish physical availability, "
        "clinical urgency, optimal inventory, or request fulfilment."
    )