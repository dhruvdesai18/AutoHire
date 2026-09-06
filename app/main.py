import hmac
from datetime import datetime, timedelta, timezone
from functools import wraps
from io import BytesIO

from flask import Flask, render_template, request, jsonify, send_file
from google.cloud import firestore

from app.clients import bucket, db
from app.config import (
    ATS_SCORE_THRESHOLD,
    BASE_URL,
    DASHBOARD_PASSWORD,
    INTERVIEW_SCORE_THRESHOLD,
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


def require_recruiter_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        auth = request.authorization
        if not auth or not hmac.compare_digest(auth.password or "", DASHBOARD_PASSWORD):
            return "Authentication required", 401, {"WWW-Authenticate": 'Basic realm="AutoHire Recruiter"'}
        return view(*args, **kwargs)

    return wrapped


@app.route("/")
@require_recruiter_auth
def index():
    return render_template("index.html")


@app.route("/jobs", methods=["POST"])
@require_recruiter_auth
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
            "created_at": firestore.SERVER_TIMESTAMP,
        }
    )

    return jsonify({"job_id": job_ref.id})


@app.route("/jobs", methods=["GET"])
@require_recruiter_auth
def list_jobs():
    jobs_ref = (
        db.collection("jobs")
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .stream()
    )
    jobs = [{"job_id": j.id, "title": j.get("title")} for j in jobs_ref]
    return jsonify({"jobs": jobs})


@app.route("/jobs/<job_id>/candidates")
@require_recruiter_auth
def list_job_candidates(job_id):
    candidates_ref = db.collection("candidates").where("job_id", "==", job_id).stream()
    candidates = []
    for c in candidates_ref:
        d = c.to_dict()
        candidates.append(
            {
                "candidate_id": c.id,
                "name": d.get("candidate_name"),
                "filename": d.get("filename"),
                "email": d.get("email"),
                "status": d.get("status"),
                "ats_score": d.get("ats_score"),
                "conversation_score": d.get("conversation_score"),
            }
        )
    return jsonify({"candidates": candidates})


@app.route("/candidates/<candidate_id>/resume")
@require_recruiter_auth
def view_resume(candidate_id):
    candidate = db.collection("candidates").document(candidate_id).get()
    if not candidate.exists:
        return jsonify({"error": "Candidate not found"}), 404

    candidate_data = candidate.to_dict()
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
    return render_template(
        "apply.html",
        job_id=job_id,
        title=job_data.get("title"),
        description=job_data.get("description"),
        sections=formatted.get("sections") if formatted else None,
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

    job_description = job.get("description")

    candidate_ref = db.collection("candidates").document()
    gcs_path = f"resumes/{candidate_ref.id}/{resume_file.filename}"
    bucket.blob(gcs_path).upload_from_file(
        resume_file, content_type=resume_file.content_type
    )
    candidate_ref.set(
        {
            "job_id": job_id,
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


@app.route("/upload/resume", methods=["POST"])
@require_recruiter_auth
def upload_resume():
    if "resume" not in request.files:
        return jsonify({"error": "No resume file provided"}), 400

    resume_file = request.files["resume"]
    if resume_file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    candidate_ref = db.collection("candidates").document()
    gcs_path = f"resumes/{candidate_ref.id}/{resume_file.filename}"

    blob = bucket.blob(gcs_path)
    blob.upload_from_file(resume_file, content_type=resume_file.content_type)

    candidate_ref.set(
        {
            "filename": resume_file.filename,
            "gcs_path": gcs_path,
            "status": "uploaded",
            "created_at": firestore.SERVER_TIMESTAMP,
        }
    )

    return jsonify({"candidate_id": candidate_ref.id, "status": "uploaded"})


@app.route("/parse/<candidate_id>", methods=["POST"])
@require_recruiter_auth
def parse_resume(candidate_id):
    candidate_ref = db.collection("candidates").document(candidate_id)
    candidate = candidate_ref.get()
    if not candidate.exists:
        return jsonify({"error": "Candidate not found"}), 404

    gcs_path = candidate.get("gcs_path")
    pdf_bytes = bucket.blob(gcs_path).download_as_bytes()

    parsed_text = extract_text(pdf_bytes)

    candidate_ref.update({"parsed_text": parsed_text, "status": "parsed"})

    return jsonify(
        {
            "candidate_id": candidate_id,
            "status": "parsed",
            "parsed_text_preview": parsed_text[:300],
        }
    )


@app.route("/score/<candidate_id>", methods=["POST"])
@require_recruiter_auth
def score_candidate(candidate_id):
    job_description = request.get_json(silent=True, force=True).get("job_description")
    if not job_description:
        return jsonify({"error": "job_description is required"}), 400

    candidate_ref = db.collection("candidates").document(candidate_id)
    candidate = candidate_ref.get()
    if not candidate.exists:
        return jsonify({"error": "Candidate not found"}), 404

    parsed_text = candidate.get("parsed_text")
    if not parsed_text:
        return jsonify({"error": "Candidate has not been parsed yet"}), 400

    result = score_resume(parsed_text, job_description)
    passed = result["score"] >= ATS_SCORE_THRESHOLD
    status = "screening_passed" if passed else "rejected"

    candidate_ref.update(
        {
            "job_description": job_description,
            "candidate_name": result["candidate_name"],
            "ats_score": result["score"],
            "ats_matched_skills": result["matched_skills"],
            "ats_missing_skills": result["missing_skills"],
            "ats_reasoning": result["reasoning"],
            "status": status,
        }
    )

    return jsonify({"candidate_id": candidate_id, "status": status, **result})


@app.route("/generate-interview-prep/<candidate_id>", methods=["POST"])
@require_recruiter_auth
def generate_interview_prep_route(candidate_id):
    candidate_ref = db.collection("candidates").document(candidate_id)
    candidate = candidate_ref.get()
    if not candidate.exists:
        return jsonify({"error": "Candidate not found"}), 404

    if candidate.get("status") != "screening_passed":
        return (
            jsonify({"error": "Candidate has not passed ATS screening"}),
            400,
        )

    result = generate_interview_prep(
        candidate.get("parsed_text"), candidate.get("job_description")
    )

    candidate_ref.update(
        {
            "email": result["email"],
            "interview_questions": result["questions"],
            "status": "interview_prep_ready",
        }
    )

    return jsonify(
        {"candidate_id": candidate_id, "status": "interview_prep_ready", **result}
    )


def _build_interview_email_body(candidate_id, first_name):
    return (
        f"Hello {first_name},\n\n"
        "Thanks for applying! You've been shortlisted for this role. Please "
        "complete your assessment within 24 hours using the link below:\n\n"
        f"{BASE_URL}/interview/{candidate_id}\n\n"
        "Best of luck,\nAutoHire"
    )


@app.route("/send-interview-link/<candidate_id>", methods=["POST"])
@require_recruiter_auth
def send_interview_link(candidate_id):
    candidate_ref = db.collection("candidates").document(candidate_id)
    candidate = candidate_ref.get()
    if not candidate.exists:
        return jsonify({"error": "Candidate not found"}), 404

    candidate_data = candidate.to_dict()
    if candidate_data.get("status") != "interview_prep_ready":
        return jsonify({"error": "Candidate has no interview prep ready"}), 400

    body = _build_interview_email_body(
        candidate_id, _first_name(candidate_data.get("candidate_name"))
    )
    send_email(candidate_data.get("email"), "You've Been Shortlisted", body)

    candidate_ref.update(
        {
            "status": "interview_link_sent",
            "link_sent_at": firestore.SERVER_TIMESTAMP,
            "assessment_deadline": datetime.now(timezone.utc) + ASSESSMENT_WINDOW,
        }
    )

    return jsonify({"candidate_id": candidate_id, "status": "interview_link_sent"})


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
@require_recruiter_auth
def evaluate_interview_route(candidate_id):
    candidate_ref = db.collection("candidates").document(candidate_id)
    candidate = candidate_ref.get()
    if not candidate.exists:
        return jsonify({"error": "Candidate not found"}), 404

    candidate_data = candidate.to_dict()
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
