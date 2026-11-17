"""Order-reader boundaries and shared session integration checks."""

from datetime import date, datetime, timedelta, timezone
import unittest

from pandas.testing import assert_frame_equal

from src.config import PROJECT_ROOT
from src.services.workflow_models import (
    CreateOrderInput,
    Role,
    SubmitRequestInput,
    SupplyFeedbackInput,
    WorkflowError,
)
from src.ui import session


class OrderQueryTests(unittest.TestCase):
    def setUp(self):
        self.path = (
            PROJECT_ROOT / "data" / "sample_medications_extended.csv"
        )
        self.original_bytes = self.path.read_bytes()
        self.store = {}
        self.clock = datetime(
            2026, 11, 17, 12, 0,
            tzinfo=timezone.utc,
        )

        session.ensure_demo_session(
            self.path,
            state_store=self.store,
            now=self.tick(),
        )

        result = self.action(
            "submit_request",
            SubmitRequestInput(
                medication_id="MED003",
                quantity=5,
                unit="tablet",
                requesting_location="Demo Ward",
                reason="Synthetic order-reader check",
            ),
            "query-request",
            role=Role.CLINICAL,
        )
        self.request_id = result.request_id

        self.action(
            "start_review",
            self.request_id,
            role=Role.PHARMACIST,
        )
        self.action(
            "escalate_shortage",
            self.request_id,
            "Recorded stock does not cover the request",
            role=Role.PHARMACIST,
        )
        self.action(
            "update_supply_feedback",
            self.request_id,
            SupplyFeedbackInput("Synthetic supply review"),
            role=Role.PROCUREMENT,
        )

    def tick(self):
        self.clock += timedelta(seconds=1)
        return self.clock

    def info(self):
        return session.get_session_info(state_store=self.store)

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

    def confirm(self):
        return self.action(
            "confirm_order",
            self.request_id,
            CreateOrderInput(300, "tablet"),
            "query-order",
            role=Role.PROCUREMENT,
        ).order_id

    def details(self, order_id, role):
        return session.read_order_details(
            order_id,
            role,
            state_store=self.store,
        )

    def test_preview_is_detached_and_never_publishes_state(self):
        info = self.info()
        root = self.store[session.STATE_KEY]

        preview = session.preview_simulated_order(
            self.request_id,
            CreateOrderInput(300, "tablet"),
            expected_run_id=info.run_id,
            expected_revision=info.revision,
            source_path=self.path,
            state_store=self.store,
            now=self.tick(),
        )
        preview["warnings"].append("Changed presentation copy")

        self.assertIs(self.store[session.STATE_KEY], root)
        self.assertEqual(self.info().revision, info.revision)
        self.assertFalse(root.orders)

    def test_role_projections_exclude_restricted_fields_and_keys(self):
        order_id = self.confirm()

        clinical = self.details(order_id, Role.CLINICAL)
        pharmacist = self.details(order_id, Role.PHARMACIST)
        warehouse = self.details(order_id, Role.WAREHOUSE)
        procurement = self.details(order_id, Role.PROCUREMENT)

        for field in (
            "ordered_quantity",
            "quantity_received",
            "quantity_outstanding",
            "supplier",
            "unit_cost",
            "order_value_cad",
            "order_history",
        ):
            self.assertNotIn(field, clinical)

        for projection in (pharmacist, warehouse):
            for field in (
                "unit_cost",
                "order_value_cad",
                "order_value_note",
                "status_reason",
            ):
                self.assertNotIn(field, projection)

        self.assertIn("supplier", pharmacist)
        self.assertNotIn("supplier", warehouse)
        self.assertEqual(procurement["ordered_quantity"], 300)
        self.assertIn("order_value_cad", procurement)

        for projection in (
            clinical, pharmacist, warehouse, procurement
        ):
            self.assertNotIn("order_key", projection)

        for role in (Role.EXECUTIVE, Role.REPORTING, Role.SYSTEM):
            with self.subTest(role=role):
                with self.assertRaises(WorkflowError):
                    self.details(order_id, role)

    def test_commercial_reason_does_not_leak_through_history(self):
        order_id = self.confirm()
        private_reason = "PRIVATE_COMMERCIAL_NOTE_36_CAD"

        self.action(
            "update_order_delivery",
            order_id,
            date(2026, 11, 25),
            private_reason,
            role=Role.PROCUREMENT,
        )

        self.assertIn(
            private_reason,
            repr(self.details(order_id, Role.PROCUREMENT)),
        )

        for role in (
            Role.CLINICAL,
            Role.PHARMACIST,
            Role.WAREHOUSE,
        ):
            with self.subTest(role=role):
                self.assertNotIn(
                    private_reason,
                    repr(self.details(order_id, role)),
                )

        for role in (Role.CLINICAL, Role.PHARMACIST):
            request = session.read_request_details(
                self.request_id,
                role,
                state_store=self.store,
            )
            self.assertNotIn(private_reason, repr(request))

    def test_requests_receive_linked_role_projected_progress(self):
        order_id = self.confirm()

        for role in (
            Role.CLINICAL,
            Role.PHARMACIST,
            Role.PROCUREMENT,
        ):
            with self.subTest(role=role):
                request = session.read_request_details(
                    self.request_id,
                    role,
                    state_store=self.store,
                )
                self.assertEqual(request["status"], "on_order")
                self.assertEqual(request["order_ids"], [order_id])
                self.assertEqual(
                    request["orders"][0]["order_id"],
                    order_id,
                )

        for role in (Role.PHARMACIST, Role.PROCUREMENT):
            actionable = session.read_requests(
                role,
                actionable_only=True,
                state_store=self.store,
            )
            self.assertIn(
                self.request_id,
                [request["request_id"] for request in actionable],
            )

        reporting_request = session.read_request_details(
            self.request_id,
            Role.REPORTING,
            state_store=self.store,
        )
        self.assertEqual(reporting_request["status"], "on_order")
        self.assertNotIn("orders", reporting_request)

    def test_order_and_nested_request_outputs_are_detached(self):
        order_id = self.confirm()
        order = self.details(order_id, Role.PROCUREMENT)
        order["order_history"][0]["reason"] = "Changed copy"

        request = session.read_request_details(
            self.request_id,
            Role.PHARMACIST,
            state_store=self.store,
        )
        request["orders"][0]["ordered_quantity"] = 999

        self.assertNotEqual(
            self.details(
                order_id, Role.PROCUREMENT
            )["order_history"][0]["reason"],
            "Changed copy",
        )
        self.assertEqual(
            self.details(
                order_id, Role.PHARMACIST
            )["ordered_quantity"],
            300,
        )

    def test_cancelled_order_history_remains_visible(self):
        order_id = self.confirm()
        self.action(
            "cancel_order",
            order_id,
            "Synthetic cancellation before receipt",
            role=Role.PROCUREMENT,
        )

        all_orders = session.read_orders(
            Role.PROCUREMENT,
            state_store=self.store,
        )
        open_orders = session.read_orders(
            Role.PROCUREMENT,
            open_only=True,
            state_store=self.store,
        )

        self.assertEqual(len(all_orders), 1)
        self.assertEqual(all_orders[0]["order_status"], "cancelled")
        self.assertEqual(open_orders, [])
        self.assertEqual(
            len(
                self.details(
                    order_id, Role.PROCUREMENT
                )["order_history"]
            ),
            2,
        )

    def test_duplicate_confirmation_does_not_publish_a_new_root(self):
        old_info = self.info()
        self.confirm()
        root = self.store[session.STATE_KEY]

        with self.assertRaises(WorkflowError) as caught:
            session.apply_workflow_action(
                "confirm_order",
                self.request_id,
                CreateOrderInput(300, "tablet"),
                "query-order",
                acting_role=Role.PROCUREMENT,
                expected_run_id=old_info.run_id,
                expected_revision=old_info.revision,
                source_path=self.path,
                state_store=self.store,
                now=self.tick(),
            )
        self.assertEqual(caught.exception.code, "stale_state")
        self.assertIs(self.store[session.STATE_KEY], root)

        with self.assertRaises(WorkflowError) as caught:
            self.action(
                "confirm_order",
                self.request_id,
                CreateOrderInput(300, "tablet"),
                "query-order",
                role=Role.PROCUREMENT,
            )
        self.assertEqual(caught.exception.code, "duplicate_action")
        self.assertIs(self.store[session.STATE_KEY], root)

    def test_reset_clears_order_records_and_order_ui_state(self):
        self.confirm()
        previous = self.info()

        self.store["workflow_ui_order_preview_test"] = {
            "temporary": True
        }

        session.reset_demo_session(
            clinical_tab_label="Clinical",
            state_store=self.store,
            now=self.tick(),
        )
        state = self.store[session.STATE_KEY]

        self.assertNotEqual(state.run_id, previous.run_id)
        self.assertFalse(state.orders)
        self.assertFalse(state.requests)
        self.assertEqual(state.next_order_number, 1)
        self.assertNotIn(
            "workflow_ui_order_preview_test",
            self.store,
        )
        assert_frame_equal(
            state.inventory, state.initial_inventory
        )
        self.assertEqual(self.path.read_bytes(), self.original_bytes)


if __name__ == "__main__":
    unittest.main()