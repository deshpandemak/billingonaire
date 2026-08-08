"""The exported Excel bill must match the office's reference format.

build_bill_workbook is a pure function (no Firestore, no auth, no I/O) split
out of the /bills/export/excel route specifically so this could be tested
directly: give it entries, get back an openpyxl Workbook, assert on it.

The specific values asserted here (fonts, sizes, column widths, column
headers, footer labels) were read directly off a reference bill the office
confirmed is the correct, final format — see the "Match the Excel bill
export" plan for the full comparison. Changing any of these is a formatting
regression unless the reference format itself changes.
"""

import os

os.environ.setdefault("TESTING", "true")

from main import build_bill_workbook  # noqa: E402

LONG_PARTY_NAME = (
    "VAJRESHWARI YOGINIDEVI SANSTHAN THROUGH ITS TRUSTEE SHRI.RAJU SHANTARAM "
    "PATIL Versus STATE OF MAHARASHTRA THR REVENUE AND FOREST DEPT."
)


def _entries():
    return [
        {
            "date": "2026-04-01",
            "case_detail": "WP/10000/2017",
            "results": "ADJOURNED",
            "parties_name": "SHRI A Versus SHRI B",
            "fees_rs": 1250,
        },
        {
            "date": "2026-04-01",
            "case_detail": "WP/12489/2023",
            "results": "HEARD & ADJN.",
            "parties_name": "A Versus B",
            "fees_rs": 1875,
        },
        {
            "date": "2026-04-02",
            "case_detail": "WP/1932/2026",
            "results": "WP DISPOSED OF",
            "parties_name": LONG_PARTY_NAME,
            "fees_rs": 2500,
        },
    ]


def _build():
    return build_bill_workbook(
        _entries(),
        agp_name="SMT POOJA JOSHI DESHPANDE",
        bill_number="BILL/2026/010",
        period_str="APRIL 2026 - JUNE 2026",
    )


class TestColumnStructure:
    """Reference bill has 6 columns, not the legacy 8 (CASE TYPE/NO/YEAR
    collapsed into one CASE DETAILS column)."""

    def test_six_columns_not_eight(self):
        ws = _build().active
        assert ws.max_column == 6

    def test_header_row_labels_and_order(self):
        ws = _build().active
        header_row = 6
        labels = [ws.cell(row=header_row, column=c).value for c in range(1, 7)]
        assert labels == [
            "SR. NO.",
            "DATE",
            "CASE DETAILS",
            "RESULTS",
            "PARTIES NAME",
            "FEES (RS.)",
        ]

    def test_case_details_column_holds_the_combined_case_ref(self):
        ws = _build().active
        assert ws["C7"].value == "WP/10000/2017"

    def test_column_widths_match_reference(self):
        ws = _build().active
        expected = {"A": 10, "B": 20.43, "C": 28.86, "D": 29.0, "E": 58.57, "F": 15.0}
        for col, width in expected.items():
            assert ws.column_dimensions[col].width == width


class TestTypography:
    """Reference: Times New Roman 18pt everywhere, bold only on the header
    row. Old code used Calibri-default body text with bold title/header."""

    def test_every_sampled_cell_is_times_new_roman_18pt(self):
        ws = _build().active
        for coord in ["A1", "A2", "A3", "A5", "A6", "A7", "C7", "E7", "F7"]:
            font = ws[coord].font
            assert font.name == "Times New Roman", coord
            assert font.size == 18, coord

    def test_bold_only_on_the_header_row(self):
        ws = _build().active
        for c in range(1, 7):
            assert ws.cell(row=6, column=c).font.bold is True

        non_bold_cells = ["A1", "A2", "A3", "A5", "A7", "C7", "E7"]
        for coord in non_bold_cells:
            assert ws[coord].font.bold is not True, coord


class TestBorders:
    """Reference borders every cell in the merged header block, not just the
    merge's anchor cell — otherwise the box outline breaks visually."""

    def test_every_cell_in_title_merge_has_a_border(self):
        ws = _build().active
        for c in range(1, 7):
            cell = ws.cell(row=1, column=c)
            b = cell.border
            assert b.top.style == "thin", cell.coordinate
            assert b.bottom.style == "thin", cell.coordinate
        assert ws.cell(row=1, column=1).border.left.style == "thin"
        assert ws.cell(row=1, column=6).border.right.style == "thin"

    def test_data_cells_are_bordered(self):
        ws = _build().active
        for c in range(1, 7):
            cell = ws.cell(row=7, column=c)
            assert cell.border.left.style == "thin"
            assert cell.border.right.style == "thin"


class TestHeaderWording:
    def test_title_includes_agp_prefix_and_name(self):
        ws = _build().active
        assert ws["A1"].value == (
            "STATEMENT OF PROFESSIONAL FEES BILL OF AGP SMT POOJA JOSHI DESHPANDE"
        )

    def test_government_resolution_uses_slash_separators(self):
        """Reference uses '/' throughout ('VIDE:/', 'MEETING/GPH/2023/.../D/14',
        'DATED/30TH'); the legacy code used '-' in the same spots."""
        ws = _build().active
        text = ws["A3"].value
        assert "SANCTIONED VIDE:/" in text
        assert "MEETING/GPH/2023/C.R.29/D/14" in text
        assert "DATED/30TH OCTOBER, 2023" in text
        assert "VIDE:-" not in text

    def test_months_and_bill_number_on_one_row_no_label_on_number(self):
        ws = _build().active
        assert ws["A4"].value == "MONTHS : APRIL 2026 - JUNE 2026"
        assert ws["E4"].value == "BILL/2026/010"
        assert "BILL NO" not in str(ws["E4"].value)

    def test_declaration_cites_the_bill_number(self):
        ws = _build().active
        assert "bill no. BILL/2026/010" in ws["A5"].value


class TestRowHeights:
    """'Content gap': rows must be tall enough for their wrapped text, and
    should scale with how much text is actually in them."""

    def test_long_party_name_row_is_taller_than_short_one(self):
        ws = _build().active
        short_row_height = ws.row_dimensions[7].height  # "A Versus B"-ish
        long_row_height = ws.row_dimensions[9].height  # LONG_PARTY_NAME
        assert long_row_height > short_row_height

    def test_no_row_is_shorter_than_one_line(self):
        ws = _build().active
        for r in range(1, 10):
            assert ws.row_dimensions[r].height >= 23.25

    def test_a_short_and_a_long_case_produce_different_heights(self):
        """Regression guard: heights must be computed per row, not a single
        constant copied onto every row."""
        ws = _build().active
        heights = {ws.row_dimensions[r].height for r in (1, 6, 7, 9)}
        assert len(heights) > 1


class TestFooter:
    """Entirely missing before this change — old code just wrote one
    'TOTAL:' row and stopped."""

    def test_gross_amount_is_a_live_formula_over_the_fee_column(self):
        ws = _build().active
        # header(6) + 3 data rows -> data occupies rows 7-9, footer starts at 10
        gross_row = next(
            r for r in range(7, 20) if ws.cell(row=r, column=4).value == "GROSS AMOUNT"
        )
        formula = ws.cell(row=gross_row, column=5).value
        assert formula == "=SUM(F7:F9)"

    def test_ceiling_tds_and_net_amount_are_left_blank(self):
        """These depend on the annual ceiling and cumulative prior claims,
        which this system does not track -- must stay blank for manual
        completion, not guessed at."""
        ws = _build().active
        labels_to_rows = {}
        for r in range(7, 20):
            v = ws.cell(row=r, column=4).value
            if v in ("Fees Earn Due To Ceiling", "TOTAL TDS 10%", "NET AMOUNT"):
                labels_to_rows[v] = r
        assert set(labels_to_rows) == {
            "Fees Earn Due To Ceiling",
            "TOTAL TDS 10%",
            "NET AMOUNT",
        }
        for label, r in labels_to_rows.items():
            assert ws.cell(row=r, column=5).value is None, label

    def test_signature_block_has_verified_and_correct(self):
        ws = _build().active
        found = any(
            ws.cell(row=r, column=1).value == "VERIFIED & CORRECT" for r in range(7, 25)
        )
        assert found

    def test_signature_uses_the_agp_name(self):
        ws = _build().active
        found = any(
            ws.cell(row=r, column=5).value == "(SMT POOJA JOSHI DESHPANDE)"
            for r in range(7, 25)
        )
        assert found

    def test_role_title_spelling_is_corrected_not_the_reference_typo(self):
        """The reference bill has 'Assisstant Governtment Pleader' -- a typo.
        AGP terminology was standardized elsewhere this session; don't
        reproduce the misspelling here."""
        ws = _build().active
        all_text = " ".join(
            str(ws.cell(row=r, column=c).value or "")
            for r in range(1, ws.max_row + 1)
            for c in range(1, 7)
        )
        assert "Assistant Government Pleader" in all_text
        assert "Assisstant" not in all_text
        assert "Governtment" not in all_text

    def test_place_defaults_to_mumbai(self):
        ws = _build().active
        found = any(ws.cell(row=r, column=2).value == "Mumbai" for r in range(7, 25))
        assert found


class TestDataIntegrity:
    def test_fees_column_holds_numbers_not_strings(self):
        ws = _build().active
        for r in (7, 8, 9):
            assert isinstance(ws.cell(row=r, column=6).value, (int, float))

    def test_serial_numbers_are_sequential_from_one(self):
        ws = _build().active
        assert [ws.cell(row=r, column=1).value for r in (7, 8, 9)] == [1, 2, 3]

    def test_missing_case_detail_falls_back_to_type_no_year(self):
        """Older saved bills may predate the case_detail field."""
        entries = [
            {
                "date": "2026-04-01",
                "case_type": "WP",
                "case_no": "999",
                "case_year": "2026",
                "results": "ADJOURNED",
                "parties_name": "X Versus Y",
                "fees_rs": 1250,
            }
        ]
        ws = build_bill_workbook(
            entries, "SMT TEST", "BILL/2026/001", "APRIL 2026"
        ).active
        assert ws["C7"].value == "WP/999/2026"

    def test_all_entries_produce_a_workbook_even_when_empty(self):
        ws = build_bill_workbook([], "SMT TEST", "BILL/2026/001", "APRIL 2026").active
        assert ws["A6"].value == "SR. NO."
