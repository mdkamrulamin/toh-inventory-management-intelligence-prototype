"""Checks for role projections and current-session read queries."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import unittest

import pandas as pd

from src.config import PROJECT_ROOT
from src.data.loader import load_medications
from src.services import workflow as wf
from src.services import workflow_queries as queries
from src.services.workflow_models import (
    RequestStatus,
    Role,
    SubmitRequestInput,
    SupplyFeedbackInput,
    Urgency,
    WorkflowError,
)


class WorkflowQueryTests(unittest.TestCase):
    NOW = datetime(
        2026, 11, 3, 12, 0,
        tzinfo=timezone.utc,
    )

    def new_state(
        self,
        filename="sample_medications_extended.csv",
    ):
        path = PROJECT_ROOT / "data" / filename

        return wf.initialize_demo(
            load_medications(path),
            dataset_path=str(path),
            dataset_fingerprint=sha256(
                path.read_bytes()
            ).hexdigest(),
            now=self.NOW,
        )

    def context(self, state, role):
        now = datetime.fromisoformat(
            state.started_time
        ) + timedelta(seconds=state.revision + 1)

        return wf.make_context(state, role, now=now)

    def submit(
        self,
        state,
        medication_id="MED001",
        quantity=3,
        unit="tablet",
        urgency=Urgency.ROUTINE,
    ):
        result = wf.submit_request(
            state,
            SubmitRequestInput(
                medication_id=medication_id,
                quantity=quantity,
                unit=unit,
                requesting_location="Demo Ward",
                reason="Synthetic stock request",
                urgency=urgency,
            ),
            f"attempt-{state.next_request_number}",
            self.context(state, Role.CLINICAL),
        )

        return result.state, result.request_id

    def review(self, state, request_id):
        return wf.start_review(
            state,
            request_id,
            self.context(state, Role.PHARMACIST),
        ).state

    def release(self, state, request_id):
        state = self.review(state, request_id)

        return wf.authorize_release(
            state,
            request_id,
            "Synthetic release reviewed",
            self.context(state, Role.PHARMACIST),
        ).state

    def escalate(self, state, request_id):
        state = self.review(state, request_id)

        return wf.escalate_shortage(
            state,
            request_id,
            "Full quantity unavailable",
            self.context(state, Role.PHARMACIST),
        ).state

    def supply_feedback(self, state, request_id):
        return wf.update_supply_feedback(
            state,
            request_id,
            SupplyFeedbackInput(
                "Synthetic supply review pending"
            ),
            self.context(state, Role.PROCUREMENT),
        ).state

    def assert_error(self, code, operation):
        with self.assertRaises(WorkflowError) as caught:
            operation()

        self.assertEqual(caught.exception.code, code)

    def test_clinical_inventory_excludes_commercial_fields(self):
        state = self.new_state()

        result = queries.get_inventory_snapshot(
            state,
            Role.CLINICAL,
        )

        self.assertIn("medication_id", result)
        self.assertIn("current_stock", result)
        self.assertIn("stock_unit", result)
        self.assertIn("status", result)
        self.assertIn("reorder_point", result)

        for column in (
            "unit_cost",
            "supplier",
            "lead_time_days",
        ):
            self.assertNotIn(column, result)

    def test_pharmacist_inventory_preserves_review_context_without_costs(self):
        state = self.new_state()

        result = queries.get_inventory_snapshot(
            state,
            Role.PHARMACIST,
        )

        for column in (
            "expiry_date",
            "primary_location",
            "counted_stock",
            "reorder_point",
            "supplier",
            "lead_time_days",
        ):
            self.assertIn(column, result)

        self.assertNotIn("unit_cost", result)

    def test_warehouse_inventory_excludes_commercial_fields(self):
        state = self.new_state()

        result = queries.get_inventory_snapshot(
            state,
            Role.WAREHOUSE,
        )

        self.assertIn("last_count_date", result)
        self.assertIn("counted_stock", result)
        self.assertIn("primary_location", result)
        self.assertIn("reorder_point", result)

        self.assertNotIn("unit_cost", result)
        self.assertNotIn("supplier", result)

    def test_procurement_and_reporting_use_explicit_known_columns(self):
        state = self.new_state()

        inventory = state.inventory.copy(deep=True)
        inventory["unexpected_private_field"] = "hidden"
        state = replace(state, inventory=inventory)

        for role in (
            Role.PROCUREMENT,
            Role.REPORTING,
        ):
            with self.subTest(role=role):
                result = queries.get_inventory_snapshot(
                    state,
                    role,
                )

                self.assertEqual(result.shape, (6, 16))
                self.assertIn("unit_cost", result)
                self.assertIn("supplier", result)
                self.assertNotIn(
                    "unexpected_private_field",
                    result,
                )

    def test_executive_receives_aggregates_only(self):
        state, request_id = self.submit(
            self.new_state()
        )

        self.assert_error(
            "aggregate_only",
            lambda: queries.get_inventory_snapshot(
                state,
                Role.EXECUTIVE,
            ),
        )
        self.assert_error(
            "aggregate_only",
            lambda: queries.list_requests(
                state,
                Role.EXECUTIVE,
            ),
        )
        self.assert_error(
            "aggregate_only",
            lambda: queries.get_request_details(
                state,
                request_id,
                Role.EXECUTIVE,
            ),
        )

        summary = queries.get_inventory_summary(state)

        self.assertEqual(summary["sku_count"], 6)
        self.assertEqual(
            summary["zero_stock_count"],
            1,
        )
        self.assertAlmostEqual(
            summary["inventory_value_cad"],
            801.00,
        )
        self.assertNotIn("medication_id", summary)

    def test_inventory_snapshots_are_detached(self):
        state = self.new_state()
        original = state.inventory.copy(deep=True)

        result = queries.get_inventory_snapshot(
            state,
            Role.PROCUREMENT,
        )
        result.loc[0, "current_stock"] = 1

        pd.testing.assert_frame_equal(
            state.inventory,
            original,
        )
        pd.testing.assert_frame_equal(
            state.initial_inventory,
            original,
        )

    def test_queries_reflect_fulfillment_immediately(self):
        state, request_id = self.submit(
            self.new_state()
        )
        state = self.release(state, request_id)
        state = wf.fulfill_request(
            state,
            request_id,
            self.context(state, Role.WAREHOUSE),
        ).state

        for role in (
            Role.CLINICAL,
            Role.PHARMACIST,
            Role.PROCUREMENT,
            Role.WAREHOUSE,
            Role.REPORTING,
        ):
            with self.subTest(role=role):
                result = queries.get_inventory_snapshot(
                    state,
                    role,
                ).set_index("medication_id")

                self.assertEqual(
                    result.loc[
                        "MED001",
                        "current_stock",
                    ],
                    1197,
                )

        summary = queries.get_inventory_summary(state)

        self.assertAlmostEqual(
            summary["inventory_value_cad"],
            800.76,
        )

        review = queries.get_replenishment_review(
            state
        ).set_index("medication_id")

        self.assertEqual(
            review.loc[
                "MED001",
                "ordering_review",
            ],
            "Above illustrative reorder threshold",
        )

    def test_original_dataset_does_not_gain_fabricated_optional_values(self):
        state = self.new_state(
            "sample_medications.csv"
        )

        result = queries.get_inventory_snapshot(
            state,
            Role.PROCUREMENT,
        )

        self.assertEqual(result.shape, (6, 10))
        self.assertNotIn("reorder_point", result)
        self.assertNotIn("primary_location", result)

        review = queries.get_replenishment_review(
            state
        ).set_index("medication_id")

        self.assertTrue(
            review["reorder_point"].isna().all()
        )
        self.assertEqual(
            review.loc[
                "MED001",
                "ordering_review",
            ],
            "N/A — reorder point unavailable",
        )

    def test_request_details_preserve_role_information_boundaries(self):
        state, request_id = self.submit(
            self.new_state(),
            "MED003",
            3,
        )
        state = self.escalate(state, request_id)
        state = self.supply_feedback(
            state,
            request_id,
        )

        clinical = queries.get_request_details(
            state,
            request_id,
            Role.CLINICAL,
        )
        pharmacist = queries.get_request_details(
            state,
            request_id,
            Role.PHARMACIST,
        )

        self.assertNotIn("submission_key", clinical)
        self.assertNotIn("unit_cost", clinical)
        self.assertNotIn(
            "supplier",
            clinical["supply_feedback"],
        )
        self.assertNotIn(
            "lead_time_demand",
            clinical["supply_feedback"],
        )
        self.assertIn(
            "expected_delivery",
            clinical["supply_feedback"],
        )

        self.assertEqual(
            pharmacist["supply_feedback"]["supplier"],
            "Demo Supplier A",
        )
        self.assertIsNone(
            pharmacist["priority_class"]
        )
        self.assertEqual(
            clinical["shortfall_at_escalation"],
            3,
        )

    def test_request_outputs_are_deeply_detached(self):
        state, request_id = self.submit(
            self.new_state(),
            "MED003",
            3,
        )
        state = self.escalate(state, request_id)
        state = self.supply_feedback(
            state,
            request_id,
        )
        original = deepcopy(
            state.requests[request_id]
        )

        details = queries.get_request_details(
            state,
            request_id,
            Role.PHARMACIST,
        )
        details["status_history"][0]["reason"] = "changed"
        details["supply_feedback"]["feedback"] = "changed"

        rows = queries.list_requests(
            state,
            Role.PROCUREMENT,
        )
        rows[0]["supply_feedback"]["supplier"] = "changed"

        self.assertEqual(
            state.requests[request_id],
            original,
        )

    def test_handoff_visibility_and_actionable_queues(self):
        state, released_id = self.submit(
            self.new_state()
        )

        self.assertEqual(
            queries.list_requests(
                state,
                Role.WAREHOUSE,
            ),
            [],
        )

        state = self.release(state, released_id)

        warehouse_queue = queries.list_requests(
            state,
            Role.WAREHOUSE,
            actionable_only=True,
        )
        self.assertEqual(
            [row["request_id"] for row in warehouse_queue],
            [released_id],
        )

        state = wf.recall_release(
            state,
            released_id,
            "Synthetic re-review",
            self.context(state, Role.PHARMACIST),
        ).state

        # The handoff remains visible but is no longer actionable.
        self.assertEqual(
            [
                row["request_id"]
                for row in queries.list_requests(
                    state,
                    Role.WAREHOUSE,
                )
            ],
            [released_id],
        )
        self.assertEqual(
            queries.list_requests(
                state,
                Role.WAREHOUSE,
                actionable_only=True,
            ),
            [],
        )

        state, shortage_id = self.submit(
            state,
            "MED003",
            3,
        )
        state = self.escalate(state, shortage_id)

        procurement_queue = queries.list_requests(
            state,
            Role.PROCUREMENT,
            actionable_only=True,
        )
        self.assertEqual(
            [
                row["request_id"]
                for row in procurement_queue
            ],
            [shortage_id],
        )

        self.assertEqual(
            queries.list_requests(
                state,
                Role.REPORTING,
                actionable_only=True,
            ),
            [],
        )

    def test_queue_order_uses_urgency_then_original_arrival(self):
        state, routine_id = self.submit(
            self.new_state()
        )
        state, urgent_first = self.submit(
            state,
            urgency=Urgency.URGENT,
        )
        state, urgent_second = self.submit(
            state,
            urgency=Urgency.URGENT,
        )

        original_received = (
            state.requests[routine_id].received_time
        )

        state = self.review(state, routine_id)
        state = wf.return_to_queue(
            state,
            routine_id,
            None,
            self.context(state, Role.PHARMACIST),
        ).state

        queue = queries.list_requests(
            state,
            Role.PHARMACIST,
            actionable_only=True,
        )

        self.assertEqual(
            [row["request_id"] for row in queue],
            [
                urgent_first,
                urgent_second,
                routine_id,
            ],
        )
        self.assertEqual(
            state.requests[routine_id].received_time,
            original_received,
        )

    def test_request_summary_distinguishes_closed_outcomes(self):
        state, fulfilled_id = self.submit(
            self.new_state()
        )
        state = self.release(state, fulfilled_id)
        state = wf.fulfill_request(
            state,
            fulfilled_id,
            self.context(state, Role.WAREHOUSE),
        ).state

        state, shortage_id = self.submit(
            state,
            "MED003",
            3,
        )
        state = self.escalate(state, shortage_id)
        state = self.supply_feedback(
            state,
            shortage_id,
        )
        state = wf.close_without_supply(
            state,
            shortage_id,
            "Synthetic session ends without supply",
            self.context(state, Role.PHARMACIST),
        ).state

        summary = queries.get_session_request_summary(
            state
        )

        self.assertEqual(
            summary["total_requests"],
            2,
        )
        self.assertEqual(
            summary["open_requests"],
            0,
        )
        self.assertEqual(
            summary["fulfilled_requests"],
            1,
        )
        self.assertEqual(
            summary["closed_without_supply"],
            1,
        )
        self.assertEqual(
            summary["by_status"]["closed"],
            2,
        )

    def test_current_availability_uses_latest_session_stock(self):
        state, first_id = self.submit(
            self.new_state(),
            "MED006",
            50,
            "vial",
        )
        state = self.release(state, first_id)

        state, second_id = self.submit(
            state,
            "MED006",
            50,
            "vial",
        )
        state = self.release(state, second_id)

        before = queries.get_current_availability(
            state,
            second_id,
        )
        self.assertTrue(before["available"])
        self.assertEqual(
            before["recorded_stock"],
            80,
        )

        state = wf.fulfill_request(
            state,
            first_id,
            self.context(state, Role.WAREHOUSE),
        ).state

        after = queries.get_current_availability(
            state,
            second_id,
        )

        self.assertTrue(after["comparable"])
        self.assertFalse(after["available"])
        self.assertEqual(
            after["recorded_stock"],
            30,
        )
        self.assertEqual(
            state.requests[second_id].status,
            RequestStatus.APPROVED_FOR_RELEASE,
        )

    def test_missing_or_mismatched_units_are_not_treated_as_available(self):
        state, request_id = self.submit(
            self.new_state()
        )

        for unit in (None, "", "vial"):
            with self.subTest(unit=unit):
                inventory = state.inventory.astype(
                    object
                )
                inventory.loc[
                    inventory["medication_id"].eq(
                        "MED001"
                    ),
                    "stock_unit",
                ] = unit

                modified = replace(
                    state,
                    inventory=inventory,
                )
                result = queries.get_current_availability(
                    modified,
                    request_id,
                )

                self.assertFalse(result["comparable"])
                self.assertIsNone(result["available"])

    def test_unknown_or_unhanded_requests_are_rejected(self):
        state, request_id = self.submit(
            self.new_state()
        )

        self.assert_error(
            "unknown_request",
            lambda: queries.get_request_details(
                state,
                "REQ-9999",
                Role.CLINICAL,
            ),
        )
        self.assert_error(
            "request_not_visible",
            lambda: queries.get_request_details(
                state,
                request_id,
                Role.WAREHOUSE,
            ),
        )
        self.assert_error(
            "request_not_visible",
            lambda: queries.get_request_details(
                state,
                request_id,
                Role.PROCUREMENT,
            ),
        )

    def test_queries_do_not_mutate_business_state(self):
        state, request_id = self.submit(
            self.new_state()
        )
        inventory = state.inventory.copy(deep=True)
        baseline = (
            state.initial_inventory.copy(deep=True)
        )
        requests = deepcopy(state.requests)
        revision = state.revision
        next_number = state.next_request_number

        queries.get_inventory_snapshot(
            state,
            Role.CLINICAL,
        )
        queries.list_requests(
            state,
            Role.PHARMACIST,
        )
        queries.get_request_details(
            state,
            request_id,
            Role.CLINICAL,
        )
        queries.get_current_availability(
            state,
            request_id,
        )
        queries.get_inventory_summary(state)
        queries.get_replenishment_review(state)
        queries.get_session_request_summary(state)

        pd.testing.assert_frame_equal(
            state.inventory,
            inventory,
        )
        pd.testing.assert_frame_equal(
            state.initial_inventory,
            baseline,
        )
        self.assertEqual(state.requests, requests)
        self.assertEqual(state.revision, revision)
        self.assertEqual(
            state.next_request_number,
            next_number,
        )


if __name__ == "__main__":
    unittest.main()