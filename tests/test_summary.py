"""Checks for synthetic executive summaries and missing-data handling."""

import unittest

import pandas as pd

from src.config import PROJECT_ROOT
from src.data.loader import load_medications
from src.services.summary import summarize_inventory


class InventorySummaryTests(unittest.TestCase):
    def setUp(self):
        self.medications = load_medications(
            PROJECT_ROOT / "data" / "sample_medications_extended.csv"
        )

    def test_both_datasets_produce_expected_snapshot(self):
        for filename in (
            "sample_medications.csv",
            "sample_medications_extended.csv",
        ):
            with self.subTest(filename=filename):
                medications = load_medications(
                    PROJECT_ROOT / "data" / filename
                )
                result = summarize_inventory(medications)

                self.assertEqual(result["sku_count"], 6)
                self.assertEqual(result["zero_stock_count"], 1)
                self.assertAlmostEqual(
                    result["zero_stock_share_percent"],
                    100 / 6,
                )
                self.assertEqual(result["supplier_count"], 3)
                self.assertAlmostEqual(
                    result["inventory_value_cad"],
                    801.00,
                )

    def test_missing_cost_prevents_partial_valuation(self):
        absent = self.medications.drop(columns="unit_cost")

        partial = self.medications.copy()
        partial["unit_cost"] = partial["unit_cost"].astype("Float64")
        partial.loc[0, "unit_cost"] = pd.NA

        all_missing = self.medications.copy()
        all_missing["unit_cost"] = pd.Series(
            pd.NA,
            index=all_missing.index,
            dtype="Float64",
        )

        for label, medications in (
            ("absent column", absent),
            ("one missing cost", partial),
            ("all costs missing", all_missing),
        ):
            with self.subTest(case=label):
                result = summarize_inventory(medications)

                self.assertIsNone(result["inventory_value_cad"])
                self.assertEqual(result["sku_count"], 6)
                self.assertEqual(result["zero_stock_count"], 1)

    def test_unavailable_suppliers_remain_unknown(self):
        absent = self.medications.drop(columns="supplier")

        all_missing = self.medications.copy()
        all_missing["supplier"] = pd.Series(
            pd.NA,
            index=all_missing.index,
            dtype="string",
        )

        for medications in (absent, all_missing):
            result = summarize_inventory(medications)
            self.assertIsNone(result["supplier_count"])

    def test_empty_snapshot_has_no_rate_or_valuation(self):
        empty = self.medications.iloc[0:0].copy()
        result = summarize_inventory(empty)

        self.assertEqual(result["sku_count"], 0)
        self.assertEqual(result["zero_stock_count"], 0)
        self.assertIsNone(result["zero_stock_share_percent"])
        self.assertIsNone(result["inventory_value_cad"])
        self.assertIsNone(result["supplier_count"])

    def test_summary_does_not_modify_source_data(self):
        original = self.medications.copy(deep=True)

        summarize_inventory(self.medications)

        pd.testing.assert_frame_equal(original, self.medications)


if __name__ == "__main__":
    unittest.main()