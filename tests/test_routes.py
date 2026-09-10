from unittest.mock import MagicMock, patch


def test_dashboard_redirects_when_not_logged_in(client):
    res = client.get("/")
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]


def test_dashboard_loads_when_logged_in(logged_in_client):
    res = logged_in_client.get("/")
    assert res.status_code == 200


def test_google_auth_rejects_invalid_credential(client):
    res = client.post("/auth/google", json={"credential": "not-a-real-jwt"})
    assert res.status_code == 401


def test_create_job_requires_auth(client):
    res = client.post("/jobs", json={"title": "Engineer", "description": "..."})
    assert res.status_code == 401


def test_create_job_rejects_missing_fields(logged_in_client):
    res = logged_in_client.post("/jobs", json={"title": "Engineer"})
    assert res.status_code == 400


def test_evaluate_interview_requires_auth(client):
    res = client.post("/evaluate-interview/some-id")
    assert res.status_code == 401


def test_delete_job_requires_auth(client):
    res = client.delete("/jobs/some-id")
    assert res.status_code == 401


def test_delete_job_rejects_non_owner(logged_in_client):
    with patch("app.main.db") as mock_db:
        mock_job = MagicMock()
        mock_job.exists = True
        mock_job.to_dict.return_value = {"owner_id": "someone-else"}
        mock_db.collection.return_value.document.return_value.get.return_value = mock_job

        res = logged_in_client.delete("/jobs/some-job-id")
        assert res.status_code == 403


def test_view_resume_rejects_non_owner(logged_in_client):
    with patch("app.main.db") as mock_db:
        mock_candidate = MagicMock()
        mock_candidate.exists = True
        mock_candidate.to_dict.return_value = {"owner_id": "someone-else"}
        mock_db.collection.return_value.document.return_value.get.return_value = mock_candidate

        res = logged_in_client.get("/candidates/some-candidate-id/resume")
        assert res.status_code == 403


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
