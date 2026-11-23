"""Canonical movement identity, quantities, boundaries and reset."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

import pandas as pd

from pandas.testing import assert_frame_equal

from src.config import PROJECT_ROOT
from src.services.stock_movements import MOVEMENT_COLUMNS
from src.services.workflow_models import (
    CreateOrderInput,
    ReceiptInput,
    Role,
    SubmitRequestInput,
    SupplyFeedbackInput,
    WorkflowError,
)
from src.ui import session


class StockMovementTests(unittest.TestCase):
    def setUp(self):
        self.clock = datetime(
            2026, 11, 20, 12, 0, tzinfo=timezone.utc
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

    def movements(self):
        return session.read_stock_movements(
            Role.WAREHOUSE,
            state_store=self.store,
        )

    def submit(self, medication_id="MED003", quantity=5):
        state = self.store[session.STATE_KEY]
        unit = state.inventory.set_index(
            "medication_id"
        ).at[medication_id, "stock_unit"]

        return self.action(
            "submit_request",
            SubmitRequestInput(
                medication_id=medication_id,
                quantity=quantity,
                unit=unit,
                requesting_location="Demo Ward",
                reason="Synthetic movement check",
            ),
            f"request-{state.next_request_number}",
            role=Role.CLINICAL,
        ).request_id

    def make_order(self):
        request_id = self.submit()

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

        state = self.store[session.STATE_KEY]
        order_id = self.action(
            "confirm_order",
            request_id,
            CreateOrderInput(300, "tablet"),
            f"order-{state.next_order_number}",
            role=Role.PROCUREMENT,
        ).order_id

        return request_id, order_id

    def post(self, order_id, quantity):
        number = self.store[
            session.STATE_KEY
        ].next_receipt_number

        return self.action(
            "confirm_receipt",
            order_id,
            ReceiptInput(quantity, "tablet"),
            f"receipt-{number}",
            role=Role.WAREHOUSE,
        ).receipt_id

    def release(self, request_id):
        self.action(
            "start_review",
            request_id,
            role=Role.PHARMACIST,
        )
        self.action(
            "authorize_release",
            request_id,
            "Synthetic availability review completed",
            role=Role.PHARMACIST,
        )

    def fulfill(self, request_id):
        self.release(request_id)
        self.action(
            "fulfill_request",
            request_id,
            role=Role.WAREHOUSE,
        )

    def test_empty_session_retains_headers(self):
        movements = self.movements()

        self.assertTrue(movements.empty)
        self.assertEqual(
            list(movements.columns),
            list(MOVEMENT_COLUMNS),
        )

    def test_non_stock_actions_and_receipt_preview_create_no_movements(self):
        available_request = self.submit("MED001", 3)
        self.release(available_request)

        _, order_id = self.make_order()
        info = session.get_session_info(
            state_store=self.store
        )

        preview = session.preview_simulated_receipt(
            order_id,
            ReceiptInput(100, "tablet"),
            expected_run_id=info.run_id,
            expected_revision=info.revision,
            source_path=self.path,
            state_store=self.store,
            now=self.tick(),
        )

        self.assertEqual(preview["stock_after"], 100)
        self.assertTrue(self.movements().empty)

        self.action(
            "cancel_order",
            order_id,
            "Synthetic cancellation before receipt",
            role=Role.PROCUREMENT,
        )

        self.assertTrue(self.movements().empty)

    def test_receipt_fulfillment_receipt_sequence_is_counted_once(self):
        request_id, order_id = self.make_order()
        first_receipt = self.post(order_id, 100)

        self.fulfill(request_id)
        second_receipt = self.post(order_id, 200)

        movements = self.movements()

        self.assertEqual(len(movements), 3)
        self.assertEqual(
            movements["movement_type"].tolist(),
            ["receipt", "fulfillment", "receipt"],
        )
        self.assertEqual(
            movements["quantity_change"].tolist(),
            [100, -5, 200],
        )
        self.assertEqual(
            movements["stock_before"].tolist(),
            [0, 100, 95],
        )
        self.assertEqual(
            movements["stock_after"].tolist(),
            [100, 95, 295],
        )
        self.assertEqual(
            movements["linked_request_id"].tolist(),
            [request_id, request_id, request_id],
        )
        self.assertEqual(
            movements.loc[
                movements["movement_type"].eq("receipt"),
                "receipt_id",
            ].tolist(),
            [first_receipt, second_receipt],
        )

        fulfillment = movements.loc[
            movements["movement_type"].eq("fulfillment")
        ].iloc[0]

        self.assertEqual(
            fulfillment["movement_id"],
            self.store[session.STATE_KEY]
            .requests[request_id]
            .fulfillment.fulfillment_id,
        )
        self.assertTrue(pd.isna(fulfillment["order_id"]))

        # Two workflow events still represent one stock deduction.
        history = self.store[
            session.STATE_KEY
        ].requests[request_id].status_history

        self.assertEqual(
            sum(
                event.action in {
                    "fulfill_request",
                    "auto_close_fulfilled",
                }
                for event in history
            ),
            2,
        )
        self.assertEqual(
            int(
                movements["movement_type"]
                .eq("fulfillment")
                .sum()
            ),
            1,
        )

    def test_duplicate_actions_do_not_add_movements(self):
        request_id, order_id = self.make_order()
        self.post(order_id, 100)
        self.fulfill(request_id)

        before = self.movements()
        root = self.store[session.STATE_KEY]

        with self.assertRaises(WorkflowError):
            self.action(
                "fulfill_request",
                request_id,
                role=Role.WAREHOUSE,
            )

        with self.assertRaises(WorkflowError):
            self.action(
                "confirm_receipt",
                order_id,
                ReceiptInput(100, "tablet"),
                "receipt-1",
                role=Role.WAREHOUSE,
            )

        self.assertIs(self.store[session.STATE_KEY], root)
        assert_frame_equal(self.movements(), before)

    def test_units_and_medication_balances_remain_separate(self):
        for medication_id, quantity in (
            ("MED001", 3),
            ("MED002", 2),
            ("MED006", 1),
        ):
            self.fulfill(
                self.submit(medication_id, quantity)
            )

        movements = self.movements().set_index(
            "medication_id"
        )

        for medication_id, unit, before, after in (
            ("MED001", "tablet", 1200, 1197),
            ("MED002", "capsule", 600, 598),
            ("MED006", "vial", 80, 79),
        ):
            with self.subTest(medication=medication_id):
                self.assertEqual(
                    movements.at[medication_id, "stock_unit"],
                    unit,
                )
                self.assertEqual(
                    movements.at[medication_id, "stock_before"],
                    before,
                )
                self.assertEqual(
                    movements.at[medication_id, "stock_after"],
                    after,
                )

    def test_reader_is_detached_non_commercial_and_read_only(self):
        _, order_id = self.make_order()
        self.post(order_id, 100)

        root = self.store[session.STATE_KEY]
        before = deepcopy(root)
        movements = self.movements()

        for field in (
            "supplier",
            "unit_cost",
            "order_value_cad",
            "order_key",
            "receipt_key",
            "submission_key",
            "status_history",
        ):
            self.assertNotIn(field, movements.columns)

        movements.loc[0, "quantity_change"] = 999

        self.assertEqual(
            self.movements().iloc[0]["quantity_change"],
            100,
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
            "next_substitute_review_number",
        ):
            self.assertEqual(
                getattr(root, field),
                getattr(before, field),
                field,
            )

        self.assertEqual(
            self.path.read_bytes(),
            self.source_bytes,
        )

    def test_other_roles_do_not_receive_this_warehouse_projection(self):
        for role in (
            Role.CLINICAL,
            Role.PHARMACIST,
            Role.PROCUREMENT,
            Role.EXECUTIVE,
            Role.REPORTING,
            Role.SYSTEM,
            "unknown-role",
        ):
            with self.subTest(role=role):
                with self.assertRaises(WorkflowError):
                    session.read_stock_movements(
                        role,
                        state_store=self.store,
                    )

    def test_both_schemas_and_reset(self):
        for filename in (
            "sample_medications.csv",
            "sample_medications_extended.csv",
        ):
            with self.subTest(dataset=filename):
                self.start_session(filename)
                request_id, order_id = self.make_order()

                self.post(order_id, 300)
                self.fulfill(request_id)

                self.assertEqual(
                    self.movements()["quantity_change"].tolist(),
                    [300, -5],
                )

                session.reset_demo_session(
                    clinical_tab_label="Clinical",
                    state_store=self.store,
                    now=self.tick(),
                )

                self.assertTrue(self.movements().empty)

                state = self.store[session.STATE_KEY]
                assert_frame_equal(
                    state.inventory,
                    state.initial_inventory,
                )
                self.assertEqual(
                    self.path.read_bytes(),
                    self.source_bytes,
                )


if __name__ == "__main__":
    unittest.main()