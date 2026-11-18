"""Receipt readers, role boundaries and session publication checks."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pandas.testing import assert_frame_equal

from src.config import PROJECT_ROOT
from src.services.workflow_models import (
    CreateOrderInput,
    ReceiptInput,
    RequestStatus,
    Role,
    SupplyFeedbackInput,
    SubmitRequestInput,
    WorkflowError,
)
from src.ui import session
from src.ui.workflow_actions import pharmacist_action_callback


def nested_keys(value):
    """Collect keys recursively to check nested role projections."""
    keys = set()

    if isinstance(value, dict):
        keys.update(value)
        for child in value.values():
            keys.update(nested_keys(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            keys.update(nested_keys(child))

    return keys


class ReceiptQueriesSessionTests(unittest.TestCase):
    def setUp(self):
        self.clock = datetime(
            2026, 11, 18, 13, 0, tzinfo=timezone.utc
        )
        self.path = (
            PROJECT_ROOT
            / "data"
            / "sample_medications_extended.csv"
        )
        self.start_session(self.path)

    def tick(self):
        self.clock += timedelta(seconds=1)
        return self.clock

    def start_session(self, path):
        self.path = Path(path)
        self.store = {}

        session.ensure_demo_session(
            self.path,
            state_store=self.store,
            now=self.tick(),
        )

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

    def submit(self, quantity=5):
        number = self.info().request_count + 1

        return self.action(
            "submit_request",
            SubmitRequestInput(
                medication_id="MED003",
                quantity=quantity,
                unit="tablet",
                requesting_location="Demo Ward",
                reason="Receipt reader/session test",
            ),
            f"request-{number}",
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
            "Recorded stock cannot cover the request",
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
            f"order-{request_id}",
            role=Role.PROCUREMENT,
        ).order_id

        return request_id, order_id

    def post(self, order_id, quantity=100, key="receipt-one"):
        return self.action(
            "confirm_receipt",
            order_id,
            ReceiptInput(quantity, "tablet"),
            key,
            role=Role.WAREHOUSE,
        )

    def stock(self):
        inventory = session.read_inventory(
            Role.WAREHOUSE,
            state_store=self.store,
        )
        return inventory.loc[
            inventory["medication_id"].eq("MED003"),
            "current_stock",
        ].iloc[0]

    def assert_state_unchanged(self, before):
        current = self.store[session.STATE_KEY]

        assert_frame_equal(current.inventory, before.inventory)
        assert_frame_equal(
            current.initial_inventory,
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
                getattr(current, field),
                getattr(before, field),
                field,
            )

    def test_receipt_preview_is_detached_and_does_not_publish(self):
        _, order_id = self.make_order()
        before = deepcopy(self.store[session.STATE_KEY])
        info = self.info()

        preview = session.preview_simulated_receipt(
            order_id,
            ReceiptInput(100, "tablet"),
            expected_run_id=info.run_id,
            expected_revision=info.revision,
            source_path=self.path,
            state_store=self.store,
            now=self.tick(),
        )

        self.assertEqual(preview["run_id"], info.run_id)
        self.assertEqual(preview["revision"], info.revision)

        preview["revision"] = -1
        preview["extra"] = "Caller-owned display data"

        self.assert_state_unchanged(before)
        self.assertFalse(
            session.read_receipts(
                Role.WAREHOUSE,
                state_store=self.store,
            )
        )

    def test_receipt_publication_updates_all_shared_inventory_readers(self):
        request_id, order_id = self.make_order()
        before_revision = self.info().revision

        result = self.post(order_id, 300)

        self.assertEqual(result.receipt_id, "RCV-0001")
        self.assertEqual(
            self.info().revision,
            before_revision + 1,
        )

        for role in (
            Role.CLINICAL,
            Role.PHARMACIST,
            Role.PROCUREMENT,
            Role.WAREHOUSE,
            Role.REPORTING,
        ):
            with self.subTest(role=role):
                inventory = session.read_inventory(
                    role,
                    state_store=self.store,
                )
                stock = inventory.loc[
                    inventory["medication_id"].eq("MED003"),
                    "current_stock",
                ].iloc[0]
                self.assertEqual(stock, 300)

        summary = session.read_inventory_summary(
            state_store=self.store
        )
        self.assertEqual(summary["zero_stock_count"], 0)
        self.assertAlmostEqual(
            summary["inventory_value_cad"],
            837.00,
            places=2,
        )

        request = session.read_request_details(
            request_id,
            Role.CLINICAL,
            state_store=self.store,
        )
        self.assertEqual(request["status"], "supply_received")

    def test_receipt_projections_preserve_role_information_boundaries(self):
        request_id, order_id = self.make_order()
        receipt_id = self.post(order_id).receipt_id

        clinical = session.read_request_details(
            request_id,
            Role.CLINICAL,
            state_store=self.store,
        )
        clinical_keys = nested_keys(clinical)

        self.assertEqual(clinical["quantity"], 5)
        self.assertNotIn("ordered_quantity", clinical_keys)
        self.assertNotIn("quantity_received", clinical_keys)
        self.assertNotIn("quantity_outstanding", clinical_keys)
        self.assertNotIn("received_quantity", clinical_keys)
        self.assertNotIn("stock_before", clinical_keys)
        self.assertNotIn("stock_after", clinical_keys)
        self.assertNotIn("supplier", clinical_keys)
        self.assertNotIn("unit_cost", clinical_keys)
        self.assertNotIn("order_value_cad", clinical_keys)

        self.assertEqual(
            clinical["orders"][0]["receipt_ids"],
            [receipt_id],
        )
        self.assertEqual(
            clinical["orders"][0]["receipts"][0]["receipt_id"],
            receipt_id,
        )

        pharmacist = session.read_request_details(
            request_id,
            Role.PHARMACIST,
            state_store=self.store,
        )
        pharmacist_keys = nested_keys(pharmacist)

        self.assertEqual(
            pharmacist["orders"][0]["receipts"][0][
                "received_quantity"
            ],
            100,
        )
        self.assertNotIn("unit_cost", pharmacist_keys)
        self.assertNotIn("order_value_cad", pharmacist_keys)
        self.assertNotIn("order_value_note", pharmacist_keys)

        warehouse = session.read_order_details(
            order_id,
            Role.WAREHOUSE,
            state_store=self.store,
        )
        warehouse_keys = nested_keys(warehouse)

        self.assertNotIn("supplier", warehouse_keys)
        self.assertNotIn("lead_time_days", warehouse_keys)
        self.assertNotIn("unit_cost", warehouse_keys)
        self.assertNotIn("order_value_cad", warehouse_keys)

        for role in (
            Role.CLINICAL,
            Role.PHARMACIST,
            Role.PROCUREMENT,
            Role.WAREHOUSE,
        ):
            projection = session.read_receipt_details(
                receipt_id,
                role,
                state_store=self.store,
            )
            self.assertNotIn("receipt_key", nested_keys(projection))

    def test_pharmacist_review_flags_reflect_receipt_and_order_state(self):
        request_id, order_id = self.make_order()
        self.post(order_id, 100)

        request = session.read_request_details(
            request_id,
            Role.PHARMACIST,
            state_store=self.store,
        )
        self.assertFalse(request["after_receipt"])
        self.assertTrue(request["has_open_order"])

        self.action(
            "start_review",
            request_id,
            role=Role.PHARMACIST,
        )

        request = session.read_request_details(
            request_id,
            Role.PHARMACIST,
            state_store=self.store,
        )
        self.assertTrue(request["after_receipt"])
        self.assertTrue(request["has_open_order"])

        self.post(order_id, 200, key="receipt-two")

        request = session.read_request_details(
            request_id,
            Role.PHARMACIST,
            state_store=self.store,
        )
        self.assertEqual(request["status"], "under_review")
        self.assertTrue(request["after_receipt"])
        self.assertFalse(request["has_open_order"])

    def test_receipt_readers_are_deeply_detached(self):
        request_id, order_id = self.make_order()
        receipt_id = self.post(order_id).receipt_id
        before = deepcopy(self.store[session.STATE_KEY])

        receipt = session.read_receipt_details(
            receipt_id,
            Role.WAREHOUSE,
            state_store=self.store,
        )
        receipt["received_quantity"] = -999

        order = session.read_order_details(
            order_id,
            Role.PHARMACIST,
            state_store=self.store,
        )
        order["receipts"][0]["stock_after"] = -999
        order["receipt_ids"].clear()

        request = session.read_request_details(
            request_id,
            Role.PHARMACIST,
            state_store=self.store,
        )
        request["orders"][0]["receipts"].clear()

        self.assert_state_unchanged(before)

    def test_unavailable_receipt_readers_and_unknown_ids_are_rejected(self):
        _, order_id = self.make_order()
        receipt_id = self.post(order_id).receipt_id
        before = deepcopy(self.store[session.STATE_KEY])

        for role in (
            Role.EXECUTIVE,
            Role.REPORTING,
            Role.SYSTEM,
            "unknown-role",
        ):
            with self.subTest(role=role):
                with self.assertRaises(WorkflowError):
                    session.read_receipts(
                        role,
                        state_store=self.store,
                    )

        with self.assertRaises(WorkflowError):
            session.read_receipt_details(
                "RCV-9999",
                Role.WAREHOUSE,
                state_store=self.store,
            )

        with self.assertRaises(WorkflowError):
            session.read_receipts(
                Role.WAREHOUSE,
                order_id="PO-9999",
                state_store=self.store,
            )

        self.assert_state_unchanged(before)
        self.assertEqual(receipt_id, "RCV-0001")

    def test_public_result_copy_failure_does_not_publish_receipt(self):
        _, order_id = self.make_order()
        before = deepcopy(self.store[session.STATE_KEY])

        with patch(
            "src.ui.session.deepcopy",
            side_effect=RuntimeError("Injected public-copy failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.post(order_id)

        self.assert_state_unchanged(before)

    def test_duplicate_receipt_is_rejected_through_session_adapter(self):
        _, order_id = self.make_order()
        self.post(order_id)
        before = deepcopy(self.store[session.STATE_KEY])

        with self.assertRaises(WorkflowError):
            self.post(order_id, key="receipt-one")

        self.assert_state_unchanged(before)

    def test_changed_source_blocks_receipt_preview_and_confirmation(self):
        original = self.path.read_bytes()

        with TemporaryDirectory() as directory:
            path = Path(directory) / "medications.csv"
            path.write_bytes(original)
            self.start_session(path)

            _, order_id = self.make_order()
            before = deepcopy(self.store[session.STATE_KEY])
            info = self.info()

            path.write_bytes(original + b"\n")

            with self.assertRaises(WorkflowError) as caught:
                session.preview_simulated_receipt(
                    order_id,
                    ReceiptInput(100, "tablet"),
                    expected_run_id=info.run_id,
                    expected_revision=info.revision,
                    source_path=self.path,
                    state_store=self.store,
                    now=self.tick(),
                )

            self.assertEqual(
                caught.exception.code,
                "dataset_mismatch",
            )

            with self.assertRaises(WorkflowError):
                self.post(order_id)

            self.assert_state_unchanged(before)

    def test_return_to_on_order_callback_uses_registered_shared_action(self):
        request_id, order_id = self.make_order()
        self.post(order_id, 100)
        self.action(
            "start_review",
            request_id,
            role=Role.PHARMACIST,
        )

        # A separate valid request consumes the stock.
        other_request = self.submit(quantity=100)
        self.action(
            "start_review",
            other_request,
            role=Role.PHARMACIST,
        )
        self.action(
            "authorize_release",
            other_request,
            "Separate request uses available recorded stock",
            role=Role.PHARMACIST,
        )
        self.action(
            "fulfill_request",
            other_request,
            role=Role.WAREHOUSE,
        )

        self.assertEqual(self.stock(), 0)

        reason_key = "workflow_ui_test_post_receipt_reason"
        self.store[reason_key] = (
            "Wait for outstanding supply on the existing order"
        )
        info = self.info()

        pharmacist_action_callback(
            action_name="return_to_on_order",
            request_id=request_id,
            reason_key=reason_key,
            expected_run_id=info.run_id,
            expected_revision=info.revision,
            source_path=self.path,
            state_store=self.store,
            now=self.tick(),
        )

        request = session.read_request_details(
            request_id,
            Role.PHARMACIST,
            state_store=self.store,
        )

        self.assertEqual(
            request["status"],
            str(RequestStatus.ON_ORDER),
        )
        self.assertFalse(request["after_receipt"])
        self.assertTrue(request["has_open_order"])
        self.assertEqual(self.store[reason_key], "")
        self.assertEqual(
            self.store[session.NOTICE_KEY]["kind"],
            "success",
        )
        self.assertEqual(self.stock(), 0)

    def test_reset_clears_receipts_and_receipt_ui_state(self):
        _, order_id = self.make_order()
        receipt_id = self.post(order_id).receipt_id

        self.store["workflow_ui_receipt_test_draft"] = {
            "receipt_id": receipt_id,
        }
        old_run_id = self.info().run_id

        session.reset_demo_session(
            clinical_tab_label="Clinical",
            state_store=self.store,
            now=self.tick(),
        )

        self.assertNotEqual(self.info().run_id, old_run_id)
        self.assertEqual(self.stock(), 0)
        self.assertNotIn(
            "workflow_ui_receipt_test_draft",
            self.store,
        )
        self.assertEqual(
            session.read_receipts(
                Role.WAREHOUSE,
                state_store=self.store,
            ),
            [],
        )
        self.assertEqual(
            session.read_orders(
                Role.WAREHOUSE,
                state_store=self.store,
            ),
            [],
        )

        with self.assertRaises(WorkflowError):
            session.read_receipt_details(
                receipt_id,
                Role.WAREHOUSE,
                state_store=self.store,
            )


if __name__ == "__main__":
    unittest.main()