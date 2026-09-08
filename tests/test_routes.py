import base64
from unittest.mock import MagicMock, patch


def test_dashboard_requires_auth(client):
    res = client.get("/")
    assert res.status_code == 401


def test_dashboard_rejects_wrong_password(client):
    bad_auth = {
        "Authorization": "Basic " + base64.b64encode(b"recruiter:wrong").decode()
    }
    res = client.get("/", headers=bad_auth)
    assert res.status_code == 401


def test_dashboard_loads_with_correct_password(client, auth_header):
    res = client.get("/", headers=auth_header)
    assert res.status_code == 200


def test_create_job_requires_auth(client):
    res = client.post("/jobs", json={"title": "Engineer", "description": "..."})
    assert res.status_code == 401


def test_create_job_rejects_missing_fields(client, auth_header):
    res = client.post("/jobs", headers=auth_header, json={"title": "Engineer"})
    assert res.status_code == 400


def test_evaluate_interview_requires_auth(client):
    res = client.post("/evaluate-interview/some-id")
    assert res.status_code == 401


def test_delete_job_requires_auth(client):
    res = client.delete("/jobs/some-id")
    assert res.status_code == 401


def test_apply_page_shows_error_for_unknown_job(client):
    with patch("app.main.db") as mock_db:
        mock_doc = MagicMock()
        mock_doc.exists = False
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        res = client.get("/apply/nonexistent-job")
        assert b"not found" in res.data.lower()


def test_apply_rejects_submission_without_resume_file(client):
    with patch("app.main.db") as mock_db:
        mock_job = MagicMock()
        mock_job.exists = True
        mock_db.collection.return_value.document.return_value.get.return_value = mock_job

        res = client.post("/apply/some-job-id", data={})
        assert res.status_code == 400
        assert "resume" in res.get_json()["error"].lower()


def test_interview_page_shows_error_for_unknown_candidate(client):
    with patch("app.main.db") as mock_db:
        mock_doc = MagicMock()
        mock_doc.exists = False
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        res = client.get("/interview/nonexistent-candidate")
        assert b"not found" in res.data.lower()
