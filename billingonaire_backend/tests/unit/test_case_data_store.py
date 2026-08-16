from datetime import datetime, timedelta

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

    def get(self, transaction=None):
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


class FakeTransaction:
    """Minimal stand-in satisfying the protocol firestore.transactional's
    generated wrapper expects (_clean_up/_begin/_id/_commit/_rollback), plus
    a .set() that applies synchronously -- adequate for single-threaded
    tests where "concurrent" claims are simulated as sequential calls."""

    _read_only = False
    _max_attempts = 1

    def __init__(self):
        self._id = 1

    def _clean_up(self):
        pass

    def _begin(self, retry_id=None):
        pass

    def _commit(self):
        pass

    def _rollback(self):
        pass

    def set(self, ref, data, merge=False):
        ref.set(data, merge=merge)


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

    def get_all(self, doc_refs):
        return [ref.get() for ref in doc_refs]

    def transaction(self):
        return FakeTransaction()


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


def test_set_order_compliance_directives_updates_matching_order_by_link():
    db = FakeFirestore()
    store = CaseDataStore(db)

    case_doc_id = "WP-201-2025"
    db.collection("case-details").document(case_doc_id).set(
        {
            "case_ref": "WP/201/2025",
            "orders": [
                {
                    "order_link": "https://example.com/order-1.pdf",
                    "order_status": "analysed",
                    "order_category": "HEARD_AND_ADJOURNED",
                    "order_date": "2026-07-08",
                }
            ],
        }
    )

    directives = [
        {
            "directive_type": "FILE_REPLY_AFFIDAVIT",
            "description": "file reply affidavit",
            "deadline_date": "2026-08-13",
        }
    ]
    found = store.set_order_compliance_directives(
        "WP/201/2025", "https://example.com/order-1.pdf", "2026-07-08", directives
    )

    assert found is True
    updated_order = db.get_collection("case-details")[case_doc_id]["orders"][0]
    assert updated_order["compliance_directives"] == directives
    assert "compliance_scanned_at" in updated_order
    # Everything else about the order entry is untouched.
    assert updated_order["order_category"] == "HEARD_AND_ADJOURNED"
    assert updated_order["order_status"] == "analysed"


def test_set_order_compliance_directives_matches_by_date_when_link_missing():
    db = FakeFirestore()
    store = CaseDataStore(db)

    case_doc_id = "WP-202-2025"
    db.collection("case-details").document(case_doc_id).set(
        {
            "case_ref": "WP/202/2025",
            "orders": [{"order_link": None, "order_date": "2026-07-08"}],
        }
    )

    found = store.set_order_compliance_directives("WP/202/2025", None, "2026-07-08", [])

    assert found is True
    updated_order = db.get_collection("case-details")[case_doc_id]["orders"][0]
    assert updated_order["compliance_directives"] == []


def test_set_order_compliance_directives_is_a_noop_when_no_order_matches():
    """A compliance scan only ever targets an already-analysed order -- a
    missing match means the caller has the wrong case/date, and this must
    never create a phantom order entry with no order_status/category."""
    db = FakeFirestore()
    store = CaseDataStore(db)

    case_doc_id = "WP-203-2025"
    db.collection("case-details").document(case_doc_id).set(
        {
            "case_ref": "WP/203/2025",
            "orders": [
                {
                    "order_link": "https://example.com/other.pdf",
                    "order_date": "2026-01-01",
                }
            ],
        }
    )

    found = store.set_order_compliance_directives(
        "WP/203/2025", "https://example.com/order-1.pdf", "2026-07-08", []
    )

    assert found is False
    assert len(db.get_collection("case-details")[case_doc_id]["orders"]) == 1


def test_set_order_compliance_directives_is_a_noop_when_case_does_not_exist():
    db = FakeFirestore()
    store = CaseDataStore(db)

    found = store.set_order_compliance_directives(
        "WP/999/2025", "https://example.com/order-1.pdf", "2026-07-08", []
    )

    assert found is False


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


def test_fetch_in_progress_can_reach_manual_review_required():
    """Regression guard for the bug where the fetch pipeline's inline
    analysis (_analyze_order_with_api_metadata) tries
    fetch_in_progress -> analysis_in_progress -> manual_review_required
    while the case is still at fetch_in_progress (it never passes through
    fetch_succeeded). Before this was added, the transition was silently
    rejected -- no exception, just a logged warning -- and the case stayed
    stuck at fetch_in_progress forever, invisible to every status view since
    that state buckets to "working", not "attention"."""
    db = FakeFirestore()
    store = CaseDataStore(db)

    db.collection("case-details").document("WP-13-2026").set(
        {
            "case_ref": "WP/13/2026",
            "lifecycle_status": "fetch_in_progress",
            "lifecycle_events": [],
        }
    )

    started = store.transition_lifecycle("WP/13/2026", "analysis_in_progress")
    assert started["applied"] is True

    routed = store.transition_lifecycle(
        "WP/13/2026", "manual_review_required", reason="Low confidence"
    )
    assert routed["applied"] is True

    updated_case = db.get_collection("case-details")["WP-13-2026"]
    assert updated_case["lifecycle_status"] == "manual_review_required"


def test_fetch_in_progress_can_reach_analysed_directly():
    """The high-confidence leg of the same inline-analysis call: this edge
    already existed and must keep working."""
    db = FakeFirestore()
    store = CaseDataStore(db)

    db.collection("case-details").document("WP-14-2026").set(
        {
            "case_ref": "WP/14/2026",
            "lifecycle_status": "fetch_in_progress",
            "lifecycle_events": [],
        }
    )

    transition = store.transition_lifecycle("WP/14/2026", "analysed")
    assert transition["applied"] is True


def test_terminal_fetch_failure_can_still_record_a_concurrent_success():
    """Several board rows can share one case_ref, so two workers routinely
    process the same case at once. When one gave up (worker timeout ->
    fetch_failed_terminal) while the other went on to download and analyse
    the order successfully, the winner's transition to `analysed` was
    rejected and its completed work silently discarded -- leaving the case
    in "needs attention" with a perfectly good analysed order on file.
    A terminal failure must stop auto-retries, not block recording success."""
    db = FakeFirestore()
    store = CaseDataStore(db)

    db.collection("case-details").document("WP-15540-2025").set(
        {
            "case_ref": "WP/15540/2025",
            "lifecycle_status": "fetch_failed_terminal",
            "lifecycle_events": [],
        }
    )

    recovered = store.transition_lifecycle("WP/15540/2025", "analysed")
    assert recovered["applied"] is True
    assert (
        db.get_collection("case-details")["WP-15540-2025"]["lifecycle_status"]
        == "analysed"
    )


def test_terminal_fetch_failure_still_blocks_going_back_to_retryable():
    """The other half of the contract: "terminal" must keep meaning "stop
    automatically retrying this", so the failure -> retryable edge stays
    closed even though forward progress is now allowed."""
    db = FakeFirestore()
    store = CaseDataStore(db)

    db.collection("case-details").document("WP-15572-2025").set(
        {
            "case_ref": "WP/15572/2025",
            "lifecycle_status": "fetch_failed_terminal",
            "lifecycle_events": [],
        }
    )

    rejected = store.transition_lifecycle("WP/15572/2025", "fetch_failed_retryable")
    assert rejected["applied"] is False
    assert rejected["reason"] == "invalid_transition"


def test_terminal_analysis_failure_can_still_record_a_concurrent_success():
    """Same reasoning as the fetch-side terminal state."""
    db = FakeFirestore()
    store = CaseDataStore(db)

    db.collection("case-details").document("WP-16-2026").set(
        {
            "case_ref": "WP/16/2026",
            "lifecycle_status": "analysis_failed_terminal",
            "lifecycle_events": [],
        }
    )

    assert store.transition_lifecycle("WP/16/2026", "analysed")["applied"] is True


def test_claim_for_processing_succeeds_once_then_fails_on_replay():
    """Simulates two Cloud Run instances racing to claim the same
    fetch_queued case: only the first claim (sequential, since the fake is
    single-threaded) applies; a second attempt against the now-changed
    status must be rejected, not double-processed."""
    db = FakeFirestore()
    store = CaseDataStore(db)
    db.collection("case-details").document("WP-20-2026").set(
        {
            "case_ref": "WP/20/2026",
            "lifecycle_status": "fetch_queued",
            "lifecycle_events": [],
        }
    )

    first = store.claim_for_processing(
        "WP/20/2026", "fetch_in_progress", from_statuses={"fetch_queued"}
    )
    assert first["applied"] is True
    assert first["from_status"] == "fetch_queued"

    second = store.claim_for_processing(
        "WP/20/2026", "fetch_in_progress", from_statuses={"fetch_queued"}
    )
    assert second["applied"] is False
    assert second["reason"] == "not_claimable"

    updated_case = db.get_collection("case-details")["WP-20-2026"]
    assert updated_case["lifecycle_status"] == "fetch_in_progress"


def test_claim_for_processing_reclaims_stale_in_progress_case():
    db = FakeFirestore()
    store = CaseDataStore(db)
    stale_timestamp = (datetime.now() - timedelta(minutes=30)).isoformat()
    db.collection("case-details").document("WP-21-2026").set(
        {
            "case_ref": "WP/21/2026",
            "lifecycle_status": "fetch_in_progress",
            "lifecycle_status_updated_at": stale_timestamp,
            "lifecycle_events": [],
        }
    )

    claim = store.claim_for_processing(
        "WP/21/2026",
        "fetch_in_progress",
        from_statuses={"fetch_queued"},
        stale_after_minutes=10,
    )

    assert claim["applied"] is True
    assert claim["from_status"] == "fetch_in_progress"


def test_claim_for_processing_does_not_reclaim_fresh_in_progress_case():
    db = FakeFirestore()
    store = CaseDataStore(db)
    fresh_timestamp = (datetime.now() - timedelta(minutes=1)).isoformat()
    db.collection("case-details").document("WP-22-2026").set(
        {
            "case_ref": "WP/22/2026",
            "lifecycle_status": "fetch_in_progress",
            "lifecycle_status_updated_at": fresh_timestamp,
            "lifecycle_events": [],
        }
    )

    claim = store.claim_for_processing(
        "WP/22/2026",
        "fetch_in_progress",
        from_statuses={"fetch_queued"},
        stale_after_minutes=10,
    )

    assert claim["applied"] is False
    assert claim["reason"] == "not_claimable"


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
