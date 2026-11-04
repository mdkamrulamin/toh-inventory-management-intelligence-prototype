"""Integration tests for Warehouse and Procurement handoff callbacks."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pandas.testing import assert_frame_equal

from src.config import PROJECT_ROOT
from src.services.replenishment import (
    MISSING_REORDER_LABEL,
    REVIEW_STOCK_LABEL,
    ZERO_STOCK_LABEL,
)
from src.services.workflow_models import (
    Role,
    SubmitRequestInput,
)
from src.ui import session
from src.ui.workflow_actions import (
    procurement_feedback_callback,
    warehouse_fulfillment_callback,
)


class HandoffActionTests(unittest.TestCase):
    def setUp(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)

        self.path = Path(temporary_directory.name) / "sample.csv"
        self.path.write_bytes(
            (
                PROJECT_ROOT
                / "data"
                / "sample_medications_extended.csv"
            ).read_bytes()
        )

        self.original_bytes = self.path.read_bytes()
        self.store = {}
        self.clock = datetime(
            2026, 11, 4, 12, 0,
            tzinfo=timezone.utc,
        )
        self.submission_number = 0

        self.confirmation_key = "workflow_ui_test_fulfillment"
        self.feedback_key = "workflow_ui_test_supply_feedback"
        self.expected_date_key = "workflow_ui_test_expected_date"

        self.ensure()

    def tick(self):
        self.clock += timedelta(seconds=1)
        return self.clock

    def ensure(self):
        return session.ensure_demo_session(
            self.path,
            state_store=self.store,
            now=self.tick(),
        )

    def info(self):
        return session.get_session_info(
            state_store=self.store
        )

    def action(self, name, *args, role):
        info = self.info()

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

    def inventory(self, role=Role.REPORTING):
        return session.read_inventory(
            role,
            state_store=self.store,
        )

    def stock(self, medication_id="MED001"):
        return self.inventory().set_index(
            "medication_id"
        ).loc[medication_id, "current_stock"]

    def details(self, request_id, role=Role.CLINICAL):
        return session.read_request_details(
            request_id,
            role,
            state_store=self.store,
        )

    def queue(self, role):
        return session.read_requests(
            role,
            actionable_only=True,
            state_store=self.store,
        )

    def submit(self, medication_id="MED001", quantity=3):
        self.submission_number += 1

        unit = self.inventory().set_index(
            "medication_id"
        ).loc[medication_id, "stock_unit"]

        result = self.action(
            "submit_request",
            SubmitRequestInput(
                medication_id=medication_id,
                quantity=quantity,
                unit=unit,
                requesting_location="Demo Ward",
                reason="Synthetic handoff test",
            ),
            f"handoff-submission-{self.submission_number}",
            role=Role.CLINICAL,
        )

        return result.request_id

    def release(self, medication_id="MED001", quantity=3):
        request_id = self.submit(medication_id, quantity)

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

        return request_id

    def escalate(self, medication_id="MED003", quantity=3):
        request_id = self.submit(medication_id, quantity)

        self.action(
            "start_review",
            request_id,
            role=Role.PHARMACIST,
        )
        self.action(
            "escalate_shortage",
            request_id,
            "Full requested quantity is unavailable",
            role=Role.PHARMACIST,
        )

        return request_id

    def fulfill(
        self,
        request_id,
        *,
        confirmed=True,
        snapshot=None,
    ):
        info = self.info() if snapshot is None else snapshot
        self.store[self.confirmation_key] = confirmed

        warehouse_fulfillment_callback(
            request_id,
            self.confirmation_key,
            info.run_id,
            info.revision,
            source_path=self.path,
            state_store=self.store,
            now=self.tick(),
        )

    def feedback(
        self,
        request_id,
        text="Synthetic supplier review recorded; no order placed.",
        *,
        expected_date=None,
        snapshot=None,
    ):
        info = self.info() if snapshot is None else snapshot
        self.store[self.feedback_key] = text
        self.store[self.expected_date_key] = expected_date

        procurement_feedback_callback(
            request_id,
            self.feedback_key,
            self.expected_date_key,
            info.run_id,
            info.revision,
            source_path=self.path,
            state_store=self.store,
            now=self.tick(),
        )

    def assert_notice(self, kind):
        self.assertEqual(
            self.store[session.NOTICE_KEY]["kind"],
            kind,
        )

    def test_warehouse_queue_requires_explicit_release(self):
        received_id = self.submit()
        review_id = self.submit("MED004", 5)

        self.action(
            "start_review",
            review_id,
            role=Role.PHARMACIST,
        )

        shortage_id = self.escalate()
        released_id = self.release()

        self.assertEqual(
            [
                request["request_id"]
                for request in self.queue(Role.WAREHOUSE)
            ],
            [released_id],
        )

        for request_id in (received_id, review_id, shortage_id):
            with self.subTest(request_id=request_id):
                root = self.store[session.STATE_KEY]
                before = self.inventory()

                self.fulfill(request_id)

                self.assert_notice("error")
                self.assertIs(
                    self.store[session.STATE_KEY], root
                )
                assert_frame_equal(
                    self.inventory(), before
                )

    def test_fulfillment_requires_deliberate_confirmation(self):
        request_id = self.release()
        root = self.store[session.STATE_KEY]

        self.fulfill(request_id, confirmed=False)

        self.assert_notice("error")
        self.assertIs(self.store[session.STATE_KEY], root)
        self.assertEqual(self.stock(), 1200)
        self.assertIsNone(
            self.details(request_id)["fulfillment"]
        )

    def test_full_fulfillment_updates_all_readers_and_summary(self):
        request_id = self.release()
        self.fulfill(request_id)

        self.assert_notice("success")
        self.assertFalse(
            self.store[self.confirmation_key]
        )

        for role in (
            Role.CLINICAL,
            Role.PHARMACIST,
            Role.WAREHOUSE,
            Role.PROCUREMENT,
            Role.REPORTING,
        ):
            with self.subTest(role=role):
                stock = self.inventory(role).set_index(
                    "medication_id"
                ).loc["MED001", "current_stock"]
                self.assertEqual(stock, 1197)

        for role in (Role.CLINICAL, Role.PHARMACIST):
            request = self.details(request_id, role)

            self.assertEqual(request["status"], "closed")
            self.assertEqual(
                request["outcome"], "fulfilled"
            )
            self.assertEqual(
                request["fulfillment"]["quantity"], 3
            )
            self.assertEqual(
                request["fulfillment"]["stock_before"], 1200
            )
            self.assertEqual(
                request["fulfillment"]["stock_after"], 1197
            )
            self.assertEqual(
                request["fulfillment"]["fulfilled_by"],
                "Demo user",
            )
            self.assertEqual(
                [
                    event["to_status"]
                    for event in request["status_history"][-2:]
                ],
                ["fulfilled", "closed"],
            )

        summary = session.read_inventory_summary(
            state_store=self.store
        )
        self.assertEqual(summary["sku_count"], 6)
        self.assertEqual(summary["supplier_count"], 3)
        self.assertAlmostEqual(
            summary["inventory_value_cad"], 800.76
        )
        self.assertEqual(
            self.path.read_bytes(), self.original_bytes
        )

    def test_duplicate_clicks_do_not_deduct_or_append_history(self):
        request_id = self.release()
        original_snapshot = self.info()

        self.fulfill(request_id, snapshot=original_snapshot)

        root = self.store[session.STATE_KEY]
        history = self.details(request_id)["status_history"]

        # Retry the old rendered action.
        self.fulfill(request_id, snapshot=original_snapshot)
        self.assert_notice("error")
        self.assertIs(self.store[session.STATE_KEY], root)

        # Even a fresh revision cannot fulfill the same request again.
        self.fulfill(request_id)
        self.assert_notice("error")
        self.assertIs(self.store[session.STATE_KEY], root)

        self.assertEqual(self.stock(), 1197)
        self.assertEqual(
            self.details(request_id)["status_history"],
            history,
        )

    def test_competing_releases_recheck_latest_stock(self):
        first_id = self.release("MED006", 50)
        second_id = self.release("MED006", 50)

        self.fulfill(first_id)
        self.assertEqual(self.stock("MED006"), 30)

        root = self.store[session.STATE_KEY]
        before = self.inventory()

        self.fulfill(second_id)

        self.assert_notice("error")
        self.assertIs(self.store[session.STATE_KEY], root)
        assert_frame_equal(self.inventory(), before)

        request = self.details(second_id)
        self.assertEqual(
            request["status"], "approved_for_release"
        )
        self.assertIsNone(request["fulfillment"])
        self.assertEqual(self.stock("MED006"), 30)

    def test_fulfillment_updates_units_indicators_and_boundaries(self):
        cases = (
            ("MED001", 1200, 0, ZERO_STOCK_LABEL, 705.0, 2),
            ("MED006", 20, 60, REVIEW_STOCK_LABEL, 711.0, 1),
        )

        for (
            medication_id,
            quantity,
            expected_stock,
            expected_review,
            expected_value,
            expected_zero_count,
        ) in cases:
            with self.subTest(medication_id=medication_id):
                self.store = {}
                self.ensure()

                request_id = self.release(
                    medication_id, quantity
                )
                self.fulfill(request_id)

                self.assert_notice("success")
                self.assertEqual(
                    self.stock(medication_id),
                    expected_stock,
                )

                review = session.read_replenishment_review(
                    state_store=self.store
                ).set_index("medication_id")

                self.assertEqual(
                    review.loc[
                        medication_id, "ordering_review"
                    ],
                    expected_review,
                )

                summary = session.read_inventory_summary(
                    state_store=self.store
                )
                self.assertAlmostEqual(
                    summary["inventory_value_cad"],
                    expected_value,
                )
                self.assertEqual(
                    summary["zero_stock_count"],
                    expected_zero_count,
                )
                self.assertEqual(summary["sku_count"], 6)
                self.assertEqual(summary["supplier_count"], 3)

                if expected_stock == 0:
                    status = self.inventory().set_index(
                        "medication_id"
                    ).loc[medication_id, "status"]
                    self.assertEqual(status, "Out of stock")

    def test_procurement_feedback_requires_shortage_escalation(self):
        request_id = self.submit("MED003", 3)
        root = self.store[session.STATE_KEY]

        self.assertEqual(
            self.queue(Role.PROCUREMENT), []
        )

        self.feedback(request_id)

        self.assert_notice("error")
        self.assertIs(self.store[session.STATE_KEY], root)

        self.action(
            "start_review",
            request_id,
            role=Role.PHARMACIST,
        )
        self.action(
            "escalate_shortage",
            request_id,
            "Synthetic shortage confirmed",
            role=Role.PHARMACIST,
        )

        self.assertEqual(
            [
                request["request_id"]
                for request in self.queue(Role.PROCUREMENT)
            ],
            [request_id],
        )
        self.assertEqual(self.stock("MED003"), 0)

    def test_supply_feedback_is_shared_without_inventory_change(self):
        request_id = self.escalate()
        before = self.inventory()
        before_summary = session.read_inventory_summary(
            state_store=self.store
        )

        self.feedback(request_id)
        self.assert_notice("success")

        for role in (Role.CLINICAL, Role.PHARMACIST):
            with self.subTest(role=role):
                request = self.details(request_id, role)
                self.assertEqual(
                    request["status"], "awaiting_supply"
                )
                self.assertIsNone(request["outcome"])
                self.assertIsNone(request["fulfillment"])
                self.assertEqual(
                    request["supply_feedback"]["feedback"],
                    "Synthetic supplier review recorded; no order placed.",
                )

        clinical_feedback = self.details(
            request_id, Role.CLINICAL
        )["supply_feedback"]
        self.assertNotIn("supplier", clinical_feedback)
        self.assertNotIn(
            "lead_time_demand", clinical_feedback
        )

        pharmacist_feedback = self.details(
            request_id, Role.PHARMACIST
        )["supply_feedback"]
        self.assertIn("supplier", pharmacist_feedback)
        self.assertIn(
            "lead_time_days", pharmacist_feedback
        )

        assert_frame_equal(self.inventory(), before)
        self.assertEqual(
            session.read_inventory_summary(
                state_store=self.store
            ),
            before_summary,
        )

    def test_duplicate_feedback_is_rejected_but_edit_is_allowed(self):
        request_id = self.escalate()
        self.feedback(request_id)

        root = self.store[session.STATE_KEY]
        history = self.details(request_id)["status_history"]

        self.feedback(request_id)

        self.assert_notice("error")
        self.assertIs(self.store[session.STATE_KEY], root)
        self.assertEqual(
            self.details(request_id)["status_history"],
            history,
        )

        self.feedback(
            request_id,
            "Updated synthetic review; delivery remains unconfirmed.",
        )

        self.assert_notice("success")
        self.assertEqual(
            len(self.details(request_id)["status_history"]),
            len(history) + 1,
        )
        self.assertEqual(self.stock("MED003"), 0)

    def test_blank_feedback_preserves_request_and_entered_text(self):
        request_id = self.escalate()
        root = self.store[session.STATE_KEY]

        self.feedback(request_id, "   ")

        self.assert_notice("error")
        self.assertIs(self.store[session.STATE_KEY], root)
        self.assertEqual(
            self.details(request_id)["status"], "escalated"
        )
        self.assertEqual(
            self.store[self.feedback_key], "   "
        )

    def test_expected_date_is_informational_and_invalid_date_rejected(self):
        request_id = self.escalate()

        self.feedback(
            request_id,
            expected_date=date(2026, 11, 10),
        )

        request = self.details(request_id)
        self.assertEqual(
            request["supply_feedback"]["expected_delivery"],
            "2026-11-10",
        )
        self.assertEqual(self.stock("MED003"), 0)
        self.assertIsNone(request["fulfillment"])

        root = self.store[session.STATE_KEY]
        self.feedback(
            request_id,
            text="Another synthetic update",
            expected_date="tomorrow",
        )

        self.assert_notice("error")
        self.assertIs(self.store[session.STATE_KEY], root)
        self.assertEqual(self.stock("MED003"), 0)

    def test_both_datasets_support_fulfillment_and_supply_feedback(self):
        for filename in (
            "sample_medications.csv",
            "sample_medications_extended.csv",
        ):
            with self.subTest(dataset=filename):
                self.store = {}
                self.path.write_bytes(
                    (
                        PROJECT_ROOT / "data" / filename
                    ).read_bytes()
                )
                source_bytes = self.path.read_bytes()
                self.ensure()

                released_id = self.release()
                self.fulfill(released_id)
                self.assert_notice("success")
                self.assertEqual(self.stock(), 1197)

                shortage_id = self.escalate()
                self.feedback(shortage_id)
                self.assert_notice("success")

                feedback = self.details(
                    shortage_id, Role.PHARMACIST
                )["supply_feedback"]

                if filename == "sample_medications.csv":
                    self.assertIsNone(
                        feedback["lead_time_days"]
                    )
                    self.assertIsNone(
                        feedback["expected_delivery"]
                    )
                    self.assertIsNone(
                        feedback["lead_time_demand"]
                    )
                    self.assertNotIn(
                        "reorder_point",
                        self.inventory().columns,
                    )

                    review = session.read_replenishment_review(
                        state_store=self.store
                    ).set_index("medication_id")
                    self.assertEqual(
                        review.loc[
                            "MED001", "ordering_review"
                        ],
                        MISSING_REORDER_LABEL,
                    )

                self.assertEqual(
                    self.path.read_bytes(), source_bytes
                )

    def test_reset_restores_inventory_and_clears_handoffs(self):
        released_id = self.release()
        self.fulfill(released_id)

        shortage_id = self.escalate()
        self.feedback(shortage_id)

        old_run_id = self.info().run_id

        session.reset_demo_session(
            clinical_tab_label="Clinical",
            state_store=self.store,
            now=self.tick(),
        )

        self.assertNotEqual(
            self.info().run_id, old_run_id
        )
        self.assertEqual(self.info().request_count, 0)
        self.assertEqual(self.stock(), 1200)
        self.assertEqual(self.stock("MED003"), 0)
        self.assertEqual(self.queue(Role.WAREHOUSE), [])
        self.assertEqual(self.queue(Role.PROCUREMENT), [])

        self.assertNotIn(
            self.confirmation_key, self.store
        )
        self.assertNotIn(
            self.feedback_key, self.store
        )
        self.assertNotIn(
            self.expected_date_key, self.store
        )

        summary = session.read_inventory_summary(
            state_store=self.store
        )
        self.assertAlmostEqual(
            summary["inventory_value_cad"], 801.0
        )

    def test_callbacks_from_old_run_cannot_target_reused_ids(self):
        old_released_id = self.release()
        old_shortage_id = self.escalate()
        old_info = self.info()

        session.reset_demo_session(
            clinical_tab_label="Clinical",
            state_store=self.store,
            now=self.tick(),
        )

        new_released_id = self.release()
        new_shortage_id = self.escalate()

        self.assertEqual(old_released_id, new_released_id)
        self.assertEqual(old_shortage_id, new_shortage_id)

        root = self.store[session.STATE_KEY]
        before = self.inventory()

        self.fulfill(
            old_released_id, snapshot=old_info
        )
        self.assert_notice("error")
        self.assertIs(self.store[session.STATE_KEY], root)

        self.feedback(
            old_shortage_id, snapshot=old_info
        )
        self.assert_notice("error")
        self.assertIs(self.store[session.STATE_KEY], root)

        assert_frame_equal(self.inventory(), before)
        self.assertEqual(
            self.details(new_shortage_id)["status"],
            "escalated",
        )

    def test_failure_building_fulfillment_leaves_no_partial_deduction(self):
        request_id = self.release()
        root = self.store[session.STATE_KEY]
        before = self.inventory()

        with patch(
            "src.services.workflow.FulfillmentRecord",
            side_effect=ValueError(
                "Synthetic fulfillment record could not be built"
            ),
        ):
            self.fulfill(request_id)

        self.assert_notice("error")
        self.assertIs(self.store[session.STATE_KEY], root)
        assert_frame_equal(self.inventory(), before)
        self.assertIsNone(
            self.details(request_id)["fulfillment"]
        )
        self.assertEqual(
            self.details(request_id)["status"],
            "approved_for_release",
        )

    def test_source_change_blocks_both_callbacks(self):
        released_id = self.release()
        shortage_id = self.escalate()
        root = self.store[session.STATE_KEY]
        before = self.inventory()

        self.path.write_bytes(
            self.path.read_bytes() + b"\n"
        )

        self.fulfill(released_id)
        self.assert_notice("error")
        self.assertIs(self.store[session.STATE_KEY], root)

        self.feedback(shortage_id)
        self.assert_notice("error")
        self.assertIs(self.store[session.STATE_KEY], root)

        assert_frame_equal(self.inventory(), before)

    def test_routine_replenishment_does_not_create_requests(self):
        root = self.store[session.STATE_KEY]

        review = session.read_replenishment_review(
            state_store=self.store
        ).set_index("medication_id")

        self.assertEqual(
            review.loc["MED003", "ordering_review"],
            ZERO_STOCK_LABEL,
        )
        self.assertEqual(
            review.loc["MED006", "ordering_review"],
            REVIEW_STOCK_LABEL,
        )
        self.assertIs(self.store[session.STATE_KEY], root)
        self.assertEqual(self.info().request_count, 0)
        self.assertEqual(self.queue(Role.PROCUREMENT), [])

    def test_closure_after_feedback_is_not_fulfillment(self):
        request_id = self.escalate()
        self.feedback(request_id)
        before = self.inventory()

        self.action(
            "close_without_supply",
            request_id,
            "Synthetic request closed without supply",
            role=Role.PHARMACIST,
        )

        request = self.details(request_id)
        self.assertEqual(request["status"], "closed")
        self.assertEqual(
            request["outcome"], "closed_without_supply"
        )
        self.assertIsNone(request["fulfillment"])
        assert_frame_equal(self.inventory(), before)

        summary = session.read_request_summary(
            state_store=self.store
        )
        self.assertEqual(summary["fulfilled_requests"], 0)
        self.assertEqual(summary["closed_without_supply"], 1)


if __name__ == "__main__":
    unittest.main()