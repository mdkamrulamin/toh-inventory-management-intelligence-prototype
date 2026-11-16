"""Numerical acceptance checks for synthetic stock analytics."""

import unittest
from decimal import Decimal

import pandas as pd

from src.config import PROJECT_ROOT
from src.data.loader import load_medications
from src.services.analytics import build_stock_analytics
from src.services.replenishment import (
    ABOVE_STOCK_LABEL,
    MISSING_REORDER_LABEL,
    REVIEW_STOCK_LABEL,
    ZERO_STOCK_LABEL,
)


class StockAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.medications = load_medications(
            PROJECT_ROOT / "data" / "sample_medications_extended.csv"
        )

    def result(self, medications=None):
        return build_stock_analytics(
            self.medications if medications is None else medications
        )

    def fixture(self, values, ids=None):
        count = len(values)
        return pd.DataFrame(
            {
                "medication_id": ids or [
                    f"M{index:03d}" for index in range(count)
                ],
                "medication_name": [
                    f"Demo {index}" for index in range(count)
                ],
                "current_stock": [10] * count,
                "stock_unit": ["tablet"] * count,
                "unit_cost": values,
                "average_monthly_consumption": [1] * count,
                "reorder_point": [5] * count,
                "safety_stock_level": [2] * count,
                "lead_time_days": [3] * count,
            }
        )

    def test_baseline_values_classes_and_category_totals(self):
        result = self.result()
        rows = result.rows.set_index("medication_id")

        self.assertEqual(
            result.summary["total_monthly_consumption_value_cad"],
            Decimal("651.50"),
        )
        self.assertTrue(result.summary["abc_available"])

        expected = {
            "MED006": ("270.00", "A"),
            "MED002": ("112.50", "A"),
            "MED005": ("75.00", "A"),
            "MED004": ("70.00", "B"),
            "MED001": ("64.00", "B"),
            "MED003": ("60.00", "C"),
        }

        for medication_id, (value, classification) in expected.items():
            with self.subTest(medication_id=medication_id):
                self.assertEqual(
                    rows.at[
                        medication_id,
                        "monthly_consumption_value_cad",
                    ],
                    Decimal(value),
                )
                self.assertEqual(
                    rows.at[medication_id, "abc_class"],
                    classification,
                )

        totals = {
            row["abc_class"]: row
            for row in result.summary["class_totals"]
        }
        self.assertEqual(
            totals["A"]["monthly_consumption_value_cad"],
            Decimal("457.50"),
        )
        self.assertEqual(
            totals["B"]["monthly_consumption_value_cad"],
            Decimal("134.00"),
        )
        self.assertEqual(
            totals["C"]["monthly_consumption_value_cad"],
            Decimal("60.00"),
        )
        self.assertEqual(
            f"{rows.at['MED006', 'abc_share_percent']:.2f}",
            "41.44",
        )
        self.assertEqual(
            f"{rows.at['MED004', 'abc_cumulative_share_percent']:.2f}",
            "80.97",
        )

    def test_baseline_coverage_gap_and_lead_time_demand(self):
        rows = self.result().rows.set_index("medication_id")

        self.assertEqual(
            f"{rows.at['MED006', 'stock_coverage_months']:.2f}",
            "1.33",
        )
        self.assertEqual(
            rows.at["MED006", "reorder_gap"],
            Decimal(10),
        )
        self.assertEqual(
            rows.at["MED006", "lead_time_demand"],
            Decimal(10),
        )
        self.assertEqual(
            rows.at["MED006", "ordering_review"],
            REVIEW_STOCK_LABEL,
        )
        self.assertEqual(
            rows.at["MED003", "stock_coverage_months"],
            Decimal(0),
        )
        self.assertEqual(
            rows.at["MED003", "reorder_gap"],
            Decimal(300),
        )
        self.assertEqual(
            f"{rows.at['MED003', 'lead_time_demand']:.2f}",
            "116.67",
        )

    def test_exact_80_and_95_percent_boundaries(self):
        rows = self.result(
            self.fixture(["80", "15", "5"])
        ).rows

        self.assertEqual(rows["abc_class"].tolist(), ["A", "B", "C"])
        self.assertEqual(
            rows["abc_cumulative_share_percent"].tolist(),
            [Decimal(80), Decimal(95), Decimal(100)],
        )

    def test_highest_positive_item_remains_a_above_95_percent(self):
        rows = self.result(
            self.fixture(["96", "4"])
        ).rows

        self.assertEqual(rows["abc_class"].tolist(), ["A", "C"])

    def test_equal_values_use_ascending_medication_id(self):
        rows = self.result(
            self.fixture(["1", "1", "1"], ids=["C", "A", "B"])
        ).rows.set_index("medication_id")

        self.assertEqual(rows.at["A", "abc_class"], "A")
        self.assertEqual(rows.at["B", "abc_class"], "A")
        self.assertEqual(rows.at["C", "abc_class"], "C")
        self.assertLess(
            rows.at["A", "abc_cumulative_share_percent"],
            rows.at["B", "abc_cumulative_share_percent"],
        )

    def test_unrounded_values_control_classification(self):
        rows = self.result(
            self.fixture(["79.999", "0.002", "19.999"])
        ).rows.set_index("medication_id")

        # Descending values: 79.999, 19.999, 0.002.
        # The second item reaches 99.998%, despite display rounding.
        self.assertEqual(rows.at["M000", "abc_class"], "A")
        self.assertEqual(rows.at["M002", "abc_class"], "C")

        rows = self.result(
            self.fixture(["60", "20.001", "19.999"])
        ).rows
        self.assertEqual(
            f"{rows.at[1, 'abc_cumulative_share_percent']:.2f}",
            "80.00",
        )
        self.assertEqual(rows.at[1, "abc_class"], "B")

    def test_zero_cost_is_zero_value_and_class_c(self):
        rows = self.result(
            self.fixture(["1", "0"])
        ).rows

        self.assertEqual(rows.at[1, "abc_class"], "C")
        self.assertEqual(
            rows.at[1, "monthly_consumption_value_cad"],
            Decimal(0),
        )
        self.assertEqual(
            rows.at[1, "recorded_inventory_value_cad"],
            Decimal(0),
        )
        self.assertIn(
            "Supplied unit cost is zero",
            rows.at[1, "analytics_note"],
        )

    def test_zero_usage_and_all_zero_total(self):
        medications = self.medications.copy()
        medications["average_monthly_consumption"] = 0
        result = self.result(medications)

        self.assertEqual(
            result.summary["total_monthly_consumption_value_cad"],
            Decimal(0),
        )
        self.assertFalse(result.summary["abc_available"])
        self.assertTrue(result.rows["abc_class"].isna().all())
        self.assertTrue(
            result.rows["stock_coverage_months"].isna().all()
        )
        self.assertTrue(
            result.rows["lead_time_demand"].eq(Decimal(0)).all()
        )

    def test_missing_abc_input_withholds_all_classes_and_shares(self):
        for column in (
            "unit_cost",
            "average_monthly_consumption",
            "stock_unit",
        ):
            with self.subTest(column=column):
                medications = self.medications.copy()
                medications.loc[0, column] = pd.NA
                result = self.result(medications)

                self.assertFalse(result.summary["abc_available"])
                self.assertEqual(
                    result.summary["complete_abc_count"], 5
                )
                self.assertIsNone(
                    result.summary[
                        "total_monthly_consumption_value_cad"
                    ]
                )
                self.assertTrue(
                    result.rows["abc_class"].isna().all()
                )
                self.assertTrue(
                    result.rows["abc_share_percent"].isna().all()
                )
                self.assertEqual(
                    result.rows[
                        "monthly_consumption_value_cad"
                    ].notna().sum(),
                    5,
                )
                self.assertIn(
                    "5 of 6", result.summary["abc_note"]
                )

    def test_original_schema_supports_abc_without_optional_parameters(self):
        original = load_medications(
            PROJECT_ROOT / "data" / "sample_medications.csv"
        )
        result = self.result(original)

        self.assertTrue(result.summary["abc_available"])
        for column in (
            "reorder_point",
            "safety_stock_level",
            "lead_time_days",
            "reorder_gap",
            "lead_time_demand",
        ):
            self.assertTrue(result.rows[column].isna().all())

        rows = result.rows.set_index("medication_id")
        self.assertEqual(
            rows.at["MED001", "ordering_review"],
            MISSING_REORDER_LABEL,
        )
        self.assertEqual(
            rows.at["MED003", "ordering_review"],
            ZERO_STOCK_LABEL,
        )

    def test_zero_and_missing_parameters_remain_distinct(self):
        medications = self.fixture(["1", "1"])
        medications.loc[0, "reorder_point"] = 0
        medications.loc[0, "safety_stock_level"] = pd.NA
        medications.loc[0, "lead_time_days"] = 0
        medications.loc[1, "reorder_point"] = pd.NA
        medications.loc[1, "lead_time_days"] = pd.NA

        rows = self.result(medications).rows

        self.assertEqual(rows.at[0, "reorder_gap"], Decimal(0))
        self.assertEqual(
            rows.at[0, "lead_time_demand"], Decimal(0)
        )
        self.assertEqual(
            rows.at[0, "ordering_review"], ABOVE_STOCK_LABEL
        )
        self.assertTrue(pd.isna(rows.at[1, "reorder_gap"]))
        self.assertTrue(pd.isna(rows.at[1, "lead_time_demand"]))

    def test_invalid_supplied_numbers_and_missing_stock_are_rejected(self):
        for value in (-1, float("inf"), "invalid"):
            with self.subTest(value=value):
                medications = self.fixture(["1"])
                medications["unit_cost"] = [value]
                with self.assertRaises(ValueError):
                    self.result(medications)

        medications = self.fixture(["1"])
        medications["current_stock"] = pd.NA
        with self.assertRaises(ValueError):
            self.result(medications)

    def test_nonfinite_calculated_results_are_unavailable(self):
        medications = self.fixture(["1e308"])
        medications["average_monthly_consumption"] = 1e308
        result = self.result(medications)

        self.assertFalse(result.summary["abc_available"])
        self.assertTrue(
            pd.isna(
                result.rows.at[
                    0, "monthly_consumption_value_cad"
                ]
            )
        )
        self.assertIn(
            "finite calculation range",
            result.rows.at[0, "analytics_note"],
        )

    def test_stock_refresh_changes_coverage_and_gap_but_not_abc(self):
        baseline = self.result().rows.set_index("medication_id")
        changed = self.medications.copy()
        changed.loc[
            changed["medication_id"].eq("MED001"),
            "current_stock",
        ] = 800

        rows = self.result(changed).rows.set_index("medication_id")

        self.assertEqual(
            rows.at["MED001", "stock_coverage_months"], Decimal(1)
        )
        self.assertEqual(rows.at["MED001", "reorder_gap"], Decimal(0))
        self.assertEqual(
            rows.at["MED001", "ordering_review"], REVIEW_STOCK_LABEL
        )
        self.assertEqual(
            rows.at["MED001", "abc_class"],
            baseline.at["MED001", "abc_class"],
        )
        self.assertEqual(
            rows.at["MED001", "abc_share_percent"],
            baseline.at["MED001", "abc_share_percent"],
        )

    def test_empty_population_and_source_preservation(self):
        original = self.medications.copy(deep=True)
        self.result()

        pd.testing.assert_frame_equal(self.medications, original)

        empty = self.result(self.medications.iloc[:0].copy())

        self.assertTrue(empty.rows.empty)
        self.assertEqual(empty.summary["population_count"], 0)
        self.assertFalse(empty.summary["abc_available"])
        self.assertIsNone(
            empty.summary["total_monthly_consumption_value_cad"]
        )


if __name__ == "__main__":
    unittest.main()