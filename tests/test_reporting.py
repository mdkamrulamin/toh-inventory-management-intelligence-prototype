"""Tests for supported reports, filtering and display/export content."""

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from io import StringIO
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from src.config import PROJECT_ROOT
from src.data.loader import load_medications
from src.services import workflow as wf
from src.services import workflow_queries as queries
from src.services.reporting import (
    INVENTORY_REPORT_IDS,
    SYNTHETIC_NOTICE,
    InventoryFilters,
    RequestFilters,
    build_inventory_report,
    build_request_report,
    build_request_summary,
    filter_inventory,
    inventory_filter_options,
    prepare_report_display,
)
from src.services.replenishment import (
    MISSING_REORDER_LABEL,
    REVIEW_STOCK_LABEL,
    ZERO_STOCK_LABEL,
)
from src.services.workflow_models import (
    Role,
    SubmitRequestInput,
    SupplyFeedbackInput,
)


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.clock = datetime(
            2026, 11, 4, 12, 0,
            tzinfo=timezone.utc,
        )
        self.submission_number = 0
        self.make_state()

    def tick(self):
        self.clock += timedelta(seconds=1)
        return self.clock

    def make_state(
        self,
        filename="sample_medications_extended.csv",
    ):
        path = PROJECT_ROOT / "data" / filename
        source_bytes = path.read_bytes()

        self.state = wf.initialize_demo(
            load_medications(path),
            dataset_path=str(path),
            dataset_fingerprint=sha256(source_bytes).hexdigest(),
            now=self.tick(),
        )

    def inventory(self):
        return queries.get_inventory_snapshot(
            self.state,
            Role.REPORTING,
        )

    def requests(self):
        return queries.list_requests(
            self.state,
            Role.REPORTING,
        )

    def report(self, report_id, filters=None):
        return build_inventory_report(
            self.inventory(),
            report_id,
            filters=filters,
        )

    def action(self, name, *args, role):
        context = wf.make_context(
            self.state,
            role,
            now=self.tick(),
        )
        result = getattr(wf, name)(
            self.state,
            *args,
            context=context,
        )
        self.state = result.state
        return result.request_id

    def submit(
        self,
        medication_id="MED001",
        quantity=3,
        urgency="routine",
    ):
        self.submission_number += 1
        unit = self.inventory().set_index(
            "medication_id"
        ).loc[medication_id, "stock_unit"]

        return self.action(
            "submit_request",
            SubmitRequestInput(
                medication_id=medication_id,
                quantity=quantity,
                unit=unit,
                requesting_location="Demo Ward",
                reason="Synthetic reporting test",
                urgency=urgency,
            ),
            f"report-submission-{self.submission_number}",
            role=Role.CLINICAL,
        )

    def start(self, request_id):
        self.action(
            "start_review",
            request_id,
            role=Role.PHARMACIST,
        )

    def fulfill(self, medication_id="MED001", quantity=3):
        request_id = self.submit(medication_id, quantity)
        self.start(request_id)

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

    def shortage(self, text="Synthetic supply update"):
        request_id = self.submit("MED003", 3)
        self.start(request_id)

        self.action(
            "escalate_shortage",
            request_id,
            "Full quantity unavailable",
            role=Role.PHARMACIST,
        )
        self.action(
            "update_supply_feedback",
            request_id,
            SupplyFeedbackInput(
                feedback=text,
                expected_delivery=date(2026, 11, 10),
            ),
            role=Role.PROCUREMENT,
        )
        return request_id

    def summary_values(self, report):
        return report.set_index("measure")["value"].to_dict()

    def test_inventory_snapshot_has_expected_records_and_scope(self):
        report = self.report("inventory_snapshot")

        self.assertEqual(len(report), 6)
        self.assertEqual(
            report.set_index("medication_id").loc[
                "MED003", "current_stock"
            ],
            0,
        )
        self.assertTrue(
            report["synthetic_data_notice"]
            .eq(SYNTHETIC_NOTICE)
            .all()
        )
        self.assertNotIn("unit_cost", report.columns)

    def test_all_inventory_reports_support_both_schemas(self):
        for filename in (
            "sample_medications.csv",
            "sample_medications_extended.csv",
        ):
            self.make_state(filename)

            for report_id in INVENTORY_REPORT_IDS:
                with self.subTest(
                    dataset=filename,
                    report=report_id,
                ):
                    report = self.report(report_id)
                    self.assertIn(
                        "synthetic_data_notice",
                        report.columns,
                    )
                    self.assertIn(
                        "report_note", report.columns
                    )
                    self.assertTrue(
                        report["synthetic_data_notice"]
                        .eq(SYNTHETIC_NOTICE)
                        .all()
                    )

    def test_original_optional_values_remain_unavailable(self):
        self.make_state("sample_medications.csv")

        review = self.report("replenishment_review")
        self.assertTrue(review["reorder_point"].isna().all())
        self.assertTrue(review["lead_time_days"].isna().all())
        self.assertEqual(
            review.set_index("medication_id").loc[
                "MED001", "ordering_review"
            ],
            MISSING_REORDER_LABEL,
        )

        counts = self.report("historical_counts")
        self.assertTrue(counts["counted_stock"].isna().all())
        self.assertTrue(counts["last_count_date"].isna().all())

        display = prepare_report_display(counts)
        self.assertTrue(
            display["counted_stock"].eq("N/A").all()
        )
        self.assertTrue(
            display["last_count_date"].eq("N/A").all()
        )

    def test_combined_inventory_filters_use_intersection(self):
        medication = self.inventory().set_index(
            "medication_id"
        ).loc["MED006"]

        report = self.report(
            "replenishment_review",
            InventoryFilters(
                medication_ids=("MED001", "MED006"),
                suppliers=(medication["supplier"],),
                stock_statuses=("In stock",),
                categories=(medication["category"],),
                ordering_reviews=(REVIEW_STOCK_LABEL,),
            ),
        )

        self.assertEqual(
            report["medication_id"].tolist(),
            ["MED006"],
        )

    def test_missing_supplier_can_be_selected_explicitly(self):
        inventory = self.inventory()
        inventory.loc[
            inventory["medication_id"].eq("MED001"),
            "supplier",
        ] = pd.NA

        options = inventory_filter_options(inventory)
        self.assertIn(None, options["supplier"])

        report = build_inventory_report(
            inventory,
            "inventory_snapshot",
            filters=InventoryFilters(suppliers=(None,)),
        )

        self.assertEqual(
            report["medication_id"].tolist(),
            ["MED001"],
        )
        self.assertTrue(report["supplier"].isna().all())

    def test_expiry_date_range_is_inclusive_and_excludes_missing(self):
        inventory = self.inventory()
        expiry = inventory.set_index(
            "medication_id"
        ).loc["MED001", "expiry_date"].date()

        selected = filter_inventory(
            inventory,
            InventoryFilters(
                medication_ids=("MED001",),
                expiry_from=expiry,
                expiry_to=expiry,
            ),
        )
        self.assertEqual(
            selected["medication_id"].tolist(),
            ["MED001"],
        )

        inventory.loc[
            inventory["medication_id"].eq("MED001"),
            "expiry_date",
        ] = pd.NaT

        selected = filter_inventory(
            inventory,
            InventoryFilters(
                medication_ids=("MED001",),
                expiry_from=expiry,
                expiry_to=expiry,
            ),
        )
        self.assertTrue(selected.empty)

    def test_reversed_expiry_range_is_rejected(self):
        with self.assertRaises(ValueError):
            self.report(
                "expiry_overview",
                InventoryFilters(
                    expiry_from=date(2027, 2, 1),
                    expiry_to=date(2027, 1, 1),
                ),
            )

    def test_empty_selection_does_not_invent_summary_values(self):
        filters = InventoryFilters(
            medication_ids=("UNKNOWN",),
        )
        snapshot = self.report("inventory_snapshot", filters)
        self.assertTrue(snapshot.empty)

        summary = self.summary_values(
            self.report("inventory_summary", filters)
        )
        self.assertEqual(summary["Medication SKUs"], 0)
        self.assertTrue(
            pd.isna(summary["Synthetic inventory value"])
        )
        self.assertTrue(
            pd.isna(summary["Recorded zero-stock share"])
        )

    def test_filtered_summary_reuses_existing_inventory_calculations(self):
        filters = InventoryFilters(
            medication_ids=("MED006",),
        )
        summary = self.summary_values(
            self.report("inventory_summary", filters)
        )

        self.assertEqual(summary["Medication SKUs"], 1)
        self.assertEqual(
            summary["Recorded zero-stock SKUs"], 0
        )
        self.assertAlmostEqual(
            summary["Synthetic inventory value"], 360.0
        )
        self.assertEqual(summary[REVIEW_STOCK_LABEL], 1)

    def test_fulfillment_updates_snapshot_zero_report_and_summary(self):
        self.fulfill("MED001", 1200)

        snapshot = self.report(
            "inventory_snapshot"
        ).set_index("medication_id")
        self.assertEqual(
            snapshot.loc["MED001", "current_stock"], 0
        )
        self.assertEqual(
            snapshot.loc["MED001", "status"],
            "Out of stock",
        )

        zero_report = self.report("zero_stock")
        self.assertEqual(
            set(zero_report["medication_id"]),
            {"MED001", "MED003"},
        )

        summary = self.summary_values(
            self.report("inventory_summary")
        )
        self.assertEqual(summary["Medication SKUs"], 6)
        self.assertEqual(
            summary["Recorded zero-stock SKUs"], 2
        )
        self.assertEqual(summary[ZERO_STOCK_LABEL], 2)
        self.assertAlmostEqual(
            summary["Synthetic inventory value"], 705.0
        )

    def test_supply_feedback_changes_request_report_not_inventory(self):
        before = self.report("inventory_snapshot")
        request_id = self.shortage()

        assert_frame_equal(
            self.report("inventory_snapshot"),
            before,
        )

        report = build_request_report(
            self.requests()
        ).set_index("request_id")

        self.assertEqual(
            report.loc[request_id, "request_status"],
            "awaiting_supply",
        )
        self.assertEqual(
            report.loc[request_id, "supply_update"],
            "Synthetic supply update",
        )
        self.assertEqual(
            report.loc[request_id, "expected_delivery"],
            "2026-11-10",
        )
        self.assertTrue(
            pd.isna(
                report.loc[
                    request_id, "fulfillment_quantity"
                ]
            )
        )

    def test_request_filters_keep_status_urgency_and_outcome_distinct(self):
        fulfilled_id = self.fulfill()
        waiting_id = self.shortage()
        urgent_id = self.submit("MED006", 2, "urgent")

        cases = (
            (
                RequestFilters(statuses=("awaiting_supply",)),
                [waiting_id],
            ),
            (
                RequestFilters(urgencies=("urgent",)),
                [urgent_id],
            ),
            (
                RequestFilters(outcomes=("fulfilled",)),
                [fulfilled_id],
            ),
            (
                RequestFilters(outcomes=(None,)),
                [waiting_id, urgent_id],
            ),
        )

        for filters, expected_ids in cases:
            with self.subTest(filters=filters):
                report = build_request_report(
                    self.requests(),
                    filters=filters,
                )
                self.assertEqual(
                    set(report["request_id"]),
                    set(expected_ids),
                )

    def test_empty_medication_allowlist_exports_no_requests(self):
        self.submit()

        unrestricted = build_request_report(self.requests())
        restricted = build_request_report(
            self.requests(),
            allowed_medication_ids=(),
        )

        self.assertEqual(len(unrestricted), 1)
        self.assertTrue(restricted.empty)

    def test_request_summary_reuses_closed_outcomes(self):
        self.fulfill()
        shortage_id = self.shortage()

        self.action(
            "close_without_supply",
            shortage_id,
            "Synthetic closure without supply",
            role=Role.PHARMACIST,
        )

        summary = queries.get_session_request_summary(
            self.state
        )
        values = self.summary_values(
            build_request_summary(summary)
        )

        self.assertEqual(values["Submitted requests"], 2)
        self.assertEqual(values["Open requests"], 0)
        self.assertEqual(values["Fulfilled outcomes"], 1)
        self.assertEqual(values["Closed without supply"], 1)
        self.assertEqual(values["Current state: Closed"], 2)

    def test_reset_restores_reports_and_clears_request_summary(self):
        baseline = self.report("inventory_snapshot")

        self.fulfill()
        self.shortage()

        self.state = wf.reset_demo(
            self.state,
            now=self.tick(),
        )

        assert_frame_equal(
            self.report("inventory_snapshot"),
            baseline,
        )
        self.assertTrue(
            build_request_report(self.requests()).empty
        )
        values = self.summary_values(
            build_request_summary(
                queries.get_session_request_summary(
                    self.state
                )
            )
        )
        self.assertEqual(values["Submitted requests"], 0)

    def test_reports_do_not_mutate_state_or_leak_unknown_fields(self):
        inventory_before = self.state.inventory.copy(deep=True)
        requests_before = deepcopy(self.state.requests)

        inventory = self.inventory()
        inventory["future_private_field"] = "not a report field"

        for report_id in INVENTORY_REPORT_IDS:
            report = build_inventory_report(
                inventory,
                report_id,
            )
            self.assertNotIn(
                "future_private_field", report.columns
            )
            prepare_report_display(report)

        assert_frame_equal(
            self.state.inventory,
            inventory_before,
        )
        self.assertEqual(
            self.state.requests,
            requests_before,
        )

    def test_request_report_excludes_internal_submission_keys(self):
        self.submit()
        requests = self.requests()

        # Even an unexpected extra field is not flattened into the report.
        requests[0]["submission_key"] = "internal-token"
        requests[0]["status_history"] = [{"private": "value"}]

        report = build_request_report(requests)

        self.assertNotIn("submission_key", report.columns)
        self.assertNotIn("status_history", report.columns)
        self.assertNotIn(
            "internal-token",
            report.to_string(),
        )

    def test_display_dates_missing_values_and_zero_are_preserved(self):
        report = self.report("historical_counts")
        report.loc[report.index[0], "last_count_date"] = pd.NaT
        report.loc[report.index[0], "counted_stock"] = 0

        before = report.copy(deep=True)
        display = prepare_report_display(report)

        self.assertEqual(
            display.iloc[0]["last_count_date"], "N/A"
        )
        self.assertEqual(
            display.iloc[0]["counted_stock"], 0
        )
        assert_frame_equal(report, before)

    def test_csv_compatible_table_contains_filtered_current_stock(self):
        self.fulfill()

        report = self.report(
            "inventory_snapshot",
            InventoryFilters(
                medication_ids=("MED001",),
            ),
        )
        display = prepare_report_display(report)

        decoded = pd.read_csv(
            StringIO(display.to_csv(index=False)),
            dtype="string",
            keep_default_na=False,
        )

        self.assertEqual(len(decoded), 1)
        self.assertEqual(
            decoded.iloc[0]["medication_id"], "MED001"
        )
        self.assertEqual(
            float(decoded.iloc[0]["current_stock"]), 1197
        )
        self.assertEqual(
            decoded.iloc[0]["synthetic_data_notice"],
            SYNTHETIC_NOTICE,
        )

    def test_csv_compatible_request_text_retains_commas_and_newlines(self):
        text = "Synthetic review, delivery unconfirmed.\nNo receipt recorded."
        self.shortage(text)

        display = prepare_report_display(
            build_request_report(self.requests())
        )
        decoded = pd.read_csv(
            StringIO(display.to_csv(index=False)),
            dtype="string",
            keep_default_na=False,
        )

        self.assertEqual(
            decoded.iloc[0]["supply_update"], text
        )
        self.assertEqual(
            decoded.iloc[0]["request_status"],
            "Awaiting supply",
        )

    def test_empty_csv_table_retains_headers_without_fake_records(self):
        report = self.report(
            "inventory_snapshot",
            InventoryFilters(
                medication_ids=("UNKNOWN",),
            ),
        )
        display = prepare_report_display(report)

        decoded = pd.read_csv(
            StringIO(display.to_csv(index=False))
        )

        self.assertTrue(decoded.empty)
        self.assertIn(
            "synthetic_data_notice",
            decoded.columns,
        )
        self.assertIn("medication_id", decoded.columns)

    def test_unsupported_performance_report_is_rejected(self):
        with self.assertRaises(ValueError):
            self.report("inventory_turnover")


if __name__ == "__main__":
    unittest.main()