import db


def test_upsert_and_get_scheduled_review_reminder(test_db):
    del test_db
    concept_id = db.add_concept("Reminder Concept", "Desc")

    db.upsert_scheduled_review_reminder(
        concept_id,
        "What is the key idea?",
        first_sent_at="2026-04-27 09:00:00",
        last_sent_at="2026-04-27 09:00:00",
        reminder_count=0,
    )

    reminder = db.get_scheduled_review_reminder()

    assert reminder is not None
    assert reminder["concept_id"] == concept_id
    assert reminder["question_text"] == "What is the key idea?"
    assert reminder["status"] == "pending"
    assert reminder["reminder_count"] == 0


def test_resolve_scheduled_review_reminder_hides_pending_row(test_db):
    del test_db
    concept_id = db.add_concept("Resolved Reminder", "Desc")
    db.upsert_scheduled_review_reminder(
        concept_id,
        "Why is this due?",
        first_sent_at="2026-04-27 09:00:00",
        last_sent_at="2026-04-27 09:00:00",
    )

    db.resolve_scheduled_review_reminder("answered")

    assert db.get_scheduled_review_reminder() is None

    resolved = db.get_scheduled_review_reminder(include_resolved=True)
    assert resolved is not None
    assert resolved["status"] == "answered"