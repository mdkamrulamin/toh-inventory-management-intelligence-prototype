"""Integration checks for analytics, reports and active session inventory."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from io import StringIO
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from src.config import PROJECT_ROOT
from src.data.loader import load_medications
from src.services import workflow as wf
from src.services import workflow_queries as queries
from src.services.analytics import build_stock_analytics
from src.services.reporting import (
    InventoryFilters,
    build_inventory_report,
    prepare_report_display,
)
from src.services.replenishment import (
    REVIEW_STOCK_LABEL,
    ZERO_STOCK_LABEL,
)
from src.services.summary import summarize_inventory
from src.services.workflow_models import (
    Role,
    SubmitRequestInput,
    SupplyFeedbackInput,
    WorkflowError,
)


class AnalyticsIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.clock = datetime(
            2026, 11, 13, 12, 0,
            tzinfo=timezone.utc,
        )
        self.make_state()

    def tick(self):
        self.clock += timedelta(seconds=1)
        return self.clock

    def make_state(self, filename="sample_medications_extended.csv"):
        self.path = PROJECT_ROOT / "data" / filename
        self.source_bytes = self.path.read_bytes()

        self.state = wf.initialize_demo(
            load_medications(self.path),
            dataset_path=str(self.path),
            dataset_fingerprint=sha256(self.source_bytes).hexdigest(),
            now=self.tick(),
        )

    def inventory(self, role=Role.REPORTING):
        return queries.get_inventory_snapshot(self.state, role)

    def report(self, report_id="stock_analytics", filters=None):
        return build_inventory_report(
            self.inventory(),
            report_id,
            filters=filters,
        )

    def action(self, name, *args, role):
        result = getattr(wf, name)(
            self.state,
            *args,
            context=wf.make_context(
                self.state,
                role,
                now=self.tick(),
            ),
        )
        self.state = result.state
        return result.request_id

    def submit(self, medication_id="MED001", quantity=3):
        unit = self.inventory().set_index(
            "medication_id"
        ).at[medication_id, "stock_unit"]

        return self.action(
            "submit_request",
            SubmitRequestInput(
                medication_id=medication_id,
                quantity=quantity,
                unit=unit,
                requesting_location="Demo Ward",
                reason="Synthetic analytics acceptance check",
            ),
            f"analytics-{self.state.next_request_number}",
            role=Role.CLINICAL,
        )

    def fulfill(self, quantity):
        request_id = self.submit(quantity=quantity)

        self.action(
            "start_review",
            request_id,
            role=Role.PHARMACIST,
        )
        self.action(
            "authorize_release",
            request_id,
            "Synthetic release reviewed",
            role=Role.PHARMACIST,
        )
        self.action(
            "fulfill_request",
            request_id,
            role=Role.WAREHOUSE,
        )
        return request_id

    def test_filter_retains_global_abc_but_inventory_summary_is_selected(self):
        filters = InventoryFilters(medication_ids=("MED006",))

        report = self.report(filters=filters)
        self.assertEqual(report["medication_id"].tolist(), ["MED006"])
        self.assertEqual(report.iloc[0]["abc_class"], "A")
        self.assertEqual(
            f"{report.iloc[0]['abc_share_percent']:.2f}",
            "41.44",
        )

        summary = self.report(
            "inventory_summary",
            filters,
        ).set_index("measure")["value"]

        self.assertEqual(summary["Medication SKUs"], 1)
        self.assertAlmostEqual(
            summary["Synthetic inventory value"],
            360.00,
        )

    def test_abc_category_totals_ignore_inventory_filters(self):
        totals = self.report(
            "abc_summary",
            InventoryFilters(medication_ids=("UNKNOWN",)),
        ).set_index("abc_class")

        self.assertEqual(set(totals.index), {"A", "B", "C"})
        self.assertTrue(totals["population_count"].eq(6).all())

        expected = {
            "A": ("457.50", "70.22", 3),
            "B": ("134.00", "20.57", 2),
            "C": ("60.00", "9.21", 1),
        }

        for classification, (value, share, count) in expected.items():
            with self.subTest(classification=classification):
                self.assertEqual(
                    totals.at[
                        classification,
                        "monthly_consumption_value_cad",
                    ],
                    Decimal(value),
                )
                self.assertEqual(
                    f"{totals.at[classification, 'abc_share_percent']:.2f}",
                    share,
                )
                self.assertEqual(
                    totals.at[classification, "sku_count"],
                    count,
                )

    def test_filtered_out_missing_cost_still_blocks_population_abc(self):
        inventory = self.inventory()
        inventory.loc[
            inventory["medication_id"].eq("MED001"),
            "unit_cost",
        ] = pd.NA

        report = build_inventory_report(
            inventory,
            "stock_analytics",
            filters=InventoryFilters(medication_ids=("MED006",)),
        )

        self.assertEqual(len(report), 1)
        self.assertTrue(report["abc_class"].isna().all())
        self.assertTrue(report["abc_share_percent"].isna().all())
        self.assertIn("5 of 6", report.iloc[0]["abc_note"])
        self.assertEqual(
            report.iloc[0]["monthly_consumption_value_cad"],
            Decimal("270.00"),
        )

    def test_export_content_has_two_decimal_values_and_scope(self):
        report = self.report(
            filters=InventoryFilters(medication_ids=("MED006",))
        )
        before = report.copy(deep=True)

        display = prepare_report_display(report)
        decoded = pd.read_csv(
            StringIO(display.to_csv(index=False)),
            dtype="string",
            keep_default_na=False,
        )

        self.assertEqual(len(decoded), 1)
        row = decoded.iloc[0]

        self.assertEqual(row["medication_id"], "MED006")
        self.assertEqual(row["monthly_consumption_value_cad"], "270.00")
        self.assertEqual(row["abc_share_percent"], "41.44")
        self.assertEqual(row["stock_coverage_months"], "1.33")
        self.assertEqual(row["reorder_gap"], "10.00")
        self.assertEqual(row["lead_time_demand"], "10.00")
        self.assertIn("before display filters", row["abc_scope"])
        self.assertIn("30-day", row["lead_time_basis"])
        self.assertIn("Synthetic", row["synthetic_data_notice"])

        assert_frame_equal(report, before)

    def test_both_schemas_support_analytics_and_missing_parameter_exports(self):
        for filename in (
            "sample_medications.csv",
            "sample_medications_extended.csv",
        ):
            with self.subTest(dataset=filename):
                self.make_state(filename)
                report = self.report()

                self.assertEqual(len(report), 6)
                self.assertEqual(
                    report["medication_id"].tolist(),
                    [
                        "MED006",
                        "MED002",
                        "MED005",
                        "MED004",
                        "MED001",
                        "MED003",
                    ],
                )
                self.assertEqual(
                    report["abc_class"].tolist(),
                    ["A", "A", "A", "B", "B", "C"],
                )

                if filename == "sample_medications.csv":
                    review = self.report("replenishment_review")
                    display = prepare_report_display(review)

                    for column in (
                        "reorder_point",
                        "safety_stock_level",
                        "lead_time_days",
                        "reorder_gap",
                        "lead_time_demand",
                    ):
                        self.assertTrue(
                            display[column].eq("N/A").all()
                        )

                    self.assertTrue(
                        display["analytics_note"]
                        .str.contains("Threshold gap", regex=False)
                        .all()
                    )

    def test_fulfillment_400_refreshes_analytics_and_preserves_inputs(self):
        before = self.inventory()
        self.fulfill(400)

        row = self.report().set_index(
            "medication_id"
        ).loc["MED001"]

        self.assertEqual(row["current_stock"], 800)
        self.assertEqual(row["ordering_review"], REVIEW_STOCK_LABEL)
        self.assertEqual(row["stock_coverage_months"], Decimal(1))
        self.assertEqual(row["reorder_gap"], Decimal(0))
        self.assertEqual(row["abc_class"], "B")
        self.assertEqual(
            row["monthly_consumption_value_cad"],
            Decimal("64.00"),
        )
        self.assertAlmostEqual(
            queries.get_inventory_summary(
                self.state
            )["inventory_value_cad"],
            769.00,
        )

        supplied_columns = [
            "unit_cost",
            "average_monthly_consumption",
            "reorder_point",
            "safety_stock_level",
            "lead_time_days",
            "counted_stock",
            "last_count_date",
        ]
        assert_frame_equal(
            before[supplied_columns],
            self.inventory()[supplied_columns],
        )
        self.assertEqual(self.path.read_bytes(), self.source_bytes)

    def test_full_fulfillment_refreshes_zero_stock_and_value(self):
        self.fulfill(1200)

        row = self.report().set_index(
            "medication_id"
        ).loc["MED001"]

        self.assertEqual(row["current_stock"], 0)
        self.assertEqual(row["ordering_review"], ZERO_STOCK_LABEL)
        self.assertEqual(row["stock_coverage_months"], Decimal(0))
        self.assertEqual(row["reorder_gap"], Decimal(800))
        self.assertEqual(row["abc_class"], "B")

        summary = queries.get_inventory_summary(self.state)
        self.assertEqual(summary["zero_stock_count"], 2)
        self.assertAlmostEqual(
            summary["zero_stock_share_percent"],
            100 / 3,
        )
        self.assertAlmostEqual(
            summary["inventory_value_cad"],
            705.00,
        )

    def test_duplicate_fulfillment_changes_neither_reports_nor_history(self):
        request_id = self.fulfill(400)
        before_report = self.report()
        before_inventory = self.inventory()
        before_requests = deepcopy(self.state.requests)
        before_revision = self.state.revision

        with self.assertRaises(WorkflowError):
            self.action(
                "fulfill_request",
                request_id,
                role=Role.WAREHOUSE,
            )

        assert_frame_equal(self.report(), before_report)
        assert_frame_equal(self.inventory(), before_inventory)
        self.assertEqual(self.state.requests, before_requests)
        self.assertEqual(self.state.revision, before_revision)

    def test_reset_restores_baseline_analytics_and_inventory_summary(self):
        baseline = self.report()
        baseline_totals = self.report("abc_summary")

        self.fulfill(1200)
        self.state = wf.reset_demo(
            self.state,
            now=self.tick(),
        )

        assert_frame_equal(self.report(), baseline)
        assert_frame_equal(
            self.report("abc_summary"),
            baseline_totals,
        )

        summary = queries.get_inventory_summary(self.state)
        self.assertAlmostEqual(summary["inventory_value_cad"], 801.00)
        self.assertEqual(summary["zero_stock_count"], 1)
        self.assertAlmostEqual(
            summary["zero_stock_share_percent"],
            100 / 6,
        )
        self.assertFalse(self.state.requests)
        self.assertEqual(self.path.read_bytes(), self.source_bytes)

    def test_current_analytics_cannot_rewrite_historical_supply_feedback(self):
        request_id = self.submit("MED003", 3)
        self.action(
            "start_review",
            request_id,
            role=Role.PHARMACIST,
        )
        self.action(
            "escalate_shortage",
            request_id,
            "Recorded stock cannot cover the request",
            role=Role.PHARMACIST,
        )
        self.action(
            "update_supply_feedback",
            request_id,
            SupplyFeedbackInput(
                feedback="Synthetic supply review; delivery unconfirmed"
            ),
            role=Role.PROCUREMENT,
        )

        recorded = deepcopy(
            self.state.requests[request_id].supply_feedback
        )
        before_inventory = self.inventory()
        before_revision = self.state.revision

        # A detached hypothetical input tests recalculation without
        # changing either canonical inventory or the recorded event.
        changed = self.inventory()
        changed.loc[
            changed["medication_id"].eq("MED003"),
            "lead_time_days",
        ] = 14

        current = build_stock_analytics(changed).rows.set_index(
            "medication_id"
        )
        self.assertEqual(
            f"{current.at['MED003', 'lead_time_demand']:.2f}",
            "233.33",
        )
        self.assertAlmostEqual(
            recorded.lead_time_demand,
            500 / 30 * 7,
        )

        self.report()
        self.report("abc_summary")

        self.assertEqual(
            self.state.requests[request_id].supply_feedback,
            recorded,
        )
        self.assertEqual(self.state.revision, before_revision)
        assert_frame_equal(self.inventory(), before_inventory)

    def test_missing_unit_blocks_complete_inventory_value(self):
        inventory = self.inventory()
        inventory.loc[
            inventory["medication_id"].eq("MED001"),
            "stock_unit",
        ] = pd.NA

        summary = summarize_inventory(inventory)
        self.assertIsNone(summary["inventory_value_cad"])

        analytics = build_stock_analytics(inventory)
        self.assertFalse(analytics.summary["abc_available"])

        # A valid selected-record valuation retains its own scope.
        selected_summary = build_inventory_report(
            inventory,
            "inventory_summary",
            filters=InventoryFilters(medication_ids=("MED006",)),
        ).set_index("measure")["value"]

        self.assertAlmostEqual(
            selected_summary["Synthetic inventory value"],
            360.00,
        )

    def test_empty_filtered_export_retains_headers_without_fake_records(self):
        report = self.report(
            filters=InventoryFilters(medication_ids=("UNKNOWN",))
        )
        self.assertTrue(report.empty)

        display = prepare_report_display(report)
        decoded = pd.read_csv(
            StringIO(display.to_csv(index=False))
        )

        self.assertTrue(decoded.empty)
        self.assertIn("medication_id", decoded.columns)
        self.assertIn("abc_note", decoded.columns)
        self.assertIn("synthetic_data_notice", decoded.columns)

    def test_analytics_preserves_role_information_boundaries(self):
        before_clinical = self.inventory(Role.CLINICAL)
        before_pharmacist = self.inventory(Role.PHARMACIST)

        self.report()
        self.report("abc_summary")

        assert_frame_equal(
            self.inventory(Role.CLINICAL),
            before_clinical,
        )
        assert_frame_equal(
            self.inventory(Role.PHARMACIST),
            before_pharmacist,
        )

        for role in (Role.CLINICAL, Role.PHARMACIST):
            projection = self.inventory(role)
            self.assertNotIn("unit_cost", projection.columns)
            self.assertNotIn(
                "monthly_consumption_value_cad",
                projection.columns,
            )

        with self.assertRaises(WorkflowError):
            self.inventory(Role.EXECUTIVE)

        executive = queries.get_inventory_summary(self.state)
        self.assertNotIn("medication_id", executive)
        self.assertNotIn("medication_name", executive)


if __name__ == "__main__":
    unittest.main()