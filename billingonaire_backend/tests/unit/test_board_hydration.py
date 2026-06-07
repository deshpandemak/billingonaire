import sys
from unittest.mock import MagicMock, patch


def test_hydrate_with_case_details_fills_order_fields_when_board_date_matches():
    with patch.dict(sys.modules, {"spacy": MagicMock()}):
        with patch("firebase_admin.firestore.client"):
            from Board import Board

    board = Board()
    board.case_store = MagicMock()
    board.case_store.build_case_ref.return_value = "WP/123/2026"
    board.case_store.get_case_details_map.return_value = {
        "WP/123/2026": {
            "case_ref": "WP/123/2026",
            "petitioner": "State of Maharashtra",
            "respondent": "XYZ Industries",
            "government_pleader": ["Pooja Deshpande"],
            "assigned_government_pleaders": ["A. Kulkarni"],
            "orders": [
                {
                    "board_date": "2026-03-13",
                    "order_link": "https://example.com/latest.pdf",
                    "order_status": "analysed",
                    "order_category": "ADJOURNED",
                    "order_date": "2026-03-13",
                    "government_pleader": ["Pooja Deshpande"],
                }
            ],
        }
    }

    records = [
        {
            "case_type": "WP",
            "case_no": "123",
            "case_year": "2026",
            "board_date": "2026-03-13",
            "order_link": None,
            "order_status": None,
            "order_category": None,
            "order_date": None,
            "order_petitioner": None,
            "order_respondent": None,
            "government_pleader": None,
        }
    ]

    hydrated = board._hydrate_with_case_details(records)
    row = hydrated[0]

    assert row["case_ref"] == "WP/123/2026"
    assert row["order_link"] == "https://example.com/latest.pdf"
    assert row["order_status"] == "analysed"
    assert row["order_category"] == "ADJOURNED"
    assert row["order_date"] == "2026-03-13"
    assert row["order_petitioner"] == "State of Maharashtra"
    assert row["order_respondent"] == "XYZ Industries"
    assert row["government_pleader"] == ["Pooja Deshpande"]
    assert row["assigned_government_pleaders"] == ["A. Kulkarni"]
    assert isinstance(row["order_history"], list)


def test_hydrate_no_order_fields_when_no_board_date_match():
    """
    When no order matches the record's board_date, all order display fields
    must be empty — board details are shown without order data.
    """
    with patch.dict(sys.modules, {"spacy": MagicMock()}):
        with patch("firebase_admin.firestore.client"):
            from Board import Board

    board = Board()
    board.case_store = MagicMock()
    board.case_store.build_case_ref.return_value = "WP/555/2026"
    board.case_store.get_case_details_map.return_value = {
        "WP/555/2026": {
            "case_ref": "WP/555/2026",
            "orders": [
                {
                    "board_date": "2026-03-10",
                    "order_link": "https://example.com/march.pdf",
                    "order_status": "analysed",
                    "order_category": "DISPOSED_OFF",
                    "order_date": "2026-03-10",
                    "government_pleader": ["Ms. A. Nadkarni, AGP"],
                }
            ],
        }
    }

    # Board date is May — no order exists for this date
    records = [
        {
            "case_type": "WP",
            "case_no": "555",
            "case_year": "2026",
            "board_date": "2026-05-08",
            "respondent_lawyer": "Ms. A. Nadkarni",
        }
    ]

    hydrated = board._hydrate_with_case_details(records)
    row = hydrated[0]

    # No order for 2026-05-08 — order display fields must be empty
    assert row["order_link"] is None
    assert row["order_date"] is None
    assert row["order_category"] is None
    assert row["government_pleader"] == []
