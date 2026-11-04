"""Tests for shared-state initialization, publication, and reset."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.config import PROJECT_ROOT
from src.data.loader import load_medications
from src.services.workflow_models import (
    Role,
    SubmitRequestInput,
    WorkflowError,
)
from src.ui import session


class SessionAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)

        self.path = (
            Path(self.temporary_directory.name) / "sample.csv"
        )
        self.path.write_bytes(
            (
                PROJECT_ROOT
                / "data"
                / "sample_medications_extended.csv"
            ).read_bytes()
        )

        self.store = {}
        self.clock = datetime(
            2026, 11, 3, 12, 0,
            tzinfo=timezone.utc,
        )

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

    def action(self, name, *args, role, **kwargs):
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
            **kwargs,
        )

    def submit(self, token="submission-1"):
        result = self.action(
            "submit_request",
            SubmitRequestInput(
                medication_id="MED001",
                quantity=3,
                unit="tablet",
                requesting_location="Demo Ward",
                reason="Synthetic stock request",
            ),
            token,
            role=Role.CLINICAL,
        )

        return result.request_id

    def fulfill(self, request_id):
        self.action(
            "start_review",
            request_id,
            role=Role.PHARMACIST,
        )
        self.action(
            "authorize_release",
            request_id,
            "Synthetic release reviewed",
            role=Role.PHARMACIST,
        )
        return self.action(
            "fulfill_request",
            request_id,
            role=Role.WAREHOUSE,
        )

    def stock(self):
        return session.read_inventory(
            Role.CLINICAL,
            state_store=self.store,
        ).set_index("medication_id").loc[
            "MED001",
            "current_stock",
        ]

    def assert_error(self, code, operation):
        with self.assertRaises(WorkflowError) as caught:
            operation()

        self.assertEqual(caught.exception.code, code)

    def change_source(self):
        # A harmless byte change still requires deliberate replacement.
        self.path.write_bytes(
            self.path.read_bytes() + b"\n"
        )

    def test_initialization_loads_once_on_normal_reruns(self):
        with patch(
            "src.ui.session.load_medications",
            wraps=load_medications,
        ) as loader:
            first = self.ensure()
            root = self.store[session.STATE_KEY]

            second = self.ensure()
            third = self.ensure()

        self.assertEqual(loader.call_count, 1)
        self.assertEqual(first.run_id, second.run_id)
        self.assertEqual(second.run_id, third.run_id)
        self.assertIs(
            self.store[session.STATE_KEY],
            root,
        )

    def test_mutations_are_shared_and_survive_normal_reruns(self):
        initial = self.ensure()
        request_id = self.submit()
        self.fulfill(request_id)

        completed = self.store[session.STATE_KEY]

        self.ensure()
        self.ensure()

        self.assertIs(
            self.store[session.STATE_KEY],
            completed,
        )
        self.assertEqual(
            self.info().run_id,
            initial.run_id,
        )
        self.assertEqual(self.stock(), 1197)

        for role in (
            Role.CLINICAL,
            Role.PHARMACIST,
            Role.PROCUREMENT,
            Role.WAREHOUSE,
            Role.REPORTING,
        ):
            with self.subTest(role=role):
                frame = session.read_inventory(
                    role,
                    state_store=self.store,
                ).set_index("medication_id")

                self.assertEqual(
                    frame.loc["MED001", "current_stock"],
                    1197,
                )

        summary = session.read_inventory_summary(
            state_store=self.store
        )
        self.assertAlmostEqual(
            summary["inventory_value_cad"],
            800.76,
        )

    def test_returned_results_and_readers_are_detached(self):
        self.ensure()

        result = self.action(
            "submit_request",
            SubmitRequestInput(
                "MED001",
                3,
                "tablet",
                "Demo Ward",
                "Synthetic request",
            ),
            "submission-1",
            role=Role.CLINICAL,
        )
        request_id = result.request_id

        result.state.inventory.loc[0, "current_stock"] = 1
        result.state.requests[
            request_id
        ].status_history.clear()

        frame = session.read_inventory(
            Role.CLINICAL,
            state_store=self.store,
        )
        frame.loc[0, "current_stock"] = 2

        details = session.read_request_details(
            request_id,
            Role.CLINICAL,
            state_store=self.store,
        )
        details["status_history"][0]["reason"] = "changed"

        self.assertEqual(self.stock(), 1200)

        fresh = session.read_request_details(
            request_id,
            Role.CLINICAL,
            state_store=self.store,
        )
        self.assertEqual(
            len(fresh["status_history"]),
            1,
        )
        self.assertNotEqual(
            fresh["status_history"][0]["reason"],
            "changed",
        )

    def test_reset_restores_inventory_workflow_and_ui_state(self):
        self.ensure()
        request_id = self.submit()
        self.fulfill(request_id)

        previous = self.info()
        source_bytes = self.path.read_bytes()

        self.store.update(
            {
                "clinical_medication_lookup": "MED001",
                "clinical_request_quantity_MED001": 3,
                "workflow_ui_example_filter": "selected",
                "dashboard_role_tabs": "Warehouse",
                "unrelated_setting": "keep",
            }
        )

        reset = session.reset_demo_session(
            clinical_tab_label="Clinical",
            state_store=self.store,
            now=self.tick(),
        )

        self.assertNotEqual(
            reset.run_id,
            previous.run_id,
        )
        self.assertEqual(reset.revision, 0)
        self.assertEqual(reset.request_count, 0)
        self.assertEqual(self.stock(), 1200)
        self.assertEqual(
            session.read_requests(
                Role.CLINICAL,
                state_store=self.store,
            ),
            [],
        )
        self.assertIsNone(
            self.store["clinical_medication_lookup"]
        )
        self.assertEqual(
            self.store["dashboard_role_tabs"],
            "Clinical",
        )
        self.assertNotIn(
            "clinical_request_quantity_MED001",
            self.store,
        )
        self.assertNotIn(
            "workflow_ui_example_filter",
            self.store,
        )
        self.assertEqual(
            self.store["unrelated_setting"],
            "keep",
        )
        self.assertEqual(
            self.path.read_bytes(),
            source_bytes,
        )

    def test_old_run_action_cannot_change_reset_session(self):
        self.ensure()
        old_info = self.info()
        old_id = self.submit()

        session.reset_demo_session(
            clinical_tab_label="Clinical",
            state_store=self.store,
            now=self.tick(),
        )
        new_id = self.submit()
        self.assertEqual(old_id, new_id)

        root = self.store[session.STATE_KEY]

        self.assert_error(
            "wrong_run",
            lambda: session.apply_workflow_action(
                "start_review",
                new_id,
                acting_role=Role.PHARMACIST,
                expected_run_id=old_info.run_id,
                expected_revision=old_info.revision,
                source_path=self.path,
                state_store=self.store,
                now=self.tick(),
            ),
        )

        self.assertIs(
            self.store[session.STATE_KEY],
            root,
        )

    def test_source_change_requires_explicit_reinitialization(self):
        self.ensure()
        root = self.store[session.STATE_KEY]
        self.change_source()

        self.assert_error(
            "dataset_mismatch",
            self.ensure,
        )
        self.assertIs(
            self.store[session.STATE_KEY],
            root,
        )

    def test_source_change_blocks_workflow_mutation(self):
        self.ensure()
        request_id = self.submit()
        root = self.store[session.STATE_KEY]

        self.change_source()

        self.assert_error(
            "dataset_mismatch",
            lambda: self.action(
                "start_review",
                request_id,
                role=Role.PHARMACIST,
            ),
        )

        self.assertIs(
            self.store[session.STATE_KEY],
            root,
        )

    def test_explicit_dataset_replacement_clears_workflow(self):
        previous = self.ensure()
        self.submit()
        self.change_source()

        replacement = session.replace_demo_dataset(
            self.path,
            clinical_tab_label="Clinical",
            state_store=self.store,
            now=self.tick(),
        )

        self.assertNotEqual(
            replacement.run_id,
            previous.run_id,
        )
        self.assertNotEqual(
            replacement.dataset_fingerprint,
            previous.dataset_fingerprint,
        )
        self.assertEqual(
            replacement.request_count,
            0,
        )
        self.assertEqual(self.stock(), 1200)

        # Normal reruns now accept the new fingerprint.
        self.assertEqual(
            self.ensure().run_id,
            replacement.run_id,
        )

    def test_failed_replacement_preserves_current_state_and_ui(self):
        self.ensure()
        self.submit()
        root = self.store[session.STATE_KEY]
        self.store["clinical_medication_lookup"] = "MED001"

        self.path.write_text(
            "medication_id,medication_name\nBROKEN,Test\n"
        )

        with self.assertRaises(ValueError):
            session.replace_demo_dataset(
                self.path,
                clinical_tab_label="Clinical",
                state_store=self.store,
                now=self.tick(),
            )

        self.assertIs(
            self.store[session.STATE_KEY],
            root,
        )
        self.assertEqual(
            self.store["clinical_medication_lookup"],
            "MED001",
        )

    def test_failed_action_does_not_publish_candidate_state(self):
        self.ensure()
        request_id = self.submit()
        root = self.store[session.STATE_KEY]

        failure = Mock(
            side_effect=RuntimeError(
                "Injected service failure"
            )
        )

        with patch.dict(
            session._ACTIONS,
            {"start_review": failure},
        ):
            with self.assertRaises(RuntimeError):
                self.action(
                    "start_review",
                    request_id,
                    role=Role.PHARMACIST,
                )

        self.assertIs(
            self.store[session.STATE_KEY],
            root,
        )
        self.assertEqual(self.stock(), 1200)

    def test_submission_retry_does_not_publish_or_advance_state(self):
        self.ensure()
        first_id = self.submit()
        root = self.store[session.STATE_KEY]
        before = self.info()

        repeated_id = self.submit()

        self.assertEqual(repeated_id, first_id)
        self.assertIs(
            self.store[session.STATE_KEY],
            root,
        )
        self.assertEqual(
            self.info().revision,
            before.revision,
        )
        self.assertEqual(
            self.info().request_count,
            1,
        )

    def test_unknown_action_is_rejected_without_publication(self):
        self.ensure()
        root = self.store[session.STATE_KEY]

        self.assert_error(
            "invalid_action",
            lambda: self.action(
                "invented_action",
                role=Role.CLINICAL,
            ),
        )

        self.assertIs(
            self.store[session.STATE_KEY],
            root,
        )

    def test_expected_revision_is_forwarded_to_service(self):
        before = self.ensure()
        request_id = self.submit()
        root = self.store[session.STATE_KEY]

        self.assert_error(
            "stale_state",
            lambda: session.apply_workflow_action(
                "start_review",
                request_id,
                acting_role=Role.PHARMACIST,
                expected_run_id=before.run_id,
                expected_revision=before.revision,
                source_path=self.path,
                state_store=self.store,
                now=self.tick(),
            ),
        )

        self.assertIs(
            self.store[session.STATE_KEY],
            root,
        )

    def test_both_sample_schemas_are_supported(self):
        for filename, width in (
            ("sample_medications.csv", 10),
            ("sample_medications_extended.csv", 16),
        ):
            with self.subTest(dataset=filename):
                self.path.write_bytes(
                    (
                        PROJECT_ROOT
                        / "data"
                        / filename
                    ).read_bytes()
                )
                self.store = {}
                self.ensure()

                inventory = session.read_inventory(
                    Role.PROCUREMENT,
                    state_store=self.store,
                )

                self.assertEqual(
                    inventory.shape,
                    (6, width),
                )

    def test_source_changing_during_load_is_not_published(self):
        real_loader = load_medications

        def changing_loader(path):
            result = real_loader(path)
            source = Path(path)
            source.write_bytes(
                source.read_bytes() + b"\n"
            )
            return result

        with patch(
            "src.ui.session.load_medications",
            side_effect=changing_loader,
        ):
            self.assert_error(
                "dataset_changed_during_load",
                self.ensure,
            )

        self.assertNotIn(
            session.STATE_KEY,
            self.store,
        )

    def test_reset_callback_provides_a_temporary_notice(self):
        self.ensure()
        self.submit()

        session.reset_demo_callback(
            clinical_tab_label="Clinical",
            state_store=self.store,
        )

        notice = session.take_notice(
            state_store=self.store
        )

        self.assertEqual(notice["kind"], "success")
        self.assertEqual(
            self.info().request_count,
            0,
        )
        self.assertIsNone(
            session.take_notice(
                state_store=self.store
            )
        )

    def test_failed_reload_callback_preserves_state_and_reports_error(self):
        self.ensure()
        root = self.store[session.STATE_KEY]

        self.path.write_text(
            "medication_id,medication_name\nBROKEN,Test\n"
        )

        session.replace_dataset_callback(
            source_path=self.path,
            clinical_tab_label="Clinical",
            state_store=self.store,
        )

        self.assertIs(
            self.store[session.STATE_KEY],
            root,
        )
        notice = session.take_notice(
            state_store=self.store
        )
        self.assertEqual(notice["kind"], "error")


if __name__ == "__main__":
    unittest.main()