# AutoHire

An AI-driven resume screening and interview pipeline. A recruiter publishes a job; candidates apply with just a resume; AutoHire parses it, scores it against the job description, and — if it passes — automatically emails the candidate a set of tailored interview questions. The candidate records their answers as a single audio file; AutoHire diarizes the conversation, evaluates it, and advances or rejects the candidate.

Everything past "publish a job" runs with no human in the loop until the final interview evaluation.

## How it works

Three separate, single-purpose pages:

| Page | Who uses it | What it does |
|---|---|---|
| `/` | Recruiter | Publish a job (title + description), get a shareable application link, view applicants and their status per job, trigger interview evaluation |
| `/apply/<job_id>` | Candidate | See the job description, upload a resume — nothing else |
| `/interview/<candidate_id>` | Candidate | See their personalized interview questions, upload one audio recording — nothing else |

### Pipeline

1. **Publish a job** — recruiter enters a title + description, stored in Firestore
2. **Candidate applies** — resume uploaded to Cloud Storage
3. **Parse resume** — Document AI extracts the raw text
4. **Score against the job** — Gemini scores the resume 0-100 against the job description, with matched/missing skills and reasoning
5. **Gate** — below threshold → rejected (candidate sees a generic "thanks for applying" either way, never the score)
6. **Generate interview prep** — Gemini extracts the candidate's email from their resume and writes 5 questions tailored to their specific experience and the job
7. **Send interview link** — Gmail API emails the candidate their questions and a link to their personal interview page
8. **Candidate submits interview audio** — uploaded to Cloud Storage
9. **Diarize + evaluate** — Gemini processes the audio directly (speaker diarization, transcription, and conversation-skill scoring in one multimodal call), no separate speech-to-text step
10. **Gate** — below threshold → rejected, above → advanced. Recruiter dashboard reflects the final status

### Tech stack

- **Flask** — single backend app, server-rendered HTML + vanilla JS (no frontend framework)
- **Cloud Storage** — resumes and interview audio
- **Firestore** — job postings and candidate records/status (the source of truth the whole pipeline reads and writes)
- **Document AI** — resume text extraction (OCR)
- **Vertex AI (Gemini, via `google-genai`)** — resume scoring, interview question generation, audio diarization and evaluation
- **Gmail API (OAuth)** — sending interview emails

## Project structure

```
app/
  main.py         Flask routes
  clients.py      GCP client setup (Storage, Firestore, Document AI)
  config.py       env-var based configuration
  document_ai.py  resume text extraction
  gemini.py       all Gemini prompts (scoring, question generation, interview evaluation)
  gmail.py        OAuth + email sending
  templates/      index.html (recruiter), apply.html (candidate), interview.html (candidate)
  static/         style.css
```

## Setup

1. Create a GCP project, enable billing, and enable these APIs: Vertex AI, Document AI, Cloud Storage, Firestore, Gmail.
2. Create a Cloud Storage bucket and a Firestore database (Native mode), same region for both.
3. Create a Document AI **Document OCR** processor (region `us` or `eu`) — note its processor ID.
4. Authenticate locally so the Google client libraries can call these APIs as you:
   ```bash
   gcloud auth application-default login
   ```
5. Set up Gmail OAuth: **APIs & Services → OAuth consent screen**, add yourself as a test user, then **Credentials → Create OAuth client ID → Desktop app**, download the JSON and save it as `client_secret.json` in the project root (gitignored — never commit this).
6. Copy `.env.example` to `.env` and fill in your project ID, region, bucket name, and Document AI processor ID.
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
9. Open `http://127.0.0.1:5000/`, publish a job, and try the flow. The first time an email is sent, a browser window will open asking you to approve Gmail access — after that it's silent (cached in `token.json`, also gitignored).

## Status

The full pipeline above is built and working. It currently runs locally only — the links emailed to candidates point at `127.0.0.1`, so this hasn't yet been deployed anywhere publicly reachable (e.g. Cloud Run). That's the natural next step for turning this into something a real candidate outside this machine could use.


## Demo
<img width="731" height="711" alt="Screenshot 2026-07-29 at 21 07 31" src="https://github.com/user-attachments/assets/8e9ac88d-f2f9-4d6f-b336-0198f560dc96" />

<img width="737" height="775" alt="Screenshot 2026-07-29 at 21 07 41" src="https://github.com/user-attachments/assets/6b18db80-6f74-416d-9d38-a5e8cd058d48" />

<img width="440" height="755" alt="Screenshot 2026-07-29 at 22 06 23" src="https://github.com/user-attachments/assets/68b8f186-e239-43c3-9e4e-1b463dfab27a" />


<img width="751" height="803" alt="Screenshot 2026-07-29 at 21 14 39" src="https://github.com/user-attachments/assets/628d167a-a959-48e9-aa6f-34c2c75f8eef" />

<img width="698" height="779" alt="Screenshot 2026-07-29 at 21 14 27" src="https://github.com/user-attachments/assets/d46f2363-22e1-4b7b-a728-5d784c0cbea1" />

