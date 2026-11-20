"""Shared-session integration and substitute-information boundaries."""

from copy import deepcopy
import csv
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pandas.testing import assert_frame_equal

from src.config import PROJECT_ROOT
from src.data.substitute_loader import load_substitute_relationships
from src.services.substitute_queries import ALTERNATIVES_COLUMN
from src.services.workflow_models import (
    CreateOrderInput,
    ReceiptInput,
    Role,
    SubstituteDecision,
    SubstituteReviewInput,
    SupplyFeedbackInput,
    SubmitRequestInput,
    WorkflowError,
)
from src.ui import session


def nested_keys(value):
    keys = set()

    if isinstance(value, dict):
        keys.update(value)
        for child in value.values():
            keys.update(nested_keys(child))
    elif isinstance(value, (tuple, list)):
        for child in value:
            keys.update(nested_keys(child))

    return keys


class SubstituteSessionTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.fixture_path = (
            Path(self.directory.name) / "relationships.csv"
        )
        self.fixture_path.write_bytes(
            (
                PROJECT_ROOT
                / "data"
                / "sample_substitute_relationships.csv"
            ).read_bytes()
        )
        self.clock = datetime(
            2026, 11, 18, 16, 0, tzinfo=timezone.utc
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
        self.store = {}
        self.ensure()

    def ensure(self):
        return session.ensure_demo_session(
            self.path,
            relationship_path=self.fixture_path,
            state_store=self.store,
            now=self.tick(),
        )

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
        result = self.action(
            "submit_request",
            SubmitRequestInput(
                medication_id=medication_id,
                quantity=quantity,
                unit="tablet",
                requesting_location="Demo Ward",
                reason="Substitute session test",
                substitution_allowed=preference,
            ),
            f"submission-{self.info().request_count + 1}",
            role=Role.CLINICAL,
        )
        self.action("start_review", result.request_id)
        return result.request_id

    def record(
        self,
        request_id,
        decision=SubstituteDecision.KEPT_FOR_CONSIDERATION,
        reason="Clinical suitability is not assessed",
    ):
        return self.action(
            "record_substitute_review",
            request_id,
            SubstituteReviewInput(
                relationship_id="SR-001",
                decision=decision,
                reason=reason,
            ),
        )

    def context(self, request_id):
        return session.read_request_alternatives(
            request_id,
            Role.PHARMACIST,
            state_store=self.store,
        )

    def history(self, request_id=None):
        return session.read_substitute_reviews(
            Role.PHARMACIST,
            request_id=request_id,
            state_store=self.store,
        )

    def fulfill(self, request_id):
        self.action(
            "authorize_release",
            request_id,
            "Explicit synthetic release",
        )
        self.action(
            "fulfill_request",
            request_id,
            role=Role.WAREHOUSE,
        )

    def make_order(self, request_id, quantity):
        self.action(
            "escalate_shortage",
            request_id,
            "Recorded stock cannot cover the request",
        )
        self.action(
            "update_supply_feedback",
            request_id,
            SupplyFeedbackInput("Synthetic supply review"),
            role=Role.PROCUREMENT,
        )
        return self.action(
            "confirm_order",
            request_id,
            CreateOrderInput(quantity, "tablet"),
            f"order-{request_id}",
            role=Role.PROCUREMENT,
        ).order_id

    def receive(self, order_id, quantity, key):
        return self.action(
            "confirm_receipt",
            order_id,
            ReceiptInput(quantity, "tablet"),
            key,
            role=Role.WAREHOUSE,
        )

    def assert_unchanged(self, before):
        current = self.store[session.STATE_KEY]
        assert_frame_equal(current.inventory, before.inventory)
        assert_frame_equal(
            current.initial_inventory,
            before.initial_inventory,
        )

        for field in (
            "run_id",
            "revision",
            "requests",
            "orders",
            "receipts",
            "substitute_fixture",
            "substitute_reviews",
            "next_request_number",
            "next_order_number",
            "next_receipt_number",
            "next_substitute_review_number",
        ):
            self.assertEqual(
                getattr(current, field),
                getattr(before, field),
                field,
            )

    def test_initialization_loads_fixture_once_on_normal_reruns(self):
        self.store = {}

        with patch(
            "src.ui.session.load_substitute_relationships",
            wraps=load_substitute_relationships,
        ) as loader:
            first = self.ensure()
            root = self.store[session.STATE_KEY]
            second = self.ensure()
            self.ensure()

        self.assertEqual(loader.call_count, 1)
        self.assertEqual(first.run_id, second.run_id)
        self.assertIs(self.store[session.STATE_KEY], root)
        self.assertEqual(
            session.read_substitute_fixture_info(
                state_store=self.store
            )["relationship_count"],
            2,
        )

    def test_fixture_changes_wait_until_deliberate_reset(self):
        request_id = self.submit()
        self.record(request_id)
        previous = session.read_substitute_fixture_info(
            state_store=self.store
        )
        old_run = self.info().run_id

        # Keep only the reverse relationship in the on-disk fixture.
        with self.fixture_path.open(
            encoding="utf-8",
            newline="",
        ) as source:
            reader = csv.DictReader(source)
            columns = reader.fieldnames
            rows = list(reader)

        content = StringIO(newline="")
        writer = csv.DictWriter(content, fieldnames=columns)
        writer.writeheader()
        writer.writerow(rows[1])
        self.fixture_path.write_text(
            content.getvalue(),
            encoding="utf-8",
        )

        self.ensure()

        frozen = session.read_substitute_fixture_info(
            state_store=self.store
        )
        self.assertEqual(
            frozen["source_fingerprint"],
            previous["source_fingerprint"],
        )
        self.assertEqual(frozen["relationship_count"], 2)
        self.assertEqual(len(self.history()), 1)
        self.assertEqual(
            len(self.context(request_id)["candidates"]),
            1,
        )

        session.reset_demo_session(
            clinical_tab_label="Clinical",
            state_store=self.store,
            now=self.tick(),
        )

        current = session.read_substitute_fixture_info(
            state_store=self.store
        )
        self.assertNotEqual(self.info().run_id, old_run)
        self.assertNotEqual(
            current["source_fingerprint"],
            previous["source_fingerprint"],
        )
        self.assertEqual(current["relationship_count"], 1)
        self.assertEqual(self.history(), [])
        self.assertEqual(
            self.store[session.STATE_KEY].next_substitute_review_number,
            1,
        )

    def test_missing_fixture_does_not_block_existing_workflow(self):
        self.fixture_path.unlink()
        self.start_session()

        info = session.read_substitute_fixture_info(
            state_store=self.store
        )
        self.assertFalse(info["available"])

        table = session.read_inventory_alternatives(
            Role.CLINICAL,
            state_store=self.store,
        )
        self.assertTrue(
            table[ALTERNATIVES_COLUMN].eq(
                "Substitute information unavailable"
            ).all()
        )

        request_id = self.submit(
            medication_id="MED001",
            quantity=5,
        )
        self.fulfill(request_id)

        stock = session.read_inventory(
            Role.CLINICAL,
            state_store=self.store,
        ).set_index("medication_id").loc[
            "MED001", "current_stock"
        ]
        self.assertEqual(stock, 1195)

    def test_both_schemas_preserve_inventory_shapes_and_display_rules(self):
        for filename, width in (
            ("sample_medications.csv", 10),
            ("sample_medications_extended.csv", 16),
        ):
            with self.subTest(dataset=filename):
                self.start_session(filename)

                inventory = session.read_inventory(
                    Role.PROCUREMENT,
                    state_store=self.store,
                )
                self.assertEqual(inventory.shape, (6, width))

                table = session.read_inventory_alternatives(
                    Role.PHARMACIST,
                    state_store=self.store,
                ).set_index("medication_id")

                self.assertEqual(
                    table.loc["MED001", ALTERNATIVES_COLUMN],
                    "—",
                )
                self.assertEqual(
                    table.loc["MED003", ALTERNATIVES_COLUMN],
                    "Paracetamol 500 mg",
                )

                if width == 10:
                    self.assertEqual(
                        table.loc["MED006", ALTERNATIVES_COLUMN],
                        "—",
                    )
                else:
                    self.assertEqual(
                        table.loc["MED006", ALTERNATIVES_COLUMN],
                        "No relationship recorded",
                    )

                # Detailed candidate indicators remain available
                # in the Pharmacist request-review context.
                request_id = self.submit()
                candidate = self.context(request_id)["candidates"][0]

                self.assertEqual(
                    candidate["inventory"]["indicator"],
                    "Neutral" if width == 10 else "Green",
                )

    def test_review_action_uses_canonical_session_publication(self):
        request_id = self.submit()
        before = deepcopy(self.store[session.STATE_KEY])
        result = self.record(request_id)

        self.assertEqual(
            result.substitute_review_id,
            "SUB-REV-0001",
        )
        self.assertEqual(
            self.info().revision,
            before.revision + 1,
        )
        assert_frame_equal(
            self.store[session.STATE_KEY].inventory,
            before.inventory,
        )
        self.assertEqual(
            self.store[session.STATE_KEY].requests,
            before.requests,
        )
        self.assertEqual(len(self.history(request_id)), 1)
        self.assertEqual(
            self.context(request_id)["candidates"][0][
                "decision_status"
            ],
            "Kept for consideration (demo)",
        )

    def test_query_permissions_and_pharmacist_cost_boundary(self):
        request_id = self.submit()
        self.record(request_id)

        context = self.context(request_id)
        keys = nested_keys(context) | nested_keys(self.history())

        for field in (
            "unit_cost",
            "order_value_cad",
            "inventory_value_cad",
            "recorded_inventory_value_cad",
        ):
            self.assertNotIn(field, keys)

        for role in Role:
            if role != Role.PHARMACIST:
                with self.subTest(role=role):
                    with self.assertRaises(WorkflowError):
                        session.read_substitute_reviews(
                            role,
                            state_store=self.store,
                        )
                    with self.assertRaises(WorkflowError):
                        session.read_request_alternatives(
                            request_id,
                            role,
                            state_store=self.store,
                        )

        for role in (
            Role.WAREHOUSE,
            Role.EXECUTIVE,
            Role.REPORTING,
            Role.SYSTEM,
        ):
            with self.assertRaises(WorkflowError):
                session.read_inventory_alternatives(
                    role,
                    state_store=self.store,
                )

        for role in (
            Role.CLINICAL,
            Role.PHARMACIST,
            Role.PROCUREMENT,
        ):
            table = session.read_inventory_alternatives(
                role,
                state_store=self.store,
            )
            self.assertNotIn("unit_cost", table.columns)
            self.assertNotIn("decision", table.columns)
            self.assertNotIn("reason", table.columns)

    def test_readers_are_detached_and_do_not_advance_revision(self):
        request_id = self.submit()
        self.record(request_id)
        before = deepcopy(self.store[session.STATE_KEY])

        metadata = session.read_substitute_fixture_info(
            state_store=self.store
        )
        metadata["issues"].append("Caller change")

        context = self.context(request_id)
        context["candidates"][0]["inventory"]["recorded_stock"] = -1

        history = self.history()
        history[0]["reason"] = "Caller change"

        table = session.read_inventory_alternatives(
            Role.CLINICAL,
            state_store=self.store,
        )
        table.loc[0, ALTERNATIVES_COLUMN] = "Caller change"

        self.assert_unchanged(before)

    def test_preference_source_coverage_and_red_candidate_eligibility(self):
        request_id = self.submit(preference=False)
        context = self.context(request_id)

        self.assertEqual(len(context["candidates"]), 1)
        self.assertFalse(context["decisions_enabled"])
        self.assertFalse(context["candidates"][0]["can_keep"])
        self.assertFalse(
            context["candidates"][0]["can_do_not_pursue"]
        )
        self.assertFalse(
            context["candidates"][0]["can_more_review"]
        )

        covered = self.submit(
            medication_id="MED001",
            quantity=5,
        )
        context = self.context(covered)
        self.assertFalse(context["shortage"])
        self.assertFalse(context["decisions_enabled"])
        self.assertIn("covers this request", context["message"])

        oversized = self.submit(
            medication_id="MED001",
            quantity=1500,
        )
        context = self.context(oversized)
        self.assertTrue(context["shortage"])
        self.assertTrue(context["decisions_enabled"])
        candidate = context["candidates"][0]
        self.assertEqual(candidate["inventory"]["indicator"], "Red")
        self.assertFalse(candidate["can_keep"])
        self.assertTrue(candidate["can_do_not_pursue"])
        self.assertTrue(candidate["can_more_review"])

    def test_history_survives_handoffs_receipt_and_closure(self):
        request_id = self.submit()
        self.record(request_id)
        order_id = self.make_order(request_id, quantity=3)

        self.assertEqual(
            self.context(request_id)["request_status"],
            "on_order",
        )
        self.assertEqual(len(self.history(request_id)), 1)

        self.receive(order_id, 3, "receipt-one")
        context = self.context(request_id)

        self.assertEqual(
            context["request_status"],
            "supply_received",
        )
        self.assertFalse(context["decisions_enabled"])
        self.assertEqual(len(self.history(request_id)), 1)

        self.action(
            "close_without_supply",
            request_id,
            "Synthetic request no longer needed",
        )
        actionable = session.read_requests(
            Role.PHARMACIST,
            actionable_only=True,
            state_store=self.store,
        )

        self.assertNotIn(
            request_id,
            [row["request_id"] for row in actionable],
        )
        self.assertEqual(len(self.history(request_id)), 1)
        self.assertEqual(len(self.history()), 1)

    def test_live_receipts_refresh_candidate_without_rewriting_snapshots(self):
        # Deplete MED001 through the existing authorized workflow.
        depletion = self.submit(
            medication_id="MED001",
            quantity=1200,
        )
        self.fulfill(depletion)

        request_id = self.submit()
        context = self.context(request_id)
        candidate = context["candidates"][0]
        self.assertEqual(candidate["inventory"]["recorded_stock"], 0)
        self.assertEqual(candidate["inventory"]["indicator"], "Red")
        self.assertFalse(candidate["can_keep"])

        self.record(
            request_id,
            decision=SubstituteDecision.DO_NOT_PURSUE,
            reason="Candidate has no recorded stock",
        )

        # Receipt must belong to a separate eligible MED001 order.
        supply_request = self.submit(
            medication_id="MED001",
            quantity=100,
        )
        order_id = self.make_order(supply_request, quantity=801)
        self.receive(order_id, 100, "candidate-receipt-one")

        candidate = self.context(request_id)["candidates"][0]
        self.assertEqual(
            candidate["inventory"]["recorded_stock"],
            100,
        )
        self.assertEqual(
            candidate["inventory"]["indicator"],
            "Yellow",
        )
        self.assertTrue(candidate["can_keep"])

        self.record(
            request_id,
            decision=SubstituteDecision.NEEDS_MORE_REVIEW,
            reason="Review after synthetic supply arrived",
        )

        self.receive(order_id, 701, "candidate-receipt-two")

        candidate = self.context(request_id)["candidates"][0]
        self.assertEqual(
            candidate["inventory"]["recorded_stock"],
            801,
        )
        self.assertEqual(
            candidate["inventory"]["indicator"],
            "Green",
        )

        history = self.history(request_id)
        self.assertEqual(
            [row["candidate_stock_at_review"] for row in history],
            [0, 100],
        )
        self.assertEqual(
            [row["candidate_indicator_at_review"] for row in history],
            ["Red", "Yellow"],
        )
        self.assertEqual(
            self.context(request_id)["request_status"],
            "under_review",
        )

    def test_public_copy_failure_does_not_publish_review(self):
        request_id = self.submit()
        before = deepcopy(self.store[session.STATE_KEY])

        with patch(
            "src.ui.session.deepcopy",
            side_effect=RuntimeError("Injected copy failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.record(request_id)

        self.assert_unchanged(before)


if __name__ == "__main__":
    unittest.main()