from case_data_store import CaseDataStore


class FakeDocSnapshot:
    def __init__(self, exists, data):
        self.exists = exists
        self._data = data

    def to_dict(self):
        return dict(self._data) if self._data else {}


class FakeDocumentRef:
    def __init__(self, storage, doc_id):
        self._storage = storage
        self._doc_id = doc_id

    def get(self):
        data = self._storage.get(self._doc_id)
        return FakeDocSnapshot(data is not None, data)

    def set(self, data, merge=False):
        if (
            merge
            and self._doc_id in self._storage
            and isinstance(self._storage[self._doc_id], dict)
        ):
            merged = dict(self._storage[self._doc_id])
            merged.update(data)
            self._storage[self._doc_id] = merged
        else:
            self._storage[self._doc_id] = dict(data)


class FakeQuery:
    def __init__(self, storage, field, op, values):
        self._storage = storage
        self._field = field
        self._op = op
        self._values = values

    def stream(self):
        if self._op != "in":
            return []
        result = []
        for doc_id, data in self._storage.items():
            if data.get(self._field) in self._values:
                result.append(FakeDocSnapshot(True, data))
        return result


class FakeCollectionRef:
    def __init__(self, storage):
        self._storage = storage

    def document(self, doc_id):
        return FakeDocumentRef(self._storage, doc_id)

    def where(self, field, op, values):
        return FakeQuery(self._storage, field, op, values)


class FakeFirestore:
    def __init__(self):
        self._collections = {}

    def collection(self, name):
        if name not in self._collections:
            self._collections[name] = {}
        return FakeCollectionRef(self._collections[name])

    def get_collection(self, name):
        return self._collections.get(name, {})


def test_upsert_from_board_entry_merges_pleaders_and_board_ids():
    db = FakeFirestore()
    store = CaseDataStore(db)

    case_doc_id = "WP-123-2024"
    db.collection("case-details").document(case_doc_id).set(
        {
            "case_ref": "WP/123/2024",
            "assigned_government_pleaders": ["Pooja Deshpande"],
            "board_assignment_ids": ["old-board"],
            "created_at": "2025-01-01T00:00:00",
        }
    )

    case_ref = store.upsert_from_board_entry(
        "new-board",
        {
            "case_type": "wp",
            "case_no": "123",
            "case_year": "2024",
            "board_date": "2026-03-12",
            "respondent_lawyer": "Pooja Deshpande",
            "additional_respondent_lawyers": ["A. Kulkarni"],
        },
    )

    assert case_ref == "WP/123/2024"

    updated_case = db.get_collection("case-details")[case_doc_id]
    assert updated_case["created_at"] == "2025-01-01T00:00:00"
    assert "old-board" in updated_case["board_assignment_ids"]
    assert "new-board" in updated_case["board_assignment_ids"]
    assert updated_case["assigned_government_pleaders"] == [
        "Pooja Deshpande",
        "A. Kulkarni",
    ]


def test_append_case_order_updates_existing_event_and_supports_normalized_party_keys():
    db = FakeFirestore()
    store = CaseDataStore(db)

    case_doc_id = "WP-200-2025"
    db.collection("case-details").document(case_doc_id).set(
        {
            "case_ref": "WP/200/2025",
            "orders": [
                {
                    "order_link": "https://example.com/order-1.pdf",
                    "order_status": "linked",
                    "order_date": "2026-03-11",
                }
            ],
            "petitioner": "",
            "respondent": "",
            "government_pleader": [],
        }
    )

    store.append_case_order(
        "WP/200/2025",
        {
            "order_link": "https://example.com/order-1.pdf",
            "order_status": "analysed",
            "order_category": "DISPOSED_OFF",
            "order_date": "2026-03-11",
            "petitioner": "State of Maharashtra",
            "respondent": "ABC Pvt Ltd",
            "government_pleader": ["Pooja Deshpande"],
        },
    )

    updated_case = db.get_collection("case-details")[case_doc_id]
    assert len(updated_case["orders"]) == 1
    assert updated_case["orders"][0]["order_status"] == "analysed"
    assert updated_case["latest_order_status"] == "analysed"
    assert updated_case["latest_order_category"] == "DISPOSED_OFF"
    assert updated_case["petitioner"] == "State of Maharashtra"
    assert updated_case["respondent"] == "ABC Pvt Ltd"
    assert updated_case["government_pleader"] == ["Pooja Deshpande"]


def test_get_case_details_map_returns_requested_refs():
    db = FakeFirestore()
    store = CaseDataStore(db)

    db.collection("case-details").document("WP-1-2025").set(
        {
            "case_ref": "WP/1/2025",
            "petitioner": "A",
        }
    )
    db.collection("case-details").document("WP-2-2025").set(
        {
            "case_ref": "WP/2/2025",
            "petitioner": "B",
        }
    )

    details_map = store.get_case_details_map(["WP/1/2025", "WP/2/2025", "WP/3/2025"])

    assert "WP/1/2025" in details_map
    assert "WP/2/2025" in details_map
    assert "WP/3/2025" not in details_map


def test_transition_lifecycle_applies_valid_transition_and_records_event():
    db = FakeFirestore()
    store = CaseDataStore(db)

    db.collection("case-details").document("WP-11-2026").set(
        {
            "case_ref": "WP/11/2026",
            "lifecycle_status": "board_ingested",
            "lifecycle_events": [],
        }
    )

    transition = store.transition_lifecycle(
        "WP/11/2026",
        "fetch_queued",
        reason="Ready for fetch",
        metadata={"source": "test"},
        event_type="queue_fetch",
    )

    assert transition["applied"] is True
    assert transition["from_status"] == "board_ingested"
    assert transition["to_status"] == "fetch_queued"

    updated_case = db.get_collection("case-details")["WP-11-2026"]
    assert updated_case["lifecycle_status"] == "fetch_queued"
    assert len(updated_case["lifecycle_events"]) == 1
    assert updated_case["lifecycle_events"][0]["event_type"] == "queue_fetch"
    assert updated_case["lifecycle_events"][0]["status"] == "fetch_queued"


def test_transition_lifecycle_rejects_invalid_transition_without_force():
    db = FakeFirestore()
    store = CaseDataStore(db)

    db.collection("case-details").document("WP-12-2026").set(
        {
            "case_ref": "WP/12/2026",
            "lifecycle_status": "board_ingested",
            "lifecycle_events": [],
        }
    )

    transition = store.transition_lifecycle("WP/12/2026", "analysed")

    assert transition["applied"] is False
    assert transition["reason"] == "invalid_transition"

    unchanged_case = db.get_collection("case-details")["WP-12-2026"]
    assert unchanged_case["lifecycle_status"] == "board_ingested"
    assert unchanged_case["lifecycle_events"] == []


def test_get_case_timeline_respects_limit():
    db = FakeFirestore()
    store = CaseDataStore(db)

    db.collection("case-details").document("WP-13-2026").set(
        {
            "case_ref": "WP/13/2026",
            "lifecycle_events": [
                {"event_type": "e1", "status": "board_ingested"},
                {"event_type": "e2", "status": "fetch_queued"},
                {"event_type": "e3", "status": "fetch_in_progress"},
            ],
        }
    )

    timeline = store.get_case_timeline("WP/13/2026", limit=2)

    assert len(timeline) == 2
    assert timeline[0]["event_type"] == "e2"
    assert timeline[1]["event_type"] == "e3"
