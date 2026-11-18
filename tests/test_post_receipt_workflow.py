"""Post-receipt review, routing and fulfillment regression checks."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import unittest
from unittest.mock import patch

from pandas.testing import assert_frame_equal

from src.config import PROJECT_ROOT
from src.data.loader import load_medications
from src.services import orders
from src.services import receipts
from src.services import workflow as wf
from src.services.summary import summarize_inventory
from src.services.workflow_models import (
    CreateOrderInput,
    OrderStatus,
    ReceiptInput,
    RequestOutcome,
    RequestStatus,
    Role,
    SupplyFeedbackInput,
    SubmitRequestInput,
    WorkflowError,
)


class PostReceiptWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.clock = datetime(
            2026, 11, 18, 12, 0, tzinfo=timezone.utc
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

    def context(self, role=Role.PHARMACIST):
        return wf.make_context(
            self.state,
            role,
            now=self.tick(),
        )

    def action(self, name, *args, role=Role.PHARMACIST, module=wf):
        result = getattr(module, name)(
            self.state,
            *args,
            context=self.context(role),
        )
        self.state = result.state
        return result

    def submit(self, quantity=5):
        return self.action(
            "submit_request",
            SubmitRequestInput(
                medication_id="MED003",
                quantity=quantity,
                unit="tablet",
                requesting_location="Demo Ward",
                reason="Post-receipt workflow test",
            ),
            f"submission-{self.state.next_request_number}",
            role=Role.CLINICAL,
        ).request_id

    def make_order(self, requested=5, ordered=300):
        request_id = self.submit(requested)

        self.action("start_review", request_id)
        self.action(
            "escalate_shortage",
            request_id,
            "Recorded stock cannot cover the request",
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
            CreateOrderInput(ordered, "tablet"),
            f"order-{self.state.next_order_number}",
            role=Role.PROCUREMENT,
            module=orders,
        ).order_id

        return request_id, order_id

    def post(self, order_id, quantity):
        return self.action(
            "confirm_receipt",
            order_id,
            ReceiptInput(quantity, "tablet"),
            f"receipt-{self.state.next_receipt_number}",
            role=Role.WAREHOUSE,
            module=receipts,
        )

    def stock(self):
        return self.state.inventory.loc[
            self.state.inventory["medication_id"].eq("MED003"),
            "current_stock",
        ].iloc[0]

    def assert_unchanged(self, before):
        assert_frame_equal(self.state.inventory, before.inventory)
        assert_frame_equal(
            self.state.initial_inventory,
            before.initial_inventory,
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
                field,
            )

    def consume_available_stock(self, quantity):
        """Use a separate valid request instead of editing inventory."""
        request_id = self.submit(quantity)

        self.action("start_review", request_id)
        self.action(
            "authorize_release",
            request_id,
            "Separate synthetic request covers the available stock",
        )
        self.action(
            "fulfill_request",
            request_id,
            role=Role.WAREHOUSE,
        )

        return request_id

    def test_full_receipt_review_release_and_fulfillment_both_schemas(self):
        for filename in (
            "sample_medications.csv",
            "sample_medications_extended.csv",
        ):
            with self.subTest(dataset=filename):
                self.make_state(filename)
                request_id, order_id = self.make_order()

                self.post(order_id, 300)

                request = self.state.requests[request_id]
                self.assertEqual(
                    request.status,
                    RequestStatus.SUPPLY_RECEIVED,
                )
                self.assertFalse(request.after_receipt)
                self.assertEqual(self.stock(), 300)

                self.action("start_review", request_id)
                self.assertTrue(
                    self.state.requests[request_id].after_receipt
                )

                self.action(
                    "authorize_release",
                    request_id,
                    "Explicit synthetic review after receipt",
                )

                self.assertEqual(self.stock(), 300)
                self.assertTrue(
                    self.state.requests[request_id].after_receipt
                )

                self.action(
                    "fulfill_request",
                    request_id,
                    role=Role.WAREHOUSE,
                )

                request = self.state.requests[request_id]
                self.assertEqual(request.status, RequestStatus.CLOSED)
                self.assertEqual(
                    request.outcome,
                    RequestOutcome.FULFILLED,
                )
                self.assertFalse(request.after_receipt)
                self.assertEqual(self.stock(), 295)

                summary = summarize_inventory(self.state.inventory)
                self.assertAlmostEqual(
                    summary["inventory_value_cad"],
                    836.40,
                    places=2,
                )
                self.assertEqual(summary["zero_stock_count"], 0)
                self.assertEqual(self.path.read_bytes(), self.source)

                before = deepcopy(self.state)

                with self.assertRaises(WorkflowError):
                    self.action(
                        "fulfill_request",
                        request_id,
                        role=Role.WAREHOUSE,
                    )

                self.assert_unchanged(before)

    def test_initial_review_returns_to_received_queue(self):
        request_id = self.submit()
        self.action("start_review", request_id)
        self.action("return_to_queue", request_id, None)

        request = self.state.requests[request_id]
        self.assertEqual(request.status, RequestStatus.RECEIVED)
        self.assertFalse(request.after_receipt)

    def test_post_receipt_review_returns_to_supply_received_queue(self):
        request_id, order_id = self.make_order()
        self.post(order_id, 300)

        self.action("start_review", request_id)
        before = deepcopy(self.state.inventory)
        self.action("return_to_queue", request_id, "Review paused")

        request = self.state.requests[request_id]
        self.assertEqual(
            request.status,
            RequestStatus.SUPPLY_RECEIVED,
        )
        self.assertTrue(request.after_receipt)
        assert_frame_equal(self.state.inventory, before)

        self.action("start_review", request_id)

        self.assertEqual(
            self.state.requests[request_id].status,
            RequestStatus.UNDER_REVIEW,
        )
        self.assertTrue(
            self.state.requests[request_id].after_receipt
        )

    def test_final_return_is_blocked_after_receipt(self):
        request_id, order_id = self.make_order()
        self.post(order_id, 300)
        self.action("start_review", request_id)
        before = deepcopy(self.state)

        with self.assertRaises(WorkflowError):
            self.action(
                "return_request",
                request_id,
                "Attempt final return after receipt",
            )

        self.assert_unchanged(before)

    def test_initial_review_still_allows_final_return(self):
        request_id = self.submit()
        self.action("start_review", request_id)

        self.action(
            "return_request",
            request_id,
            "Synthetic initial request needs correction",
        )

        request = self.state.requests[request_id]
        self.assertEqual(request.status, RequestStatus.RETURNED)
        self.assertEqual(request.outcome, RequestOutcome.RETURNED)

    def test_complete_small_order_requires_new_review_and_supply_feedback(self):
        request_id, first_order = self.make_order(ordered=3)
        self.post(first_order, 3)

        self.assertEqual(
            self.state.requests[request_id].status,
            RequestStatus.SUPPLY_RECEIVED,
        )

        self.action("start_review", request_id)
        before = deepcopy(self.state)

        with self.assertRaises(WorkflowError):
            self.action(
                "authorize_release",
                request_id,
                "Insufficient recorded stock",
            )
        self.assert_unchanged(before)

        with self.assertRaises(WorkflowError):
            self.action(
                "return_to_on_order",
                request_id,
                "No outstanding order exists",
            )
        self.assert_unchanged(before)

        self.action(
            "escalate_shortage",
            request_id,
            "Completed order did not cover the full request",
        )

        request = self.state.requests[request_id]
        self.assertEqual(request.status, RequestStatus.ESCALATED)
        self.assertFalse(request.after_receipt)
        self.assertEqual(request.shortfall, 2)

        before = deepcopy(self.state)

        with self.assertRaises(WorkflowError):
            self.action(
                "confirm_order",
                request_id,
                CreateOrderInput(2, "tablet"),
                "too-early-order",
                role=Role.PROCUREMENT,
                module=orders,
            )
        self.assert_unchanged(before)

        self.action(
            "update_supply_feedback",
            request_id,
            SupplyFeedbackInput(
                "Additional synthetic supply review for remaining two"
            ),
            role=Role.PROCUREMENT,
        )

        second_order = self.action(
            "confirm_order",
            request_id,
            CreateOrderInput(2, "tablet"),
            "second-order",
            role=Role.PROCUREMENT,
            module=orders,
        ).order_id

        self.assertEqual(
            self.state.requests[request_id].order_ids,
            (first_order, second_order),
        )

        self.post(second_order, 2)
        self.action("start_review", request_id)
        self.action(
            "authorize_release",
            request_id,
            "Latest stock now covers the full request",
        )
        self.action(
            "fulfill_request",
            request_id,
            role=Role.WAREHOUSE,
        )

        self.assertEqual(self.stock(), 0)
        self.assertEqual(
            self.state.requests[request_id].outcome,
            RequestOutcome.FULFILLED,
        )

    def test_open_order_blocks_escalation_and_allows_return_to_on_order(self):
        request_id, order_id = self.make_order()
        self.post(order_id, 200)
        self.action("start_review", request_id)

        self.consume_available_stock(200)
        self.assertEqual(self.stock(), 0)

        before = deepcopy(self.state)

        with self.assertRaises(WorkflowError) as caught:
            self.action(
                "escalate_shortage",
                request_id,
                "Attempt escalation while supply remains outstanding",
            )

        self.assertEqual(caught.exception.code, "open_order_exists")
        self.assert_unchanged(before)

        self.action(
            "return_to_on_order",
            request_id,
            "Await the remaining quantity on the linked order",
        )

        request = self.state.requests[request_id]
        self.assertEqual(request.status, RequestStatus.ON_ORDER)
        self.assertFalse(request.after_receipt)
        self.assertEqual(request.shortfall, 5)
        self.assertEqual(len(self.state.orders), 1)

        self.post(order_id, 100)

        self.assertEqual(
            self.state.requests[request_id].status,
            RequestStatus.SUPPLY_RECEIVED,
        )

        self.action("start_review", request_id)
        self.action(
            "authorize_release",
            request_id,
            "New receipt permits explicit release",
        )
        self.action(
            "fulfill_request",
            request_id,
            role=Role.WAREHOUSE,
        )

        self.assertEqual(self.stock(), 95)
        self.assertFalse(
            self.state.requests[request_id].after_receipt
        )

    def test_failed_fulfillment_retains_flag_and_allows_recall_routing(self):
        request_id, order_id = self.make_order()
        self.post(order_id, 200)
        self.action("start_review", request_id)
        self.action(
            "authorize_release",
            request_id,
            "Stock covers the request at release time",
        )

        self.consume_available_stock(200)
        before = deepcopy(self.state)

        with self.assertRaises(WorkflowError) as caught:
            self.action(
                "fulfill_request",
                request_id,
                role=Role.WAREHOUSE,
            )

        self.assertEqual(caught.exception.code, "insufficient_stock")
        self.assert_unchanged(before)
        self.assertTrue(
            self.state.requests[request_id].after_receipt
        )

        self.action(
            "recall_release",
            request_id,
            "Latest stock no longer covers the request",
        )
        self.assertTrue(
            self.state.requests[request_id].after_receipt
        )

        self.action(
            "return_to_on_order",
            request_id,
            "Outstanding supply remains on the existing order",
        )

        self.assertEqual(
            self.state.requests[request_id].status,
            RequestStatus.ON_ORDER,
        )
        self.assertFalse(
            self.state.requests[request_id].after_receipt
        )

    def test_return_to_on_order_requires_shortage_and_post_receipt_review(self):
        request_id = self.submit()
        self.action("start_review", request_id)
        before = deepcopy(self.state)

        with self.assertRaises(WorkflowError):
            self.action(
                "return_to_on_order",
                request_id,
                "Not a post-receipt review",
            )
        self.assert_unchanged(before)

        self.make_state()
        request_id, order_id = self.make_order()
        self.post(order_id, 100)
        self.action("start_review", request_id)
        before = deepcopy(self.state)

        with self.assertRaises(WorkflowError):
            self.action(
                "return_to_on_order",
                request_id,
                "Current stock already covers the request",
            )
        self.assert_unchanged(before)

    def test_return_to_on_order_context_and_reason_guards(self):
        request_id, order_id = self.make_order()
        self.post(order_id, 100)
        self.action("start_review", request_id)
        self.consume_available_stock(100)

        before = deepcopy(self.state)
        good = self.context()

        invalid_contexts = (
            replace(good, acting_role=Role.WAREHOUSE),
            replace(good, expected_run_id="old-run"),
            replace(
                good,
                expected_revision=good.expected_revision - 1,
            ),
            replace(
                good,
                now=datetime(2020, 1, 1, tzinfo=timezone.utc),
            ),
        )

        for context in invalid_contexts:
            with self.subTest(context=context):
                with self.assertRaises(WorkflowError):
                    wf.return_to_on_order(
                        self.state,
                        request_id,
                        "Wait for outstanding supply",
                        context,
                    )
                self.assert_unchanged(before)

        with self.assertRaises(WorkflowError):
            self.action("return_to_on_order", request_id, " ")

        self.assert_unchanged(before)

    def test_later_receipts_preserve_existing_review_and_closed_statuses(self):
        for stage in (
            "supply_received",
            "under_review",
            "approved",
            "fulfilled",
            "closed_without_fulfillment",
        ):
            with self.subTest(stage=stage):
                self.make_state()
                request_id, order_id = self.make_order()
                self.post(order_id, 100)

                if stage in {
                    "under_review",
                    "approved",
                    "fulfilled",
                }:
                    self.action("start_review", request_id)

                if stage in {"approved", "fulfilled"}:
                    self.action(
                        "authorize_release",
                        request_id,
                        "Explicit release after partial receipt",
                    )

                if stage == "fulfilled":
                    self.action(
                        "fulfill_request",
                        request_id,
                        role=Role.WAREHOUSE,
                    )

                if stage == "closed_without_fulfillment":
                    self.action(
                        "close_without_supply",
                        request_id,
                        "Synthetic request is no longer needed",
                    )

                before = self.state.requests[request_id]
                previous_stock = self.stock()

                self.post(order_id, 200)

                after = self.state.requests[request_id]
                self.assertEqual(after.status, before.status)
                self.assertEqual(after.outcome, before.outcome)
                self.assertEqual(
                    after.after_receipt,
                    before.after_receipt,
                )
                self.assertEqual(
                    after.fulfillment,
                    before.fulfillment,
                )
                self.assertEqual(self.stock(), previous_stock + 200)
                self.assertEqual(
                    self.state.orders[order_id].status,
                    OrderStatus.RECEIVED,
                )

    def test_post_receipt_closure_preserves_stock_and_open_order(self):
        for stage in ("supply_received", "under_review"):
            with self.subTest(stage=stage):
                self.make_state()
                request_id, order_id = self.make_order()
                self.post(order_id, 100)

                if stage == "under_review":
                    self.action("start_review", request_id)

                before_inventory = self.state.inventory.copy(deep=True)
                before_order = deepcopy(self.state.orders[order_id])

                self.action(
                    "close_without_supply",
                    request_id,
                    "Synthetic request no longer requires fulfillment",
                )

                request = self.state.requests[request_id]
                self.assertEqual(request.status, RequestStatus.CLOSED)
                self.assertEqual(
                    request.outcome,
                    RequestOutcome.CLOSED_WITHOUT_SUPPLY,
                )
                self.assertFalse(request.after_receipt)
                self.assertIsNone(request.fulfillment)
                assert_frame_equal(
                    self.state.inventory,
                    before_inventory,
                )
                self.assertEqual(
                    self.state.orders[order_id],
                    before_order,
                )

    def test_initial_under_review_cannot_use_post_receipt_closure(self):
        request_id = self.submit()
        self.action("start_review", request_id)
        before = deepcopy(self.state)

        with self.assertRaises(WorkflowError):
            self.action(
                "close_without_supply",
                request_id,
                "Initial review is not post-receipt review",
            )

        self.assert_unchanged(before)

    def test_return_to_on_order_publication_failure_is_atomic(self):
        request_id, order_id = self.make_order()
        self.post(order_id, 100)
        self.action("start_review", request_id)
        self.consume_available_stock(100)
        before = deepcopy(self.state)

        with patch(
            "src.services.workflow._publish",
            side_effect=RuntimeError("Injected publication failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.action(
                    "return_to_on_order",
                    request_id,
                    "Wait for the remaining linked supply",
                )

        self.assert_unchanged(before)


if __name__ == "__main__":
    unittest.main()