"""Checks for substitute callbacks and always-visible Pharmacist sections."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd
from pandas.testing import assert_frame_equal

from src.config import PROJECT_ROOT
from src.services.workflow_models import (
    Role,
    SubstituteDecision,
    SubmitRequestInput,
)
from src.ui import session
from src.ui.substitute_actions import (
    substitute_reason_key,
    substitute_review_callback,
)
from src.ui.substitute_panels import build_candidate_comparison
from src.ui.views import pharmacist


class SubstituteActionTests(unittest.TestCase):
    def setUp(self):
        self.path = (
            PROJECT_ROOT
            / "data"
            / "sample_medications_extended.csv"
        )
        self.store = {}
        self.clock = datetime(
            2026, 11, 18, 17, 0, tzinfo=timezone.utc
        )

        session.ensure_demo_session(
            self.path,
            state_store=self.store,
            now=self.tick(),
        )

    def tick(self):
        self.clock += timedelta(seconds=1)
        return self.clock

    def info(self):
        return session.get_session_info(state_store=self.store)

    def action(self, name, *args, role=Role.PHARMACIST):
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

    def submit(
        self,
        medication_id="MED003",
        quantity=5,
        preference=True,
    ):
        request_id = self.action(
            "submit_request",
            SubmitRequestInput(
                medication_id=medication_id,
                quantity=quantity,
                unit="tablet",
                requesting_location="Demo Ward",
                reason="Substitute callback test",
                substitution_allowed=preference,
            ),
            f"submission-{self.info().request_count + 1}",
            role=Role.CLINICAL,
        ).request_id

        self.action("start_review", request_id)
        return request_id

    def reason_key(self, request_id, relationship_id="SR-001"):
        return substitute_reason_key(
            self.info().run_id,
            request_id,
            relationship_id,
        )

    def callback(
        self,
        request_id,
        decision=SubstituteDecision.KEPT_FOR_CONSIDERATION,
        relationship_id="SR-001",
        info=None,
    ):
        info = self.info() if info is None else info

        substitute_review_callback(
            request_id=request_id,
            relationship_id=relationship_id,
            decision=decision,
            expected_run_id=info.run_id,
            expected_revision=info.revision,
            source_path=self.path,
            state_store=self.store,
            now=self.tick(),
        )

    def history(self):
        return session.read_substitute_reviews(
            Role.PHARMACIST,
            state_store=self.store,
        )

    def assert_no_change(self, before):
        current = self.store[session.STATE_KEY]
        assert_frame_equal(current.inventory, before.inventory)
        self.assertEqual(current.requests, before.requests)
        self.assertEqual(current.orders, before.orders)
        self.assertEqual(current.receipts, before.receipts)
        self.assertEqual(
            current.substitute_reviews,
            before.substitute_reviews,
        )
        self.assertEqual(current.revision, before.revision)
        self.assertEqual(
            current.next_substitute_review_number,
            before.next_substitute_review_number,
        )

    def test_success_records_once_and_clears_only_its_reason(self):
        request_id = self.submit()
        key = self.reason_key(request_id)
        self.store[key] = "  Needs human discussion  "
        self.store["unrelated_setting"] = "keep"
        before = deepcopy(self.store[session.STATE_KEY])

        self.callback(request_id)

        self.assertEqual(len(self.history()), 1)
        self.assertEqual(
            self.history()[0]["reason"],
            "Needs human discussion",
        )
        self.assertEqual(self.store[key], "")
        self.assertEqual(self.store["unrelated_setting"], "keep")
        self.assertEqual(
            self.store[session.NOTICE_KEY]["kind"],
            "success",
        )
        self.assertEqual(
            self.info().revision,
            before.revision + 1,
        )
        self.assertEqual(
            self.store[session.STATE_KEY].requests,
            before.requests,
        )
        assert_frame_equal(
            self.store[session.STATE_KEY].inventory,
            before.inventory,
        )

    def test_blank_reason_cannot_record(self):
        request_id = self.submit()
        key = self.reason_key(request_id)

        for reason in ("", "   "):
            with self.subTest(reason=reason):
                self.store[key] = reason
                before = deepcopy(self.store[session.STATE_KEY])

                self.callback(request_id)

                self.assert_no_change(before)
                self.assertEqual(
                    self.store[session.NOTICE_KEY]["kind"],
                    "error",
                )

    def test_unchecked_preference_cannot_record(self):
        request_id = self.submit(preference=False)
        key = self.reason_key(request_id)
        self.store[key] = "Attempt a disabled decision"
        before = deepcopy(self.store[session.STATE_KEY])

        self.callback(request_id)

        self.assert_no_change(before)
        self.assertIn(
            "did not allow consideration",
            self.store[session.NOTICE_KEY]["message"],
        )
        self.assertEqual(
            self.store[key],
            "Attempt a disabled decision",
        )

    def test_duplicate_and_stale_callbacks_do_not_append(self):
        request_id = self.submit()
        key = self.reason_key(request_id)
        self.store[key] = "Same demo note"
        old_info = self.info()

        self.callback(request_id)
        before = deepcopy(self.store[session.STATE_KEY])

        self.store[key] = "Same demo note"
        self.callback(request_id, info=old_info)
        self.assert_no_change(before)

        # Latest revision: this is a duplicate, not a stale retry.
        self.callback(request_id)
        self.assert_no_change(before)
        self.assertIn(
            "already recorded",
            self.store[session.NOTICE_KEY]["message"],
        )

    def test_handed_off_request_cannot_record_new_decision(self):
        request_id = self.submit()
        key = self.reason_key(request_id)
        self.store[key] = "Pending reason"

        self.action(
            "escalate_shortage",
            request_id,
            "Continue existing shortage workflow",
        )
        before = deepcopy(self.store[session.STATE_KEY])

        self.callback(request_id)

        self.assert_no_change(before)
        self.assertEqual(
            self.store[session.NOTICE_KEY]["kind"],
            "error",
        )

    def test_zero_candidate_keep_is_rejected_but_other_note_is_allowed(self):
        request_id = self.submit(
            medication_id="MED001",
            quantity=1500,
        )
        key = self.reason_key(request_id, "SR-002")
        self.store[key] = "Candidate has no recorded stock"
        before = deepcopy(self.store[session.STATE_KEY])

        self.callback(
            request_id,
            relationship_id="SR-002",
        )

        self.assert_no_change(before)

        self.callback(
            request_id,
            decision=SubstituteDecision.DO_NOT_PURSUE,
            relationship_id="SR-002",
        )

        self.assertEqual(len(self.history()), 1)
        self.assertEqual(
            self.history()[0]["candidate_stock_at_review"],
            0,
        )

    def test_old_run_callback_preserves_new_run_reason(self):
        request_id = self.submit()
        old_info = self.info()

        session.reset_demo_session(
            clinical_tab_label="Clinical",
            state_store=self.store,
            now=self.tick(),
        )

        new_request = self.submit()
        new_key = self.reason_key(new_request)
        self.store[new_key] = "Current run reason"
        before = deepcopy(self.store[session.STATE_KEY])

        self.callback(request_id, info=old_info)

        self.assert_no_change(before)
        self.assertEqual(
            self.store[new_key],
            "Current run reason",
        )

    def test_comparison_export_uses_explicit_cost_free_fields(self):
        request_id = self.submit()
        context = session.read_request_alternatives(
            request_id,
            Role.PHARMACIST,
            state_store=self.store,
        )
        candidate = context["candidates"][0]

        # Future extra fields must not leak into the comparison table.
        context["source"]["unit_cost"] = 987654.32
        candidate["inventory"]["unit_cost"] = 987654.32
        candidate["inventory"]["inventory_value_cad"] = 876543.21

        table = build_candidate_comparison(context, candidate)
        exported = table.to_csv(index=False)

        self.assertNotIn("987654", exported)
        self.assertNotIn("876543", exported)
        self.assertIn(
            "Unvalidated - synthetic demonstration only",
            exported,
        )
        self.assertIn(
            "Suitability, dose conversion",
            exported,
        )


class PharmacistSectionVisibilityTests(unittest.TestCase):
    def test_inventory_and_run_history_render_with_empty_queue(self):
        fake_st = MagicMock()
        fake_st.checkbox.return_value = False

        with (
            patch.object(pharmacist, "st", fake_st),
            patch.object(
                pharmacist,
                "render_pharmacist_inventory",
            ) as inventory,
            patch.object(
                pharmacist,
                "render_substitute_history",
            ) as history,
            patch.object(
                pharmacist,
                "read_requests",
                return_value=[],
            ),
        ):
            pharmacist.render_pharmacist_view(pd.DataFrame())

        inventory.assert_called_once()
        history.assert_called_once_with(
            title="Alternative review history — whole demo run",
            table_key="pharmacist_substitute_run",
        )

    def test_inventory_and_run_history_render_without_selection(self):
        fake_st = MagicMock()
        fake_st.checkbox.return_value = False

        with (
            patch.object(pharmacist, "st", fake_st),
            patch.object(
                pharmacist,
                "render_pharmacist_inventory",
            ) as inventory,
            patch.object(
                pharmacist,
                "render_substitute_history",
            ) as history,
            patch.object(
                pharmacist,
                "read_requests",
                return_value=[
                    {
                        "request_id": "REQ-0001",
                        "status": "received",
                    }
                ],
            ),
            patch.object(pharmacist, "render_request_table"),
            patch.object(
                pharmacist,
                "select_request",
                return_value=None,
            ),
        ):
            pharmacist.render_pharmacist_view(pd.DataFrame())

        inventory.assert_called_once()
        history.assert_called_once_with(
            title="Alternative review history — whole demo run",
            table_key="pharmacist_substitute_run",
        )


if __name__ == "__main__":
    unittest.main()