"""Pure service checks for informational substitute-review records."""

from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import unittest
from unittest.mock import patch

import pandas as pd
from pandas.testing import assert_frame_equal

from src.config import PROJECT_ROOT
from src.data.loader import load_medications
from src.data.substitute_loader import load_substitute_relationships
from src.services import substitute_reviews as reviews
from src.services import workflow as wf
from src.services.workflow_models import (
    RequestStatus,
    Role,
    SubstituteDecision,
    SubstituteReviewInput,
    SubmitRequestInput,
    WorkflowError,
)


class SubstituteReviewTests(unittest.TestCase):
    def setUp(self):
        self.clock = datetime(
            2026, 11, 18, 15, 0, tzinfo=timezone.utc
        )
        self.make_state()

    def tick(self):
        self.clock += timedelta(seconds=1)
        return self.clock

    def make_state(self, filename="sample_medications_extended.csv"):
        self.path = PROJECT_ROOT / "data" / filename
        self.source = self.path.read_bytes()
        medications = load_medications(self.path)

        fixture = load_substitute_relationships(
            medication_ids=medications["medication_id"],
        )

        self.state = wf.initialize_demo(
            medications,
            dataset_path=str(self.path),
            dataset_fingerprint=sha256(self.source).hexdigest(),
            now=self.tick(),
            substitute_fixture=fixture,
        )

    def context(self, role=Role.PHARMACIST):
        return wf.make_context(
            self.state,
            role,
            now=self.tick(),
        )

    def action(self, name, *args, role=Role.PHARMACIST):
        result = getattr(wf, name)(
            self.state,
            *args,
            context=self.context(role),
        )
        self.state = result.state
        return result

    def submit(
        self,
        medication_id="MED003",
        quantity=5,
        preference=True,
        start_review=True,
    ):
        request_id = self.action(
            "submit_request",
            SubmitRequestInput(
                medication_id=medication_id,
                quantity=quantity,
                unit=(
                    "vial"
                    if medication_id == "MED006"
                    else "tablet"
                ),
                requesting_location="Demo Ward",
                reason="Illustrative review test",
                substitution_allowed=preference,
            ),
            f"submission-{self.state.next_request_number}",
            role=Role.CLINICAL,
        ).request_id

        if start_review:
            self.action("start_review", request_id)

        return request_id

    def inputs(
        self,
        decision=SubstituteDecision.KEPT_FOR_CONSIDERATION,
        reason="Clinical suitability is not assessed in this demo",
        relationship_id="SR-001",
    ):
        return SubstituteReviewInput(
            relationship_id=relationship_id,
            decision=decision,
            reason=reason,
        )

    def record(self, request_id, inputs=None):
        result = reviews.record_substitute_review(
            self.state,
            request_id,
            self.inputs() if inputs is None else inputs,
            self.context(),
        )
        self.state = result.state
        return result

    def assert_operational_data_unchanged(self, before):
        assert_frame_equal(self.state.inventory, before.inventory)
        assert_frame_equal(
            self.state.initial_inventory,
            before.initial_inventory,
        )

        for field in (
            "run_id",
            "dataset_path",
            "dataset_fingerprint",
            "requests",
            "orders",
            "receipts",
            "next_request_number",
            "next_order_number",
            "next_receipt_number",
            "substitute_fixture",
        ):
            self.assertEqual(
                getattr(self.state, field),
                getattr(before, field),
                field,
            )

    def assert_no_change(self, before):
        self.assert_operational_data_unchanged(before)

        for field in (
            "revision",
            "substitute_reviews",
            "next_substitute_review_number",
        ):
            self.assertEqual(
                getattr(self.state, field),
                getattr(before, field),
                field,
            )

    def test_success_appends_snapshot_without_operational_changes(self):
        request_id = self.submit()
        before = deepcopy(self.state)

        result = self.record(request_id)
        record = self.state.substitute_reviews[
            result.substitute_review_id
        ]

        self.assertEqual(
            result.substitute_review_id,
            "SUB-REV-0001",
        )
        self.assertEqual(record.run_id, self.state.run_id)
        self.assertEqual(record.request_id, request_id)
        self.assertEqual(record.source_medication_id, "MED003")
        self.assertEqual(record.candidate_medication_id, "MED001")
        self.assertEqual(record.relationship_id, "SR-001")
        self.assertEqual(record.recorded_by, "Demo user")
        self.assertEqual(record.recorded_by_role, Role.PHARMACIST)
        self.assertEqual(record.fixture_version, "v1")
        self.assertEqual(
            record.fixture_fingerprint,
            self.state.substitute_fixture.source_fingerprint,
        )
        self.assertEqual(
            record.inventory_at_review.recorded_stock,
            1200,
        )
        self.assertEqual(
            record.inventory_at_review.stock_unit,
            "tablet",
        )
        self.assertEqual(
            record.inventory_at_review.indicator,
            "Green",
        )
        self.assertEqual(self.state.revision, before.revision + 1)
        self.assertEqual(self.state.next_substitute_review_number, 2)
        self.assert_operational_data_unchanged(before)
        self.assertEqual(self.path.read_bytes(), self.source)

        snapshot_fields = set(
            asdict(record.inventory_at_review)
        )
        self.assertEqual(
            snapshot_fields,
            {
                "recorded_stock",
                "stock_unit",
                "indicator",
                "indicator_text",
            },
        )

    def test_all_three_decisions_are_informational_and_append_only(self):
        request_id = self.submit()
        before = deepcopy(self.state)

        for decision in SubstituteDecision:
            self.record(
                request_id,
                self.inputs(
                    decision=decision,
                    reason=f"Demo note for {decision}",
                ),
            )

        self.assertEqual(len(self.state.substitute_reviews), 3)
        self.assertEqual(self.state.revision, before.revision + 3)
        self.assert_operational_data_unchanged(before)

    def test_blank_reasons_and_unknown_decisions_are_rejected(self):
        request_id = self.submit()
        before = deepcopy(self.state)

        invalid_inputs = (
            self.inputs(reason=""),
            self.inputs(reason="   "),
            self.inputs(decision="approved_substitute"),
            None,
        )

        for inputs in invalid_inputs:
            with self.subTest(inputs=inputs):
                with self.assertRaises(WorkflowError):
                    reviews.record_substitute_review(
                        self.state,
                        request_id,
                        inputs,
                        self.context(),
                    )
                self.assert_no_change(before)

    def test_reason_is_trimmed_before_duplicate_comparison(self):
        request_id = self.submit()

        self.record(
            request_id,
            self.inputs(reason="  Needs human review  "),
        )
        record = self.state.substitute_reviews["SUB-REV-0001"]
        self.assertEqual(record.reason, "Needs human review")

        before = deepcopy(self.state)

        with self.assertRaises(WorkflowError) as caught:
            self.record(
                request_id,
                self.inputs(reason="Needs human review"),
            )

        self.assertEqual(caught.exception.code, "duplicate_action")
        self.assert_no_change(before)

    def test_stale_retry_and_fresh_duplicate_are_distinct(self):
        request_id = self.submit()
        inputs = self.inputs()
        old_context = self.context()

        result = reviews.record_substitute_review(
            self.state,
            request_id,
            inputs,
            old_context,
        )
        self.state = result.state
        before = deepcopy(self.state)

        with self.assertRaises(WorkflowError) as caught:
            reviews.record_substitute_review(
                self.state,
                request_id,
                inputs,
                old_context,
            )
        self.assertEqual(caught.exception.code, "stale_state")
        self.assert_no_change(before)

        with self.assertRaises(WorkflowError) as caught:
            self.record(request_id, inputs)

        self.assertEqual(caught.exception.code, "duplicate_action")
        self.assert_no_change(before)

    def test_changed_decision_or_reason_appends_and_retains_old_records(self):
        request_id = self.submit()

        self.record(request_id, self.inputs(reason="First note"))
        first = deepcopy(
            self.state.substitute_reviews["SUB-REV-0001"]
        )

        self.record(request_id, self.inputs(reason="Second note"))
        self.record(
            request_id,
            self.inputs(
                decision=SubstituteDecision.NEEDS_MORE_REVIEW,
                reason="Second note",
            ),
        )
        # Returning to an older decision is allowed when it differs
        # from the latest decision/reason.
        self.record(request_id, self.inputs(reason="First note"))

        self.assertEqual(len(self.state.substitute_reviews), 4)
        self.assertEqual(
            self.state.substitute_reviews["SUB-REV-0001"],
            first,
        )

    def test_unchecked_preference_rejects_every_decision(self):
        request_id = self.submit(preference=False)
        before = deepcopy(self.state)

        for decision in SubstituteDecision:
            with self.subTest(decision=decision):
                with self.assertRaises(WorkflowError) as caught:
                    self.record(
                        request_id,
                        self.inputs(decision=decision),
                    )

                self.assertEqual(
                    caught.exception.code,
                    "substitution_not_allowed",
                )
                self.assertEqual(
                    str(caught.exception),
                    reviews.PREFERENCE_DISABLED_MESSAGE,
                )
                self.assert_no_change(before)

    def test_review_requires_under_review_status(self):
        request_id = self.submit(start_review=False)
        original = self.state

        for status in (
            RequestStatus.RECEIVED,
            RequestStatus.ESCALATED,
            RequestStatus.AWAITING_SUPPLY,
            RequestStatus.ON_ORDER,
            RequestStatus.SUPPLY_RECEIVED,
            RequestStatus.APPROVED_FOR_RELEASE,
            RequestStatus.RETURNED,
            RequestStatus.CLOSED,
        ):
            with self.subTest(status=status):
                requests = dict(original.requests)
                requests[request_id] = replace(
                    requests[request_id],
                    status=status,
                )
                self.state = replace(
                    original,
                    requests=requests,
                )
                before = deepcopy(self.state)

                with self.assertRaises(WorkflowError) as caught:
                    self.record(request_id)

                self.assertEqual(
                    caught.exception.code,
                    "invalid_transition",
                )
                self.assert_no_change(before)

    def test_wrong_roles_runs_and_times_are_rejected(self):
        request_id = self.submit()
        before = deepcopy(self.state)
        good = self.context()

        contexts = [
            replace(good, acting_role=role)
            for role in Role
            if role != Role.PHARMACIST
        ]
        contexts.extend(
            [
                replace(good, expected_run_id="old-run"),
                replace(
                    good,
                    now=datetime(2026, 11, 18, 15, 0),
                ),
                replace(
                    good,
                    now=datetime(
                        2020, 1, 1, tzinfo=timezone.utc
                    ),
                ),
            ]
        )

        for context in contexts:
            with self.subTest(context=context):
                with self.assertRaises(WorkflowError):
                    reviews.record_substitute_review(
                        self.state,
                        request_id,
                        self.inputs(),
                        context,
                    )
                self.assert_no_change(before)

    def test_missing_unknown_and_wrong_source_relationships_are_rejected(self):
        request_id = self.submit()
        before = deepcopy(self.state)

        for relationship_id in ("", "SR-999", "SR-002"):
            with self.subTest(relationship_id=relationship_id):
                with self.assertRaises(WorkflowError):
                    self.record(
                        request_id,
                        self.inputs(
                            relationship_id=relationship_id
                        ),
                    )
                self.assert_no_change(before)

        self.state = replace(
            self.state,
            substitute_fixture=None,
        )
        before = deepcopy(self.state)

        with self.assertRaises(WorkflowError) as caught:
            self.record(request_id)

        self.assertEqual(
            caught.exception.code,
            "substitute_information_unavailable",
        )
        self.assert_no_change(before)

    def test_source_stock_covering_request_blocks_decisions(self):
        request_id = self.submit(
            medication_id="MED001",
            quantity=5,
        )
        before = deepcopy(self.state)

        with self.assertRaises(WorkflowError) as caught:
            self.record(
                request_id,
                self.inputs(
                    decision=SubstituteDecision.DO_NOT_PURSUE,
                    relationship_id="SR-002",
                ),
            )

        self.assertEqual(
            caught.exception.code,
            "alternatives_not_needed",
        )
        self.assert_no_change(before)

    def test_green_source_with_oversized_request_can_be_reviewed(self):
        request_id = self.submit(
            medication_id="MED001",
            quantity=1500,
        )

        self.record(
            request_id,
            self.inputs(
                decision=SubstituteDecision.DO_NOT_PURSUE,
                relationship_id="SR-002",
            ),
        )

        record = self.state.substitute_reviews["SUB-REV-0001"]
        self.assertEqual(record.source_medication_id, "MED001")
        self.assertEqual(
            record.inventory_at_review.indicator,
            "Red",
        )
        self.assertEqual(
            self.state.requests[request_id].quantity,
            1500,
        )

    def test_zero_candidate_blocks_keep_but_allows_other_notes(self):
        request_id = self.submit(
            medication_id="MED001",
            quantity=1500,
        )
        before = deepcopy(self.state)

        with self.assertRaises(WorkflowError) as caught:
            self.record(
                request_id,
                self.inputs(relationship_id="SR-002"),
            )

        self.assertEqual(
            caught.exception.code,
            "candidate_out_of_stock",
        )
        self.assert_no_change(before)

        for decision in (
            SubstituteDecision.DO_NOT_PURSUE,
            SubstituteDecision.NEEDS_MORE_REVIEW,
        ):
            self.record(
                request_id,
                self.inputs(
                    decision=decision,
                    relationship_id="SR-002",
                ),
            )

        self.assertEqual(len(self.state.substitute_reviews), 2)
        self.assert_operational_data_unchanged(before)

    def test_candidate_quantity_is_not_compared_with_source_request(self):
        # Candidate stock is 1,200, below this source request's 1,500.
        # Keep records consideration only; it does not allocate a dose.
        request_id = self.submit(quantity=1500)
        self.record(request_id)

        record = self.state.substitute_reviews["SUB-REV-0001"]
        self.assertEqual(
            record.inventory_at_review.recorded_stock,
            1200,
        )
        self.assertEqual(
            self.state.requests[request_id].quantity,
            1500,
        )

    def test_candidate_unit_difference_does_not_imply_conversion(self):
        request_id = self.submit()
        inventory = self.state.inventory.copy(deep=True)
        mask = inventory["medication_id"].eq("MED001")
        inventory.loc[mask, "stock_unit"] = "capsule"
        self.state = replace(self.state, inventory=inventory)
        before = deepcopy(self.state)

        self.record(request_id)

        record = self.state.substitute_reviews["SUB-REV-0001"]
        self.assertEqual(
            record.inventory_at_review.stock_unit,
            "capsule",
        )
        self.assertEqual(
            self.state.requests[request_id].unit,
            "tablet",
        )
        self.assert_operational_data_unchanged(before)

    def test_missing_candidate_unit_is_neutral_without_inventing_a_unit(self):
        request_id = self.submit()
        inventory = self.state.inventory.copy(deep=True)
        mask = inventory["medication_id"].eq("MED001")
        inventory.loc[mask, "stock_unit"] = pd.NA
        self.state = replace(self.state, inventory=inventory)

        self.record(request_id)

        snapshot = self.state.substitute_reviews[
            "SUB-REV-0001"
        ].inventory_at_review

        self.assertIsNone(snapshot.stock_unit)
        self.assertEqual(snapshot.indicator, "Neutral")
        self.assertIn("stock unit unavailable", snapshot.indicator_text)

    def test_original_schema_supports_neutral_candidate_review(self):
        self.make_state("sample_medications.csv")
        request_id = self.submit()
        self.record(request_id)

        snapshot = self.state.substitute_reviews[
            "SUB-REV-0001"
        ].inventory_at_review

        self.assertEqual(snapshot.indicator, "Neutral")
        self.assertIn(
            "reorder point unavailable",
            snapshot.indicator_text,
        )

    def test_invalid_candidate_stock_and_changed_source_unit_are_rejected(self):
        request_id = self.submit()
        valid_state = self.state

        inventory = valid_state.inventory.copy(deep=True)
        inventory["current_stock"] = (
            inventory["current_stock"].astype("object")
        )
        mask = inventory["medication_id"].eq("MED001")
        inventory.loc[mask, "current_stock"] = -1
        self.state = replace(valid_state, inventory=inventory)
        before = deepcopy(self.state)

        with self.assertRaises(WorkflowError):
            self.record(request_id)
        self.assert_no_change(before)

        inventory = valid_state.inventory.copy(deep=True)
        mask = inventory["medication_id"].eq("MED003")
        inventory.loc[mask, "stock_unit"] = "capsule"
        self.state = replace(valid_state, inventory=inventory)
        before = deepcopy(self.state)

        with self.assertRaises(WorkflowError):
            self.record(request_id)
        self.assert_no_change(before)

    def test_snapshot_survives_later_valid_fulfillment(self):
        request_id = self.submit()
        self.record(request_id)
        first = deepcopy(
            self.state.substitute_reviews["SUB-REV-0001"]
        )

        other_request = self.submit(
            medication_id="MED001",
            quantity=400,
        )
        self.action(
            "authorize_release",
            other_request,
            "Separate request with sufficient recorded stock",
        )
        self.action(
            "fulfill_request",
            other_request,
            role=Role.WAREHOUSE,
        )

        self.record(
            request_id,
            self.inputs(
                decision=SubstituteDecision.NEEDS_MORE_REVIEW,
                reason="Review after candidate inventory changed",
            ),
        )

        self.assertEqual(
            self.state.substitute_reviews["SUB-REV-0001"],
            first,
        )
        self.assertEqual(
            first.inventory_at_review.recorded_stock,
            1200,
        )
        latest = self.state.substitute_reviews["SUB-REV-0002"]
        self.assertEqual(
            latest.inventory_at_review.recorded_stock,
            800,
        )
        self.assertEqual(
            latest.inventory_at_review.indicator,
            "Yellow",
        )
        self.assertEqual(
            self.state.requests[request_id].status,
            RequestStatus.UNDER_REVIEW,
        )

    def test_review_cannot_be_backdated_before_a_prior_review(self):
        request_id = self.submit()
        self.record(request_id)

        first = self.state.substitute_reviews["SUB-REV-0001"]
        context = self.context()
        context = replace(
            context,
            now=(
                datetime.fromisoformat(first.recorded_time)
                - timedelta(seconds=1)
            ),
        )
        before = deepcopy(self.state)

        with self.assertRaises(WorkflowError) as caught:
            reviews.record_substitute_review(
                self.state,
                request_id,
                self.inputs(reason="Different note"),
                context,
            )

        self.assertEqual(caught.exception.code, "invalid_time")
        self.assert_no_change(before)

    def test_reset_clears_reviews_and_rejects_old_run_actions(self):
        request_id = self.submit()
        self.record(request_id)
        old_context = self.context()
        old_fixture = self.state.substitute_fixture
        old_run = self.state.run_id

        self.state = wf.reset_demo(
            self.state,
            now=self.tick(),
        )

        self.assertNotEqual(self.state.run_id, old_run)
        self.assertEqual(self.state.substitute_reviews, {})
        self.assertEqual(
            self.state.next_substitute_review_number,
            1,
        )
        self.assertEqual(
            self.state.substitute_fixture,
            old_fixture,
        )
        assert_frame_equal(
            self.state.inventory,
            self.state.initial_inventory,
        )

        with self.assertRaises(WorkflowError) as caught:
            reviews.record_substitute_review(
                self.state,
                request_id,
                self.inputs(),
                old_context,
            )

        self.assertEqual(caught.exception.code, "wrong_run")

    def test_result_construction_failure_cannot_partially_append(self):
        request_id = self.submit()
        before = deepcopy(self.state)

        with patch(
            "src.services.substitute_reviews.WorkflowResult",
            side_effect=RuntimeError(
                "Injected result construction failure"
            ),
        ):
            with self.assertRaises(RuntimeError):
                self.record(request_id)

        self.assert_no_change(before)


if __name__ == "__main__":
    unittest.main()