from datetime import datetime, timedelta, timezone
from functools import wraps
from io import BytesIO

from flask import Flask, render_template, request, jsonify, send_file, session, redirect
from google.auth.transport import requests as google_auth_requests
from google.cloud import firestore
from google.oauth2 import id_token as google_id_token

from app.clients import bucket, db
from app.config import (
    ATS_SCORE_THRESHOLD,
    BASE_URL,
    GOOGLE_OAUTH_CLIENT_ID,
    INTERVIEW_SCORE_THRESHOLD,
    SECRET_KEY,
)
from app.document_ai import extract_text
from app.gemini import (
    evaluate_interview,
    format_job_description,
    generate_interview_prep,
    score_resume,
)
from app.gmail import send_email

ASSESSMENT_WINDOW = timedelta(hours=24)


def _first_name(candidate_name):
    if not candidate_name:
        return "there"
    return candidate_name.split(" ")[0]

app = Flask(__name__)
app.secret_key = SECRET_KEY


def require_login(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({"error": "Not authenticated"}), 401
        return view(*args, **kwargs)

    return wrapped


def _owns_or_admin(owner_id):
    return session.get("is_admin") or owner_id == session.get("user_id")


@app.route("/login")
def login_page():
    if session.get("user_id"):
        return redirect("/")
    return render_template(
        "login.html", google_client_id=GOOGLE_OAUTH_CLIENT_ID, base_url=BASE_URL
    )


@app.route("/privacy")
def privacy_page():
    return render_template("privacy.html")


@app.route("/terms")
def terms_page():
    return render_template("terms.html")


@app.route("/auth/google", methods=["POST"])
def auth_google():
    data = request.get_json(silent=True, force=True) or {}
    credential = data.get("credential")
    if not credential:
        return jsonify({"error": "Missing credential"}), 400

    try:
        claims = google_id_token.verify_oauth2_token(
            credential, google_auth_requests.Request(), GOOGLE_OAUTH_CLIENT_ID
        )
    except ValueError:
        return jsonify({"error": "Invalid credential"}), 401

    user_ref = db.collection("users").document(claims["sub"])
    existing_user = user_ref.get()
    is_admin = existing_user.to_dict().get("is_admin", False) if existing_user.exists else False

    session["user_id"] = claims["sub"]
    session["user_email"] = claims.get("email")
    session["user_name"] = claims.get("name", claims.get("email"))
    session["is_admin"] = is_admin

    user_ref.set(
        {
            "email": claims.get("email"),
            "name": claims.get("name"),
            "last_login": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )

    return jsonify({"status": "ok"})


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/")
def index():
    if not session.get("user_id"):
        return redirect("/login")
    return render_template(
        "index.html",
        ats_threshold=ATS_SCORE_THRESHOLD,
        interview_threshold=INTERVIEW_SCORE_THRESHOLD,
        user_name=session.get("user_name"),
        user_email=session.get("user_email"),
        is_admin=session.get("is_admin", False),
    )


@app.route("/jobs", methods=["POST"])
@require_login
def create_job():
    data = request.get_json(silent=True, force=True) or {}
    title = data.get("title")
    description = data.get("description")
    if not title or not description:
        return jsonify({"error": "title and description are required"}), 400

    formatted_description = format_job_description(description)

    job_ref = db.collection("jobs").document()
    job_ref.set(
        {
            "title": title,
            "description": description,
            "formatted_description": formatted_description,
            "owner_id": session["user_id"],
            "owner_email": session.get("user_email"),
            "created_at": firestore.SERVER_TIMESTAMP,
        }
    )

    return jsonify({"job_id": job_ref.id})


@app.route("/jobs", methods=["GET"])
@require_login
def list_jobs():
    if session.get("is_admin"):
        jobs_ref = db.collection("jobs").stream()
    else:
        jobs_ref = (
            db.collection("jobs")
            .where("owner_id", "==", session["user_id"])
            .stream()
        )

    jobs = []
    for j in jobs_ref:
        j_data = j.to_dict()
        candidates = [c.to_dict() for c in db.collection("candidates").where("job_id", "==", j.id).stream()]
        screened_out = sum(1 for c in candidates if c.get("status") == "rejected" and c.get("conversation_score") is None)
        assessed = sum(1 for c in candidates if c.get("conversation_score") is not None or c.get("status") in ("interview_audio_uploaded", "advanced"))
        advanced = sum(1 for c in candidates if c.get("status") == "advanced")
        created_at = j_data.get("created_at")
        jobs.append(
            {
                "job_id": j.id,
                "title": j_data.get("title"),
                "owner_email": j_data.get("owner_email"),
                "applied_count": len(candidates),
                "screened_out_count": screened_out,
                "assessed_count": assessed,
                "advanced_count": advanced,
                "created_at": created_at.isoformat() if created_at else None,
                "_sort_key": created_at or datetime.min.replace(tzinfo=timezone.utc),
            }
        )

    jobs.sort(key=lambda j: j.pop("_sort_key"), reverse=True)

    return jsonify({"jobs": jobs})


@app.route("/jobs/<job_id>", methods=["DELETE"])
@require_login
def delete_job(job_id):
    job = db.collection("jobs").document(job_id).get()
    if not job.exists:
        return jsonify({"error": "Job not found"}), 404
    if not _owns_or_admin(job.to_dict().get("owner_id")):
        return jsonify({"error": "Not authorized"}), 403

    job_ref = job.reference
    candidates = db.collection("candidates").where("job_id", "==", job_id).stream()
    for c in candidates:
        for prefix in (f"resumes/{c.id}/", f"interviews/{c.id}/"):
            for blob in bucket.list_blobs(prefix=prefix):
                blob.delete()
        c.reference.delete()

    job_ref.delete()
    return jsonify({"status": "deleted"})


@app.route("/jobs/<job_id>/candidates")
@require_login
def list_job_candidates(job_id):
    job = db.collection("jobs").document(job_id).get()
    if not job.exists:
        return jsonify({"error": "Job not found"}), 404
    if not _owns_or_admin(job.to_dict().get("owner_id")):
        return jsonify({"error": "Not authorized"}), 403

    candidates_ref = db.collection("candidates").where("job_id", "==", job_id).stream()
    candidates = []
    for c in candidates_ref:
        d = c.to_dict()
        created_at = d.get("created_at")
        link_sent_at = d.get("link_sent_at")
        candidates.append(
            {
                "candidate_id": c.id,
                "name": d.get("candidate_name"),
                "filename": d.get("filename"),
                "email": d.get("email"),
                "status": d.get("status"),
                "ats_score": d.get("ats_score"),
                "conversation_score": d.get("conversation_score"),
                "ats_matched_skills": d.get("ats_matched_skills"),
                "ats_missing_skills": d.get("ats_missing_skills"),
                "ats_reasoning": d.get("ats_reasoning"),
                "interview_summary": d.get("interview_summary"),
                "interview_evaluation_notes": d.get("interview_evaluation_notes"),
                "created_at": created_at.isoformat() if created_at else None,
                "link_sent_at": link_sent_at.isoformat() if link_sent_at else None,
            }
        )
    return jsonify({"candidates": candidates})


@app.route("/candidates/<candidate_id>/resume")
@require_login
def view_resume(candidate_id):
    candidate = db.collection("candidates").document(candidate_id).get()
    if not candidate.exists:
        return jsonify({"error": "Candidate not found"}), 404

    candidate_data = candidate.to_dict()
    if not _owns_or_admin(candidate_data.get("owner_id")):
        return jsonify({"error": "Not authorized"}), 403

    gcs_path = candidate_data.get("gcs_path")
    if not gcs_path:
        return jsonify({"error": "No resume on file for this candidate"}), 404

    pdf_bytes = bucket.blob(gcs_path).download_as_bytes()
    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=False,
        download_name=candidate_data.get("filename", "resume.pdf"),
    )


@app.route("/apply/<job_id>")
def apply_page(job_id):
    job = db.collection("jobs").document(job_id).get()
    if not job.exists:
        return render_template("apply.html", error="This job posting was not found.")

    job_data = job.to_dict()
    formatted = job_data.get("formatted_description")
    created_at = job_data.get("created_at")
    return render_template(
        "apply.html",
        job_id=job_id,
        title=job_data.get("title"),
        description=job_data.get("description"),
        sections=formatted.get("sections") if formatted else None,
        posted=f"Posted {created_at.strftime('%-d %b')}" if created_at else None,
    )


@app.route("/apply/<job_id>", methods=["POST"])
def submit_application(job_id):
    job = db.collection("jobs").document(job_id).get()
    if not job.exists:
        return jsonify({"error": "Job posting not found"}), 404

    if "resume" not in request.files:
        return jsonify({"error": "No resume file provided"}), 400

    resume_file = request.files["resume"]
    if resume_file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    job_data = job.to_dict()
    job_description = job_data.get("description")

    candidate_ref = db.collection("candidates").document()
    gcs_path = f"resumes/{candidate_ref.id}/{resume_file.filename}"
    bucket.blob(gcs_path).upload_from_file(
        resume_file, content_type=resume_file.content_type
    )
    candidate_ref.set(
        {
            "job_id": job_id,
            "owner_id": job_data.get("owner_id"),
            "job_description": job_description,
            "filename": resume_file.filename,
            "gcs_path": gcs_path,
            "status": "uploaded",
            "created_at": firestore.SERVER_TIMESTAMP,
        }
    )

    pdf_bytes = bucket.blob(gcs_path).download_as_bytes()
    parsed_text = extract_text(pdf_bytes)
    candidate_ref.update({"parsed_text": parsed_text, "status": "parsed"})

    score_result = score_resume(parsed_text, job_description)
    passed = score_result["score"] >= ATS_SCORE_THRESHOLD
    candidate_ref.update(
        {
            "candidate_name": score_result["candidate_name"],
            "ats_score": score_result["score"],
            "ats_matched_skills": score_result["matched_skills"],
            "ats_missing_skills": score_result["missing_skills"],
            "ats_reasoning": score_result["reasoning"],
            "status": "screening_passed" if passed else "rejected",
        }
    )

    if not passed:
        return jsonify({"status": "submitted"})

    prep_result = generate_interview_prep(parsed_text, job_description)
    candidate_ref.update(
        {
            "email": prep_result["email"],
            "interview_questions": prep_result["questions"],
            "status": "interview_prep_ready",
        }
    )

    body = _build_interview_email_body(
        candidate_ref.id, _first_name(score_result["candidate_name"])
    )
    send_email(prep_result["email"], "You've Been Shortlisted", body)
    candidate_ref.update(
        {
            "status": "interview_link_sent",
            "link_sent_at": firestore.SERVER_TIMESTAMP,
            "assessment_deadline": datetime.now(timezone.utc) + ASSESSMENT_WINDOW,
        }
    )

    return jsonify({"status": "submitted"})


def _build_interview_email_body(candidate_id, first_name):
    return (
        f"Hello {first_name},\n\n"
        "Thanks for applying! You've been shortlisted for this role. Please "
        "complete your assessment within 24 hours using the link below:\n\n"
        f"{BASE_URL}/interview/{candidate_id}\n\n"
        "Best of luck,\nAutoHire"
    )


def _is_expired(candidate_data: dict) -> bool:
    deadline = candidate_data.get("assessment_deadline")
    return bool(deadline and datetime.now(timezone.utc) > deadline)


@app.route("/interview/<candidate_id>")
def interview_page(candidate_id):
    candidate_ref = db.collection("candidates").document(candidate_id)
    candidate = candidate_ref.get()
    if not candidate.exists or not candidate.get("interview_questions"):
        return render_template("interview.html", error="Interview link not found.")

    candidate_data = candidate.to_dict()
    status = candidate_data.get("status")

    if status == "interview_link_sent" and _is_expired(candidate_data):
        candidate_ref.update({"status": "expired"})
        return render_template(
            "interview.html", error="This assessment link has expired."
        )
    if status == "expired":
        return render_template(
            "interview.html", error="This assessment link has expired."
        )

    if status == "interview_audio_uploaded" or status in ("advanced", "rejected"):
        return render_template(
            "interview.html", submitted=True, questions=candidate_data.get("interview_questions")
        )

    return render_template(
        "interview.html",
        candidate_id=candidate_id,
        questions=candidate_data.get("interview_questions"),
    )


@app.route("/interview/<candidate_id>/submit", methods=["POST"])
def submit_interview_assessment(candidate_id):
    candidate_ref = db.collection("candidates").document(candidate_id)
    candidate = candidate_ref.get()
    if not candidate.exists:
        return jsonify({"error": "Candidate not found"}), 404

    candidate_data = candidate.to_dict()
    if candidate_data.get("status") != "interview_link_sent":
        return jsonify({"error": "Candidate is not ready for interview audio"}), 400

    if _is_expired(candidate_data):
        candidate_ref.update({"status": "expired"})
        return jsonify({"error": "This assessment link has expired"}), 400

    questions = candidate_data.get("interview_questions")
    question_recordings = []
    for i in range(len(questions)):
        field = f"q{i}"
        if field not in request.files or request.files[field].filename == "":
            question_recordings.append(None)
            continue

        audio_file = request.files[field]
        gcs_path = f"interviews/{candidate_id}/q{i}.webm"
        bucket.blob(gcs_path).upload_from_file(
            audio_file, content_type=audio_file.content_type
        )
        question_recordings.append(
            {"gcs_path": gcs_path, "content_type": audio_file.content_type}
        )

    candidate_ref.update(
        {
            "question_recordings": question_recordings,
            "status": "interview_audio_uploaded",
        }
    )

    return jsonify({"candidate_id": candidate_id, "status": "interview_audio_uploaded"})


@app.route("/evaluate-interview/<candidate_id>", methods=["POST"])
@require_login
def evaluate_interview_route(candidate_id):
    candidate_ref = db.collection("candidates").document(candidate_id)
    candidate = candidate_ref.get()
    if not candidate.exists:
        return jsonify({"error": "Candidate not found"}), 404

    candidate_data = candidate.to_dict()
    if not _owns_or_admin(candidate_data.get("owner_id")):
        return jsonify({"error": "Not authorized"}), 403
    if candidate_data.get("status") != "interview_audio_uploaded":
        return jsonify({"error": "Candidate has no interview audio to evaluate"}), 400

    questions = candidate_data.get("interview_questions")
    recordings = candidate_data.get("question_recordings")

    question_recordings = []
    for question, recording in zip(questions, recordings):
        if recording:
            audio_bytes = bucket.blob(recording["gcs_path"]).download_as_bytes()
            question_recordings.append(
                {
                    "question": question,
                    "audio_bytes": audio_bytes,
                    "mime_type": recording["content_type"],
                }
            )
        else:
            question_recordings.append(
                {"question": question, "audio_bytes": None, "mime_type": None}
            )

    result = evaluate_interview(question_recordings)

    passed = result["conversation_score"] >= INTERVIEW_SCORE_THRESHOLD
    status = "advanced" if passed else "rejected"

    candidate_ref.update(
        {
            "interview_answers": result["answers"],
            "interview_summary": result["summary"],
            "conversation_score": result["conversation_score"],
            "interview_evaluation_notes": result["evaluation_notes"],
            "status": status,
        }
    )

    return jsonify({"candidate_id": candidate_id, "status": status, **result})


if __name__ == "__main__":
    app.run(debug=True)
