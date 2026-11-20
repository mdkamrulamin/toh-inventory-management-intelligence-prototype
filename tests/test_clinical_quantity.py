"""DEF-01 quantity parsing, current-form submission and rejection checks."""

from datetime import datetime, timedelta, timezone
import unittest

import pandas as pd

from src.config import PROJECT_ROOT
from src.services.clinical import (
    build_clinical_request_preview,
    parse_clinical_quantity,
    validate_request_quantity,
)
from src.services.workflow_models import (
    Role,
    SubmitRequestInput,
    WorkflowError,
)
from src.ui import session
from src.ui.workflow_actions import (
    clinical_input_keys,
    new_clinical_draft_callback,
    prepare_clinical_draft,
    submit_clinical_form_callback,
)


class ClinicalQuantityValidationTests(unittest.TestCase):
    def test_valid_text_is_parsed_without_rounding(self):
        for text, expected in (
            ("1", 1),
            ("3", 3),
            (" 5 ", 5),
            ("0003", 3),
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    parse_clinical_quantity(text),
                    expected,
                )

    def test_invalid_text_has_no_fallback_quantity(self):
        for text in (
            None,
            "",
            " ",
            "0",
            "-1",
            "1.5",
            "3.0",
            "abc",
            "nan",
            "inf",
            "1e3",
            "+3",
            True,
            3,
            3.0,
        ):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_clinical_quantity(text)

    def test_runtime_validator_rejects_invalid_values(self):
        for value in (
            None,
            0,
            -1,
            1.5,
            3.0,
            "3",
            True,
            pd.NA,
            float("nan"),
            float("inf"),
            10**400,
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_request_quantity(value)

    def test_preview_uses_the_same_quantity_contract(self):
        medication = pd.Series(
            {
                "medication_id": "MED001",
                "medication_name": "Paracetamol 500 mg",
                "current_stock": 1200,
                "stock_unit": "tablet",
            }
        )

        for quantity in (3, 1200, 1500):
            preview = build_clinical_request_preview(
                medication,
                parse_clinical_quantity(str(quantity)),
            )
            self.assertEqual(
                preview.requested_quantity,
                quantity,
            )


class ClinicalFormQuantityTests(unittest.TestCase):
    def setUp(self):
        self.clock = datetime(
            2026, 11, 19, 12, 0, tzinfo=timezone.utc
        )
        self.start_session()

    def tick(self):
        self.clock += timedelta(seconds=1)
        return self.clock

    def start_session(
        self,
        filename="sample_medications_extended.csv",
    ):
        self.path = PROJECT_ROOT / "data" / filename
        self.source_bytes = self.path.read_bytes()
        self.store = {}

        session.ensure_demo_session(
            self.path,
            state_store=self.store,
            now=self.tick(),
        )

    def info(self):
        return session.get_session_info(state_store=self.store)

    def draft(self, medication_id="MED001"):
        return prepare_clinical_draft(
            medication_id,
            state_store=self.store,
        )

    def fill(self, raw_quantity, medication_id="MED001"):
        keys = clinical_input_keys(medication_id)
        self.store[keys["quantity"]] = raw_quantity
        self.store[keys["location"]] = "Demo Ward"
        self.store[keys["reason"]] = "Synthetic quantity test"
        self.store[keys["urgency"]] = "routine"
        self.store[keys["substitution"]] = False
        return keys

    def click(
        self,
        medication_id="MED001",
        *,
        draft=None,
        info=None,
    ):
        draft = self.draft(medication_id) if draft is None else draft
        info = self.info() if info is None else info

        submit_clinical_form_callback(
            medication_id=medication_id,
            unit="tablet",
            submission_key=draft["submission_key"],
            expected_run_id=info.run_id,
            expected_revision=info.revision,
            source_path=self.path,
            state_store=self.store,
            now=self.tick(),
        )

    def requests(self):
        return session.read_requests(
            Role.CLINICAL,
            state_store=self.store,
        )

    def test_invalid_current_text_creates_no_request_or_state_change(self):
        draft = self.draft()

        # An obsolete numeric-widget value must never become a fallback.
        self.store["clinical_request_quantity_MED001"] = 1

        for raw in ("-1", "0", "", " ", "1.5", "abc", "nan", "inf"):
            with self.subTest(raw=raw):
                keys = self.fill(raw)
                root = self.store[session.STATE_KEY]

                self.click(draft=draft)

                self.assertIs(self.store[session.STATE_KEY], root)
                self.assertEqual(self.requests(), [])
                self.assertEqual(
                    session.read_requests(
                        Role.PHARMACIST,
                        state_store=self.store,
                    ),
                    [],
                )
                self.assertEqual(self.store[keys["quantity"]], raw)
                self.assertTrue(self.store[keys["form_error"]])
                self.assertEqual(
                    self.draft()["submission_key"],
                    draft["submission_key"],
                )

        self.assertEqual(self.path.read_bytes(), self.source_bytes)

    def test_missing_raw_quantity_does_not_submit_one(self):
        draft = self.draft()
        keys = self.fill("3")
        self.store.pop(keys["quantity"])
        self.store["clinical_request_quantity_MED001"] = 1
        root = self.store[session.STATE_KEY]

        self.click(draft=draft)

        self.assertIs(self.store[session.STATE_KEY], root)
        self.assertEqual(self.requests(), [])

    def test_previous_valid_value_is_not_submitted_after_invalid_edit(self):
        self.draft()
        keys = self.fill("3")

        self.store[keys["quantity"]] = "-1"
        root = self.store[session.STATE_KEY]
        self.click()

        self.assertIs(self.store[session.STATE_KEY], root)
        self.assertEqual(self.requests(), [])

    def test_latest_valid_form_value_is_submitted(self):
        self.draft()
        keys = self.fill("3")

        self.store[keys["quantity"]] = "5"
        self.click()

        self.assertEqual(len(self.requests()), 1)
        self.assertEqual(self.requests()[0]["quantity"], 5)
        self.assertEqual(self.requests()[0]["status"], "received")

    def test_invalid_then_corrected_draft_uses_first_request_id(self):
        draft = self.draft()
        keys = self.fill("-1")
        self.click(draft=draft)

        self.assertEqual(self.requests(), [])

        self.store[keys["quantity"]] = "3"
        self.click(draft=draft)

        self.assertEqual(self.requests()[0]["request_id"], "REQ-0001")
        self.assertEqual(self.requests()[0]["quantity"], 3)
        self.assertEqual(self.store[keys["form_error"]], "")

    def test_below_equal_above_and_zero_stock_requests_are_allowed(self):
        for medication_id, quantity in (
            ("MED001", 3),
            ("MED001", 1200),
            ("MED001", 1500),
            ("MED003", 5),
        ):
            with self.subTest(
                medication_id=medication_id,
                quantity=quantity,
            ):
                self.start_session()
                self.draft(medication_id)
                self.fill(str(quantity), medication_id)
                before = self.store[session.STATE_KEY]

                self.click(medication_id)

                self.assertEqual(
                    self.requests()[0]["quantity"],
                    quantity,
                )
                pd.testing.assert_frame_equal(
                    self.store[session.STATE_KEY].inventory,
                    before.inventory,
                )

    def test_duplicate_callback_does_not_create_another_request(self):
        draft = self.draft()
        self.fill("3")
        info = self.info()

        self.click(draft=draft, info=info)
        root = self.store[session.STATE_KEY]

        self.click(draft=draft, info=info)

        self.assertIs(self.store[session.STATE_KEY], root)
        self.assertEqual(len(self.requests()), 1)
        self.assertEqual(self.requests()[0]["quantity"], 3)

    def test_new_draft_clears_text_and_preserves_submitted_request(self):
        self.draft()
        keys = self.fill("3")
        self.click()

        old_draft = self.draft()
        root = self.store[session.STATE_KEY]
        self.store[keys["form_error"]] = "Old error"

        new_clinical_draft_callback(
            "MED001",
            state_store=self.store,
        )

        self.assertIs(self.store[session.STATE_KEY], root)
        self.assertEqual(self.store[keys["quantity"]], "")
        self.assertEqual(self.store[keys["form_error"]], "")
        self.assertNotEqual(
            self.draft()["submission_key"],
            old_draft["submission_key"],
        )
        self.assertEqual(self.requests()[0]["quantity"], 3)

        self.fill("5")
        self.click()

        self.assertEqual(
            [request["quantity"] for request in self.requests()],
            [3, 5],
        )

    def test_old_draft_cannot_submit_or_clear_current_form_error(self):
        old_draft = self.draft()
        old_info = self.info()

        new_clinical_draft_callback(
            "MED001",
            state_store=self.store,
        )
        keys = self.fill("7")
        self.store[keys["form_error"]] = "Current draft message"
        root = self.store[session.STATE_KEY]

        self.click(draft=old_draft, info=old_info)

        self.assertIs(self.store[session.STATE_KEY], root)
        self.assertEqual(self.store[keys["quantity"]], "7")
        self.assertEqual(
            self.store[keys["form_error"]],
            "Current draft message",
        )

    def test_reset_clears_form_and_rejects_old_run_callback(self):
        draft = self.draft()
        self.fill("3")
        old_info = self.info()

        session.reset_demo_session(
            clinical_tab_label="Clinical",
            state_store=self.store,
            now=self.tick(),
        )
        root = self.store[session.STATE_KEY]

        self.click(draft=draft, info=old_info)

        self.assertIs(self.store[session.STATE_KEY], root)
        self.assertEqual(self.requests(), [])
        self.assertNotIn(
            clinical_input_keys("MED001")["quantity"],
            self.store,
        )

    def test_runtime_service_rejections_do_not_consume_request_ids(self):
        draft = self.draft()
        root = self.store[session.STATE_KEY]

        for quantity in (
            None,
            0,
            -1,
            1.5,
            3.0,
            True,
            float("nan"),
            float("inf"),
            10**400,
        ):
            with self.subTest(quantity=quantity):
                info = self.info()

                with self.assertRaises(WorkflowError):
                    session.apply_workflow_action(
                        "submit_request",
                        SubmitRequestInput(
                            medication_id="MED001",
                            quantity=quantity,
                            unit="tablet",
                            requesting_location="Demo Ward",
                            reason="Invalid runtime quantity",
                        ),
                        draft["submission_key"],
                        acting_role=Role.CLINICAL,
                        expected_run_id=info.run_id,
                        expected_revision=info.revision,
                        source_path=self.path,
                        state_store=self.store,
                        now=self.tick(),
                    )

                self.assertIs(self.store[session.STATE_KEY], root)

        self.fill("3")
        self.click(draft=draft)
        self.assertEqual(self.requests()[0]["request_id"], "REQ-0001")

    def test_current_form_submission_supports_both_datasets(self):
        for filename in (
            "sample_medications.csv",
            "sample_medications_extended.csv",
        ):
            with self.subTest(dataset=filename):
                self.start_session(filename)
                self.draft()
                self.fill("3")
                self.click()

                self.assertEqual(
                    self.requests()[0]["quantity"],
                    3,
                )
                self.assertEqual(
                    self.path.read_bytes(),
                    self.source_bytes,
                )


if __name__ == "__main__":
    unittest.main()