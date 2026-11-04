"""Service-level checks for the synthetic medication workflow.

These tests do not launch Streamlit or edit the sample CSVs.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import unittest
from unittest.mock import patch

import pandas as pd

from src.config import PROJECT_ROOT
from src.data.loader import load_medications
from src.services.clinical import build_clinical_request_preview
from src.services.replenishment import build_replenishment_context
from src.services.summary import summarize_inventory
from src.services import workflow as wf
from src.services.workflow_models import (
    RequestOutcome,
    RequestStatus,
    Role,
    SubmitRequestInput,
    SupplyFeedbackInput,
    Urgency,
    WorkflowError,
)


class WorkflowTests(unittest.TestCase):
    NOW = datetime(
        2026, 11, 3, 12, 0,
        tzinfo=timezone.utc,
    )

    def new_state(
        self,
        filename="sample_medications_extended.csv",
    ):
        path = PROJECT_ROOT / "data" / filename

        return wf.initialize_demo(
            load_medications(path),
            dataset_path=str(path),
            dataset_fingerprint=sha256(
                path.read_bytes()
            ).hexdigest(),
            now=self.NOW,
        )

    def context(self, state, role):
        now = datetime.fromisoformat(
            state.started_time
        ) + timedelta(seconds=state.revision + 1)

        return wf.make_context(state, role, now=now)

    def submit(
        self,
        state,
        medication_id="MED001",
        quantity=3,
        unit="tablet",
        **changes,
    ):
        key = changes.pop(
            "submission_key",
            f"attempt-{state.next_request_number}",
        )

        inputs = SubmitRequestInput(
            medication_id=medication_id,
            quantity=quantity,
            unit=unit,
            requesting_location="Demo Ward A",
            reason="Synthetic unit stock request",
        )
        inputs = replace(inputs, **changes)

        result = wf.submit_request(
            state,
            inputs,
            key,
            self.context(state, Role.CLINICAL),
        )

        return result.state, result.request_id

    def review(self, state, request_id):
        return wf.start_review(
            state,
            request_id,
            self.context(state, Role.PHARMACIST),
        ).state

    def release(self, state, request_id):
        if (
            state.requests[request_id].status
            == RequestStatus.RECEIVED
        ):
            state = self.review(state, request_id)

        return wf.authorize_release(
            state,
            request_id,
            "Synthetic release reviewed",
            self.context(state, Role.PHARMACIST),
        ).state

    def escalate(self, state, request_id):
        if (
            state.requests[request_id].status
            == RequestStatus.RECEIVED
        ):
            state = self.review(state, request_id)

        return wf.escalate_shortage(
            state,
            request_id,
            "Full requested quantity is unavailable",
            self.context(state, Role.PHARMACIST),
        ).state

    def feedback(
        self,
        state,
        request_id,
        text="Demo supplier review pending",
    ):
        return wf.update_supply_feedback(
            state,
            request_id,
            SupplyFeedbackInput(text),
            self.context(state, Role.PROCUREMENT),
        ).state

    def stock(self, state, medication_id="MED001"):
        return state.inventory.set_index(
            "medication_id"
        ).loc[medication_id, "current_stock"]

    def assert_state_equal(self, actual, expected):
        pd.testing.assert_frame_equal(
            actual.inventory,
            expected.inventory,
        )
        pd.testing.assert_frame_equal(
            actual.initial_inventory,
            expected.initial_inventory,
        )

        for name in (
            "schema_version",
            "run_id",
            "revision",
            "dataset_path",
            "dataset_fingerprint",
            "requests",
            "next_request_number",
            "started_time",
        ):
            self.assertEqual(
                getattr(actual, name),
                getattr(expected, name),
                name,
            )

    def assert_rejected(self, state, code, operation):
        before = deepcopy(state)

        with self.assertRaises(WorkflowError) as caught:
            operation()

        self.assertEqual(caught.exception.code, code)
        self.assert_state_equal(state, before)

    def test_initialization_supports_both_datasets_and_separate_copies(self):
        for filename, width in (
            ("sample_medications.csv", 10),
            ("sample_medications_extended.csv", 16),
        ):
            with self.subTest(dataset=filename):
                state = self.new_state(filename)

                self.assertEqual(
                    state.inventory.shape,
                    (6, width),
                )
                self.assertEqual(state.requests, {})
                self.assertEqual(
                    state.next_request_number,
                    1,
                )
                self.assertEqual(state.revision, 0)

                original = (
                    state.initial_inventory.copy(deep=True)
                )
                state.inventory.loc[0, "current_stock"] = 1

                pd.testing.assert_frame_equal(
                    state.initial_inventory,
                    original,
                )

    def test_initialization_does_not_retain_caller_frame(self):
        source = load_medications()
        original = source.copy(deep=True)

        state = wf.initialize_demo(
            source,
            dataset_path="demo.csv",
            dataset_fingerprint="fixture",
            now=self.NOW,
        )

        state.inventory.loc[0, "current_stock"] = 1
        state.initial_inventory.loc[1, "current_stock"] = 2

        pd.testing.assert_frame_equal(source, original)

    def test_initialization_rejects_invalid_stock_and_duplicate_ids(self):
        source = load_medications()

        for invalid in (
            -1,
            float("inf"),
            "bad",
            None,
            True,
        ):
            with self.subTest(stock=invalid):
                frame = source.astype(object)
                frame.loc[0, "current_stock"] = invalid

                with self.assertRaises(WorkflowError):
                    wf.initialize_demo(
                        frame,
                        dataset_path="demo.csv",
                        dataset_fingerprint="fixture",
                        now=self.NOW,
                    )

        frame = source.copy()
        frame.loc[1, "medication_id"] = (
            frame.loc[0, "medication_id"]
        )

        with self.assertRaises(WorkflowError):
            wf.initialize_demo(
                frame,
                dataset_path="demo.csv",
                dataset_fingerprint="fixture",
                now=self.NOW,
            )

    def test_preview_is_separate_from_submission(self):
        state = self.new_state()
        before = deepcopy(state)

        row = state.inventory.set_index(
            "medication_id"
        ).loc["MED001"].copy()
        row["medication_id"] = "MED001"

        preview = build_clinical_request_preview(row, 3)

        self.assertEqual(
            preview.outcome,
            "sufficient",
        )
        self.assert_state_equal(state, before)

    def test_request_ids_are_unique_and_input_state_is_unchanged(self):
        initial = self.new_state()
        before = deepcopy(initial)

        first, first_id = self.submit(initial)
        second, second_id = self.submit(first)

        self.assertEqual(
            (first_id, second_id),
            ("REQ-0001", "REQ-0002"),
        )
        self.assertEqual(
            second.next_request_number,
            3,
        )
        self.assertEqual(len(second.requests), 2)
        self.assertEqual(
            second.requests[first_id].run_id,
            initial.run_id,
        )
        self.assertEqual(self.stock(second), 1200)
        self.assert_state_equal(initial, before)

    def test_same_submission_retry_is_idempotent_even_with_old_revision(self):
        state = self.new_state()

        inputs = SubmitRequestInput(
            "MED001",
            3,
            "tablet",
            "Demo Ward",
            "Demo reason",
        )
        context = self.context(state, Role.CLINICAL)

        first = wf.submit_request(
            state,
            inputs,
            "same-action",
            context,
        )
        before = deepcopy(first.state)

        retry = wf.submit_request(
            first.state,
            inputs,
            "same-action",
            context,
        )

        self.assertFalse(retry.changed)
        self.assertEqual(
            retry.request_id,
            first.request_id,
        )
        self.assert_state_equal(retry.state, before)

    def test_submission_key_cannot_be_reused_for_different_payload(self):
        state = self.new_state()

        inputs = SubmitRequestInput(
            "MED001",
            3,
            "tablet",
            "Demo Ward",
            "Demo reason",
        )

        state = wf.submit_request(
            state,
            inputs,
            "same-action",
            self.context(state, Role.CLINICAL),
        ).state

        self.assert_rejected(
            state,
            "submission_key_conflict",
            lambda: wf.submit_request(
                state,
                replace(inputs, quantity=4),
                "same-action",
                self.context(state, Role.CLINICAL),
            ),
        )

    def test_invalid_quantities_are_rejected_without_consuming_ids(self):
        for quantity in (
            None,
            0,
            -1,
            2.5,
            3.0,
            "3",
            True,
            pd.NA,
            float("nan"),
            float("inf"),
        ):
            with self.subTest(quantity=quantity):
                state = self.new_state()

                self.assert_rejected(
                    state,
                    "invalid_quantity",
                    lambda: self.submit(
                        state,
                        quantity=quantity,
                    ),
                )

    def test_unknown_or_blank_medication_is_rejected(self):
        for medication_id in ("", "UNKNOWN", None):
            with self.subTest(
                medication_id=medication_id
            ):
                state = self.new_state()

                self.assert_rejected(
                    state,
                    "unknown_medication",
                    lambda: self.submit(
                        state,
                        medication_id=medication_id,
                    ),
                )

    def test_missing_or_mismatched_units_block_submission(self):
        for unit in ("", None, "vial"):
            with self.subTest(unit=unit):
                state = self.new_state()

                self.assert_rejected(
                    state,
                    "invalid_unit",
                    lambda: self.submit(
                        state,
                        unit=unit,
                    ),
                )

        state = self.new_state()
        frame = state.inventory.drop(
            columns="stock_unit"
        )
        state = replace(state, inventory=frame)

        self.assert_rejected(
            state,
            "invalid_unit",
            lambda: self.submit(state),
        )

    def test_request_context_validation(self):
        for field, value in (
            ("requesting_location", ""),
            ("reason", ""),
            ("urgency", "emergency"),
            ("substitution_allowed", "yes"),
        ):
            with self.subTest(field=field):
                state = self.new_state()
                before = deepcopy(state)

                with self.assertRaises(WorkflowError):
                    self.submit(
                        state,
                        **{field: value},
                    )

                self.assert_state_equal(state, before)

    def test_return_to_queue_preserves_arrival_identity(self):
        state, request_id = self.submit(
            self.new_state(),
            urgency=Urgency.URGENT,
        )

        received = (
            state.requests[request_id].received_time
        )
        sequence = state.requests[request_id].sequence

        state = self.review(state, request_id)
        state = wf.return_to_queue(
            state,
            request_id,
            "Another demo reviewer can continue",
            self.context(state, Role.PHARMACIST),
        ).state

        request = state.requests[request_id]

        self.assertEqual(
            request.status,
            RequestStatus.RECEIVED,
        )
        self.assertEqual(
            request.received_time,
            received,
        )
        self.assertEqual(request.sequence, sequence)
        self.assertEqual(self.stock(state), 1200)

    def test_returned_request_is_terminal_and_requires_reason(self):
        state, request_id = self.submit(
            self.new_state()
        )
        state = self.review(state, request_id)

        self.assert_rejected(
            state,
            "reason_required",
            lambda: wf.return_request(
                state,
                request_id,
                " ",
                self.context(state, Role.PHARMACIST),
            ),
        )

        state = wf.return_request(
            state,
            request_id,
            "Request needs correction",
            self.context(state, Role.PHARMACIST),
        ).state

        self.assertEqual(
            state.requests[request_id].outcome,
            RequestOutcome.RETURNED,
        )

        self.assert_rejected(
            state,
            "invalid_transition",
            lambda: wf.start_review(
                state,
                request_id,
                self.context(state, Role.PHARMACIST),
            ),
        )

    def test_submission_review_and_authorization_never_deduct_stock(self):
        state, request_id = self.submit(
            self.new_state()
        )
        original = (
            state.initial_inventory.copy(deep=True)
        )

        state = self.review(state, request_id)

        pd.testing.assert_frame_equal(
            state.inventory,
            original,
        )

        state = self.release(state, request_id)

        pd.testing.assert_frame_equal(
            state.inventory,
            original,
        )
        self.assertEqual(
            state.requests[request_id].status,
            RequestStatus.APPROVED_FOR_RELEASE,
        )
        self.assertIsNone(
            state.requests[request_id].fulfillment
        )

    def test_authorization_rejects_insufficient_stock_without_partial_release(self):
        for medication_id, quantity, unit in (
            ("MED001", 1201, "tablet"),
            ("MED003", 3, "tablet"),
            ("MED006", 90, "vial"),
        ):
            with self.subTest(
                medication=medication_id
            ):
                state, request_id = self.submit(
                    self.new_state(),
                    medication_id,
                    quantity,
                    unit,
                )
                state = self.review(
                    state,
                    request_id,
                )

                self.assert_rejected(
                    state,
                    "insufficient_stock",
                    lambda: wf.authorize_release(
                        state,
                        request_id,
                        "Demo review",
                        self.context(
                            state,
                            Role.PHARMACIST,
                        ),
                    ),
                )

    def test_shortage_requires_deliberate_review_and_actual_shortfall(self):
        state, request_id = self.submit(
            self.new_state(),
            "MED003",
            3,
        )

        self.assert_rejected(
            state,
            "invalid_transition",
            lambda: wf.escalate_shortage(
                state,
                request_id,
                "Zero stock",
                self.context(state, Role.PHARMACIST),
            ),
        )

        state = self.escalate(state, request_id)

        self.assertEqual(
            state.requests[request_id].shortfall,
            3,
        )
        self.assertEqual(
            state.requests[request_id].status,
            RequestStatus.ESCALATED,
        )
        self.assertEqual(
            self.stock(state, "MED003"),
            0,
        )

        sufficient, sufficient_id = self.submit(
            self.new_state()
        )
        sufficient = self.review(
            sufficient,
            sufficient_id,
        )

        self.assert_rejected(
            sufficient,
            "invalid_transition",
            lambda: self.escalate(
                sufficient,
                sufficient_id,
            ),
        )

    def test_fulfillment_deducts_once_and_retains_fulfilled_outcome(self):
        state, request_id = self.submit(
            self.new_state()
        )
        state = self.release(state, request_id)
        before = deepcopy(state)

        result = wf.fulfill_request(
            state,
            request_id,
            self.context(state, Role.WAREHOUSE),
        )
        request = result.state.requests[request_id]

        self.assertEqual(
            self.stock(result.state),
            1197,
        )
        self.assertEqual(
            request.status,
            RequestStatus.CLOSED,
        )
        self.assertEqual(
            request.outcome,
            RequestOutcome.FULFILLED,
        )
        self.assertEqual(
            request.fulfillment.quantity,
            3,
        )
        self.assertEqual(
            request.fulfillment.stock_before,
            1200,
        )
        self.assertEqual(
            request.fulfillment.stock_after,
            1197,
        )
        self.assertEqual(
            [
                event.to_status
                for event in request.status_history[-2:]
            ],
            [
                RequestStatus.FULFILLED,
                RequestStatus.CLOSED,
            ],
        )
        self.assertEqual(
            result.state.revision,
            state.revision + 1,
        )
        self.assert_state_equal(state, before)

    def test_fulfillment_boundaries_and_executive_summaries(self):
        cases = (
            (
                "MED001", 3, "tablet", 1197,
                "Above", 800.76, 1,
            ),
            (
                "MED001", 400, "tablet", 800,
                "At/below", 769.00, 1,
            ),
            (
                "MED001", 1200, "tablet", 0,
                "Recorded stock = 0", 705.00, 2,
            ),
            (
                "MED006", 20, "vial", 60,
                "At/below", 711.00, 1,
            ),
            (
                "MED006", 80, "vial", 0,
                "Recorded stock = 0", 441.00, 2,
            ),
        )

        for (
            medication_id,
            quantity,
            unit,
            remaining,
            label,
            value,
            zeros,
        ) in cases:
            with self.subTest(
                medication=medication_id,
                quantity=quantity,
            ):
                state, request_id = self.submit(
                    self.new_state(),
                    medication_id,
                    quantity,
                    unit,
                )
                state = self.release(
                    state,
                    request_id,
                )
                state = wf.fulfill_request(
                    state,
                    request_id,
                    self.context(
                        state,
                        Role.WAREHOUSE,
                    ),
                ).state

                self.assertEqual(
                    self.stock(state, medication_id),
                    remaining,
                )

                review = build_replenishment_context(
                    state.inventory
                ).set_index("medication_id").loc[
                    medication_id,
                    "ordering_review",
                ]
                self.assertTrue(
                    review.startswith(label),
                    review,
                )

                summary = summarize_inventory(
                    state.inventory
                )

                self.assertAlmostEqual(
                    summary["inventory_value_cad"],
                    value,
                )
                self.assertEqual(
                    summary["zero_stock_count"],
                    zeros,
                )
                self.assertEqual(
                    summary["sku_count"],
                    6,
                )
                self.assertEqual(
                    summary["supplier_count"],
                    3,
                )

                availability = (
                    state.inventory
                    .set_index("medication_id")
                    .loc[medication_id, "status"]
                )
                self.assertEqual(
                    availability,
                    (
                        "Out of stock"
                        if remaining == 0
                        else "In stock"
                    ),
                )

    def test_warehouse_requires_release(self):
        state, request_id = self.submit(
            self.new_state()
        )

        self.assert_rejected(
            state,
            "invalid_transition",
            lambda: wf.fulfill_request(
                state,
                request_id,
                self.context(state, Role.WAREHOUSE),
            ),
        )

    def test_duplicate_fulfillment_cannot_deduct_or_add_history_again(self):
        state, request_id = self.submit(
            self.new_state()
        )
        state = self.release(state, request_id)

        state = wf.fulfill_request(
            state,
            request_id,
            self.context(state, Role.WAREHOUSE),
        ).state

        self.assert_rejected(
            state,
            "already_fulfilled",
            lambda: wf.fulfill_request(
                state,
                request_id,
                self.context(state, Role.WAREHOUSE),
            ),
        )
        self.assertEqual(self.stock(state), 1197)

    def test_latest_stock_blocks_second_request_and_allows_explicit_re_review(self):
        state, first_id = self.submit(
            self.new_state(),
            "MED006",
            50,
            "vial",
        )
        state = self.release(state, first_id)

        state, second_id = self.submit(
            state,
            "MED006",
            50,
            "vial",
        )
        state = self.release(state, second_id)

        state = wf.fulfill_request(
            state,
            first_id,
            self.context(state, Role.WAREHOUSE),
        ).state

        self.assert_rejected(
            state,
            "insufficient_stock",
            lambda: wf.fulfill_request(
                state,
                second_id,
                self.context(state, Role.WAREHOUSE),
            ),
        )

        self.assertEqual(
            self.stock(state, "MED006"),
            30,
        )
        self.assertEqual(
            state.requests[second_id].status,
            RequestStatus.APPROVED_FOR_RELEASE,
        )
        self.assertIsNone(
            state.requests[second_id].fulfillment
        )

        state = wf.recall_release(
            state,
            second_id,
            "Latest balance is no longer sufficient",
            self.context(state, Role.PHARMACIST),
        ).state
        state = self.escalate(state, second_id)

        self.assertEqual(
            state.requests[second_id].shortfall,
            20,
        )
        self.assertEqual(
            self.stock(state, "MED006"),
            30,
        )

    def test_invalid_stock_blocks_fulfillment(self):
        state, request_id = self.submit(
            self.new_state()
        )
        state = self.release(state, request_id)

        for value in (
            None,
            -1,
            "bad",
            True,
            float("inf"),
            float("nan"),
        ):
            with self.subTest(stock=value):
                inventory = state.inventory.astype(
                    object
                )
                inventory.loc[
                    inventory["medication_id"].eq(
                        "MED001"
                    ),
                    "current_stock",
                ] = value

                invalid = replace(
                    state,
                    inventory=inventory,
                )

                self.assert_rejected(
                    invalid,
                    "invalid_stock",
                    lambda: wf.fulfill_request(
                        invalid,
                        request_id,
                        self.context(
                            invalid,
                            Role.WAREHOUSE,
                        ),
                    ),
                )

    def test_changed_or_missing_unit_blocks_fulfillment(self):
        state, request_id = self.submit(
            self.new_state()
        )
        state = self.release(state, request_id)

        for value in (None, "", "vial"):
            with self.subTest(unit=value):
                inventory = state.inventory.astype(
                    object
                )
                inventory.loc[
                    inventory["medication_id"].eq(
                        "MED001"
                    ),
                    "stock_unit",
                ] = value

                invalid = replace(
                    state,
                    inventory=inventory,
                )

                self.assert_rejected(
                    invalid,
                    "invalid_unit",
                    lambda: wf.fulfill_request(
                        invalid,
                        request_id,
                        self.context(
                            invalid,
                            Role.WAREHOUSE,
                        ),
                    ),
                )

    def test_original_dataset_missing_rop_does_not_block_fulfillment(self):
        state, request_id = self.submit(
            self.new_state("sample_medications.csv")
        )
        state = self.release(state, request_id)

        state = wf.fulfill_request(
            state,
            request_id,
            self.context(state, Role.WAREHOUSE),
        ).state

        self.assertEqual(self.stock(state), 1197)

        review = build_replenishment_context(
            state.inventory
        ).set_index("medication_id").loc[
            "MED001",
            "ordering_review",
        ]

        self.assertEqual(
            review,
            "N/A — reorder point unavailable",
        )

    def test_wrong_roles_are_rejected(self):
        state, request_id = self.submit(
            self.new_state()
        )

        self.assert_rejected(
            state,
            "wrong_role",
            lambda: wf.start_review(
                state,
                request_id,
                self.context(state, Role.WAREHOUSE),
            ),
        )

        state = self.release(state, request_id)

        self.assert_rejected(
            state,
            "wrong_role",
            lambda: wf.fulfill_request(
                state,
                request_id,
                self.context(state, Role.CLINICAL),
            ),
        )

    def test_required_decision_reasons(self):
        state, request_id = self.submit(
            self.new_state()
        )
        state = self.review(state, request_id)

        for operation in (
            wf.return_request,
            wf.authorize_release,
            wf.escalate_shortage,
        ):
            with self.subTest(
                action=operation.__name__
            ):
                self.assert_rejected(
                    state,
                    "reason_required",
                    lambda: operation(
                        state,
                        request_id,
                        " ",
                        self.context(
                            state,
                            Role.PHARMACIST,
                        ),
                    ),
                )

    def test_invalid_duplicate_transition_is_rejected(self):
        state, request_id = self.submit(
            self.new_state()
        )
        state = self.review(state, request_id)

        self.assert_rejected(
            state,
            "invalid_transition",
            lambda: wf.start_review(
                state,
                request_id,
                self.context(state, Role.PHARMACIST),
            ),
        )

    def test_supply_feedback_is_linked_and_does_not_change_inventory(self):
        state, request_id = self.submit(
            self.new_state(),
            "MED003",
            3,
        )
        state = self.escalate(state, request_id)

        inventory = state.inventory.copy(deep=True)
        escalation_time = (
            state.requests[request_id].updated_time
        )

        state = self.feedback(state, request_id)
        request = state.requests[request_id]

        self.assertEqual(
            request.status,
            RequestStatus.AWAITING_SUPPLY,
        )
        self.assertEqual(
            request.supply_feedback.supplier,
            "Demo Supplier A",
        )
        self.assertEqual(
            request.supply_feedback.lead_time_days,
            7,
        )

        expected = (
            datetime.fromisoformat(
                escalation_time
            ).date()
            + timedelta(days=7)
        ).isoformat()

        self.assertEqual(
            request.supply_feedback.expected_delivery,
            expected,
        )
        self.assertAlmostEqual(
            request.supply_feedback.lead_time_demand,
            500 / 30 * 7,
        )
        self.assertIsNone(request.fulfillment)

        pd.testing.assert_frame_equal(
            state.inventory,
            inventory,
        )

        state = self.feedback(
            state,
            request_id,
            "Second synthetic review update",
        )

        self.assertEqual(
            state.requests[
                request_id
            ].supply_feedback.expected_delivery,
            expected,
        )
        pd.testing.assert_frame_equal(
            state.inventory,
            inventory,
        )

    def test_supply_feedback_before_escalation_is_rejected(self):
        state, request_id = self.submit(
            self.new_state()
        )

        self.assert_rejected(
            state,
            "invalid_transition",
            lambda: self.feedback(
                state,
                request_id,
            ),
        )

    def test_duplicate_supply_feedback_does_not_add_an_event(self):
        state, request_id = self.submit(
            self.new_state(),
            "MED003",
            3,
        )
        state = self.feedback(
            self.escalate(state, request_id),
            request_id,
        )

        self.assert_rejected(
            state,
            "duplicate_action",
            lambda: self.feedback(
                state,
                request_id,
            ),
        )

    def test_original_dataset_supply_context_remains_unavailable(self):
        state, request_id = self.submit(
            self.new_state("sample_medications.csv"),
            "MED003",
            3,
        )
        state = self.feedback(
            self.escalate(state, request_id),
            request_id,
        )
        response = (
            state.requests[request_id].supply_feedback
        )

        self.assertIsNone(response.lead_time_days)
        self.assertIsNone(response.expected_delivery)
        self.assertIsNone(response.lead_time_demand)
        self.assertEqual(
            self.stock(state, "MED003"),
            0,
        )

    def test_explicit_expected_date_remains_illustrative_and_cannot_receive_stock(self):
        state, request_id = self.submit(
            self.new_state(),
            "MED003",
            3,
        )
        state = self.escalate(state, request_id)

        state = wf.update_supply_feedback(
            state,
            request_id,
            SupplyFeedbackInput(
                "Illustrative date only",
                date(2026, 11, 20),
            ),
            self.context(state, Role.PROCUREMENT),
        ).state

        self.assertEqual(
            state.requests[
                request_id
            ].supply_feedback.expected_delivery,
            "2026-11-20",
        )
        self.assertEqual(
            self.stock(state, "MED003"),
            0,
        )
        self.assertIsNone(
            state.requests[request_id].fulfillment
        )

    def test_closed_without_supply_is_distinct_from_fulfillment(self):
        state, request_id = self.submit(
            self.new_state(),
            "MED003",
            3,
        )
        state = self.feedback(
            self.escalate(state, request_id),
            request_id,
        )

        self.assert_rejected(
            state,
            "reason_required",
            lambda: wf.close_without_supply(
                state,
                request_id,
                "",
                self.context(state, Role.PHARMACIST),
            ),
        )

        state = wf.close_without_supply(
            state,
            request_id,
            "Demo ends without receiving stock",
            self.context(state, Role.PHARMACIST),
        ).state

        self.assertEqual(
            state.requests[request_id].status,
            RequestStatus.CLOSED,
        )
        self.assertEqual(
            state.requests[request_id].outcome,
            RequestOutcome.CLOSED_WITHOUT_SUPPLY,
        )
        self.assertIsNone(
            state.requests[request_id].fulfillment
        )
        self.assertEqual(
            self.stock(state, "MED003"),
            0,
        )

    def test_reset_restores_stock_and_clears_entire_workflow(self):
        state, request_id = self.submit(
            self.new_state()
        )
        state = self.release(state, request_id)
        state = wf.fulfill_request(
            state,
            request_id,
            self.context(state, Role.WAREHOUSE),
        ).state

        old_run = state.run_id

        reset = wf.reset_demo(
            state,
            now=self.context(
                state,
                Role.CLINICAL,
            ).now,
        )

        self.assertNotEqual(reset.run_id, old_run)
        self.assertEqual(reset.requests, {})
        self.assertEqual(
            reset.next_request_number,
            1,
        )
        self.assertEqual(reset.revision, 0)

        pd.testing.assert_frame_equal(
            reset.inventory,
            state.initial_inventory,
        )
        self.assertEqual(self.stock(reset), 1200)
        self.assertEqual(self.stock(state), 1197)

        new_state, new_id = self.submit(reset)
        self.assertEqual(new_id, request_id)

        stale = replace(
            self.context(
                new_state,
                Role.PHARMACIST,
            ),
            expected_run_id=old_run,
        )

        self.assert_rejected(
            new_state,
            "wrong_run",
            lambda: wf.start_review(
                new_state,
                new_id,
                stale,
            ),
        )

    def test_stale_revision_cannot_apply_new_mutation(self):
        state, request_id = self.submit(
            self.new_state()
        )
        context = replace(
            self.context(state, Role.PHARMACIST),
            expected_revision=state.revision - 1,
        )

        self.assert_rejected(
            state,
            "stale_state",
            lambda: wf.start_review(
                state,
                request_id,
                context,
            ),
        )

    def test_naive_or_backdated_action_times_are_rejected(self):
        state, request_id = self.submit(
            self.new_state()
        )

        for now in (
            datetime(2026, 11, 3),
            self.NOW - timedelta(days=1),
        ):
            with self.subTest(now=now):
                context = replace(
                    self.context(
                        state,
                        Role.PHARMACIST,
                    ),
                    now=now,
                )

                self.assert_rejected(
                    state,
                    "invalid_time",
                    lambda: wf.start_review(
                        state,
                        request_id,
                        context,
                    ),
                )

    def test_failure_building_fulfillment_cannot_leave_partial_deduction(self):
        state, request_id = self.submit(
            self.new_state()
        )
        state = self.release(state, request_id)
        before = deepcopy(state)

        with patch(
            "src.services.workflow.FulfillmentRecord",
            side_effect=RuntimeError(
                "Injected candidate-build failure"
            ),
        ):
            with self.assertRaises(RuntimeError):
                wf.fulfill_request(
                    state,
                    request_id,
                    self.context(
                        state,
                        Role.WAREHOUSE,
                    ),
                )

        self.assert_state_equal(state, before)

    def test_fulfillment_preserves_other_fields_and_source_files(self):
        state = self.new_state()
        path = Path(state.dataset_path)
        original_bytes = path.read_bytes()
        original = state.inventory.copy(deep=True)

        state, request_id = self.submit(state)
        state = self.release(state, request_id)
        state = wf.fulfill_request(
            state,
            request_id,
            self.context(state, Role.WAREHOUSE),
        ).state

        unchanged_columns = [
            column
            for column in original.columns
            if column not in (
                "current_stock",
                "status",
            )
        ]

        pd.testing.assert_frame_equal(
            state.inventory[unchanged_columns],
            original[unchanged_columns],
        )
        pd.testing.assert_frame_equal(
            state.initial_inventory,
            original,
        )
        self.assertEqual(
            path.read_bytes(),
            original_bytes,
        )


if __name__ == "__main__":
    unittest.main()