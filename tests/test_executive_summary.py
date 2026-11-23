"""Executive aggregates, completeness and active-session refresh checks."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from src.config import PROJECT_ROOT
from src.data.loader import load_medications
from src.services.executive_summary import build_executive_summary
from src.services.workflow_models import (
    CreateOrderInput,
    ReceiptInput,
    Role,
    SubmitRequestInput,
    SupplyFeedbackInput,
    WorkflowError,
)
from src.ui import session


def nested_keys(value):
    keys = set()

    if isinstance(value, dict):
        keys.update(value)
        for child in value.values():
            keys.update(nested_keys(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            keys.update(nested_keys(child))

    return keys


class ExecutiveSummaryTests(unittest.TestCase):
    def setUp(self):
        self.medications = load_medications(
            PROJECT_ROOT
            / "data"
            / "sample_medications_extended.csv"
        )
        self.clock = datetime(
            2026, 11, 23, 12, 0, tzinfo=timezone.utc
        )

    def tick(self):
        self.clock += timedelta(seconds=1)
        return self.clock

    def start_session(self, filename):
        self.path = PROJECT_ROOT / "data" / filename
        self.source_bytes = self.path.read_bytes()
        self.store = {}

        session.ensure_demo_session(
            self.path,
            state_store=self.store,
            now=self.tick(),
        )

    def summary(self):
        return session.read_inventory_summary(
            state_store=self.store
        )

    def action(self, name, *args, role):
        info = session.get_session_info(
            state_store=self.store
        )
        return session.apply_workflow_action(
            name,
            *args,
            acting_role=role,
            expected_run_id=info.run_id,
            expected_revision=info.revision,
            source_path=self.path,
            state_store=self.store,
            now=self.tick(),
        )

    def make_order(self):
        request_id = self.action(
            "submit_request",
            SubmitRequestInput(
                medication_id="MED003",
                quantity=5,
                unit="tablet",
                requesting_location="Demo Ward",
                reason="Synthetic Executive summary check",
            ),
            "executive-request",
            role=Role.CLINICAL,
        ).request_id

        self.action(
            "start_review",
            request_id,
            role=Role.PHARMACIST,
        )
        self.action(
            "escalate_shortage",
            request_id,
            "Recorded stock is insufficient",
            role=Role.PHARMACIST,
        )
        self.action(
            "update_supply_feedback",
            request_id,
            SupplyFeedbackInput("Synthetic supply review"),
            role=Role.PROCUREMENT,
        )

        order_id = self.action(
            "confirm_order",
            request_id,
            CreateOrderInput(300, "tablet"),
            "executive-order",
            role=Role.PROCUREMENT,
        ).order_id

        return request_id, order_id

    def test_both_schemas_match_independent_expected_totals(self):
        expected_classes = {
            "A": (3, Decimal("457.50"), "70.22"),
            "B": (2, Decimal("134.00"), "20.57"),
            "C": (1, Decimal("60.00"), "9.21"),
        }

        for filename in (
            "sample_medications.csv",
            "sample_medications_extended.csv",
        ):
            with self.subTest(dataset=filename):
                medications = load_medications(
                    PROJECT_ROOT / "data" / filename
                )
                result = build_executive_summary(medications)
                analytics = result["analytics"]

                self.assertEqual(result["sku_count"], 6)
                self.assertEqual(result["zero_stock_count"], 1)
                self.assertAlmostEqual(
                    result["inventory_value_cad"], 801.00
                )
                self.assertEqual(
                    analytics[
                        "total_monthly_consumption_value_cad"
                    ],
                    Decimal("651.50"),
                )
                self.assertTrue(analytics["abc_available"])
                self.assertEqual(
                    analytics["complete_abc_count"], 6
                )

                for item in analytics["class_totals"]:
                    count, value, share = expected_classes[
                        item["abc_class"]
                    ]
                    self.assertEqual(item["sku_count"], count)
                    self.assertEqual(
                        item["monthly_consumption_value_cad"],
                        value,
                    )
                    self.assertEqual(
                        f"{item['abc_share_percent']:.2f}",
                        share,
                    )

                expected_reviews = (
                    {
                        "at_or_below_rop": 0,
                        "above_rop": 0,
                        "unavailable": 5,
                    }
                    if filename == "sample_medications.csv"
                    else {
                        "at_or_below_rop": 1,
                        "above_rop": 4,
                        "unavailable": 0,
                    }
                )
                self.assertEqual(
                    result["stock_review_counts"],
                    expected_reviews,
                )

    def test_missing_inputs_withhold_population_totals_and_classes(self):
        for column in (
            "unit_cost",
            "average_monthly_consumption",
            "stock_unit",
        ):
            with self.subTest(column=column):
                medications = self.medications.copy(deep=True)
                medications.loc[0, column] = pd.NA

                result = build_executive_summary(medications)
                analytics = result["analytics"]

                self.assertFalse(analytics["abc_available"])
                self.assertEqual(
                    analytics["complete_abc_count"], 5
                )
                self.assertIsNone(
                    analytics[
                        "total_monthly_consumption_value_cad"
                    ]
                )
                self.assertIn("5 of 6", analytics["abc_note"])

                for item in analytics["class_totals"]:
                    self.assertIsNone(item["sku_count"])
                    self.assertIsNone(
                        item["monthly_consumption_value_cad"]
                    )
                    self.assertIsNone(
                        item["abc_share_percent"]
                    )

                if column == "average_monthly_consumption":
                    self.assertAlmostEqual(
                        result["inventory_value_cad"], 801.00
                    )
                else:
                    self.assertIsNone(
                        result["inventory_value_cad"]
                    )

    def test_zero_monthly_value_is_distinct_from_missing(self):
        medications = self.medications.copy(deep=True)
        medications["average_monthly_consumption"] = 0

        analytics = build_executive_summary(
            medications
        )["analytics"]

        self.assertEqual(
            analytics["total_monthly_consumption_value_cad"],
            Decimal(0),
        )
        self.assertEqual(analytics["complete_abc_count"], 6)
        self.assertFalse(analytics["abc_available"])
        self.assertIn("is zero", analytics["abc_note"])

        for item in analytics["class_totals"]:
            self.assertIsNone(item["sku_count"])

    def test_valid_empty_abc_category_has_zero_not_unavailable(self):
        medications = self.medications.copy(deep=True)
        medications["average_monthly_consumption"] = 0
        medications.loc[
            medications["medication_id"].eq("MED001"),
            "average_monthly_consumption",
        ] = 800

        analytics = build_executive_summary(
            medications
        )["analytics"]
        totals = {
            item["abc_class"]: item
            for item in analytics["class_totals"]
        }

        self.assertTrue(analytics["abc_available"])
        self.assertEqual(totals["B"]["sku_count"], 0)
        self.assertEqual(
            totals["B"]["monthly_consumption_value_cad"],
            Decimal(0),
        )
        self.assertEqual(
            totals["B"]["abc_share_percent"],
            Decimal(0),
        )

    def test_equality_uses_existing_review_rule(self):
        medications = self.medications.copy(deep=True)
        medications.loc[
            medications["medication_id"].eq("MED001"),
            "current_stock",
        ] = 800

        result = build_executive_summary(medications)

        self.assertEqual(
            result["stock_review_counts"],
            {
                "at_or_below_rop": 2,
                "above_rop": 3,
                "unavailable": 0,
            },
        )
        self.assertEqual(result["zero_stock_count"], 1)
        self.assertAlmostEqual(
            result["inventory_value_cad"], 769.00
        )
        self.assertEqual(
            result["analytics"][
                "total_monthly_consumption_value_cad"
            ],
            Decimal("651.50"),
        )

    def test_empty_population_has_no_fabricated_value_or_classes(self):
        result = build_executive_summary(
            self.medications.iloc[:0].copy()
        )
        analytics = result["analytics"]

        self.assertEqual(result["sku_count"], 0)
        self.assertIsNone(result["zero_stock_share_percent"])
        self.assertIsNone(result["inventory_value_cad"])
        self.assertEqual(analytics["population_count"], 0)
        self.assertFalse(analytics["abc_available"])
        self.assertIsNone(
            analytics["total_monthly_consumption_value_cad"]
        )

        for item in analytics["class_totals"]:
            self.assertIsNone(item["sku_count"])

    def test_aggregate_output_has_no_item_level_records(self):
        before = self.medications.copy(deep=True)
        medications = self.medications.copy(deep=True)
        medications["future_private_field"] = "PRIVATE_VALUE"

        result = build_executive_summary(medications)
        keys = nested_keys(result)

        self.assertTrue(
            keys.isdisjoint(
                {
                    "medication_id",
                    "medication_name",
                    "supplier",
                    "unit_cost",
                    "current_stock",
                    "rows",
                    "requests",
                    "orders",
                    "receipts",
                    "future_private_field",
                }
            )
        )
        self.assertNotIn("PRIVATE_VALUE", repr(result))
        assert_frame_equal(self.medications, before)

    def test_receipt_fulfillment_and_reset_refresh_stock_aggregates(self):
        for filename in (
            "sample_medications.csv",
            "sample_medications_extended.csv",
        ):
            with self.subTest(dataset=filename):
                self.start_session(filename)
                baseline = self.summary()

                request_id, order_id = self.make_order()

                # An order does not increase stock or change analytics.
                self.assertEqual(self.summary(), baseline)

                self.action(
                    "confirm_receipt",
                    order_id,
                    ReceiptInput(300, "tablet"),
                    "executive-receipt",
                    role=Role.WAREHOUSE,
                )

                received = self.summary()
                self.assertEqual(
                    received["zero_stock_count"], 0
                )
                self.assertAlmostEqual(
                    received["inventory_value_cad"], 837.00
                )
                self.assertEqual(
                    received["analytics"],
                    baseline["analytics"],
                )

                if filename == "sample_medications_extended.csv":
                    self.assertEqual(
                        received["stock_review_counts"],
                        {
                            "at_or_below_rop": 2,
                            "above_rop": 4,
                            "unavailable": 0,
                        },
                    )

                self.action(
                    "start_review",
                    request_id,
                    role=Role.PHARMACIST,
                )
                self.action(
                    "authorize_release",
                    request_id,
                    "Synthetic post-receipt review completed",
                    role=Role.PHARMACIST,
                )
                self.action(
                    "fulfill_request",
                    request_id,
                    role=Role.WAREHOUSE,
                )

                fulfilled = self.summary()
                self.assertAlmostEqual(
                    fulfilled["inventory_value_cad"],
                    836.40,
                )
                self.assertEqual(
                    fulfilled["analytics"],
                    baseline["analytics"],
                )

                session.reset_demo_session(
                    clinical_tab_label="Clinical",
                    state_store=self.store,
                    now=self.tick(),
                )

                self.assertEqual(self.summary(), baseline)
                self.assertEqual(
                    self.path.read_bytes(),
                    self.source_bytes,
                )

    def test_session_summary_is_detached_and_preserves_state(self):
        self.start_session("sample_medications_extended.csv")
        root = self.store[session.STATE_KEY]
        before = deepcopy(root)

        result = self.summary()
        result["analytics"]["class_totals"][0][
            "sku_count"
        ] = 999
        result["stock_review_counts"]["above_rop"] = 999

        fresh = self.summary()
        self.assertEqual(
            fresh["analytics"]["class_totals"][0][
                "sku_count"
            ],
            3,
        )
        self.assertEqual(
            fresh["stock_review_counts"]["above_rop"],
            4,
        )
        self.assertIs(self.store[session.STATE_KEY], root)

        assert_frame_equal(root.inventory, before.inventory)
        assert_frame_equal(
            root.initial_inventory,
            before.initial_inventory,
        )

        for field in (
            "revision",
            "requests",
            "orders",
            "receipts",
            "next_request_number",
            "next_order_number",
            "next_receipt_number",
        ):
            self.assertEqual(
                getattr(root, field),
                getattr(before, field),
            )

        with self.assertRaises(WorkflowError):
            session.read_inventory(
                Role.EXECUTIVE,
                state_store=self.store,
            )


if __name__ == "__main__":
    unittest.main()