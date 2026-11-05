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


def test_delete_job_allows_admin_for_non_owned_job(admin_client):
    with patch("app.main.db") as mock_db:
        mock_job = MagicMock()
        mock_job.exists = True
        mock_job.to_dict.return_value = {"owner_id": "someone-else"}
        mock_db.collection.return_value.document.return_value.get.return_value = mock_job
        mock_db.collection.return_value.where.return_value.stream.return_value = []

        res = admin_client.delete("/jobs/some-job-id")
        assert res.status_code == 200


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


def test_generate_team_requires_auth(client):
    res = client.post("/jobs/generate-team", json={"project_description": "A project"})
    assert res.status_code == 401


def test_generate_team_rejects_missing_description(logged_in_client):
    res = logged_in_client.post("/jobs/generate-team", json={})
    assert res.status_code == 400


def test_generate_team_streams_events(logged_in_client):
    fake_events = [
        {"type": "team_planned", "roles": [{"title": "Backend Engineer", "count": 1, "rationale": "..."}]},
        {"type": "done", "results": [{"role": {"title": "Backend Engineer"}, "jd": {"title": "Backend Engineer"}}]},
    ]
    with patch("app.main.generate_team_job_descriptions", return_value=iter(fake_events)) as mock_gen:
        res = logged_in_client.post(
            "/jobs/generate-team",
            json={"project_description": "A project", "max_revisions": 1},
        )
        assert res.status_code == 200
        body = res.get_data(as_text=True)
        assert "team_planned" in body
        assert "Backend Engineer" in body
        assert '"type": "done"' in body or '"type":"done"' in body
        mock_gen.assert_called_once_with("A project", 1)


def test_team_plan_page_redirects_when_not_logged_in(client):
    res = client.get("/jobs/team-plan")
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]


def test_team_plan_page_loads_when_logged_in(logged_in_client):
    res = logged_in_client.get("/jobs/team-plan")
    assert res.status_code == 200


def _candidate_doc(**overrides):
    data = {
        "owner_id": "test-user-id",
        "status": "interview_prep_ready",
        "email": "someone@example.com",
        "candidate_name": "Jordan Ellis",
    }
    data.update(overrides)
    doc = MagicMock()
    doc.exists = True
    doc.to_dict.return_value = data
    return doc


def test_resend_email_requires_auth(client):
    res = client.post("/candidates/some-id/resend-email")
    assert res.status_code == 401


def test_resend_email_rejects_non_owner(logged_in_client):
    with patch("app.main.db") as mock_db, patch("app.main.send_email") as mock_send:
        mock_db.collection.return_value.document.return_value.get.return_value = _candidate_doc(owner_id="someone-else")
        res = logged_in_client.post("/candidates/c1/resend-email")
        assert res.status_code == 403
        mock_send.assert_not_called()


def test_resend_email_rejects_candidate_not_waiting_on_email(logged_in_client):
    with patch("app.main.db") as mock_db, patch("app.main.send_email") as mock_send:
        mock_db.collection.return_value.document.return_value.get.return_value = _candidate_doc(status="interview_link_sent")
        res = logged_in_client.post("/candidates/c1/resend-email")
        assert res.status_code == 400
        mock_send.assert_not_called()


def test_resend_email_sends_and_marks_link_sent(logged_in_client):
    with patch("app.main.db") as mock_db, patch("app.main.send_email") as mock_send:
        ref = mock_db.collection.return_value.document.return_value
        ref.get.return_value = _candidate_doc()
        res = logged_in_client.post("/candidates/c1/resend-email")
        assert res.status_code == 200
        assert res.get_json()["status"] == "interview_link_sent"
        mock_send.assert_called_once()
        assert mock_send.call_args.args[0] == "someone@example.com"
        updates = ref.update.call_args.args[0]
        assert updates["status"] == "interview_link_sent"


def test_resend_email_failure_returns_502_and_keeps_status(logged_in_client):
    with patch("app.main.db") as mock_db, patch("app.main.send_email", side_effect=RuntimeError("token expired")):
        ref = mock_db.collection.return_value.document.return_value
        ref.get.return_value = _candidate_doc()
        res = logged_in_client.post("/candidates/c1/resend-email")
        assert res.status_code == 502
        updates = ref.update.call_args.args[0]
        assert "status" not in updates
        assert "token expired" in updates["email_error"]


def test_apply_does_not_500_when_shortlist_email_fails(client):
    import io

    job = MagicMock()
    job.exists = True
    job.to_dict.return_value = {"description": "A job", "owner_id": "owner-1"}
    with patch("app.main.db") as mock_db, patch("app.main.bucket"), \
         patch("app.main.extract_text", return_value="resume text"), \
         patch("app.main.score_resume", return_value={
             "candidate_name": "Jordan Ellis", "score": 95,
             "matched_skills": [], "missing_skills": [], "reasoning": "good"}), \
         patch("app.main.generate_interview_prep", return_value={
             "email": "jordan@example.com", "questions": ["q1"]}), \
         patch("app.main.send_email", side_effect=RuntimeError("invalid_grant")):
        ref = mock_db.collection.return_value.document.return_value
        ref.get.return_value = job
        res = client.post(
            "/apply/job-1",
            data={"resume": (io.BytesIO(b"%PDF-1.4"), "resume.pdf")},
            content_type="multipart/form-data",
        )
        assert res.status_code == 200
        assert res.get_json() == {"status": "submitted"}
        updates = [c.args[0] for c in ref.update.call_args_list]
        assert any("invalid_grant" in u.get("email_error", "") for u in updates)
        assert not any(u.get("status") == "interview_link_sent" for u in updates)


# ---- delayed shortlist email + 48-hour window ----


def _apply(client, mock_db):
    import io

    job = MagicMock()
    job.exists = True
    job.to_dict.return_value = {"description": "A job", "owner_id": "owner-1"}
    ref = mock_db.collection.return_value.document.return_value
    ref.get.return_value = job
    res = client.post(
        "/apply/job-1",
        data={"resume": (io.BytesIO(b"%PDF-1.4"), "resume.pdf")},
        content_type="multipart/form-data",
    )
    return res, ref


_PASSING = {
    "candidate_name": "Jordan Ellis", "score": 95,
    "matched_skills": [], "missing_skills": [], "reasoning": "good",
}


def test_apply_schedules_email_instead_of_sending_when_delay_is_set(client):
    from datetime import datetime, timedelta, timezone

    with patch("app.main.db") as mock_db, patch("app.main.bucket"), \
         patch("app.main.extract_text", return_value="resume text"), \
         patch("app.main.score_resume", return_value=_PASSING), \
         patch("app.main.generate_interview_prep", return_value={"email": "j@example.com", "questions": ["q1"]}), \
         patch("app.main.SHORTLIST_EMAIL_DELAY_HOURS", 25), \
         patch("app.main.send_email") as mock_send:
        before = datetime.now(timezone.utc)
        res, ref = _apply(client, mock_db)
        assert res.status_code == 200
        assert res.get_json() == {"status": "submitted"}
        mock_send.assert_not_called()
        scheduled = [c.args[0] for c in ref.update.call_args_list if c.args[0].get("status") == "email_scheduled"]
        assert len(scheduled) == 1
        send_at = scheduled[0]["email_send_at"]
        assert timedelta(hours=24, minutes=59) < send_at - before < timedelta(hours=25, minutes=1)


def test_apply_sends_immediately_when_no_delay(client):
    with patch("app.main.db") as mock_db, patch("app.main.bucket"), \
         patch("app.main.extract_text", return_value="resume text"), \
         patch("app.main.score_resume", return_value=_PASSING), \
         patch("app.main.generate_interview_prep", return_value={"email": "j@example.com", "questions": ["q1"]}), \
         patch("app.main.SHORTLIST_EMAIL_DELAY_HOURS", 0), \
         patch("app.main.send_email") as mock_send:
        res, ref = _apply(client, mock_db)
        assert res.status_code == 200
        mock_send.assert_called_once()
        updates = [c.args[0] for c in ref.update.call_args_list]
        assert any(u.get("status") == "interview_link_sent" for u in updates)
        assert not any(u.get("status") == "email_scheduled" for u in updates)


def test_assessment_window_is_48_hours_and_stated_in_email():
    from datetime import timedelta

    from app import main

    assert main.ASSESSMENT_WINDOW == timedelta(hours=48)
    assert "within 48 hours" in main._build_interview_email_body("c1", "Jordan")


def test_send_due_emails_rejects_unauthenticated_requests(client):
    with patch("app.main.send_email") as mock_send:
        assert client.post("/internal/send-due-emails").status_code == 401
        res = client.post("/internal/send-due-emails", headers={"Authorization": "Bearer junk"})
        assert res.status_code == 401
        mock_send.assert_not_called()


def test_scheduler_token_must_come_from_the_scheduler_service_account(client):
    sa = "scheduler@proj.iam.gserviceaccount.com"
    headers = {"Authorization": "Bearer tok"}
    with patch("app.main.SCHEDULER_SERVICE_ACCOUNT", sa), \
         patch("app.main.google_id_token.verify_oauth2_token") as verify, \
         patch("app.main._send_due_shortlist_emails", return_value=(0, 0)):
        verify.return_value = {"email": sa, "email_verified": True}
        assert client.post("/internal/send-due-emails", headers=headers).status_code == 200
        assert verify.call_args.kwargs["audience"] == "http://testserver"

        verify.return_value = {"email": "someone-else@example.com", "email_verified": True}
        assert client.post("/internal/send-due-emails", headers=headers).status_code == 401

        verify.return_value = {"email": sa, "email_verified": False}
        assert client.post("/internal/send-due-emails", headers=headers).status_code == 401

        verify.side_effect = ValueError("bad token")
        assert client.post("/internal/send-due-emails", headers=headers).status_code == 401


def test_scheduler_requests_rejected_when_no_service_account_configured(client):
    with patch("app.main.SCHEDULER_SERVICE_ACCOUNT", ""), \
         patch("app.main.google_id_token.verify_oauth2_token") as verify:
        verify.return_value = {"email": "", "email_verified": True}
        res = client.post("/internal/send-due-emails", headers={"Authorization": "Bearer tok"})
        assert res.status_code == 401
        verify.assert_not_called()


def _scheduled_snap(cid, to, send_at):
    snap = MagicMock()
    snap.id = cid
    snap.reference.id = cid
    snap.to_dict.return_value = {
        "status": "email_scheduled", "email": to, "candidate_name": "Jordan Ellis", "email_send_at": send_at,
    }
    return snap


def test_due_sender_sends_only_due_emails_and_survives_failures():
    from datetime import datetime, timedelta, timezone

    from google.api_core.exceptions import FailedPrecondition

    from app import main

    now = datetime.now(timezone.utc)
    due = _scheduled_snap("due", "due@example.com", now - timedelta(minutes=1))
    future = _scheduled_snap("future", "future@example.com", now + timedelta(hours=3))
    claimed = _scheduled_snap("claimed", "claimed@example.com", now - timedelta(minutes=5))
    claimed.reference.update.side_effect = FailedPrecondition("claimed by another run")
    broken = _scheduled_snap("broken", "broken@example.com", now - timedelta(minutes=2))

    def fake_send(to, subject, body):
        if to == "broken@example.com":
            raise RuntimeError("invalid_grant")

    with patch("app.main.db") as mock_db, patch("app.main.send_email", side_effect=fake_send) as mock_send:
        mock_db.collection.return_value.where.return_value.stream.return_value = [due, future, claimed, broken]
        sent, failed = main._send_due_shortlist_emails()

    assert (sent, failed) == (1, 1)
    assert [c.args[0] for c in mock_send.call_args_list] == ["due@example.com", "broken@example.com"]
    due_updates = [c.args[0] for c in due.reference.update.call_args_list]
    assert due_updates[0]["email_send_at"] > now  # leased before sending
    assert any(u.get("status") == "interview_link_sent" for u in due_updates)
    future.reference.update.assert_not_called()
    broken_updates = [c.args[0] for c in broken.reference.update.call_args_list]
    assert broken_updates[-1]["status"] == "interview_prep_ready"
    assert "invalid_grant" in broken_updates[-1]["email_error"]


def test_resend_endpoint_can_send_a_scheduled_email_now(logged_in_client):
    with patch("app.main.db") as mock_db, patch("app.main.send_email") as mock_send:
        ref = mock_db.collection.return_value.document.return_value
        ref.get.return_value = _candidate_doc(status="email_scheduled")
        res = logged_in_client.post("/candidates/c1/resend-email")
        assert res.status_code == 200
        mock_send.assert_called_once()
        assert ref.update.call_args.args[0]["status"] == "interview_link_sent"
