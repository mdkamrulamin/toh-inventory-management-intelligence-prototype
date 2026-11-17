"""Checks for linked synthetic orders and mutation safeguards."""

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import unittest
from unittest.mock import patch

import pandas as pd
from pandas.testing import assert_frame_equal

from src.config import PROJECT_ROOT
from src.data.loader import load_medications
from src.services import orders
from src.services import workflow as wf
from src.services import workflow_queries as queries
from src.services.workflow_models import (
    CreateOrderInput,
    OrderStatus,
    RequestOutcome,
    RequestStatus,
    Role,
    SupplyFeedbackInput,
    SubmitRequestInput,
    WorkflowError,
)


class SyntheticOrderTests(unittest.TestCase):
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

    def context(self, role=Role.PROCUREMENT):
        return wf.make_context(self.state, role, now=self.tick())

    def action(self, name, *args, role, module=wf):
        result = getattr(module, name)(
            self.state, *args, context=self.context(role)
        )
        self.state = result.state
        return result

    def shortage(self):
        result = self.action(
            "submit_request",
            SubmitRequestInput(
                medication_id="MED003",
                quantity=5,
                unit="tablet",
                requesting_location="Demo Ward",
                reason="Synthetic order test",
            ),
            f"request-{self.state.next_request_number}",
            role=Role.CLINICAL,
        )
        request_id = result.request_id
        self.action("start_review", request_id, role=Role.PHARMACIST)
        self.action(
            "escalate_shortage",
            request_id,
            "Recorded stock cannot cover the request",
            role=Role.PHARMACIST,
        )
        self.action(
            "update_supply_feedback",
            request_id,
            SupplyFeedbackInput("Synthetic supply review"),
            role=Role.PROCUREMENT,
        )
        return request_id

    def confirm(self, request_id, quantity=300, key=None):
        return self.action(
            "confirm_order",
            request_id,
            CreateOrderInput(quantity=quantity, unit="tablet"),
            key or f"order-{self.state.next_order_number}",
            role=Role.PROCUREMENT,
            module=orders,
        ).order_id

    def assert_unchanged(self, before):
        assert_frame_equal(self.state.inventory, before.inventory)
        assert_frame_equal(
            self.state.initial_inventory, before.initial_inventory
        )
        self.assertEqual(self.state.requests, before.requests)
        self.assertEqual(self.state.orders, before.orders)
        self.assertEqual(self.state.revision, before.revision)
        self.assertEqual(
            self.state.next_order_number, before.next_order_number
        )
        self.assertEqual(
            self.state.next_request_number, before.next_request_number
        )

    def test_preview_creates_no_records_or_ids(self):
        request_id = self.shortage()
        before = deepcopy(self.state)

        preview = orders.preview_order(
            self.state,
            request_id,
            CreateOrderInput(300, "tablet"),
            self.context(),
        )

        self.assertEqual(preview["order_value_cad"], Decimal("36.00"))
        self.assertEqual(preview["current_shortfall"], 5)
        self.assertEqual(preview["reorder_gap"], Decimal(300))
        self.assertEqual(preview["expected_delivery"], "2026-11-24")
        self.assert_unchanged(before)

    def test_confirmation_links_records_without_changing_stock(self):
        request_id = self.shortage()
        before = deepcopy(self.state)
        order_id = self.confirm(request_id)
        order = self.state.orders[order_id]
        request = self.state.requests[request_id]

        self.assertEqual(order_id, "PO-0001")
        self.assertEqual(order.linked_request_id, request_id)
        self.assertEqual(order.medication_id, "MED003")
        self.assertEqual(order.status, OrderStatus.ORDERED)
        self.assertEqual(order.quantity_received, 0)
        self.assertEqual(order.quantity_outstanding, 300)
        self.assertEqual(request.status, RequestStatus.ON_ORDER)
        self.assertEqual(request.order_ids, ("PO-0001",))
        self.assertEqual(self.state.revision, before.revision + 1)
        self.assertEqual(self.state.next_order_number, 2)
        assert_frame_equal(self.state.inventory, before.inventory)
        self.assertFalse(before.orders)
        self.assertEqual(self.path.read_bytes(), self.source)

        summary = queries.get_session_request_summary(self.state)
        self.assertEqual(summary["open_requests"], 1)
        self.assertEqual(summary["by_status"]["on_order"], 1)

    def test_same_medication_other_request_warns_but_is_allowed(self):
        first_request = self.shortage()
        first_order = self.confirm(first_request)
        second_request = self.shortage()

        preview = orders.preview_order(
            self.state,
            second_request,
            CreateOrderInput(300, "tablet"),
            self.context(),
        )
        self.assertIn(first_order, " ".join(preview["warnings"]))

        second_order = self.confirm(second_request)
        self.assertEqual(second_order, "PO-0002")
        self.assertEqual(len(self.state.orders), 2)

    def test_quantity_below_shortfall_is_allowed_with_warning(self):
        request_id = self.shortage()
        preview = orders.preview_order(
            self.state,
            request_id,
            CreateOrderInput(3, "tablet"),
            self.context(),
        )
        self.assertIn("below", " ".join(preview["warnings"]))
        order_id = self.confirm(request_id, quantity=3)
        self.assertEqual(
            self.state.orders[order_id].ordered_quantity, 3
        )

    def test_duplicate_and_second_open_order_are_rejected(self):
        request_id = self.shortage()
        self.confirm(request_id, key="one-confirmation")
        before = deepcopy(self.state)

        for key in ("one-confirmation", "different-confirmation"):
            with self.subTest(key=key):
                with self.assertRaises(WorkflowError):
                    self.confirm(request_id, key=key)
                self.assert_unchanged(before)

    def test_invalid_service_quantities_and_units_do_not_mutate(self):
        request_id = self.shortage()
        before = deepcopy(self.state)

        for quantity in (
            None, 0, -1, 1.5, 3.0, True,
            "3", float("nan"), float("inf"), 10**400,
        ):
            with self.subTest(quantity=quantity):
                with self.assertRaises(WorkflowError):
                    orders.confirm_order(
                        self.state,
                        request_id,
                        CreateOrderInput(quantity, "tablet"),
                        "invalid-attempt",
                        self.context(),
                    )
                self.assert_unchanged(before)

        with self.assertRaises(WorkflowError):
            orders.confirm_order(
                self.state,
                request_id,
                CreateOrderInput(300, "vial"),
                "wrong-unit",
                self.context(),
            )
        self.assert_unchanged(before)

    def test_ui_quantity_parser_does_not_coerce_invalid_entries(self):
        self.assertEqual(orders.parse_order_quantity(" 300 "), 300)

        for text in (
            None, "", " ", "0", "-1", "1.5", "3.0",
            "nan", "inf", "abc",
        ):
            with self.subTest(text=text):
                with self.assertRaises(WorkflowError):
                    orders.parse_order_quantity(text)

    def test_wrong_role_stale_run_and_revision_are_rejected(self):
        request_id = self.shortage()
        before = deepcopy(self.state)
        good = self.context()

        contexts = (
            replace(good, acting_role=Role.WAREHOUSE),
            replace(good, expected_run_id="another-run"),
            replace(good, expected_revision=good.expected_revision - 1),
            replace(
                good,
                now=datetime(2020, 1, 1, tzinfo=timezone.utc),
            ),
        )

        for context in contexts:
            with self.subTest(context=context):
                with self.assertRaises(WorkflowError):
                    orders.confirm_order(
                        self.state,
                        request_id,
                        CreateOrderInput(300, "tablet"),
                        "guarded-confirmation",
                        context,
                    )
                self.assert_unchanged(before)

    def test_order_date_defaults_do_not_rewrite_old_supply_feedback(self):
        request_id = self.shortage()
        feedback = deepcopy(
            self.state.requests[request_id].supply_feedback
        )
        self.clock += timedelta(days=3)
        order_id = self.confirm(request_id)

        self.assertEqual(
            self.state.orders[order_id].order_date, "2026-11-20"
        )
        self.assertEqual(
            self.state.orders[order_id].expected_delivery,
            "2026-11-27",
        )
        self.assertEqual(
            self.state.requests[request_id].supply_feedback,
            feedback,
        )

    def test_date_update_requires_reason_and_preserves_history(self):
        request_id = self.shortage()
        order_id = self.confirm(request_id)
        before = deepcopy(self.state)

        with self.assertRaises(WorkflowError):
            self.action(
                "update_order_delivery",
                order_id,
                date(2026, 11, 25),
                " ",
                role=Role.PROCUREMENT,
                module=orders,
            )
        self.assert_unchanged(before)

        self.action(
            "update_order_delivery",
            order_id,
            date(2026, 11, 25),
            "Illustrative delivery date revised",
            role=Role.PROCUREMENT,
            module=orders,
        )
        order = self.state.orders[order_id]

        self.assertEqual(order.expected_delivery, "2026-11-25")
        self.assertEqual(len(order.order_history), 2)
        self.assertEqual(
            order.order_history[0].expected_delivery_after,
            "2026-11-24",
        )
        self.assertEqual(
            order.order_history[1].expected_delivery_before,
            "2026-11-24",
        )
        self.assertEqual(
            self.state.requests[request_id].status,
            RequestStatus.ON_ORDER,
        )

    def test_cancel_allows_another_order_and_retains_previous_id(self):
        request_id = self.shortage()
        first = self.confirm(request_id)

        self.action(
            "cancel_order",
            first,
            "Synthetic order no longer needed",
            role=Role.PROCUREMENT,
            module=orders,
        )
        self.assertEqual(
            self.state.requests[request_id].status,
            RequestStatus.AWAITING_SUPPLY,
        )
        self.assertEqual(
            self.state.orders[first].status,
            OrderStatus.CANCELLED,
        )

        second = self.confirm(request_id)
        self.assertEqual(second, "PO-0002")
        self.assertEqual(
            self.state.requests[request_id].order_ids,
            ("PO-0001", "PO-0002"),
        )

    def test_closed_request_stays_closed_when_order_is_updated_or_cancelled(self):
        request_id = self.shortage()
        order_id = self.confirm(request_id)

        self.action(
            "close_without_supply",
            request_id,
            "Synthetic request no longer required",
            role=Role.PHARMACIST,
        )
        self.action(
            "update_order_delivery",
            order_id,
            date(2026, 11, 25),
            "Order continues as illustrative replenishment",
            role=Role.PROCUREMENT,
            module=orders,
        )
        self.action(
            "cancel_order",
            order_id,
            "Cancel before any receipt",
            role=Role.PROCUREMENT,
            module=orders,
        )

        request = self.state.requests[request_id]
        self.assertEqual(request.status, RequestStatus.CLOSED)
        self.assertEqual(
            request.outcome, RequestOutcome.CLOSED_WITHOUT_SUPPLY
        )

    def test_both_schemas_and_missing_commercial_context_are_supported(self):
        for filename in (
            "sample_medications.csv",
            "sample_medications_extended.csv",
        ):
            with self.subTest(dataset=filename):
                self.make_state(filename)
                request_id = self.shortage()
                order_id = self.confirm(request_id)
                order = self.state.orders[order_id]
                self.assertEqual(order.order_value_cad, Decimal("36.00"))

                if filename == "sample_medications.csv":
                    self.assertIsNone(order.expected_delivery)
                    self.assertIsNone(order.lead_time_days)

        self.make_state()
        request_id = self.shortage()
        inventory = self.state.inventory.copy(deep=True)
        mask = inventory["medication_id"].eq("MED003")
        for column in ("unit_cost", "supplier", "lead_time_days"):
            inventory.loc[mask, column] = pd.NA
        self.state = replace(self.state, inventory=inventory)

        order_id = self.confirm(request_id)
        order = self.state.orders[order_id]
        self.assertIsNone(order.supplier)
        self.assertIsNone(order.unit_cost)
        self.assertIsNone(order.order_value_cad)
        self.assertIsNone(order.expected_delivery)

    def test_reset_clears_orders_and_rejects_old_run_actions(self):
        request_id = self.shortage()
        order_id = self.confirm(request_id)
        old_context = self.context()

        self.state = wf.reset_demo(self.state, now=self.tick())

        self.assertFalse(self.state.requests)
        self.assertFalse(self.state.orders)
        self.assertEqual(self.state.next_order_number, 1)
        assert_frame_equal(
            self.state.inventory, self.state.initial_inventory
        )

        with self.assertRaises(WorkflowError) as caught:
            orders.cancel_order(
                self.state, order_id, "Old action", old_context
            )
        self.assertEqual(caught.exception.code, "wrong_run")

    def test_failure_before_publication_leaves_no_partial_order(self):
        request_id = self.shortage()
        before = deepcopy(self.state)

        with patch(
            "src.services.orders._publish_order",
            side_effect=RuntimeError("Injected publication failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.confirm(request_id)

        self.assert_unchanged(before)


if __name__ == "__main__":
    unittest.main()