"""Connect stable role IDs to their dashboard view functions."""

from src.ui.views.clinical import render_clinical_view
from src.ui.views.executive import render_executive_view
from src.ui.views.pharmacist import render_pharmacist_view
from src.ui.views.procurement_inventory import render_procurement_inventory_view
from src.ui.views.warehouse import render_warehouse_view
from src.ui.views.reporting import render_reporting_view

ROLE_RENDERERS = {
    "clinical": render_clinical_view,
    "pharmacist": render_pharmacist_view,
    "procurement_inventory": render_procurement_inventory_view,
    "warehouse": render_warehouse_view,
    "executive": render_executive_view,
    "reporting": render_reporting_view,
}