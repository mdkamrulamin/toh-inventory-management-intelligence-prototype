"""Integration checks for Procurement order callbacks."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import unittest

from pandas.testing import assert_frame_equal

from src.config import PROJECT_ROOT
from src.services.workflow_models import (
    Role,
    SubmitRequestInput,
    SupplyFeedbackInput,
)
from src.ui import session
from src.ui.order_actions import (
    new_order_draft_callback,
    order_creation_callback,
    order_input_keys,
    order_management_callback,
    prepare_order_draft,
)


class OrderActionTests(unittest.TestCase):
    def setUp(self):
        self.clock = datetime(
            2026, 11, 17, 12, 0,
            tzinfo=timezone.utc,
        )
        self.make_session()

    def tick(self):
        self.clock += timedelta(seconds=1)
        return self.clock

    def info(self):
        return session.get_session_info(state_store=self.store)

    def root(self):
        return self.store[session.STATE_KEY]

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

    def make_session(self, filename="sample_medications_extended.csv"):
        self.path = PROJECT_ROOT / "data" / filename
        self.original_bytes = self.path.read_bytes()
        self.store = {}

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
                reason="Synthetic callback check",
            ),
            "order-ui-request",
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
            "Recorded stock is insufficient",
            role=Role.PHARMACIST,
        )
        self.action(
            "update_supply_feedback",
            self.request_id,
            SupplyFeedbackInput("Synthetic supply review"),
            role=Role.PROCUREMENT,
        )
        self.prepare_inputs()

    def prepare_inputs(self):
        self.draft = prepare_order_draft(
            self.request_id,
            state_store=self.store,
        )
        self.keys = order_input_keys(self.request_id, self.draft)
        self.store[self.keys["quantity"]] = "300"
        self.store[self.keys["date"]] = None
        self.store[self.keys["reason"]] = ""

    def creation(self, action_name, info=None):
        info = self.info() if info is None else info

        order_creation_callback(
            action_name=action_name,
            request_id=self.request_id,
            unit="tablet",
            order_key=self.draft["order_key"],
            expected_run_id=info.run_id,
            expected_revision=info.revision,
            source_path=self.path,
            state_store=self.store,
            now=self.tick(),
        )

    def confirm(self):
        self.store[self.keys["confirmation"]] = True
        self.creation("confirm_order")

    def recorded_order(self):
        return next(iter(self.root().orders.values()))

    def manage(self, action_name, *, confirmed=True):
        info = self.info()
        self.store["workflow_ui_test_cancel_confirmation"] = confirmed

        order_management_callback(
            action_name=action_name,
            order_id=self.recorded_order().order_id,
            reason_key="workflow_ui_test_order_reason",
            expected_date_key="workflow_ui_test_order_date",
            confirmation_key=(
                "workflow_ui_test_cancel_confirmation"
                if action_name == "cancel_order"
                else None
            ),
            expected_run_id=info.run_id,
            expected_revision=info.revision,
            source_path=self.path,
            state_store=self.store,
            now=self.tick(),
        )

    def test_invalid_ui_quantities_never_become_one_or_create_orders(self):
        root = self.root()

        for text in ("", " ", "0", "-1", "1.5", "3.0", "abc", "inf"):
            with self.subTest(quantity=text):
                self.store[self.keys["quantity"]] = text
                self.creation("preview_order")

                self.assertEqual(
                    self.store[session.NOTICE_KEY]["kind"],
                    "error",
                )
                self.assertIs(self.root(), root)
                self.assertFalse(self.root().orders)
                self.assertEqual(self.root().next_order_number, 1)

    def test_confirmation_requires_preview_and_checked_confirmation(self):
        root = self.root()
        self.confirm()

        self.assertIs(self.root(), root)
        self.assertFalse(self.root().orders)

        self.creation("preview_order")
        self.creation("confirm_order")

        self.assertIs(self.root(), root)
        self.assertFalse(self.root().orders)
        self.assertIn(
            "Tick",
            self.store[session.NOTICE_KEY]["message"],
        )

        self.confirm()
        self.assertEqual(len(self.root().orders), 1)

    def test_valid_confirmation_creates_one_order_without_stock_change(self):
        before = self.root().inventory.copy(deep=True)
        revision = self.info().revision

        self.creation("preview_order")
        self.confirm()

        order = self.recorded_order()
        self.assertEqual(order.order_id, "PO-0001")
        self.assertEqual(order.ordered_quantity, 300)
        self.assertEqual(order.order_value_cad, Decimal("36.00"))
        self.assertEqual(self.info().revision, revision + 1)
        assert_frame_equal(self.root().inventory, before)

        root = self.root()
        self.confirm()

        self.assertIs(self.root(), root)
        self.assertEqual(len(self.root().orders), 1)
        self.assertEqual(self.path.read_bytes(), self.original_bytes)

    def test_changed_quantity_requires_a_new_preview(self):
        self.creation("preview_order")
        root = self.root()

        self.store[self.keys["quantity"]] = "301"
        self.confirm()

        self.assertIs(self.root(), root)
        self.assertFalse(self.root().orders)
        self.assertEqual(
            self.store[session.NOTICE_KEY]["kind"],
            "error",
        )

        self.creation("preview_order")
        self.confirm()

        self.assertEqual(
            self.recorded_order().ordered_quantity,
            301,
        )

    def test_changed_revision_rejects_old_confirmation(self):
        self.creation("preview_order")
        old_info = self.info()

        self.action(
            "update_supply_feedback",
            self.request_id,
            SupplyFeedbackInput("Revised synthetic supply review"),
            role=Role.PROCUREMENT,
        )
        root = self.root()

        self.store[self.keys["confirmation"]] = True
        self.creation("confirm_order", info=old_info)

        self.assertIs(self.root(), root)
        self.assertFalse(self.root().orders)
        self.assertIn(
            "changed",
            self.store[session.NOTICE_KEY]["message"],
        )

    def test_changed_calendar_date_requires_a_fresh_preview(self):
        self.creation("preview_order")
        root = self.root()

        self.clock += timedelta(days=1)
        self.confirm()

        self.assertIs(self.root(), root)
        self.assertFalse(self.root().orders)
        self.assertEqual(
            self.store[session.NOTICE_KEY]["kind"],
            "error",
        )

    def test_management_reads_submitted_values_and_preserves_inventory(self):
        self.creation("preview_order")
        self.confirm()
        before = self.root().inventory.copy(deep=True)

        self.store["workflow_ui_test_order_reason"] = (
            "PRIVATE_COMMERCIAL_NOTE_36_CAD"
        )
        self.store["workflow_ui_test_order_date"] = date(2026, 11, 25)
        self.manage("update_order_delivery")

        self.assertEqual(
            self.recorded_order().expected_delivery,
            "2026-11-25",
        )
        self.assertNotIn(
            "PRIVATE_COMMERCIAL_NOTE",
            self.store[session.NOTICE_KEY]["message"],
        )

        root = self.root()
        self.store["workflow_ui_test_order_reason"] = " "
        self.manage("cancel_order")
        self.assertIs(self.root(), root)

        self.store["workflow_ui_test_order_reason"] = (
            "Cancel before any receipt"
        )
        self.manage("cancel_order", confirmed=False)
        self.assertIs(self.root(), root)

        self.manage("cancel_order", confirmed=True)
        self.assertEqual(
            str(self.recorded_order().status),
            "cancelled",
        )
        self.assertEqual(
            str(self.root().requests[self.request_id].status),
            "awaiting_supply",
        )
        assert_frame_equal(self.root().inventory, before)

    def test_new_draft_retains_previous_order_and_uses_new_identity(self):
        self.creation("preview_order")
        self.confirm()
        self.store["workflow_ui_test_order_reason"] = "Cancel demo order"
        self.manage("cancel_order")

        root = self.root()
        previous_key = self.draft["order_key"]

        new_order_draft_callback(
            request_id=self.request_id,
            expected_run_id=self.info().run_id,
            order_key=previous_key,
            state_store=self.store,
        )
        self.assertIs(self.root(), root)

        self.prepare_inputs()
        self.assertNotEqual(self.draft["order_key"], previous_key)

        self.creation("preview_order")
        self.confirm()

        self.assertEqual(
            self.root().requests[self.request_id].order_ids,
            ("PO-0001", "PO-0002"),
        )
        self.assertEqual(len(self.root().orders), 2)

    def test_original_schema_can_confirm_with_unavailable_expected_date(self):
        self.make_session("sample_medications.csv")
        self.creation("preview_order")
        self.confirm()

        self.assertEqual(
            self.store[session.NOTICE_KEY]["kind"],
            "success",
        )
        self.assertIsNone(self.recorded_order().expected_delivery)
        self.assertEqual(
            self.recorded_order().order_value_cad,
            Decimal("36.00"),
        )

    def test_old_run_callback_cannot_recreate_an_order_after_reset(self):
        self.creation("preview_order")
        old_info = self.info()

        session.reset_demo_session(
            clinical_tab_label="Clinical",
            state_store=self.store,
            now=self.tick(),
        )
        root = self.root()

        self.creation("confirm_order", info=old_info)

        self.assertIs(self.root(), root)
        self.assertFalse(self.root().orders)
        self.assertFalse(self.root().requests)
        self.assertEqual(self.root().next_order_number, 1)


if __name__ == "__main__":
    unittest.main()