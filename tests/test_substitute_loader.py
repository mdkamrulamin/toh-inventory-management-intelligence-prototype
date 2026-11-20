"""Validation checks for the illustrative relationship fixture."""

import csv
from dataclasses import FrozenInstanceError
from hashlib import sha256
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from src.config import PROJECT_ROOT
from src.data.loader import load_medications
from src.data.substitute_loader import load_substitute_relationships
from src.data.substitute_schema import (
    RELATIONSHIP_COLUMNS,
    RELATIONSHIP_LABEL,
    RELATIONSHIP_PROVENANCE,
    RELATIONSHIP_VALIDATION_STATUS,
    SUBSTITUTE_INFORMATION_UNAVAILABLE,
)


class SubstituteLoaderTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

        self.path = (
            Path(self.directory.name)
            / "sample_substitute_relationships.csv"
        )
        self.medication_ids = tuple(
            f"MED{number:03d}"
            for number in range(1, 7)
        )

    def row(self, **changes):
        result = {
            "relationship_id": "SR-001",
            "source_medication_id": "MED003",
            "candidate_medication_id": "MED001",
            "relationship_label": RELATIONSHIP_LABEL,
            "relationship_validation_status": (
                RELATIONSHIP_VALIDATION_STATUS
            ),
            "provenance": RELATIONSHIP_PROVENANCE,
            "comparison_note": (
                "Same dosage form (tablet). Dose, strength "
                "and clinical suitability not assessed"
            ),
            "fixture_version": "v1",
        }
        result.update(changes)
        return result

    def write(self, rows, columns=RELATIONSHIP_COLUMNS):
        content = StringIO(newline="")
        writer = csv.DictWriter(
            content,
            fieldnames=columns,
        )
        writer.writeheader()

        for row in rows:
            writer.writerow(
                {
                    column: row.get(column, "")
                    for column in columns
                }
            )

        self.path.write_text(
            content.getvalue(),
            encoding="utf-8",
        )

    def load(self):
        return load_substitute_relationships(
            self.path,
            medication_ids=self.medication_ids,
        )

    def test_accepted_fixture_supports_both_medication_schemas(self):
        fixture_path = (
            PROJECT_ROOT
            / "data"
            / "sample_substitute_relationships.csv"
        )
        fixture_bytes = fixture_path.read_bytes()

        for filename in (
            "sample_medications.csv",
            "sample_medications_extended.csv",
        ):
            with self.subTest(dataset=filename):
                medication_path = PROJECT_ROOT / "data" / filename
                original_bytes = medication_path.read_bytes()
                medications = load_medications(medication_path)

                result = load_substitute_relationships(
                    fixture_path,
                    medication_ids=medications["medication_id"],
                )

                self.assertTrue(result.available)
                self.assertEqual(result.fixture_version, "v1")
                self.assertEqual(result.ignored_row_count, 0)
                self.assertEqual(len(result.relationships), 2)

                self.assertEqual(
                    [
                        (
                            row.relationship_id,
                            row.source_medication_id,
                            row.candidate_medication_id,
                        )
                        for row in result.relationships
                    ],
                    [
                        ("SR-001", "MED003", "MED001"),
                        ("SR-002", "MED001", "MED003"),
                    ],
                )

                self.assertEqual(
                    result.source_fingerprint,
                    sha256(fixture_bytes).hexdigest(),
                )
                self.assertEqual(
                    medication_path.read_bytes(),
                    original_bytes,
                )

        self.assertEqual(
            fixture_path.read_bytes(),
            fixture_bytes,
        )

    def test_unknown_self_and_malformed_identifiers_are_ignored(self):
        changes = (
            {"source_medication_id": "MED999"},
            {"candidate_medication_id": "MED999"},
            {"candidate_medication_id": "MED003"},
            {"relationship_id": ""},
            {"relationship_id": "SR-1"},
            {"relationship_id": "OTHER-001"},
        )

        for change in changes:
            with self.subTest(change=change):
                self.write([self.row(**change)])
                result = self.load()

                self.assertTrue(result.available)
                self.assertEqual(result.relationships, ())
                self.assertEqual(result.ignored_row_count, 1)
                self.assertTrue(result.issues)

    def test_fixed_labels_and_provenance_are_enforced(self):
        changes = (
            {"relationship_label": "Recommended alternative"},
            {
                "relationship_validation_status": (
                    "Clinically approved"
                )
            },
            {"provenance": ""},
            {"provenance": "An unsupported clinical source"},
        )

        for change in changes:
            with self.subTest(change=change):
                self.write([self.row(**change)])
                result = self.load()

                self.assertEqual(result.relationships, ())
                self.assertEqual(result.ignored_row_count, 1)

    def test_version_identifier_is_required_and_validated(self):
        for version in ("", "1", "v0", "v-1", "version one"):
            with self.subTest(version=version):
                self.write(
                    [self.row(fixture_version=version)]
                )
                result = self.load()

                self.assertEqual(result.relationships, ())
                self.assertEqual(result.ignored_row_count, 1)

        self.write([self.row(fixture_version="v2")])
        result = self.load()

        self.assertEqual(result.fixture_version, "v2")
        self.assertEqual(len(result.relationships), 1)

    def test_one_fixture_does_not_mix_versions(self):
        self.write(
            [
                self.row(),
                self.row(
                    relationship_id="SR-002",
                    source_medication_id="MED001",
                    candidate_medication_id="MED003",
                    fixture_version="v2",
                ),
            ]
        )

        result = self.load()

        self.assertEqual(result.fixture_version, "v1")
        self.assertEqual(len(result.relationships), 1)
        self.assertEqual(result.ignored_row_count, 1)

    def test_later_duplicate_relationship_id_is_ignored(self):
        self.write(
            [
                self.row(),
                self.row(
                    source_medication_id="MED001",
                    candidate_medication_id="MED003",
                ),
            ]
        )

        result = self.load()

        self.assertEqual(len(result.relationships), 1)
        self.assertEqual(
            result.relationships[0].source_medication_id,
            "MED003",
        )
        self.assertEqual(result.ignored_row_count, 1)

    def test_later_duplicate_directed_pair_is_ignored(self):
        self.write(
            [
                self.row(),
                self.row(relationship_id="SR-002"),
            ]
        )

        result = self.load()

        self.assertEqual(len(result.relationships), 1)
        self.assertEqual(
            result.relationships[0].relationship_id,
            "SR-001",
        )
        self.assertEqual(result.ignored_row_count, 1)

    def test_invalid_row_does_not_replace_a_later_valid_record(self):
        self.write(
            [
                self.row(candidate_medication_id="MED999"),
                self.row(),
            ]
        )

        result = self.load()

        self.assertEqual(len(result.relationships), 1)
        self.assertEqual(
            result.relationships[0].candidate_medication_id,
            "MED001",
        )
        self.assertEqual(result.ignored_row_count, 1)

    def test_directed_relationship_does_not_create_reverse_pair(self):
        self.write([self.row()])

        result = self.load()

        self.assertEqual(len(result.relationships), 1)
        self.assertFalse(
            any(
                row.source_medication_id == "MED001"
                for row in result.relationships
            )
        )

    def test_optional_comparison_note_can_be_missing(self):
        columns = tuple(
            column
            for column in RELATIONSHIP_COLUMNS
            if column != "comparison_note"
        )
        self.write([self.row()], columns=columns)

        result = self.load()

        self.assertTrue(result.available)
        self.assertEqual(len(result.relationships), 1)
        self.assertEqual(
            result.relationships[0].comparison_note,
            "",
        )

    def test_missing_unexpected_and_duplicate_headers_are_unavailable(self):
        missing_columns = tuple(
            column
            for column in RELATIONSHIP_COLUMNS
            if column != "provenance"
        )
        self.write([self.row()], columns=missing_columns)
        result = self.load()

        self.assertFalse(result.available)

        self.write(
            [self.row()],
            columns=(*RELATIONSHIP_COLUMNS, "recommendation_score"),
        )
        result = self.load()

        self.assertFalse(result.available)

        self.path.write_text(
            "relationship_id,relationship_id\nSR-001,SR-002\n",
            encoding="utf-8",
        )
        result = self.load()

        self.assertFalse(result.available)
        self.assertEqual(
            result.notice,
            SUBSTITUTE_INFORMATION_UNAVAILABLE,
        )

    def test_missing_or_unreadable_file_degrades_gracefully(self):
        result = self.load()

        self.assertFalse(result.available)
        self.assertEqual(result.relationships, ())
        self.assertIsNone(result.source_fingerprint)

        with patch(
            "src.data.substitute_loader.Path.read_bytes",
            side_effect=PermissionError("Unreadable test fixture"),
        ):
            result = self.load()

        self.assertFalse(result.available)
        self.assertEqual(
            result.notice,
            SUBSTITUTE_INFORMATION_UNAVAILABLE,
        )

    def test_empty_invalid_encoding_and_malformed_csv_are_unavailable(self):
        invalid_files = (
            b"",
            b"\xff\xfe\x00",
            b'relationship_id,source_medication_id\n"unfinished',
        )

        for content in invalid_files:
            with self.subTest(content=content):
                self.path.write_bytes(content)
                result = self.load()

                self.assertFalse(result.available)
                self.assertEqual(result.relationships, ())
                self.assertEqual(
                    result.source_fingerprint,
                    sha256(content).hexdigest(),
                )

    def test_bad_record_field_count_does_not_discard_valid_rows(self):
        self.write([self.row()])

        with self.path.open("a", encoding="utf-8") as output:
            output.write("SR-002,MED001\n")

        result = self.load()

        self.assertTrue(result.available)
        self.assertEqual(len(result.relationships), 1)
        self.assertEqual(result.ignored_row_count, 1)
        self.assertIn("field count", result.issues[0])

    def test_different_candidate_unit_is_not_a_relationship_failure(self):
        # MED002 is a capsule; MED003 is a tablet.
        # Relationship validation does not assess clinical equivalence.
        self.write(
            [
                self.row(
                    candidate_medication_id="MED002",
                    comparison_note=(
                        "Different stock units. "
                        "No conversion has been assessed."
                    ),
                )
            ]
        )

        result = self.load()

        self.assertEqual(len(result.relationships), 1)
        self.assertEqual(
            result.relationships[0].candidate_medication_id,
            "MED002",
        )

    def test_fixture_snapshots_are_immutable_and_fingerprinted(self):
        self.write([self.row()])
        first = self.load()

        with self.assertRaises(FrozenInstanceError):
            first.fixture_version = "v99"

        with self.assertRaises(FrozenInstanceError):
            first.relationships[0].candidate_medication_id = "MED002"

        self.write(
            [
                self.row(
                    comparison_note=(
                        "Revised synthetic comparison note."
                    )
                )
            ]
        )
        second = self.load()

        self.assertNotEqual(
            first.source_fingerprint,
            second.source_fingerprint,
        )
        self.assertNotEqual(
            first.relationships[0].comparison_note,
            second.relationships[0].comparison_note,
        )
        self.assertEqual(first.fixture_version, "v1")

    def test_header_only_fixture_has_no_invented_relationships(self):
        self.write([])

        result = self.load()

        self.assertTrue(result.available)
        self.assertEqual(result.relationships, ())
        self.assertIsNone(result.fixture_version)
        self.assertEqual(result.ignored_row_count, 0)

    def test_normalized_whitespace_and_optional_blank_note(self):
        self.write(
            [
                self.row(
                    relationship_id=" SR-001 ",
                    source_medication_id=" MED003 ",
                    candidate_medication_id=" MED001 ",
                    comparison_note=" ",
                )
            ]
        )

        result = self.load()

        self.assertEqual(len(result.relationships), 1)
        self.assertEqual(
            result.relationships[0].relationship_id,
            "SR-001",
        )
        self.assertEqual(
            result.relationships[0].comparison_note,
            "",
        )


if __name__ == "__main__":
    unittest.main()