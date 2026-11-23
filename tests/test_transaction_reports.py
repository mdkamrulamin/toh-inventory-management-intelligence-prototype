"""Read-only transaction reports, filtering and export checks."""

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from io import StringIO
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from src.config import PROJECT_ROOT
from src.services.transaction_reports import (
    TRANSACTION_COLUMNS,
    TransactionFilters,
    build_transaction_report,
    prepare_transaction_report_display,
)
from src.services.workflow_models import (
    CreateOrderInput,
    ReceiptInput,
    Role,
    SubmitRequestInput,
    SupplyFeedbackInput,
    WorkflowError,
)
from src.ui import session


class TransactionReportTests(unittest.TestCase):
    def setUp(self):
        self.clock = datetime(
            2026, 11, 19, 23, 50, tzinfo=timezone.utc
        )
        self.start_session("sample_medications_extended.csv")

    def tick(self):
        self.clock += timedelta(seconds=1)
        return self.clock

    def start_session(self, filename):
        self.path = PROJECT_ROOT / "data" / filename
        self.source_bytes = self.path.read_bytes()
        self.store = {}

        session.ensure_demo_session(
            self.path,
            state_store=self.store,
            now=self.tick(),
        )

    def action(self, name, *args, role):
        info = session.get_session_info(
            state_store=self.store
        )
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

    def make_order(self):
        number = self.store[
            session.STATE_KEY
        ].next_request_number

        request_id = self.action(
            "submit_request",
            SubmitRequestInput(
                medication_id="MED003",
                quantity=5,
                unit="tablet",
                requesting_location="Demo Ward",
                reason="Synthetic reporting test",
            ),
            f"request-{number}",
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
            "Recorded stock is insufficient",
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
            f"order-{number}",
            role=Role.PROCUREMENT,
        ).order_id

        return request_id, order_id

    def post(self, order_id, quantity):
        number = self.store[
            session.STATE_KEY
        ].next_receipt_number

        return self.action(
            "confirm_receipt",
            order_id,
            ReceiptInput(quantity, "tablet"),
            f"receipt-{number}",
            role=Role.WAREHOUSE,
        ).receipt_id

    def records(self, report_id):
        reader = (
            session.read_orders
            if report_id == "session_orders"
            else session.read_receipts
        )
        return reader(
            Role.REPORTING,
            state_store=self.store,
        )

    def report(self, report_id, filters=None):
        return build_transaction_report(
            self.records(report_id),
            report_id,
            filters=filters,
        )

    def test_empty_reports_retain_headers_and_export(self):
        for report_id, columns in TRANSACTION_COLUMNS.items():
            with self.subTest(report=report_id):
                report = self.report(report_id)

                self.assertTrue(report.empty)
                self.assertTrue(
                    set(columns).issubset(report.columns)
                )

                display = prepare_transaction_report_display(
                    report
                )
                exported = pd.read_csv(
                    StringIO(display.to_csv(index=False))
                )
                self.assertTrue(exported.empty)
                self.assertEqual(
                    list(exported.columns),
                    list(display.columns),
                )

    def test_all_order_states_and_linked_ids_are_reported(self):
        _, cancelled_id = self.make_order()
        _, ordered_id = self.make_order()
        partial_request, partial_id = self.make_order()
        received_request, received_id = self.make_order()

        self.action(
            "cancel_order",
            cancelled_id,
            "Synthetic cancellation",
            role=Role.PROCUREMENT,
        )
        partial_receipt = self.post(partial_id, 100)
        full_receipt = self.post(received_id, 300)

        orders = self.report("session_orders").set_index(
            "order_id"
        )

        for order_id, expected in (
            (cancelled_id, "cancelled"),
            (ordered_id, "ordered"),
            (partial_id, "partially_received"),
            (received_id, "received"),
        ):
            self.assertEqual(
                orders.at[order_id, "order_status"],
                expected,
            )

        self.assertEqual(
            orders.at[partial_id, "quantity_received"], 100
        )
        self.assertEqual(
            orders.at[partial_id, "quantity_outstanding"], 200
        )
        self.assertEqual(
            orders.at[received_id, "quantity_outstanding"], 0
        )
        self.assertEqual(
            orders.at[partial_id, "linked_request_id"],
            partial_request,
        )

        receipts = self.report(
            "session_receipts"
        ).set_index("receipt_id")

        self.assertEqual(
            receipts.at[partial_receipt, "stock_before"], 0
        )
        self.assertEqual(
            receipts.at[partial_receipt, "stock_after"], 100
        )
        self.assertEqual(
            receipts.at[full_receipt, "stock_before"], 100
        )
        self.assertEqual(
            receipts.at[full_receipt, "stock_after"], 400
        )
        self.assertEqual(
            receipts.at[full_receipt, "linked_request_id"],
            received_request,
        )

    def test_filters_select_exact_ids_and_order_status(self):
        request_id, order_id = self.make_order()
        _, other_id = self.make_order()
        receipt_id = self.post(order_id, 100)

        filters = TransactionFilters(
            medication_ids=("MED003",),
            order_ids=(order_id,),
            request_ids=(request_id,),
            statuses=("partially_received",),
        )
        selected = self.report("session_orders", filters)

        self.assertEqual(
            selected["order_id"].tolist(), [order_id]
        )
        self.assertNotIn(
            other_id, selected["order_id"].tolist()
        )

        receipts = self.report(
            "session_receipts",
            TransactionFilters(
                order_ids=(order_id,),
                statuses=("posted",),
            ),
        )
        self.assertEqual(
            receipts["receipt_id"].tolist(), [receipt_id]
        )

        empty = self.report(
            "session_orders",
            TransactionFilters(
                medication_ids=("MED001",),
                order_ids=(order_id,),
            ),
        )
        self.assertTrue(empty.empty)
        self.assertIn("ordered_quantity", empty.columns)

    def test_order_and_receipt_dates_have_distinct_scope(self):
        _, order_id = self.make_order()
        first_id = self.post(order_id, 100)

        self.clock = datetime(
            2026, 11, 20, 0, 0, tzinfo=timezone.utc
        )
        second_id = self.post(order_id, 200)

        nov19 = TransactionFilters(
            date_from=date(2026, 11, 19),
            date_to=date(2026, 11, 19),
        )
        nov20 = TransactionFilters(
            date_from=date(2026, 11, 20),
            date_to=date(2026, 11, 20),
        )

        self.assertEqual(
            self.report(
                "session_orders", nov19
            )["order_id"].tolist(),
            [order_id],
        )
        self.assertTrue(
            self.report("session_orders", nov20).empty
        )
        self.assertEqual(
            self.report(
                "session_receipts", nov19
            )["receipt_id"].tolist(),
            [first_id],
        )
        self.assertEqual(
            self.report(
                "session_receipts", nov20
            )["receipt_id"].tolist(),
            [second_id],
        )

    def test_invalid_filters_are_rejected(self):
        for filters in (
            TransactionFilters(
                date_from=date(2026, 11, 20),
                date_to=date(2026, 11, 19),
            ),
            TransactionFilters(date_from="2026-11-19"),
            TransactionFilters(statuses=("invented",)),
        ):
            with self.subTest(filters=filters):
                with self.assertRaises(ValueError):
                    self.report("session_orders", filters)

        with self.assertRaises(ValueError):
            build_transaction_report([], "unknown")

    def test_reporting_projection_excludes_private_fields(self):
        _, order_id = self.make_order()
        self.post(order_id, 100)

        self.action(
            "update_order_delivery",
            order_id,
            date(2026, 11, 28),
            "PRIVATE_COMMERCIAL_NOTE",
            role=Role.PROCUREMENT,
        )

        order = session.read_order_details(
            order_id,
            Role.REPORTING,
            state_store=self.store,
        )

        for field in (
            "supplier",
            "unit_cost",
            "order_value_cad",
            "order_value_note",
            "status_reason",
            "order_key",
            "order_history",
            "receipts",
        ):
            self.assertNotIn(field, order)

        self.assertNotIn(
            "PRIVATE_COMMERCIAL_NOTE", repr(order)
        )

        clinical = session.read_order_details(
            order_id,
            Role.CLINICAL,
            state_store=self.store,
        )
        self.assertNotIn("ordered_quantity", clinical)

        for report_id in TRANSACTION_COLUMNS:
            records = self.records(report_id)

            # Even an accidental extra input field is not exported.
            records[0]["private_token"] = "SECRET"
            records[0]["supplier"] = "PRIVATE_SUPPLIER"

            report = build_transaction_report(
                records, report_id
            )
            self.assertNotIn("private_token", report.columns)
            self.assertNotIn("supplier", report.columns)
            self.assertNotIn("SECRET", report.to_csv())

        for role in (Role.EXECUTIVE, Role.SYSTEM):
            with self.subTest(role=role):
                with self.assertRaises(WorkflowError):
                    session.read_orders(
                        role, state_store=self.store
                    )
                with self.assertRaises(WorkflowError):
                    session.read_receipts(
                        role, state_store=self.store
                    )

    def test_reports_export_selected_content_without_mutation(self):
        request_id, order_id = self.make_order()
        receipt_id = self.post(order_id, 100)

        root = self.store[session.STATE_KEY]
        before = deepcopy(root)

        report = self.report(
            "session_receipts",
            TransactionFilters(order_ids=(order_id,)),
        )
        display = prepare_transaction_report_display(report)
        exported = pd.read_csv(
            StringIO(display.to_csv(index=False)),
            dtype="string",
            keep_default_na=False,
        )

        self.assertEqual(
            exported["receipt_id"].tolist(), [receipt_id]
        )
        self.assertEqual(
            exported["linked_request_id"].tolist(),
            [request_id],
        )
        self.assertEqual(
            exported["received_quantity"].tolist(), ["100"]
        )
        self.assertEqual(
            exported["order_status"].tolist(),
            ["Partially received"],
        )
        self.assertTrue(
            exported["synthetic_data_notice"]
            .str.contains("Synthetic", regex=False)
            .all()
        )
        self.assertIn(
            order_id, exported.at[0, "report_scope"]
        )

        # Changing caller-owned results cannot change session state.
        report.loc[0, "received_quantity"] = 999
        records = self.records("session_orders")
        records[0]["ordered_quantity"] = 999

        self.assertIs(self.store[session.STATE_KEY], root)
        assert_frame_equal(root.inventory, before.inventory)
        assert_frame_equal(
            root.initial_inventory, before.initial_inventory
        )

        for field in (
            "run_id",
            "revision",
            "requests",
            "orders",
            "receipts",
            "substitute_reviews",
            "next_request_number",
            "next_order_number",
            "next_receipt_number",
            "next_substitute_review_number",
        ):
            self.assertEqual(
                getattr(root, field),
                getattr(before, field),
                field,
            )

        self.assertEqual(
            self.path.read_bytes(), self.source_bytes
        )

    def test_both_schemas_and_reset(self):
        for filename in (
            "sample_medications.csv",
            "sample_medications_extended.csv",
        ):
            with self.subTest(dataset=filename):
                self.start_session(filename)
                _, order_id = self.make_order()
                receipt_id = self.post(order_id, 300)

                self.assertEqual(
                    self.report(
                        "session_orders"
                    )["order_id"].tolist(),
                    [order_id],
                )
                self.assertEqual(
                    self.report(
                        "session_receipts"
                    )["receipt_id"].tolist(),
                    [receipt_id],
                )

                session.reset_demo_session(
                    clinical_tab_label="Clinical",
                    state_store=self.store,
                    now=self.tick(),
                )

                self.assertTrue(
                    self.report("session_orders").empty
                )
                self.assertTrue(
                    self.report("session_receipts").empty
                )
                self.assertEqual(
                    self.path.read_bytes(), self.source_bytes
                )
                
    def test_current_status_updates_without_rewriting_receipt_stock(self):
        request_id, order_id = self.make_order()
        receipt_id = self.post(order_id, 300)

        self.action(
            "start_review",
            request_id,
            role=Role.PHARMACIST,
        )
        self.action(
            "authorize_release",
            request_id,
            "Synthetic post-receipt review completed",
            role=Role.PHARMACIST,
        )
        self.action(
            "fulfill_request",
            request_id,
            role=Role.WAREHOUSE,
        )

        order = self.report("session_orders").iloc[0]
        receipt = (
            self.report("session_receipts")
            .set_index("receipt_id")
            .loc[receipt_id]
        )

        self.assertEqual(order["order_status"], "received")
        self.assertEqual(order["request_status"], "closed")
        self.assertEqual(receipt["request_status"], "closed")

        # Receipt observations remain historical even after fulfillment.
        self.assertEqual(receipt["stock_before"], 0)
        self.assertEqual(receipt["stock_after"], 300)

        inventory = session.read_inventory(
            Role.REPORTING,
            state_store=self.store,
        ).set_index("medication_id")

        self.assertEqual(
            inventory.at["MED003", "current_stock"],
            295,
        )


if __name__ == "__main__":
    unittest.main()