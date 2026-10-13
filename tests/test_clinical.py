"""Checks for stock-aware, nonpersistent Clinical request previews."""

import unittest

import pandas as pd

from src.services.clinical import build_clinical_request_preview


class ClinicalRequestPreviewTests(unittest.TestCase):
    def setUp(self):
        self.medication = pd.Series(
            {
                "medication_id": "MED001",
                "medication_name": "Paracetamol 500 mg",
                "current_stock": 1200,
                "stock_unit": "tablet",
                "counted_stock": 1195,
            }
        )

    def test_zero_stock_requires_review(self):
        medication = self.medication.copy()
        medication["medication_id"] = "MED003"
        medication["medication_name"] = "Ibuprofen 200 mg"
        medication["current_stock"] = 0

        preview = build_clinical_request_preview(medication, 3)

        self.assertEqual(preview.outcome, "out_of_stock")
        self.assertEqual(preview.recorded_stock, 0)
        self.assertEqual(preview.requested_quantity, 3)
        self.assertEqual(preview.medication_id, "MED003")

    def test_sufficient_recorded_stock(self):
        preview = build_clinical_request_preview(self.medication, 3)

        self.assertEqual(preview.outcome, "sufficient")
        self.assertEqual(preview.recorded_stock, 1200)
        self.assertEqual(preview.requested_quantity, 3)

    def test_quantity_equal_to_stock_is_sufficient(self):
        preview = build_clinical_request_preview(
            self.medication,
            1200,
        )

        self.assertEqual(preview.outcome, "sufficient")

    def test_quantity_above_stock_requires_review(self):
        preview = build_clinical_request_preview(
            self.medication,
            1500,
        )

        self.assertEqual(preview.outcome, "insufficient")
        self.assertEqual(preview.requested_quantity, 1500)
        self.assertEqual(preview.recorded_stock, 1200)

    def test_selected_identity_and_stock_unit_are_preserved(self):
        for stock_unit in ("capsule", "vial"):
            with self.subTest(stock_unit=stock_unit):
                medication = self.medication.copy()
                medication["medication_id"] = "DEMO"
                medication["medication_name"] = "Selected demo medicine"
                medication["stock_unit"] = stock_unit

                preview = build_clinical_request_preview(
                    medication,
                    3,
                )

                self.assertEqual(preview.medication_id, "DEMO")
                self.assertEqual(
                    preview.medication_name,
                    "Selected demo medicine",
                )
                self.assertEqual(preview.stock_unit, stock_unit)
                self.assertEqual(preview.requested_quantity, 3)

    def test_invalid_quantities_are_rejected(self):
        for quantity in (None, 0, -1, 1.5, "3", True, pd.NA):
            with self.subTest(quantity=quantity):
                with self.assertRaisesRegex(
                    ValueError,
                    "positive whole-number",
                ):
                    build_clinical_request_preview(
                        self.medication,
                        quantity,
                    )

    def test_historical_count_does_not_replace_recorded_stock(self):
        medication = self.medication.copy()
        medication["current_stock"] = 0
        medication["counted_stock"] = 1500

        preview = build_clinical_request_preview(medication, 3)

        self.assertEqual(preview.outcome, "out_of_stock")
        self.assertEqual(preview.recorded_stock, 0)

    def test_source_record_is_not_modified(self):
        original = self.medication.copy(deep=True)

        build_clinical_request_preview(self.medication, 3)

        pd.testing.assert_series_equal(self.medication, original)


if __name__ == "__main__":
    unittest.main()