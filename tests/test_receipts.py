"""Synthetic receipt posting, quantities, history and reset checks."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import unittest
from unittest.mock import patch

import pandas as pd
from pandas.testing import assert_frame_equal

from src.config import PROJECT_ROOT
from src.data.loader import load_medications
from src.services import orders
from src.services import receipts
from src.services import workflow as wf
from src.services import workflow_queries as queries
from src.services.analytics import build_stock_analytics
from src.services.workflow_models import (
    CreateOrderInput,
    OrderStatus,
    ReceiptInput,
    RequestStatus,
    Role,
    SubmitRequestInput,
    SupplyFeedbackInput,
    WorkflowError,
)


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.clock = datetime(
            2026, 11, 17, 12, 0, tzinfo=timezone.utc
        )
        self.make_state()

    def tick(self):
        self.clock += timedelta(seconds=1)
        return self.clock

    def make_state(self, filename="sample_medications_extended.csv"):
        self.path = PROJECT_ROOT / "data" / filename
        self.source = self.path.read_bytes()
        self.state = wf.initialize_demo(
            load_medications(self.path),
            dataset_path=str(self.path),
            dataset_fingerprint=sha256(self.source).hexdigest(),
            now=self.tick(),
        )

    def context(self, role=Role.WAREHOUSE):
        return wf.make_context(self.state, role, now=self.tick())

    def action(self, name, *args, role, module=wf):
        result = getattr(module, name)(
            self.state, *args, context=self.context(role)
        )
        self.state = result.state
        return result

    def make_order(self, requested=5, ordered=300):
        result = self.action(
            "submit_request",
            SubmitRequestInput(
                medication_id="MED003",
                quantity=requested,
                unit="tablet",
                requesting_location="Demo Ward",
                reason="Synthetic receipt check",
            ),
            f"request-{self.state.next_request_number}",
            role=Role.CLINICAL,
        )
        request_id = result.request_id
        self.action("start_review", request_id, role=Role.PHARMACIST)
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
        result = self.action(
            "confirm_order",
            request_id,
            CreateOrderInput(ordered, "tablet"),
            f"order-{self.state.next_order_number}",
            role=Role.PROCUREMENT,
            module=orders,
        )
        return request_id, result.order_id

    def post(self, order_id, quantity, key=None):
        return self.action(
            "confirm_receipt",
            order_id,
            ReceiptInput(quantity, "tablet"),
            key or f"receipt-{self.state.next_receipt_number}",
            role=Role.WAREHOUSE,
            module=receipts,
        ).receipt_id

    def stock(self):
        return self.state.inventory.set_index(
            "medication_id"
        ).at["MED003", "current_stock"]

    def assert_unchanged(self, before):
        assert_frame_equal(self.state.inventory, before.inventory)
        assert_frame_equal(
            self.state.initial_inventory, before.initial_inventory
        )
        for field in (
            "requests",
            "orders",
            "receipts",
            "revision",
            "next_request_number",
            "next_order_number",
            "next_receipt_number",
        ):
            self.assertEqual(
                getattr(self.state, field),
                getattr(before, field),
            )

    def test_preview_has_no_records_counter_or_stock_effect(self):
        request_id, order_id = self.make_order()
        before = deepcopy(self.state)

        preview = receipts.preview_receipt(
            self.state,
            order_id,
            ReceiptInput(300, "tablet"),
            self.context(),
        )
        self.assertEqual(preview["stock_before"], 0)
        self.assertEqual(preview["stock_after"], 300)
        self.assertEqual(preview["order_status_after"], "received")
        self.assertEqual(
            preview["request_status_after"], "supply_received"
        )
        self.assert_unchanged(before)

    def test_full_receipt_links_records_and_increases_stock_once(self):
        request_id, order_id = self.make_order()
        before = deepcopy(self.state)
        receipt_id = self.post(order_id, 300)

        record = self.state.receipts[receipt_id]
        self.assertEqual(receipt_id, "RCV-0001")
        self.assertEqual(record.order_id, order_id)
        self.assertEqual(record.linked_request_id, request_id)
        self.assertEqual(record.medication_id, "MED003")
        self.assertEqual(record.received_quantity, 300)
        self.assertEqual(record.stock_before, 0)
        self.assertEqual(record.stock_after, 300)
        self.assertTrue(record.inventory_added)
        self.assertEqual(record.recorded_by_role, Role.WAREHOUSE)

        self.assertEqual(self.stock(), 300)
        self.assertEqual(
            self.state.orders[order_id].status,
            OrderStatus.RECEIVED,
        )
        self.assertEqual(
            self.state.orders[order_id].quantity_outstanding, 0
        )
        self.assertEqual(
            self.state.requests[request_id].status,
            RequestStatus.SUPPLY_RECEIVED,
        )
        self.assertFalse(
            self.state.requests[request_id].after_receipt
        )
        self.assertEqual(self.state.revision, before.revision + 1)
        self.assertEqual(self.state.next_receipt_number, 2)

        summary = queries.get_session_request_summary(self.state)
        self.assertEqual(summary["open_requests"], 1)
        self.assertEqual(summary["by_status"]["supply_received"], 1)

    def test_partial_receipt_can_enable_review_before_order_completion(self):
        request_id, order_id = self.make_order()
        self.post(order_id, 200)

        self.assertEqual(self.stock(), 200)
        self.assertEqual(
            self.state.orders[order_id].status,
            OrderStatus.PARTIALLY_RECEIVED,
        )
        self.assertEqual(
            self.state.orders[order_id].quantity_outstanding, 100
        )
        self.assertEqual(
            self.state.requests[request_id].status,
            RequestStatus.SUPPLY_RECEIVED,
        )

        self.post(order_id, 100)
        self.assertEqual(self.stock(), 300)
        self.assertEqual(len(self.state.receipts), 2)
        self.assertEqual(
            self.state.orders[order_id].status,
            OrderStatus.RECEIVED,
        )

    def test_insufficient_partial_receipt_keeps_request_on_order(self):
        request_id, order_id = self.make_order(
            requested=500, ordered=600
        )
        self.post(order_id, 100)

        self.assertEqual(
            self.state.requests[request_id].status,
            RequestStatus.ON_ORDER,
        )
        self.post(order_id, 400)
        self.assertEqual(
            self.state.requests[request_id].status,
            RequestStatus.SUPPLY_RECEIVED,
        )
        self.assertEqual(
            self.state.orders[order_id].quantity_outstanding, 100
        )

    def test_complete_undersized_order_still_triggers_review(self):
        request_id, order_id = self.make_order(
            requested=5, ordered=3
        )
        self.post(order_id, 3)

        self.assertEqual(self.stock(), 3)
        self.assertEqual(
            self.state.orders[order_id].status,
            OrderStatus.RECEIVED,
        )
        self.assertEqual(
            self.state.requests[request_id].status,
            RequestStatus.SUPPLY_RECEIVED,
        )

    def test_receipt_does_not_reopen_a_closed_request(self):
        request_id, order_id = self.make_order()
        self.action(
            "close_without_supply",
            request_id,
            "Request no longer required",
            role=Role.PHARMACIST,
        )
        outcome = self.state.requests[request_id].outcome

        self.post(order_id, 300)

        self.assertEqual(self.stock(), 300)
        self.assertEqual(
            self.state.requests[request_id].status,
            RequestStatus.CLOSED,
        )
        self.assertEqual(
            self.state.requests[request_id].outcome, outcome
        )
        with self.assertRaises(WorkflowError):
            self.action(
                "cancel_order",
                order_id,
                "Cancellation after receipt",
                role=Role.PROCUREMENT,
                module=orders,
            )

    def test_duplicate_receipt_cannot_become_another_partial_receipt(self):
        _, order_id = self.make_order()
        self.post(order_id, 100, key="first-receipt")
        before = deepcopy(self.state)

        with self.assertRaises(WorkflowError) as caught:
            self.post(order_id, 100, key="first-receipt")
        self.assertEqual(caught.exception.code, "duplicate_action")
        self.assert_unchanged(before)

        # A separate deliberate receipt has its own identity.
        self.post(order_id, 100, key="second-receipt")
        self.assertEqual(self.stock(), 200)
        self.assertEqual(len(self.state.receipts), 2)

    def test_invalid_quantities_units_and_over_receipts_are_rejected(self):
        _, order_id = self.make_order()
        before = deepcopy(self.state)

        for quantity in (
            None, 0, -1, 1.5, 3.0, True,
            "3", float("nan"), float("inf"), 301,
        ):
            with self.subTest(quantity=quantity):
                with self.assertRaises(WorkflowError):
                    receipts.confirm_receipt(
                        self.state,
                        order_id,
                        ReceiptInput(quantity, "tablet"),
                        "invalid-receipt",
                        self.context(),
                    )
                self.assert_unchanged(before)

        with self.assertRaises(WorkflowError):
            receipts.confirm_receipt(
                self.state,
                order_id,
                ReceiptInput(100, "vial"),
                "wrong-unit",
                self.context(),
            )
        self.assert_unchanged(before)

    def test_wrong_role_run_revision_and_time_do_not_mutate(self):
        _, order_id = self.make_order()
        before = deepcopy(self.state)
        good = self.context()

        for context in (
            replace(good, acting_role=Role.PROCUREMENT),
            replace(good, expected_run_id="older-run"),
            replace(good, expected_revision=good.expected_revision - 1),
            replace(good, now=datetime(2026, 11, 17)),
            replace(
                good,
                now=datetime(2020, 1, 1, tzinfo=timezone.utc),
            ),
        ):
            with self.subTest(context=context):
                with self.assertRaises(WorkflowError):
                    receipts.confirm_receipt(
                        self.state,
                        order_id,
                        ReceiptInput(100, "tablet"),
                        "guarded-receipt",
                        context,
                    )
                self.assert_unchanged(before)

    def test_changed_unit_and_invalid_stock_block_receipt(self):
        _, order_id = self.make_order()
        baseline = deepcopy(self.state)

        for invalid_stock in (pd.NA, -1, float("inf")):
            with self.subTest(stock=invalid_stock):
                inventory = baseline.inventory.copy(deep=True)
                inventory["current_stock"] = (
                    inventory["current_stock"].astype("Float64")
                )
                inventory.loc[
                    inventory["medication_id"].eq("MED003"),
                    "current_stock",
                ] = invalid_stock
                self.state = replace(baseline, inventory=inventory)
                before = deepcopy(self.state)

                with self.assertRaises(WorkflowError):
                    self.post(order_id, 100)
                self.assert_unchanged(before)

        inventory = baseline.inventory.copy(deep=True)
        inventory.loc[
            inventory["medication_id"].eq("MED003"),
            "stock_unit",
        ] = "vial"
        self.state = replace(baseline, inventory=inventory)
        before = deepcopy(self.state)

        with self.assertRaises(WorkflowError):
            self.post(order_id, 100)
        self.assert_unchanged(before)

    def test_both_schemas_refresh_analytics_and_preserve_source_fields(self):
        for filename in (
            "sample_medications.csv",
            "sample_medications_extended.csv",
        ):
            with self.subTest(dataset=filename):
                self.make_state(filename)
                _, order_id = self.make_order()
                before = self.state.inventory.copy(deep=True)

                self.post(order_id, 300)

                summary = queries.get_inventory_summary(self.state)
                self.assertAlmostEqual(
                    summary["inventory_value_cad"], 837.00
                )
                self.assertEqual(summary["zero_stock_count"], 0)

                row = build_stock_analytics(
                    self.state.inventory
                ).rows.set_index("medication_id").loc["MED003"]

                self.assertEqual(
                    row["stock_coverage_months"], Decimal("0.6")
                )
                self.assertEqual(row["abc_class"], "C")
                self.assertEqual(
                    row["monthly_consumption_value_cad"],
                    Decimal("60.00"),
                )
                if filename == "sample_medications_extended.csv":
                    self.assertEqual(row["reorder_gap"], Decimal(0))
                else:
                    self.assertTrue(pd.isna(row["reorder_gap"]))

                unchanged_columns = [
                    column for column in before.columns
                    if column not in {"current_stock", "status"}
                ]
                assert_frame_equal(
                    before[unchanged_columns],
                    self.state.inventory[unchanged_columns],
                )
                self.assertEqual(self.path.read_bytes(), self.source)

    def test_reset_clears_receipts_orders_and_counters(self):
        _, order_id = self.make_order()
        self.post(order_id, 300)
        old_context = self.context()

        self.state = wf.reset_demo(self.state, now=self.tick())

        self.assertFalse(self.state.receipts)
        self.assertFalse(self.state.orders)
        self.assertFalse(self.state.requests)
        self.assertEqual(self.state.next_receipt_number, 1)
        self.assertEqual(self.state.next_order_number, 1)
        assert_frame_equal(
            self.state.inventory, self.state.initial_inventory
        )

        with self.assertRaises(WorkflowError) as caught:
            receipts.confirm_receipt(
                self.state,
                order_id,
                ReceiptInput(300, "tablet"),
                "old-run-receipt",
                old_context,
            )
        self.assertEqual(caught.exception.code, "wrong_run")

    def test_late_failure_cannot_publish_partial_receipt_changes(self):
        _, order_id = self.make_order()
        before = deepcopy(self.state)

        with patch(
            "src.services.receipts.WorkflowResult",
            side_effect=RuntimeError("Injected result failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.post(order_id, 300)

        self.assert_unchanged(before)


if __name__ == "__main__":
    unittest.main()