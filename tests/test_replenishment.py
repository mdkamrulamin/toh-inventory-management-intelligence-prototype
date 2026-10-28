"""Checks for illustrative replenishment-review rules."""

import unittest

import pandas as pd

from src.config import PROJECT_ROOT
from src.data.loader import load_medications
from src.services.replenishment import build_replenishment_context


class ReplenishmentContextTests(unittest.TestCase):
    def setUp(self):
        self.medications = pd.DataFrame(
            {
                "medication_id": ["ZERO", "BELOW", "EQUAL", "ABOVE"],
                "medication_name": ["Demo A", "Demo B", "Demo C", "Demo D"],
                "current_stock": [0, 80, 90, 100],
                "stock_unit": ["tablet"] * 4,
                "reorder_point": [90, 90, 90, 90],
            }
        )

    def context(self, medications=None):
        if medications is None:
            medications = self.medications

        return build_replenishment_context(
            medications
        ).set_index("medication_id")

    def test_zero_stock_has_its_own_flag(self):
        result = self.context()

        self.assertEqual(
            result.loc["ZERO", "ordering_review"],
            "Recorded stock = 0 — availability/order review",
        )

    def test_below_and_equal_threshold_require_review(self):
        result = self.context()

        for medication_id in ("BELOW", "EQUAL"):
            with self.subTest(medication_id=medication_id):
                self.assertEqual(
                    result.loc[medication_id, "ordering_review"],
                    "At/below illustrative reorder threshold — review",
                )

    def test_above_threshold_has_correct_flag(self):
        result = self.context()

        self.assertEqual(
            result.loc["ABOVE", "ordering_review"],
            "Above illustrative reorder threshold",
        )

    def test_absent_optional_columns_remain_missing(self):
        medications = self.medications.drop(columns="reorder_point")
        result = self.context(medications)

        for column in (
            "reorder_point",
            "safety_stock_level",
            "lead_time_days",
        ):
            self.assertTrue(result[column].isna().all())

        self.assertEqual(
            result.loc["BELOW", "ordering_review"],
            "N/A — reorder point unavailable",
        )
        self.assertTrue(
            result.loc["ZERO", "ordering_review"].startswith(
                "Recorded stock = 0"
            )
        )

    def test_blank_threshold_remains_unavailable(self):
        medications = self.medications.copy()
        medications["reorder_point"] = (
            medications["reorder_point"].astype("Float64")
        )
        medications.loc[
            medications["medication_id"].eq("BELOW"),
            "reorder_point",
        ] = pd.NA

        result = self.context(medications)

        self.assertEqual(
            result.loc["BELOW", "ordering_review"],
            "N/A — reorder point unavailable",
        )

    def test_source_data_is_not_modified(self):
        original = self.medications.copy(deep=True)

        build_replenishment_context(self.medications)

        pd.testing.assert_frame_equal(original, self.medications)
        
    def test_above_boundary_91_is_above_threshold(self):
        medications = self.medications.copy()
        medications.loc[
            medications["medication_id"].eq("ABOVE"),
            "current_stock",
        ] = 91

        result = self.context(medications)

        self.assertEqual(
            result.loc["ABOVE", "ordering_review"],
            "Above illustrative reorder threshold",
        )

    def test_explicit_zero_threshold_is_not_missing(self):
        medications = self.medications.copy()
        medications["reorder_point"] = 0

        result = self.context(medications)

        self.assertEqual(
            result.loc["ZERO", "ordering_review"],
            "Recorded stock = 0 — availability/order review",
        )

        for medication_id in ("BELOW", "EQUAL", "ABOVE"):
            with self.subTest(medication_id=medication_id):
                self.assertEqual(
                    result.loc[medication_id, "ordering_review"],
                    "Above illustrative reorder threshold",
                )

    def test_missing_unit_prevents_positive_stock_comparison(self):
        medications = self.medications.drop(columns="stock_unit")

        result = self.context(medications)

        self.assertTrue(result["stock_unit"].isna().all())

        for medication_id in ("BELOW", "EQUAL", "ABOVE"):
            with self.subTest(medication_id=medication_id):
                self.assertEqual(
                    result.loc[medication_id, "ordering_review"],
                    "N/A — stock unit unavailable",
                )

        self.assertEqual(
            result.loc["ZERO", "ordering_review"],
            "Recorded stock = 0 — availability/order review",
        )

    def test_blank_units_prevent_positive_stock_comparison(self):
        for missing_unit in ("", "   ", None, pd.NA):
            with self.subTest(stock_unit=missing_unit):
                medications = self.medications.copy()
                medications["stock_unit"] = missing_unit

                result = self.context(medications)

                self.assertEqual(
                    result.loc["BELOW", "ordering_review"],
                    "N/A — stock unit unavailable",
                )
                self.assertEqual(
                    result.loc["ZERO", "ordering_review"],
                    "Recorded stock = 0 — availability/order review",
                )

    def test_supporting_fields_do_not_override_recorded_stock(self):
        medications = self.medications.copy()
        medications["counted_stock"] = 9999
        medications["safety_stock_level"] = 9999
        medications["expiry_date"] = "2000-01-01"
        medications["lead_time_days"] = 999

        result = self.context(medications)

        self.assertEqual(
            result.loc["ZERO", "ordering_review"],
            "Recorded stock = 0 — availability/order review",
        )
        self.assertEqual(
            result.loc["BELOW", "ordering_review"],
            "At/below illustrative reorder threshold — review",
        )
        self.assertEqual(
            result.loc["ABOVE", "ordering_review"],
            "Above illustrative reorder threshold",
        )

    def test_sample_datasets_have_expected_reviews(self):
        extended = load_medications(
            PROJECT_ROOT / "data" / "sample_medications_extended.csv"
        )
        extended_result = self.context(extended)

        expected = {
            "MED003": "Recorded stock = 0 — availability/order review",
            "MED006": "At/below illustrative reorder threshold — review",
            "MED001": "Above illustrative reorder threshold",
        }

        for medication_id, label in expected.items():
            with self.subTest(medication_id=medication_id):
                self.assertEqual(
                    extended_result.loc[medication_id, "ordering_review"],
                    label,
                )

        original = load_medications(
            PROJECT_ROOT / "data" / "sample_medications.csv"
        )
        original_result = self.context(original)

        self.assertTrue(original_result["reorder_point"].isna().all())
        self.assertEqual(
            original_result.loc["MED003", "ordering_review"],
            "Recorded stock = 0 — availability/order review",
        )

        positive_rows = original_result["current_stock"].gt(0)
        self.assertTrue(
            original_result.loc[
                positive_rows, "ordering_review"
            ].eq("N/A — reorder point unavailable").all()
        )


if __name__ == "__main__":
    unittest.main()