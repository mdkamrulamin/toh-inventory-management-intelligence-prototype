"""Checks for receipt form drafts, previews and confirmation callbacks."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from pandas.testing import assert_frame_equal

from src.config import PROJECT_ROOT
from src.services.workflow_models import (
    CreateOrderInput,
    Role,
    SupplyFeedbackInput,
    SubmitRequestInput,
)
from src.ui import session
from src.ui.receipt_actions import (
    new_receipt_draft_callback,
    prepare_receipt_draft,
    receipt_action_callback,
    receipt_input_keys,
)


class ReceiptActionTests(unittest.TestCase):
    def setUp(self):
        self.clock = datetime(
            2026, 11, 18, 14, 0, tzinfo=timezone.utc
        )
        self.path = (
            PROJECT_ROOT
            / "data"
            / "sample_medications_extended.csv"
        )
        self.store = {}

        session.ensure_demo_session(
            self.path,
            state_store=self.store,
            now=self.tick(),
        )

        request_id = self.action(
            "submit_request",
            SubmitRequestInput(
                medication_id="MED003",
                quantity=5,
                unit="tablet",
                requesting_location="Demo Ward",
                reason="Receipt callback test",
            ),
            "request-one",
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
            "Recorded stock cannot cover this request",
            role=Role.PHARMACIST,
        )
        self.action(
            "update_supply_feedback",
            request_id,
            SupplyFeedbackInput("Synthetic supply review"),
            role=Role.PROCUREMENT,
        )

        self.order_id = self.action(
            "confirm_order",
            request_id,
            CreateOrderInput(300, "tablet"),
            "order-one",
            role=Role.PROCUREMENT,
        ).order_id

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

    def draft(self):
        return prepare_receipt_draft(
            self.order_id,
            state_store=self.store,
        )

    def keys(self):
        return receipt_input_keys(
            self.order_id,
            self.draft(),
        )

    def callback(self, name, *, draft=None, info=None):
        draft = self.draft() if draft is None else draft
        info = self.info() if info is None else info

        receipt_action_callback(
            action_name=name,
            order_id=self.order_id,
            unit="tablet",
            receipt_key=draft["receipt_key"],
            expected_run_id=info.run_id,
            expected_revision=info.revision,
            source_path=self.path,
            state_store=self.store,
            now=self.tick(),
        )

    def preview(self, quantity="100"):
        self.store[self.keys()["quantity"]] = quantity
        self.callback("preview_receipt")

    def confirm(self):
        self.store[self.keys()["confirmation"]] = True
        self.callback("confirm_receipt")

    def stock(self):
        inventory = session.read_inventory(
            Role.WAREHOUSE,
            state_store=self.store,
        )
        return inventory.loc[
            inventory["medication_id"].eq("MED003"),
            "current_stock",
        ].iloc[0]

    def assert_unchanged(self, before):
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
            "next_receipt_number",
            "next_order_number",
            "next_request_number",
        ):
            self.assertEqual(
                getattr(current, field),
                getattr(before, field),
                field,
            )

    def test_default_quantity_is_outstanding_and_draft_is_detached(self):
        before = deepcopy(self.store[session.STATE_KEY])
        draft = self.draft()
        keys = receipt_input_keys(self.order_id, draft)

        self.assertEqual(self.store[keys["quantity"]], "300")

        original_key = draft["receipt_key"]
        draft["receipt_key"] = "caller-change"

        self.assertEqual(
            self.draft()["receipt_key"],
            original_key,
        )

        self.store[keys["quantity"]] = "123"
        self.draft()
        self.assertEqual(self.store[keys["quantity"]], "123")
        self.assert_unchanged(before)

    def test_preview_does_not_change_business_state(self):
        before = deepcopy(self.store[session.STATE_KEY])
        self.preview("100")

        self.assertIsNotNone(self.draft()["preview"])
        self.assertEqual(
            self.draft()["preview_inputs"].quantity,
            100,
        )
        self.assert_unchanged(before)

    def test_confirmation_requires_preview(self):
        self.draft()
        before = deepcopy(self.store[session.STATE_KEY])

        self.confirm()

        self.assertEqual(
            self.store[session.NOTICE_KEY]["kind"],
            "error",
        )
        self.assert_unchanged(before)

    def test_unchecked_confirmation_retains_valid_preview(self):
        self.preview()
        before = deepcopy(self.store[session.STATE_KEY])

        self.callback("confirm_receipt")

        self.assertIsNotNone(self.draft()["preview"])
        self.assert_unchanged(before)

        self.confirm()

        self.assertEqual(self.stock(), 100)
        self.assertEqual(
            self.draft()["confirmed_receipt_id"],
            "RCV-0001",
        )

    def test_changed_quantity_requires_another_preview(self):
        self.preview("100")
        before = deepcopy(self.store[session.STATE_KEY])

        keys = self.keys()
        self.store[keys["quantity"]] = "101"
        self.store[keys["confirmation"]] = True

        self.callback("confirm_receipt")

        self.assertIsNone(self.draft()["preview"])
        self.assert_unchanged(before)

    def test_invalid_ui_quantities_cannot_post_receipts(self):
        for text in (
            "",
            " ",
            "0",
            "-1",
            "1.5",
            "3.0",
            "nan",
            "inf",
            "abc",
            "301",
        ):
            with self.subTest(text=text):
                before = deepcopy(self.store[session.STATE_KEY])
                self.preview(text)

                self.assertEqual(
                    self.store[session.NOTICE_KEY]["kind"],
                    "error",
                )
                self.assertIsNone(self.draft()["preview"])
                self.assert_unchanged(before)

    def test_successful_draft_stays_locked_against_repeat_confirmation(self):
        self.preview()
        self.confirm()
        before = deepcopy(self.store[session.STATE_KEY])

        self.confirm()
        self.assert_unchanged(before)

        # Re-previewing the same completed draft cannot unlock it.
        self.callback("preview_receipt")
        self.assert_unchanged(before)
        self.assertEqual(
            self.draft()["confirmed_receipt_id"],
            "RCV-0001",
        )

    def test_another_partial_receipt_requires_explicit_new_draft(self):
        self.preview("100")
        self.confirm()

        old_draft = self.draft()
        info = self.info()
        before = deepcopy(self.store[session.STATE_KEY])

        new_receipt_draft_callback(
            self.order_id,
            info.run_id,
            old_draft["receipt_key"],
            state_store=self.store,
        )

        new_draft = self.draft()

        self.assertNotEqual(
            new_draft["receipt_key"],
            old_draft["receipt_key"],
        )
        self.assertEqual(
            self.store[self.keys()["quantity"]],
            "200",
        )
        self.assert_unchanged(before)

        self.preview("200")
        self.confirm()

        self.assertEqual(self.stock(), 300)
        self.assertEqual(
            self.draft()["confirmed_receipt_id"],
            "RCV-0002",
        )
        self.assertEqual(
            len(
                session.read_receipts(
                    Role.WAREHOUSE,
                    state_store=self.store,
                )
            ),
            2,
        )

    def test_new_draft_is_rejected_before_posting_or_after_full_receipt(self):
        draft = self.draft()
        info = self.info()
        before = deepcopy(self.store[session.STATE_KEY])

        new_receipt_draft_callback(
            self.order_id,
            info.run_id,
            draft["receipt_key"],
            state_store=self.store,
        )
        self.assert_unchanged(before)
        self.assertEqual(
            self.draft()["receipt_key"],
            draft["receipt_key"],
        )

        self.preview("300")
        self.confirm()

        draft = self.draft()
        info = self.info()
        before = deepcopy(self.store[session.STATE_KEY])

        new_receipt_draft_callback(
            self.order_id,
            info.run_id,
            draft["receipt_key"],
            state_store=self.store,
        )
        self.assert_unchanged(before)
        self.assertEqual(
            self.draft()["receipt_key"],
            draft["receipt_key"],
        )

    def test_business_change_invalidates_receipt_confirmation(self):
        self.preview()
        old_info = self.info()
        draft = self.draft()

        self.action(
            "submit_request",
            SubmitRequestInput(
                medication_id="MED001",
                quantity=1,
                unit="tablet",
                requesting_location="Another Demo Ward",
                reason="Advance shared business revision",
            ),
            "another-request",
            role=Role.CLINICAL,
        )

        self.store[self.keys()["confirmation"]] = True
        before = deepcopy(self.store[session.STATE_KEY])

        self.callback(
            "confirm_receipt",
            draft=draft,
            info=old_info,
        )

        self.assertIsNone(self.draft()["preview"])
        self.assert_unchanged(before)

    def test_old_run_callback_cannot_change_new_run(self):
        self.preview()
        old_draft = self.draft()
        old_info = self.info()

        session.reset_demo_session(
            clinical_tab_label="Clinical",
            state_store=self.store,
            now=self.tick(),
        )
        before = deepcopy(self.store[session.STATE_KEY])

        self.callback(
            "confirm_receipt",
            draft=old_draft,
            info=old_info,
        )

        self.assert_unchanged(before)
        self.assertFalse(
            session.read_receipts(
                Role.WAREHOUSE,
                state_store=self.store,
            )
        )


if __name__ == "__main__":
    unittest.main()