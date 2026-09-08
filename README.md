# AutoHire

An AI-driven resume screening and interview pipeline. A recruiter publishes a job and gets a shareable link. A candidate applies with just a resume — no other input. AutoHire parses it, scores it against the job description, and — if it passes — automatically emails the candidate a personalized "you've been shortlisted" message with a link to a timed assessment. The candidate answers each question with its own in-browser recording (2 tries, 90 seconds each, 30 minutes overall); AutoHire evaluates each answer directly against its question and advances or rejects the candidate.

Everything past "publish a job" runs with no human in the loop until the recruiter reviews the final evaluation.

**Live:** deployed on Google Cloud Run — the recruiter dashboard is password-protected; candidate-facing pages are open to anyone with a job's application link.

## How it works

Three separate, single-purpose pages:

| Page | Who uses it | What it does |
|---|---|---|
| `/` | Recruiter (password-protected) | Publish a job, get a shareable application link, view candidates and their status per job (with resume, scores, and name), delete a job and all its data, trigger interview evaluation |
| `/apply/<job_id>` | Candidate | See the job description (auto-formatted into sections), upload a resume — nothing else |
| `/interview/<candidate_id>` | Candidate | A timed assessment: see instructions, start a 30-minute clock, record an answer to each question directly in the browser (2 tries, 90s each) — auto-submits whatever's recorded when time runs out |

### Pipeline

1. **Publish a job** — recruiter enters a title + description; Gemini reformats it into structured sections (Overview, Responsibilities, Requirements, etc.) for the candidate-facing page
2. **Candidate applies** — resume uploaded to Cloud Storage
3. **Parse resume** — Document AI extracts the raw text
4. **Score against the job** — Gemini scores the resume 0-100 against the job description, also extracting the candidate's name and matched/missing skills
5. **Gate** — below threshold → rejected (candidate sees a generic "thanks for applying" either way, never the score)
6. **Generate interview prep** — Gemini extracts the candidate's email and writes 5 questions tailored to their specific experience and the job
7. **Send shortlist email** — Gmail API sends a short, personalized email ("Hello \<Name\>, thanks for applying...") with a link to the candidate's assessment page and a 24-hour deadline (enforced server-side)
8. **Candidate completes the timed assessment** — records an answer to each question in-browser; partial completion is fine, whatever's recorded gets submitted
9. **Evaluate** — Gemini scores each recorded answer directly against its specific question (no speaker-diarization guessing — every clip is unambiguously "the candidate's answer to question N"), factoring in any unanswered questions
10. **Gate** — below threshold → rejected, above → advanced. Recruiter dashboard reflects the final status, both scores, and the candidate's name

### Tech stack

- **Flask** — single backend app, server-rendered HTML + vanilla JS (no frontend framework), deployed on **Cloud Run** via Docker + gunicorn
- **Cloud Storage** — resumes and per-question interview recordings
- **Firestore** — job postings and candidate records/status (the source of truth the whole pipeline reads and writes)
- **Document AI** — resume text extraction (OCR)
- **Vertex AI (Gemini, via `google-genai`)** — resume scoring + name extraction, interview question generation, JD formatting, per-question answer evaluation
- **Gmail API (OAuth)** — sending shortlist emails, credentials stored in **Secret Manager** in production
- **MediaRecorder API** — real-time in-browser audio recording on the candidate assessment page

### Security

- The recruiter dashboard and every recruiter-only endpoint require HTTP Basic Auth (a shared password, since this is a single-recruiter tool for now)
- Candidate-facing pages (`/apply`, `/interview`) are intentionally open — no login, since candidates shouldn't need an account
- Secrets (`.env`, `client_secret.json`, the Gmail OAuth `token.json`) are gitignored and never enter the repo; in production the Gmail token is injected via a Secret Manager volume mount, not baked into the container

## Project structure

```
app/
  main.py         Flask routes
  clients.py      GCP client setup (Storage, Firestore, Document AI)
  config.py       env-var based configuration
  document_ai.py  resume text extraction
  gemini.py       all Gemini prompts (scoring, JD formatting, question generation, answer evaluation)
  gmail.py        OAuth + email sending
  templates/      index.html (recruiter), apply.html (candidate), interview.html (candidate assessment)
  static/         style.css
Dockerfile        Cloud Run container definition
```

## Setup

1. Create a GCP project, enable billing, and enable these APIs: Vertex AI, Document AI, Cloud Storage, Firestore, Gmail, Secret Manager.
2. Create a Cloud Storage bucket and a Firestore database (Native mode), same region for both.
3. Create a Document AI **Document OCR** processor (region `us` or `eu`) — note its processor ID.
4. Authenticate locally so the Google client libraries can call these APIs as you:
   ```bash
   gcloud auth application-default login
   ```
5. Set up Gmail OAuth: **APIs & Services → OAuth consent screen**, add yourself as a test user, then **Credentials → Create OAuth client ID → Desktop app**, download the JSON and save it as `client_secret.json` in the project root (gitignored — never commit this).
6. Copy `.env.example` to `.env` and fill in your project ID, region, bucket name, Document AI processor ID, and a `DASHBOARD_PASSWORD` of your choice.
7. Install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
8. Run the app:
   ```bash
   python -m app.main
   ```
9. Open `http://127.0.0.1:5000/`, log in with your dashboard password, publish a job, and try the flow. The first time an email is sent, a browser window opens asking you to approve Gmail access — after that it's silent (cached in `token.json`, also gitignored).

### Deploying to Cloud Run

```bash
gcloud run deploy autohire --source . --region us-central1 \
  --set-env-vars GCP_PROJECT_ID=...,GCS_BUCKET_NAME=...,DASHBOARD_PASSWORD=...,BASE_URL=https://your-service-url \
  --set-secrets=/secrets/token.json=gmail-token:latest
```
Store your local `token.json` in Secret Manager (`gcloud secrets create gmail-token --data-file=token.json`) so the deployed container never bundles it directly.

## Status

The full pipeline is built, deployed, and working end to end — publish, apply, screen, personalized email, real-time recorded assessment, evaluation, and a recruiter dashboard to manage it all.

Known limitation: the Gmail OAuth app is currently in Google's "Testing" publishing status, so refresh tokens expire every 7 days and need periodic re-authentication. Moving it to "In production" would remove that limit.

## Demo
<img width="731" height="711" alt="Screenshot 2026-07-29 at 21 07 31" src="https://github.com/user-attachments/assets/8e9ac88d-f2f9-4d6f-b336-0198f560dc96" />

<img width="737" height="775" alt="Screenshot 2026-07-29 at 21 07 41" src="https://github.com/user-attachments/assets/6b18db80-6f74-416d-9d38-a5e8cd058d48" />

<img width="440" height="755" alt="Screenshot 2026-07-29 at 22 06 23" src="https://github.com/user-attachments/assets/68b8f186-e239-43c3-9e4e-1b463dfab27a" />


<img width="751" height="803" alt="Screenshot 2026-07-29 at 21 14 39" src="https://github.com/user-attachments/assets/628d167a-a959-48e9-aa6f-34c2c75f8eef" />

<img width="698" height="779" alt="Screenshot 2026-07-29 at 21 14 27" src="https://github.com/user-attachments/assets/d46f2363-22e1-4b7b-a728-5d784c0cbea1" />
