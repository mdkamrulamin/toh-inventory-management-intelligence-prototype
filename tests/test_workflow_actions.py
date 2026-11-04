"""Integration tests for Clinical and Pharmacist UI callbacks."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.config import PROJECT_ROOT
from src.services.clinical import build_clinical_request_preview
from src.services.workflow_models import Role
from src.ui import session
from src.ui.navigation import (
    _reset_clinical_lookup_on_role_change,
)
from src.ui.workflow_actions import (
    clinical_input_keys,
    new_clinical_draft_callback,
    pharmacist_action_callback,
    prepare_clinical_draft,
    submit_clinical_request_callback,
)


class WorkflowActionTests(unittest.TestCase):
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
            2026, 11, 3, 12, 0,
            tzinfo=timezone.utc,
        )
        self.reason_key = "workflow_ui_pharmacist_test_reason"

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

    def draft(self, medication_id="MED001"):
        return prepare_clinical_draft(
            medication_id,
            state_store=self.store,
        )

    def fill_form(
        self,
        medication_id="MED001",
        *,
        reason="Synthetic ward stock request",
        urgency="routine",
        substitution=False,
    ):
        keys = clinical_input_keys(medication_id)
        self.store[keys["location"]] = "Demo Ward"
        self.store[keys["reason"]] = reason
        self.store[keys["urgency"]] = urgency
        self.store[keys["substitution"]] = substitution

    def submit(
        self,
        medication_id="MED001",
        quantity=3,
        *,
        reason="Synthetic ward stock request",
        urgency="routine",
        substitution=False,
    ):
        draft = self.draft(medication_id)
        self.fill_form(
            medication_id,
            reason=reason,
            urgency=urgency,
            substitution=substitution,
        )
        info = self.info()

        submit_clinical_request_callback(
            medication_id,
            quantity,
            "tablet",
            draft["submission_key"],
            info.run_id,
            info.revision,
            source_path=self.path,
            state_store=self.store,
            now=self.tick(),
        )

        return self.draft(medication_id)[
            "submitted_request_id"
        ]

    def review(
        self,
        action_name,
        request_id,
        reason="Synthetic review decision",
        *,
        snapshot=None,
    ):
        info = self.info() if snapshot is None else snapshot
        self.store[self.reason_key] = reason

        pharmacist_action_callback(
            action_name,
            request_id,
            self.reason_key,
            info.run_id,
            info.revision,
            source_path=self.path,
            state_store=self.store,
            now=self.tick(),
        )

    def details(self, request_id, role=Role.CLINICAL):
        return session.read_request_details(
            request_id,
            role,
            state_store=self.store,
        )

    def inventory(self):
        return session.read_inventory(
            Role.CLINICAL,
            state_store=self.store,
        )

    def stock(self, medication_id="MED001"):
        return self.inventory().set_index(
            "medication_id"
        ).loc[medication_id, "current_stock"]

    def assert_notice(self, kind):
        self.assertEqual(
            self.store[session.NOTICE_KEY]["kind"],
            kind,
        )

    def test_draft_is_stable_and_does_not_change_business_state(self):
        root = self.store[session.STATE_KEY]
        first = self.draft()
        second = self.draft()

        self.assertEqual(first, second)
        self.assertIs(self.store[session.STATE_KEY], root)
        self.assertEqual(self.info().revision, 0)
        self.assertEqual(self.info().request_count, 0)

        # A caller receives a detached draft.
        first["submitted_request_id"] = "invented"
        self.assertIsNone(
            self.draft()["submitted_request_id"]
        )

    def test_submission_preserves_fields_and_is_shared(self):
        request_id = self.submit(
            quantity=7,
            urgency="urgent",
            substitution=True,
        )

        self.assertEqual(request_id, "REQ-0001")
        self.assert_notice("success")

        for role in (Role.CLINICAL, Role.PHARMACIST):
            with self.subTest(role=role):
                request = self.details(request_id, role)
                self.assertEqual(
                    request["medication_id"], "MED001"
                )
                self.assertEqual(request["quantity"], 7)
                self.assertEqual(request["unit"], "tablet")
                self.assertEqual(
                    request["requesting_location"], "Demo Ward"
                )
                self.assertEqual(request["urgency"], "urgent")
                self.assertTrue(
                    request["substitution_allowed"]
                )
                self.assertEqual(
                    request["status"], "received"
                )

        self.assertEqual(self.stock(), 1200)
        self.assertEqual(
            self.path.read_bytes(), self.original_bytes
        )

    def test_repeated_submission_callback_creates_only_one_request(self):
        draft = self.draft()
        self.fill_form()
        snapshot = self.info()

        def click():
            submit_clinical_request_callback(
                "MED001",
                3,
                "tablet",
                draft["submission_key"],
                snapshot.run_id,
                snapshot.revision,
                source_path=self.path,
                state_store=self.store,
                now=self.tick(),
            )

        click()
        root = self.store[session.STATE_KEY]
        click()

        self.assertIs(self.store[session.STATE_KEY], root)
        self.assertEqual(self.info().request_count, 1)
        self.assertEqual(self.info().revision, 1)
        self.assert_notice("success")

    def test_new_draft_allows_another_request_without_deleting_first(self):
        first_id = self.submit()
        first_token = self.draft()["submission_key"]
        root = self.store[session.STATE_KEY]

        new_clinical_draft_callback(
            "MED001",
            state_store=self.store,
        )

        self.assertIs(self.store[session.STATE_KEY], root)
        self.assertNotEqual(
            self.draft()["submission_key"], first_token
        )

        second_id = self.submit()

        self.assertEqual(first_id, "REQ-0001")
        self.assertEqual(second_id, "REQ-0002")
        self.assertEqual(self.info().request_count, 2)
        self.assertEqual(
            self.details(first_id)["status"], "received"
        )
        self.assertEqual(self.stock(), 1200)

    def test_invalid_submission_keeps_draft_and_inventory(self):
        draft = self.draft()
        root = self.store[session.STATE_KEY]

        request_id = self.submit(reason="   ")

        self.assertIsNone(request_id)
        self.assert_notice("error")
        self.assertIs(self.store[session.STATE_KEY], root)
        self.assertEqual(
            self.draft()["submission_key"],
            draft["submission_key"],
        )
        self.assertEqual(self.info().request_count, 0)
        self.assertEqual(self.stock(), 1200)

        # Correcting the same draft can still use the first ID.
        self.assertEqual(self.submit(), "REQ-0001")

    def test_preview_and_navigation_preserve_submitted_requests(self):
        request_id = self.submit()
        root = self.store[session.STATE_KEY]

        row = self.inventory().set_index(
            "medication_id", drop=False
        ).loc["MED001"]

        preview = build_clinical_request_preview(row, 3)
        self.assertEqual(preview.outcome, "sufficient")
        self.assertIs(self.store[session.STATE_KEY], root)

        self.store["clinical_medication_lookup"] = "MED001"
        self.store["dashboard_role_tabs"] = "Pharmacist"

        with patch(
            "src.ui.navigation.st.session_state",
            self.store,
        ):
            _reset_clinical_lookup_on_role_change("Clinical")

        self.assertIsNone(
            self.store["clinical_medication_lookup"]
        )
        self.assertIs(self.store[session.STATE_KEY], root)
        self.assertEqual(
            self.details(request_id)["status"], "received"
        )
        self.assertEqual(self.stock(), 1200)

    def test_opening_is_read_only_then_explicit_review_releases(self):
        request_id = self.submit()
        root = self.store[session.STATE_KEY]

        opened = self.details(
            request_id, Role.PHARMACIST
        )

        self.assertEqual(opened["status"], "received")
        self.assertIs(self.store[session.STATE_KEY], root)

        self.review("start_review", request_id)
        self.assertEqual(
            self.details(request_id)["status"],
            "under_review",
        )

        self.review(
            "authorize_release",
            request_id,
            "Synthetic full release checked",
        )

        self.assertEqual(
            self.details(request_id)["status"],
            "approved_for_release",
        )
        warehouse_queue = session.read_requests(
            Role.WAREHOUSE,
            actionable_only=True,
            state_store=self.store,
        )
        self.assertEqual(
            [item["request_id"] for item in warehouse_queue],
            [request_id],
        )
        self.assertEqual(self.stock(), 1200)

    def test_zero_and_insufficient_stock_route_to_procurement(self):
        cases = (
            ("MED003", 3, 0),
            ("MED001", 1201, 1200),
        )

        for medication_id, quantity, expected_stock in cases:
            with self.subTest(medication_id=medication_id):
                request_id = self.submit(
                    medication_id, quantity
                )
                self.review("start_review", request_id)
                self.review(
                    "escalate_shortage",
                    request_id,
                    "Full requested quantity is unavailable",
                )

                clinical = self.details(request_id)
                self.assertEqual(
                    clinical["status"], "escalated"
                )
                self.assertEqual(
                    clinical["status_reason"],
                    "Full requested quantity is unavailable",
                )
                queue = session.read_requests(
                    Role.PROCUREMENT,
                    actionable_only=True,
                    state_store=self.store,
                )
                self.assertIn(
                    request_id,
                    [item["request_id"] for item in queue],
                )
                self.assertEqual(
                    self.stock(medication_id),
                    expected_stock,
                )

    def test_return_to_queue_and_final_return_preserve_reasons(self):
        request_id = self.submit()
        received_time = self.details(request_id)[
            "received_time"
        ]

        self.review("start_review", request_id)
        self.review(
            "return_to_queue",
            request_id,
            "Review interrupted",
        )

        queued = self.details(request_id)
        self.assertEqual(queued["status"], "received")
        self.assertEqual(
            queued["received_time"], received_time
        )
        self.assertEqual(
            queued["status_reason"], "Review interrupted"
        )

        self.review("start_review", request_id)
        self.review(
            "return_request",
            request_id,
            "Clarify the synthetic requesting location",
        )

        returned = self.details(request_id)
        self.assertEqual(returned["status"], "returned")
        self.assertEqual(returned["outcome"], "returned")
        self.assertEqual(
            returned["status_reason"],
            "Clarify the synthetic requesting location",
        )
        self.assertEqual(self.stock(), 1200)

    def test_invalid_review_actions_do_not_publish_changes(self):
        request_id = self.submit()
        self.review("start_review", request_id)

        cases = (
            ("start_review", "Duplicate review"),
            ("authorize_release", "   "),
            ("escalate_shortage", "Stock is actually sufficient"),
        )

        for action_name, reason in cases:
            with self.subTest(action=action_name):
                root = self.store[session.STATE_KEY]
                self.review(action_name, request_id, reason)

                self.assert_notice("error")
                self.assertIs(
                    self.store[session.STATE_KEY], root
                )
                self.assertEqual(
                    self.details(request_id)["status"],
                    "under_review",
                )
                self.assertEqual(self.stock(), 1200)

    def test_stale_review_callback_cannot_change_latest_state(self):
        request_id = self.submit()
        stale_snapshot = self.info()

        self.review("start_review", request_id)
        root = self.store[session.STATE_KEY]

        self.review(
            "return_request",
            request_id,
            "Stale decision",
            snapshot=stale_snapshot,
        )

        self.assert_notice("error")
        self.assertIs(self.store[session.STATE_KEY], root)
        self.assertEqual(
            self.details(request_id)["status"],
            "under_review",
        )

    def test_old_submission_cannot_recreate_request_after_reset(self):
        old_draft = self.draft()
        old_info = self.info()
        self.fill_form()

        session.reset_demo_session(
            clinical_tab_label="Clinical",
            state_store=self.store,
            now=self.tick(),
        )
        root = self.store[session.STATE_KEY]

        submit_clinical_request_callback(
            "MED001",
            3,
            "tablet",
            old_draft["submission_key"],
            old_info.run_id,
            old_info.revision,
            source_path=self.path,
            state_store=self.store,
            now=self.tick(),
        )

        self.assert_notice("error")
        self.assertIs(self.store[session.STATE_KEY], root)
        self.assertEqual(self.info().request_count, 0)

    def test_old_review_cannot_target_reused_id_after_reset(self):
        old_request_id = self.submit()
        old_info = self.info()

        session.reset_demo_session(
            clinical_tab_label="Clinical",
            state_store=self.store,
            now=self.tick(),
        )

        new_request_id = self.submit()
        self.assertEqual(new_request_id, old_request_id)
        root = self.store[session.STATE_KEY]

        self.review(
            "start_review",
            old_request_id,
            snapshot=old_info,
        )

        self.assert_notice("error")
        self.assertIs(self.store[session.STATE_KEY], root)
        self.assertEqual(
            self.details(new_request_id)["status"],
            "received",
        )

    def test_pharmacist_callback_cannot_perform_warehouse_action(self):
        request_id = self.submit()
        root = self.store[session.STATE_KEY]

        self.review("fulfill_request", request_id)

        self.assert_notice("error")
        self.assertIs(self.store[session.STATE_KEY], root)
        self.assertEqual(self.stock(), 1200)

    def test_recall_returns_release_to_review_without_stock_change(self):
        request_id = self.submit()
        self.review("start_review", request_id)
        self.review("authorize_release", request_id)
        self.review(
            "recall_release",
            request_id,
            "Recheck this synthetic release",
        )

        request = self.details(request_id)
        self.assertEqual(
            request["status"], "under_review"
        )
        self.assertEqual(
            request["status_reason"],
            "Recheck this synthetic release",
        )
        self.assertEqual(self.stock(), 1200)

    def test_submission_supports_both_source_datasets(self):
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
                self.ensure()

                request_id = self.submit()
                self.review("start_review", request_id)
                self.review(
                    "authorize_release", request_id
                )

                self.assertEqual(
                    self.details(request_id)["status"],
                    "approved_for_release",
                )
                self.assertEqual(self.stock(), 1200)
                self.assertNotIn(
                    "unit_cost", self.inventory().columns
                )

    def test_source_change_blocks_callback_without_publication(self):
        draft = self.draft()
        self.fill_form()
        info = self.info()
        root = self.store[session.STATE_KEY]

        self.path.write_bytes(
            self.path.read_bytes() + b"\n"
        )

        submit_clinical_request_callback(
            "MED001",
            3,
            "tablet",
            draft["submission_key"],
            info.run_id,
            info.revision,
            source_path=self.path,
            state_store=self.store,
            now=self.tick(),
        )

        self.assert_notice("error")
        self.assertIs(self.store[session.STATE_KEY], root)
        self.assertEqual(self.info().request_count, 0)


if __name__ == "__main__":
    unittest.main()