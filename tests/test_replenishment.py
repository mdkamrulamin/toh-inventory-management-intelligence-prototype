"""Checks for illustrative replenishment-review rules."""

import unittest

import pandas as pd

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
                    "At/below illustrative reorder threshold - review",
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
            "N/A - reorder threshold unavailable",
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
            "N/A - reorder threshold unavailable",
        )

    def test_source_data_is_not_modified(self):
        original = self.medications.copy(deep=True)

        build_replenishment_context(self.medications)

        pd.testing.assert_frame_equal(original, self.medications)


if __name__ == "__main__":
    unittest.main()