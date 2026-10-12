"""Regression checks for the original and extended medication CSVs."""

import tempfile
import unittest
from pathlib import Path

import pandas as pd
from pandas.api.types import (
    is_datetime64_any_dtype,
    is_numeric_dtype,
)

from src.config import PROJECT_ROOT
from src.data.loader import load_medications


class MedicationLoaderTests(unittest.TestCase):
    def setUp(self):
        """Use temporary CSVs so tests never edit the demonstration files."""
        self.original_path = PROJECT_ROOT / "data" / "sample_medications.csv"
        self.extended_path = (
            PROJECT_ROOT / "data" / "sample_medications_extended.csv"
        )
        self.raw = pd.read_csv(self.extended_path, dtype="string")

        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.case_path = Path(self.temporary_directory.name) / "case.csv"

    def load_case(self, frame):
        """Write a temporary test input and load it through the public loader."""
        frame.to_csv(self.case_path, index=False)
        return load_medications(self.case_path)

    def test_original_and_extended_preserve_existing_values(self):
        original = load_medications(self.original_path)
        extended = load_medications(self.extended_path)

        self.assertEqual(original.shape, (6, 10))
        self.assertEqual(extended.shape, (6, 16))

        pd.testing.assert_frame_equal(
            original,
            extended[list(original.columns)],
        )

        sample = extended.set_index("medication_id").loc["MED001"]
        self.assertEqual(sample["current_stock"], 1200)
        self.assertEqual(sample["counted_stock"], 1195)

    def test_optional_fields_have_correct_types(self):
        extended = load_medications(self.extended_path)

        for column in (
            "reorder_point",
            "safety_stock_level",
            "lead_time_days",
            "counted_stock",
        ):
            with self.subTest(column=column):
                self.assertTrue(is_numeric_dtype(extended[column]))

        for column in ("expiry_date", "last_count_date"):
            with self.subTest(column=column):
                self.assertTrue(is_datetime64_any_dtype(extended[column]))

    def test_blank_optional_values_remain_missing(self):
        frame = self.raw.copy()
        optional_columns = (
            "primary_location",
            "reorder_point",
            "safety_stock_level",
            "lead_time_days",
            "last_count_date",
            "counted_stock",
        )

        for column in optional_columns:
            frame.loc[0, column] = pd.NA

        loaded = self.load_case(frame)

        for column in optional_columns:
            with self.subTest(column=column):
                self.assertTrue(pd.isna(loaded.loc[0, column]))

        self.assertEqual(loaded.loc[0, "current_stock"], 1200)

    def test_invalid_numbers_are_rejected(self):
        numeric_columns = (
            "current_stock",
            "unit_cost",
            "average_monthly_consumption",
            "reorder_point",
            "safety_stock_level",
            "lead_time_days",
            "counted_stock",
        )

        for column in numeric_columns:
            for invalid_value in ("-1", "not-a-number", "inf"):
                with self.subTest(column=column, value=invalid_value):
                    frame = self.raw.copy()
                    frame.loc[0, column] = invalid_value

                    with self.assertRaisesRegex(ValueError, column):
                        self.load_case(frame)

    def test_invalid_dates_are_rejected(self):
        for column in ("expiry_date", "last_count_date"):
            for invalid_value in ("2026-02-30", "12/10/2026"):
                with self.subTest(column=column, value=invalid_value):
                    frame = self.raw.copy()
                    frame.loc[0, column] = invalid_value

                    with self.assertRaisesRegex(ValueError, column):
                        self.load_case(frame)

    def test_missing_current_stock_is_rejected(self):
        frame = self.raw.copy()
        frame.loc[0, "current_stock"] = pd.NA

        with self.assertRaisesRegex(ValueError, "current_stock"):
            self.load_case(frame)

    def test_conflicting_status_is_rejected(self):
        frame = self.raw.copy()
        frame.loc[0, "status"] = "Out of stock"

        with self.assertRaisesRegex(ValueError, "status conflicts"):
            self.load_case(frame)

    def test_missing_status_is_derived(self):
        frame = self.raw.drop(columns="status")
        loaded = self.load_case(frame).set_index("medication_id")

        self.assertEqual(loaded.loc["MED001", "status"], "In stock")
        self.assertEqual(loaded.loc["MED003", "status"], "Out of stock")

    def test_leading_zero_identifier_is_preserved(self):
        frame = self.raw.copy()
        frame.loc[0, "medication_id"] = "000001"

        loaded = self.load_case(frame)
        self.assertEqual(loaded.loc[0, "medication_id"], "000001")

    def test_duplicate_identifiers_are_rejected(self):
        frame = self.raw.copy()
        frame.loc[1, "medication_id"] = frame.loc[0, "medication_id"]

        with self.assertRaisesRegex(ValueError, "unique"):
            self.load_case(frame)

    def test_missing_required_column_is_rejected(self):
        frame = self.raw.drop(columns="medication_name")

        with self.assertRaisesRegex(ValueError, "Missing required"):
            self.load_case(frame)


if __name__ == "__main__":
    unittest.main()