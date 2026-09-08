from datetime import datetime, timedelta, timezone

from app.main import _first_name, _is_expired


def test_first_name_takes_first_word_of_full_name():
    assert _first_name("Dhruv Atul Desai") == "Dhruv"


def test_first_name_handles_single_word_name():
    assert _first_name("Madonna") == "Madonna"


def test_first_name_falls_back_when_missing():
    assert _first_name(None) == "there"
    assert _first_name("") == "there"


def test_is_expired_true_for_past_deadline():
    candidate = {"assessment_deadline": datetime.now(timezone.utc) - timedelta(hours=1)}
    assert _is_expired(candidate) is True


def test_is_expired_false_for_future_deadline():
    candidate = {"assessment_deadline": datetime.now(timezone.utc) + timedelta(hours=1)}
    assert _is_expired(candidate) is False


def test_is_expired_false_when_no_deadline_set():
    assert _is_expired({}) is False
