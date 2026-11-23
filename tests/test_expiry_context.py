"""Representative expiry boundaries, shared reference and role checks."""

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from src.config import PROJECT_ROOT
from src.data.loader import load_medications
from src.services import workflow as wf
from src.services import workflow_queries as queries
from src.services.expiry import (
    AFTER_REFERENCE,
    BEFORE_REFERENCE,
    EXPIRY_CONTEXT_COLUMNS,
    MISSING_EXPIRY,
    MISSING_REFERENCE,
    ON_REFERENCE,
    add_representative_expiry_context,
    demo_reference_date,
    describe_representative_expiry,
)
from src.services.substitute_queries import (
    get_request_alternatives,
)
from src.services.workflow_models import (
    Role,
    SubmitRequestInput,
    WorkflowError,
)
from src.ui import session
from io import StringIO

from src.services.reporting import (
    InventoryFilters,
    build_inventory_report,
    prepare_report_display,
)


class ExpiryContextTests(unittest.TestCase):
    def setUp(self):
        self.as_of = date(2026, 11, 20)
        self.now = datetime(
            2026, 11, 20, 12, 0, tzinfo=timezone.utc
        )
        self.make_state()

    def make_state(
        self,
        filename="sample_medications_extended.csv",
    ):
        self.path = PROJECT_ROOT / "data" / filename
        self.source_bytes = self.path.read_bytes()
        self.medications = load_medications(self.path)

        self.state = wf.initialize_demo(
            self.medications,
            dataset_path=str(self.path),
            dataset_fingerprint=sha256(
                self.source_bytes
            ).hexdigest(),
            now=self.now,
        )

    def test_before_on_and_after_reference_date(self):
        for expiry, days, label in (
            ("2026-11-19", -1, BEFORE_REFERENCE),
            ("2026-11-20", 0, ON_REFERENCE),
            ("2026-11-21", 1, AFTER_REFERENCE),
        ):
            with self.subTest(expiry=expiry):
                result = describe_representative_expiry(
                    expiry,
                    as_of=self.as_of,
                )

                self.assertEqual(
                    result["expiry_date"], expiry
                )
                self.assertEqual(
                    result["days_to_representative_expiry"],
                    days,
                )
                self.assertEqual(
                    result["representative_expiry_context"],
                    label,
                )
                self.assertEqual(
                    result["shelf_life_as_of"],
                    "2026-11-20",
                )

    def test_missing_or_invalid_expiry_is_not_zero_days(self):
        for value in (
            None,
            pd.NA,
            pd.NaT,
            float("nan"),
            "",
            "not a date",
            "2026-02-30",
            "20261120",
            0,
            True,
        ):
            with self.subTest(value=repr(value)):
                result = describe_representative_expiry(
                    value,
                    as_of=self.as_of,
                )

                self.assertIsNone(result["expiry_date"])
                self.assertIsNone(
                    result["days_to_representative_expiry"]
                )
                self.assertEqual(
                    result["representative_expiry_context"],
                    MISSING_EXPIRY,
                )

    def test_missing_reference_does_not_use_current_clock(self):
        result = describe_representative_expiry(
            "2027-06-30",
            as_of=None,
        )

        self.assertEqual(
            result["expiry_date"], "2027-06-30"
        )
        self.assertIsNone(
            result["days_to_representative_expiry"]
        )
        self.assertIsNone(result["shelf_life_as_of"])
        self.assertEqual(
            result["representative_expiry_context"],
            MISSING_REFERENCE,
        )

    def test_reference_uses_utc_calendar_date(self):
        self.assertEqual(
            demo_reference_date(
                "2026-11-19T23:30:00-05:00"
            ),
            date(2026, 11, 20),
        )
        self.assertEqual(
            demo_reference_date(
                "2026-11-20T00:30:00+02:00"
            ),
            date(2026, 11, 19),
        )

    def test_invalid_reference_inputs_are_rejected(self):
        for value in (
            None,
            "",
            "invalid",
            "2026-11-20",
            "2026-11-20T12:00:00",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    demo_reference_date(value)

        for value in (
            "2026-11-20",
            datetime(2026, 11, 20),
        ):
            with self.subTest(as_of=value):
                with self.assertRaises(ValueError):
                    describe_representative_expiry(
                        "2027-06-30",
                        as_of=value,
                    )

    def test_frame_preserves_source_fields_index_and_missing_values(self):
        source = pd.DataFrame(
            {
                "medication_id": ["A", "B", "C"],
                "current_stock": [10, 0, 5],
                "expiry_date": pd.to_datetime(
                    [
                        "2026-11-19",
                        "2026-11-20",
                        None,
                    ]
                ),
            },
            index=[7, 2, 9],
        )
        before = source.copy(deep=True)

        result = add_representative_expiry_context(
            source,
            as_of=self.as_of,
        )

        assert_frame_equal(source, before)
        assert_frame_equal(result[source.columns], before)

        self.assertEqual(
            result["days_to_representative_expiry"].dtype,
            pd.Int64Dtype(),
        )
        self.assertEqual(
            result.at[7, "days_to_representative_expiry"],
            -1,
        )
        self.assertEqual(
            result.at[2, "days_to_representative_expiry"],
            0,
        )
        self.assertTrue(
            pd.isna(
                result.at[
                    9, "days_to_representative_expiry"
                ]
            )
        )

    def test_absent_expiry_column_and_empty_frame_are_supported(self):
        source = pd.DataFrame(
            {"medication_id": ["A"]}
        )

        result = add_representative_expiry_context(
            source,
            as_of=self.as_of,
        )

        self.assertTrue(
            pd.isna(result.at[0, "expiry_date"])
        )
        self.assertEqual(
            result.at[
                0, "representative_expiry_context"
            ],
            MISSING_EXPIRY,
        )

        empty = add_representative_expiry_context(
            source.iloc[:0],
            as_of=self.as_of,
        )

        self.assertTrue(empty.empty)
        self.assertTrue(
            set(EXPIRY_CONTEXT_COLUMNS)
            .issubset(empty.columns)
        )

    def test_role_queries_support_both_schemas_without_mutation(self):
        for filename in (
            "sample_medications.csv",
            "sample_medications_extended.csv",
        ):
            with self.subTest(dataset=filename):
                self.make_state(filename)
                before = deepcopy(self.state)

                for role in (
                    Role.PHARMACIST,
                    Role.WAREHOUSE,
                    Role.REPORTING,
                ):
                    snapshot = queries.get_inventory_snapshot(
                        self.state,
                        role,
                    )
                    context = (
                        queries.get_inventory_expiry_context(
                            self.state,
                            role,
                        )
                    )

                    assert_frame_equal(
                        context[snapshot.columns],
                        snapshot,
                    )
                    self.assertTrue(
                        context["shelf_life_as_of"]
                        .eq("2026-11-20")
                        .all()
                    )

                    if role != Role.REPORTING:
                        self.assertNotIn(
                            "unit_cost", context.columns
                        )

                assert_frame_equal(
                    self.state.inventory,
                    before.inventory,
                )
                assert_frame_equal(
                    self.state.initial_inventory,
                    before.initial_inventory,
                )
                self.assertEqual(
                    self.state.revision, before.revision
                )
                self.assertEqual(
                    self.state.requests, before.requests
                )
                self.assertEqual(
                    self.path.read_bytes(),
                    self.source_bytes,
                )

    def test_clinical_and_executive_do_not_receive_expiry_projection(self):
        for role in (
            Role.CLINICAL,
            Role.EXECUTIVE,
            Role.SYSTEM,
            "unknown-role",
        ):
            with self.subTest(role=role):
                with self.assertRaises(WorkflowError):
                    queries.get_inventory_expiry_context(
                        self.state,
                        role,
                    )

    def test_substitute_comparison_uses_shared_expiry_fields(self):
        result = wf.submit_request(
            self.state,
            SubmitRequestInput(
                medication_id="MED003",
                quantity=5,
                unit="tablet",
                requesting_location="Demo Ward",
                reason="Synthetic shared expiry check",
                substitution_allowed=True,
            ),
            "expiry-request",
            context=wf.make_context(
                self.state,
                Role.CLINICAL,
                now=self.now + timedelta(seconds=1),
            ),
        )
        self.state = result.state

        context = get_request_alternatives(
            self.state,
            result.request_id,
            Role.PHARMACIST,
        )

        row = self.medications.set_index(
            "medication_id"
        ).loc["MED003"]

        expected = describe_representative_expiry(
            row["expiry_date"],
            as_of=self.as_of,
        )

        for field, value in expected.items():
            self.assertEqual(
                context["source"][field],
                value,
            )

        self.assertEqual(
            context["as_of_date"], "2026-11-20"
        )

    def test_session_readers_and_reset_reference(self):
        store = {session.STATE_KEY: self.state}

        self.assertEqual(
            session.read_demo_reference_date(
                state_store=store
            ),
            self.as_of,
        )

        result = session.read_inventory_expiry_context(
            Role.WAREHOUSE,
            state_store=store,
        )
        result.loc[0, "current_stock"] = 999

        assert_frame_equal(
            self.state.inventory,
            self.medications,
        )

        reset_state = wf.reset_demo(
            self.state,
            now=self.now + timedelta(days=2),
        )
        store[session.STATE_KEY] = reset_state

        self.assertEqual(
            session.read_demo_reference_date(
                state_store=store
            ),
            date(2026, 11, 22),
        )
        reset_context = (
            session.read_inventory_expiry_context(
                Role.WAREHOUSE,
                state_store=store,
            )
        )
        self.assertTrue(
            reset_context["shelf_life_as_of"]
            .eq("2026-11-22")
            .all()
        )
        
    def test_expiry_report_boundaries_and_missing_csv_values(self):
        inventory = self.medications.copy(deep=True)
        ids = inventory["medication_id"].iloc[:4].tolist()

        for medication_id, expiry in zip(
            ids,
            [
                pd.Timestamp("2026-11-19"),
                pd.Timestamp("2026-11-20"),
                pd.Timestamp("2026-11-21"),
                pd.NaT,
            ],
            strict=True,
        ):
            inventory.loc[
                inventory["medication_id"].eq(medication_id),
                "expiry_date",
            ] = expiry

        before = inventory.copy(deep=True)

        report = build_inventory_report(
            inventory,
            "expiry_overview",
            filters=InventoryFilters(
                medication_ids=tuple(ids),
            ),
            as_of=self.as_of,
        )

        self.assertEqual(
            report["representative_expiry_context"].tolist(),
            [
                BEFORE_REFERENCE,
                ON_REFERENCE,
                AFTER_REFERENCE,
                MISSING_EXPIRY,
            ],
        )

        display = prepare_report_display(report)
        decoded = pd.read_csv(
            StringIO(display.to_csv(index=False)),
            dtype="string",
            keep_default_na=False,
        )

        self.assertEqual(
            decoded["medication_id"].tolist(),
            ids,
        )
        self.assertEqual(
            decoded["days_to_representative_expiry"].tolist(),
            ["-1", "0", "1", "N/A"],
        )
        self.assertEqual(
            decoded["shelf_life_as_of"].tolist(),
            ["2026-11-20"] * 4,
        )
        self.assertEqual(
            decoded.iloc[3]["expiry_date"],
            "N/A",
        )

        assert_frame_equal(inventory, before)

    def test_expiry_report_matches_warehouse_for_both_schemas(self):
        columns = [
            "medication_id",
            "current_stock",
            "stock_unit",
            "expiry_date",
            *EXPIRY_CONTEXT_COLUMNS,
        ]

        for filename in (
            "sample_medications.csv",
            "sample_medications_extended.csv",
        ):
            with self.subTest(dataset=filename):
                self.make_state(filename)

                warehouse = (
                    queries.get_inventory_expiry_context(
                        self.state,
                        Role.WAREHOUSE,
                    )
                )
                reporting_inventory = (
                    queries.get_inventory_snapshot(
                        self.state,
                        Role.REPORTING,
                    )
                )

                report = build_inventory_report(
                    reporting_inventory,
                    "expiry_overview",
                    as_of=self.as_of,
                )

                assert_frame_equal(
                    report[columns].reset_index(drop=True),
                    warehouse[columns].reset_index(drop=True),
                )

                expiry = (
                    reporting_inventory.set_index("medication_id")
                    .at["MED001", "expiry_date"]
                    .date()
                )
                filtered = build_inventory_report(
                    reporting_inventory,
                    "expiry_overview",
                    filters=InventoryFilters(
                        medication_ids=("MED001",),
                        expiry_from=expiry,
                        expiry_to=expiry,
                    ),
                    as_of=self.as_of,
                )

                self.assertEqual(
                    filtered["medication_id"].tolist(),
                    ["MED001"],
                )

    def test_expiry_report_without_reference_explains_unavailability(self):
        report = build_inventory_report(
            self.medications,
            "expiry_overview",
        )

        self.assertTrue(report["expiry_date"].notna().all())
        self.assertTrue(
            report["days_to_representative_expiry"]
            .isna()
            .all()
        )
        self.assertTrue(
            report["representative_expiry_context"]
            .eq(MISSING_REFERENCE)
            .all()
        )


if __name__ == "__main__":
    unittest.main()