import sys
from unittest.mock import MagicMock, patch


def test_hydrate_with_case_details_fills_missing_order_fields():
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
            "latest_order_link": "https://example.com/latest.pdf",
            "latest_order_status": "analysed",
            "latest_order_category": "ADJOURNED",
            "latest_order_date": "2026-03-13",
            "orders": [
                {
                    "order_link": "https://example.com/latest.pdf",
                    "order_status": "analysed",
                    "order_category": "ADJOURNED",
                    "order_date": "2026-03-13",
                }
            ],
        }
    }

    records = [
        {
            "case_type": "WP",
            "case_no": "123",
            "case_year": "2026",
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


def test_hydrate_with_case_details_overrides_with_normalized_latest_order_fields():
    with patch.dict(sys.modules, {"spacy": MagicMock()}):
        with patch("firebase_admin.firestore.client"):
            from Board import Board

    board = Board()
    board.case_store = MagicMock()
    board.case_store.build_case_ref.return_value = "WP/555/2026"
    board.case_store.get_case_details_map.return_value = {
        "WP/555/2026": {
            "case_ref": "WP/555/2026",
            "latest_order_link": "https://example.com/from-store.pdf",
            "latest_order_status": "analysed",
            "latest_order_category": "DISPOSED_OFF",
            "latest_order_date": "2026-03-10",
            "orders": [],
        }
    }

    records = [
        {
            "case_type": "WP",
            "case_no": "555",
            "case_year": "2026",
            "order_link": "https://example.com/already-set.pdf",
            "order_status": "linked",
            "order_category": "ADJOURNED",
            "order_date": "2026-03-12",
        }
    ]

    hydrated = board._hydrate_with_case_details(records)
    row = hydrated[0]

    assert row["order_link"] == "https://example.com/from-store.pdf"
    assert row["order_status"] == "analysed"
    assert row["order_category"] == "DISPOSED_OFF"
    assert row["order_date"] == "2026-03-10"
