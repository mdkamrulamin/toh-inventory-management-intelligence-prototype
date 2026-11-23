"""Cost-free Pharmacist coverage, expiry and session refresh checks."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from src.config import PROJECT_ROOT
from src.services.analytics import (
    build_stock_analytics,
    build_stock_coverage_context,
)
from src.services.reporting import prepare_report_display
from src.services.workflow_models import (
    CreateOrderInput,
    ReceiptInput,
    Role,
    SubmitRequestInput,
    SupplyFeedbackInput,
    WorkflowError,
)
from src.ui import session


class PharmacistContextTests(unittest.TestCase):
    def setUp(self):
        self.clock = datetime(
            2026, 11, 23, 12, 0, tzinfo=timezone.utc
        )
        self.start_session("sample_medications_extended.csv")

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

        self.medications = self.store[
            session.STATE_KEY
        ].inventory.copy(deep=True)

    def read(self):
        return session.read_pharmacist_inventory_context(
            Role.PHARMACIST,
            state_store=self.store,
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
                reason="Synthetic coverage check",
            ),
            "coverage-request",
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
            "coverage-order",
            role=Role.PROCUREMENT,
        ).order_id

        return request_id, order_id

    def test_both_schemas_match_known_and_existing_coverage_values(self):
        expected = {
            "MED001": "1.50",
            "MED002": "1.33",
            "MED003": "0.00",
            "MED004": "1.29",
            "MED005": "1.40",
            "MED006": "1.33",
        }

        for filename in (
            "sample_medications.csv",
            "sample_medications_extended.csv",
        ):
            with self.subTest(dataset=filename):
                self.start_session(filename)

                context = self.read().set_index(
                    "medication_id"
                )
                existing = build_stock_analytics(
                    self.medications
                ).rows.set_index("medication_id")

                for medication_id, text in expected.items():
                    value = context.at[
                        medication_id,
                        "stock_coverage_months",
                    ]
                    self.assertEqual(f"{value:.2f}", text)
                    self.assertEqual(
                        value,
                        existing.at[
                            medication_id,
                            "stock_coverage_months",
                        ],
                    )

                self.assertEqual(
                    context.at[
                        "MED003", "stock_coverage_months"
                    ],
                    Decimal(0),
                )

    def test_missing_and_zero_inputs_have_explicit_reasons(self):
        for column, value, reason in (
            (
                "average_monthly_consumption",
                pd.NA,
                "monthly use unavailable",
            ),
            (
                "average_monthly_consumption",
                0,
                "monthly use is zero",
            ),
            (
                "stock_unit",
                pd.NA,
                "stock unit unavailable",
            ),
            (
                "stock_unit",
                " ",
                "stock unit unavailable",
            ),
        ):
            with self.subTest(column=column, value=repr(value)):
                medications = self.medications.copy(deep=True)
                medications.loc[0, column] = value

                result = build_stock_coverage_context(
                    medications
                ).set_index("medication_id")

                self.assertTrue(
                    pd.isna(
                        result.at[
                            "MED001", "stock_coverage_months"
                        ]
                    )
                )
                self.assertIn(
                    reason,
                    result.at["MED001", "coverage_note"],
                )

    def test_coverage_does_not_require_or_expose_cost_inputs(self):
        medications = self.medications.copy(deep=True)
        medications["unit_cost"] = "PRIVATE_COST_VALUE"
        medications["future_private_field"] = "PRIVATE_VALUE"
        before = medications.copy(deep=True)

        result = build_stock_coverage_context(medications)

        self.assertEqual(
            list(result.columns),
            [
                "medication_id",
                "stock_coverage_months",
                "coverage_note",
            ],
        )
        self.assertEqual(
            f"{result.iloc[0]['stock_coverage_months']:.2f}",
            "1.50",
        )
        self.assertNotIn("PRIVATE", result.to_string())
        assert_frame_equal(medications, before)

    def test_out_of_range_coverage_and_empty_inputs(self):
        medications = self.medications.iloc[:1].copy()
        medications["current_stock"] = pd.Series(
            [1e308],
            index=medications.index,
            dtype="Float64",
        )
        medications["average_monthly_consumption"] = pd.Series(
            [1e-308],
            index=medications.index,
            dtype="Float64",
        )

        result = build_stock_coverage_context(medications)

        self.assertTrue(
            pd.isna(result.iloc[0]["stock_coverage_months"])
        )
        self.assertIn(
            "finite calculation range",
            result.iloc[0]["coverage_note"],
        )

        empty = build_stock_coverage_context(
            self.medications.iloc[:0]
        )
        self.assertTrue(empty.empty)
        self.assertEqual(
            list(empty.columns),
            [
                "medication_id",
                "stock_coverage_months",
                "coverage_note",
            ],
        )

    def test_query_is_cost_free_detached_and_read_only(self):
        root = self.store[session.STATE_KEY]
        before = deepcopy(root)

        context = self.read()

        for column in (
            "unit_cost",
            "monthly_consumption_value_cad",
            "recorded_inventory_value_cad",
            "abc_class",
            "abc_share_percent",
            "abc_note",
        ):
            self.assertNotIn(column, context.columns)

        self.assertTrue(
            context["shelf_life_as_of"]
            .eq("2026-11-23")
            .all()
        )

        context.loc[0, "stock_coverage_months"] = Decimal(999)

        self.assertEqual(
            self.read().iloc[0]["stock_coverage_months"],
            Decimal("1.5"),
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
            "substitute_reviews",
            "next_request_number",
            "next_order_number",
            "next_receipt_number",
        ):
            self.assertEqual(
                getattr(root, field),
                getattr(before, field),
            )

        self.assertEqual(
            self.path.read_bytes(),
            self.source_bytes,
        )

    def test_other_roles_do_not_receive_pharmacist_projection(self):
        for role in (
            Role.CLINICAL,
            Role.PROCUREMENT,
            Role.WAREHOUSE,
            Role.EXECUTIVE,
            Role.REPORTING,
            Role.SYSTEM,
            "unknown-role",
        ):
            with self.subTest(role=role):
                with self.assertRaises(WorkflowError):
                    session.read_pharmacist_inventory_context(
                        role,
                        state_store=self.store,
                    )

    def test_receipt_fulfillment_and_reset_refresh_coverage(self):
        for filename in (
            "sample_medications.csv",
            "sample_medications_extended.csv",
        ):
            with self.subTest(dataset=filename):
                self.start_session(filename)
                baseline = self.read()

                request_id, order_id = self.make_order()

                # Submission, review, feedback and ordering do not
                # change the active inventory or coverage.
                assert_frame_equal(self.read(), baseline)

                self.action(
                    "confirm_receipt",
                    order_id,
                    ReceiptInput(300, "tablet"),
                    "coverage-receipt",
                    role=Role.WAREHOUSE,
                )

                received = self.read().set_index(
                    "medication_id"
                )
                self.assertEqual(
                    received.at[
                        "MED003", "stock_coverage_months"
                    ],
                    Decimal("0.6"),
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

                fulfilled = self.read().set_index(
                    "medication_id"
                )
                self.assertEqual(
                    fulfilled.at[
                        "MED003", "stock_coverage_months"
                    ],
                    Decimal("0.59"),
                )

                expiry_columns = [
                    "medication_id",
                    "expiry_date",
                    "days_to_representative_expiry",
                    "shelf_life_as_of",
                    "representative_expiry_context",
                ]
                assert_frame_equal(
                    self.read()[expiry_columns],
                    baseline[expiry_columns],
                )

                session.reset_demo_session(
                    clinical_tab_label="Clinical",
                    state_store=self.store,
                    now=self.tick(),
                )

                assert_frame_equal(self.read(), baseline)
                self.assertEqual(
                    self.path.read_bytes(),
                    self.source_bytes,
                )

    def test_export_preserves_months_zero_and_reference_date(self):
        display = prepare_report_display(self.read())
        decoded = pd.read_csv(
            StringIO(display.to_csv(index=False)),
            dtype="string",
            keep_default_na=False,
        ).set_index("medication_id")

        self.assertEqual(
            decoded.at["MED001", "stock_coverage_months"],
            "1.50",
        )
        self.assertEqual(
            decoded.at["MED003", "stock_coverage_months"],
            "0.00",
        )
        self.assertTrue(
            decoded["shelf_life_as_of"]
            .eq("2026-11-23")
            .all()
        )
        self.assertNotIn("unit_cost", decoded.columns)
        self.assertNotIn(
            "monthly_consumption_value_cad",
            decoded.columns,
        )


if __name__ == "__main__":
    unittest.main()