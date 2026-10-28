"""Tests for resetting the Clinical lookup on role changes."""

import unittest
from unittest.mock import patch

from src.ui.navigation import (
    _reset_clinical_lookup_on_role_change,
)


class ClinicalNavigationTests(unittest.TestCase):
    def test_other_roles_clear_clinical_selection(self):
        for role in ("Procurement", "Warehouse", "Executive"):
            with self.subTest(role=role):
                state = {
                    "dashboard_role_tabs": role,
                    "clinical_medication_lookup": "MED003",
                }

                with patch(
                    "src.ui.navigation.st.session_state", state
                ):
                    _reset_clinical_lookup_on_role_change("Clinical")

                self.assertIsNone(
                    state["clinical_medication_lookup"]
                )

    def test_clinical_tab_keeps_current_selection(self):
        state = {
            "dashboard_role_tabs": "Clinical",
            "clinical_medication_lookup": "MED001",
        }

        with patch("src.ui.navigation.st.session_state", state):
            _reset_clinical_lookup_on_role_change("Clinical")

        self.assertEqual(
            state["clinical_medication_lookup"], "MED001"
        )

    def test_unrelated_state_is_preserved(self):
        state = {
            "dashboard_role_tabs": "Warehouse",
            "clinical_medication_lookup": "MED003",
            "other_view_setting": "keep",
        }

        with patch("src.ui.navigation.st.session_state", state):
            _reset_clinical_lookup_on_role_change("Clinical")

        self.assertEqual(
            state,
            {
                "dashboard_role_tabs": "Warehouse",
                "clinical_medication_lookup": None,
                "other_view_setting": "keep",
            },
        )


if __name__ == "__main__":
    unittest.main()