# AutoHire — project context for Claude Code

Read this whole file before doing anything in this repo. It's written so a
session with zero prior context can get productive in minutes.

## What this is

AutoHire is an AI-driven hiring pipeline, built as a public, recruiter-facing
portfolio project (the goal is to post it publicly — e.g. LinkedIn — for
strangers to sign in and try). A recruiter publishes a role and gets a
shareable link. A candidate applies with **just a resume** — no account, no
form. From there, everything runs automatically: resume parsing, AI scoring
against the job description, a gate, a personalized shortlist email, a
timed recorded interview the candidate takes in-browser, AI evaluation of
the answers, and a final advance/reject decision — all visible to the
recruiter on a live dashboard. A human only re-enters the loop to review the
final decision (or publish a role, or evaluate a finished assessment).

**Live:** https://autohire-568278938456.us-central1.run.app
**Repo:** github.com/dhruvdesai18/AutoHire

## Tech stack

- **Flask** — single backend app, server-rendered Jinja2 + vanilla JS (no
  frontend framework), deployed on **Cloud Run** via Docker + gunicorn
  (`--workers 4 --timeout 600` — the timeout is intentionally high to allow
  the multi-call SSE team-planning stream to run to completion)
- **Cloud Storage** — resumes and per-question interview recordings
- **Firestore (Native mode)** — `jobs`, `candidates`, `users` collections;
  the single source of truth the whole pipeline reads/writes
- **Document AI** — resume text extraction (OCR)
- **Vertex AI (Gemini 2.5 Flash, via the `google-genai` SDK)** — resume
  scoring, JD formatting, interview question generation, per-answer
  evaluation, and the team-planning multi-agent pipeline. All structured
  output goes through `_generate_json()` in `app/gemini.py`, which sets
  `response_mime_type="application/json"` and retries up to 3x on a
  `JSONDecodeError` (Gemini occasionally drops a closing bracket on long
  lists even in JSON mode — this bit us once in production, see Known
  issues below)
- **Gmail API (OAuth, Desktop app client)** — sends the shortlist email;
  credentials live only in Secret Manager (`gmail-token`), never in the repo
- **MediaRecorder API** — real-time in-browser audio recording for the
  candidate's assessment
- **Google Identity Services** — recruiter "Sign in with Google" (client-side
  JWT, verified server-side)

## The pipeline, step by step

1. **Publish a role** — recruiter types a title + description (or generates
   one via "Describe a project", see below). `format_job_description()`
   (Gemini) reformats it into structured sections (overview, responsibilities,
   requirements, etc.) for the candidate-facing page. A shareable
   `/apply/<job_id>` link is issued.
2. **Candidate applies** — uploads a PDF resume to GCS. No other input.
3. **Parse** — Document AI extracts raw text (`app/document_ai.py`).
4. **Score** — `score_resume()` (Gemini) scores 0-100 against the JD, also
   extracting the candidate's name and matched/missing skills.
5. **Gate 1** — below `ATS_SCORE_THRESHOLD` → rejected. Candidate always
   sees the same generic "thanks for applying" message either way — the
   score is never shown to them.
6. **Generate interview prep** — `generate_interview_prep()` (Gemini)
   extracts the candidate's email and writes 5 questions tailored to their
   resume and the role.
7. **Send shortlist email** — Gmail API sends a short personalized email
   with a link to the assessment and a 24-hour deadline (enforced
   server-side via `assessment_deadline` / `_is_expired()`).
8. **Candidate takes the assessment** (`/interview/<candidate_id>`) — a
   30-minute overall window, 2 tries per question, 90 seconds per try,
   in-browser recording via MediaRecorder. Partial completion is fine;
   whatever's recorded gets submitted (auto-submits at zero).
9. **Evaluate** — recruiter clicks "Evaluate" on the dashboard;
   `evaluate_interview()` (Gemini, multimodal — audio + question text per
   clip, no diarization needed since each clip is already "this candidate's
   answer to question N") transcribes and scores each answer, 0-100 overall.
10. **Gate 2** — below `INTERVIEW_SCORE_THRESHOLD` → rejected, above →
    advanced. Recruiter dashboard reflects the final status for both gates
    and the full decision trail.

### "Describe a project" (team-planning agents)

A separate, newer flow (`/jobs/team-plan`, `app/role_planner.py`): the
recruiter describes a whole project in plain language instead of one role.
A 4-stage agent pipeline (plain Python, **no LangGraph** — deliberately
reimplemented against the existing `_generate_json()` convention to avoid a
second LLM-calling pattern in the codebase) runs:

1. **Team planning** — `plan_team()` decides which roles the project
   actually needs and how many of each, with a "rationale" per role written
   as 3-5 natural, specific sentences (not a generic blurb — this prompt was
   rewritten once already after it was too vague, see git history on
   `role_planner.py`).
2. **Requirements** — `define_role_requirements()`, per role, works out
   what *this project specifically* demands of that role.
3. **Write** — `write_job_description()` turns requirements into a JD.
4. **Review** — `review_job_description()` checks for vague language,
   unrealistic requirements, missing skills, jargon; loops back to Write
   with revision instructions if rejected, up to `max_revisions`.

This whole thing streams over **Server-Sent Events**
(`POST /jobs/generate-team`, consumed by `team_plan.html`) because a
multi-role run is realistically a multi-minute, many-Gemini-call process —
far too long for a normal blocking request. Each generated role card has a
**Description** tab (the actual JD) and an **Explanation** tab (the plain-
language rationale for why the role exists). Publishing a role from this
page updates that card in place (shows a "Published" badge + shareable
link) — it deliberately does **not** navigate away, because the first
version did, and publishing one role out of a generated batch wiped out all
the other generated roles, forcing the recruiter to regenerate from
scratch. Don't reintroduce that redirect.

## Repo map

```
app/
  main.py          Flask routes (everything — pipeline, auth, team-plan)
  clients.py        GCS/Firestore/Document AI client setup
  config.py          env-var config (see below)
  document_ai.py      resume text extraction
  gemini.py            all Gemini prompts/calls — score_resume,
                         generate_interview_prep, format_job_description,
                         evaluate_interview, plus the shared _generate_json/
                         _call_json retry-wrapped JSON-calling helpers
  gmail.py              OAuth + email sending (token.json locally /
                         Secret Manager in prod)
  role_planner.py        the 4-agent team-planning pipeline (see above)
  templates/
    index.html            recruiter dashboard (3-column: roles rail,
                            candidate table, profile panel) — search/filter/
                            sort on both roles and candidates, count-up
                            animated scores, guided tour, welcome modal
    team_plan.html          "Describe a project" page (see above)
    apply.html               candidate apply page — drag-and-drop resume
                               dropzone, staggered JD section entrance
    interview.html            candidate assessment page — per-question and
                                overall visual progress bars, smooth
                                intro→live transition
    login.html                 Google Sign-In
    privacy.html, terms.html    static legal pages
  static/
    style.css    one shared design system — parchment/gold/serif
                   ("Classical" theme, intentionally kept, not a generic
                   SaaS look — see Design identity below)
    app.js         small shared helpers: showToast, skeletonLines,
                     escapeHtml (shared because both index.html and
                     team_plan.html need it)
tests/
  conftest.py       mocks every GCP/Gemini client at import time;
                      logged_in_client / admin_client fixtures craft valid
                      signed session cookies without real OAuth
  test_routes.py, test_helpers.py, test_role_planner.py
Dockerfile          gunicorn --workers 4 --timeout 600
.github/workflows/deploy.yml   CI (pytest) → CD (gcloud run deploy) on
                                  push to main
```

28 tests, all mocked (no network calls in CI). Run with
`source venv/bin/activate && python -m pytest -q`.

## Design identity

The UI is a deliberate "Classical" editorial theme — parchment background
(`--color-bg: #f3f2f2`), gold accent (`--color-accent: #b68235`), Cormorant
Garamond serif headings, Lora serif body. **This was a deliberate choice,
confirmed explicitly with the user** ("refine the current look, don't
replace it") when asked about a full redesign — don't swap it for a generic
modern-SaaS look without being asked again. Within that constraint, the
user does want real interactivity: live search/filter, sortable tables,
count-up animations, smooth transitions, drag-and-drop — all already
implemented across the dashboard and candidate-facing pages as of this
writing.

## Auth model

- **Recruiters**: Google Sign-In (GIS), verified server-side
  (`google.oauth2.id_token.verify_oauth2_token`), Flask signed-cookie
  session. Multi-tenant: every job/candidate doc has `owner_id`/
  `owner_email`; `_owns_or_admin()` gates access. `is_admin` is a manual
  flag on the Firestore `users/{google_sub}` doc — **nothing in the code
  sets it automatically**, it has to be hand-set. As of the last check only
  `hr.autohire@gmail.com` (the system/sending account) had it set — the
  user's own actual sign-in account did not. If asked "why can't I see
  other people's jobs as admin," this is almost certainly why.
- **Candidates**: no auth at all, by design (`/apply`, `/interview` are
  open). This is intentional, not a gap.

## GCP config / current project

**Always use `autohr-510611`** (see the full migration section below for
why and what changed). Key env vars (`app/config.py`, required at import —
see `.env` locally, Cloud Run env vars in prod):

```
GCP_PROJECT_ID=autohr-510611
GCP_REGION=us-central1
GCS_BUCKET_NAME=autohire-autohr-510611
DOCUMENT_AI_LOCATION=us
DOCUMENT_AI_PROCESSOR_ID=a3c647055e594662
ATS_SCORE_THRESHOLD=70
INTERVIEW_SCORE_THRESHOLD=70
GOOGLE_OAUTH_CLIENT_ID=568278938456-9cvjr5q19ucaov8k5akbdcs7vgoqcbtq.apps.googleusercontent.com
```

`SECRET_KEY` is a long random value (Flask session signing) — reuse what's
already deployed, don't rotate casually, it invalidates every active
session. `BASE_URL` is the local-dev or prod URL, used to build links in
emails and OG meta tags.

## Known issues / gotchas (read before debugging)

- **Gmail OAuth token expires every ~7 days.** The Gmail OAuth app is in
  Google's "Testing" publishing status (not "In production"), which caps
  refresh-token lifetime at 7 days regardless of use. This has broken
  production at least twice in this project's history, each time as an
  **uncaught exception inside the `/apply` POST handler** (a candidate who
  scores well enough to be shortlisted gets a raw 500 instead of "Thanks for
  applying" — the candidate record is still correctly created and scored,
  just the email step throws). Symptom in logs:
  `google.auth.exceptions.RefreshError: ('invalid_grant: Token has been
  expired or revoked.'...)`. **The fix**: re-run the interactive OAuth flow
  locally (back up the stale `token.json` first, don't just delete it blind —
  `_get_credentials()` in `app/gmail.py` will throw on `creds.refresh()`
  instead of falling through to re-auth if a stale-but-present token file
  has an already-dead refresh token), then
  `gcloud secrets versions add gmail-token --data-file=token.json
  --project=autohr-510611`, then `gcloud run deploy autohire --source . ...`
  (or just push — CI/CD picks up the new secret version on next deploy; a
  running revision does **not** auto-refresh a mounted secret). **The real
  fix** nobody has done yet: move the Gmail OAuth consent screen to "In
  production" status in Google Cloud Console, which removes the 7-day cap
  entirely. Flag this to the user periodically; it's a known standing TODO.
- **Local `.env` can silently point at a deleted/wrong GCP project.** This
  already caused a confusing debugging session once: local ADC auth kept
  "failing" when the actual bug was `.env`'s `GCP_PROJECT_ID` still pointing
  at the old, now-deleted `autohr-501816` project. Check `.env` first if any
  local Gemini/Firestore/GCS call 403s or 404s mysteriously.
- **Local Application Default Credentials (`gcloud auth application-default
  login`) are a separate credential store from `gcloud auth login` (CLI
  identity).** They can be signed into completely different Google accounts.
  If `gcloud` CLI commands work but Python client libraries 403 (or vice
  versa), this mismatch is almost always why. `gcloud auth list` shows CLI
  identities; it does *not* tell you which account ADC is using.
  `dhruvddd11@gmail.com` is the account that owns `autohr-510611` and should
  be used for both.
- **CSS: a flex child with `white-space: nowrap` content can overflow its
  container instead of wrapping.** Already bit the team-plan page once —
  `required_skills`/`preferred_skills` from the JD writer are full
  sentences, not short keywords, but were first rendered as `.tag` pills
  (which are `white-space: nowrap`, correctly, for the *short* skill tags
  used elsewhere like the dashboard's matched/missing skills). Long
  sentences in a nowrap pill don't wrap — they overflow past the card edge
  and visually widen the whole card. Fixed by rendering long free-text
  content as wrapping bullet lines (`.jd-line`), and by adding a defensive
  `.card > * { min-width: 0 }` in `style.css` (flex items default to
  `min-width: auto`, which is the actual root enabler of this class of
  overflow bug). If a `.tag` pill is ever used for Gemini-generated content
  again, check whether that content is actually short-keyword-shaped first.
- **Firestore `DocumentSnapshot.get(field)` raises `KeyError` on a missing
  field**, unlike a dict's `.get()`. Always `.to_dict().get(field, default)`
  instead. This convention is already followed everywhere in `main.py`;
  keep following it in new code.
- **`npx hyperframes` / the `brag-output/` directory** at the repo root is
  leftover from an unrelated one-off experiment (generating a launch-video
  concept with the `brag` Claude Code plugin). It is **not part of the app**
  and was deliberately never committed — don't try to wire it in or treat it
  as a real feature.

## Testing & deployment workflow (how this project actually verifies changes)

This project has a strong established pattern, used consistently — follow
it:

1. Make the change.
2. `python -m pytest -q` (all 28 should pass; add tests for new routes/logic
   following `tests/conftest.py`'s mocking pattern).
3. **Verify live, for real, before considering anything done.** This project
   does not trust "should work" — it runs the actual local dev server
   (`python -m app.main`), mints a valid signed session cookie via
   `app.test_request_context()` + `app.session_interface.save_session()`
   (real Google Sign-In can't be driven from the sandboxed browser tool),
   and drives the real UI in the Browser tool against real GCP resources —
   never mocks in this kind of verification. For data created purely to
   verify something (test candidates, test jobs), clean it up afterward
   unless it's a legitimate exercise of the real pipeline worth leaving.
4. `git add` the specific files (never `-A`/`.` — this repo has accumulated
   stray untracked files like `.Rhistory` and `brag-output/` that must never
   be committed), commit with a message explaining *why*, push to `main`.
5. CI runs pytest, then CD deploys via `gcloud run deploy --source .` on
   success. Poll `gcloud run revisions list --service=autohire
   --region=us-central1 --project=autohr-510611 --limit=1` for the new
   revision name, confirm `status.traffic` shows it at 100%, check
   `gcloud logging read '...severity=ERROR...' --freshness=5m` is clean.
6. Spot-check the live change with `curl` or the Browser tool against the
   real production URL.

Commit messages: explain the *why*, not just the *what*. **Never add a
"Co-Authored-By: Claude" trailer** — this repo's commits are plain.

## Standing user preferences

- Don't delete/clean up Firestore jobs or candidates without being asked
  directly, even ones that look like test data — ask first.
- Documentation gets compiled/updated deliberately (like this file), not
  scattered mid-build.
- This is a public, recruiter-facing portfolio project — code quality and
  not leaking secrets matters more than it would for a private tool.

---

## GCP migration (2026-10-04)

This project moved from one GCP account/project to a new one. **Always use the new project — the old one is deleted.**

| | Old (deleted) | New (current) |
|---|---|---|
| GCP account | abhijaynegi325@gmail.com | dhruvddd11@gmail.com |
| Project ID | `autohr-501816` | `autohr-510611` |
| Project number | `1090038135673` | `568278938456` |
| `autohire` URL | ~~autohire-1090038135673.us-central1.run.app~~ | https://autohire-568278938456.us-central1.run.app |
| `portfolio-chat` URL | ~~portfolio-chat-1090038135673.us-central1.run.app~~ | https://portfolio-chat-568278938456.us-central1.run.app |

Reason: the old account's free trial ended. All data (Firestore `jobs`/`candidates`/`users`, GCS resumes/interview recordings) and all GCP resources were migrated 1:1 — recreated where they couldn't be copied directly (Document AI processor, OAuth clients, Gmail token, API keys, service accounts, Workload Identity Federation).

### What has a new value (not interchangeable with the old one)

- **`DOCUMENT_AI_PROCESSOR_ID`**: `a3c647055e594662` (new OCR processor, same type/config as before, no custom training data existed to lose)
- **`GOOGLE_OAUTH_CLIENT_ID`**: `568278938456-9cvjr5q19ucaov8k5akbdcs7vgoqcbtq.apps.googleusercontent.com` (new Web application OAuth client — used for recruiter "Sign in with Google"; verified working, admin flags in Firestore `users` carried over since Google's `sub` is account-scoped, not client-scoped)
- **Gmail OAuth**: a separate **Desktop app** OAuth client was created for the `gmail.send` flow in `app/gmail.py`. The resulting `token.json` lives only in Secret Manager (`gmail-token` secret, new project) — never in this repo.
- **`SECRET_KEY`**: rotated to a fresh value on redeploy (the old one had been sitting in plaintext in Cloud Run env vars — treat that as a closed security item, not something to reuse)
- **Gemini API key**: recreated, restricted to `generativelanguage.googleapis.com`, bound to a new `recruitmanage@autohr-510611.iam.gserviceaccount.com` service account

### CI/CD (`.github/workflows/deploy.yml`)

Updated to deploy to the new project via a new Workload Identity Federation pool/provider:
- `workload_identity_provider: projects/568278938456/locations/global/workloadIdentityPools/github-pool/providers/github-provider`
- `service_account: github-deployer@autohr-510611.iam.gserviceaccount.com`

Note: `github-deployer` needs `roles/iam.serviceAccountUser` granted **directly on** the default compute service account (`568278938456-compute@developer.gserviceaccount.com`), not just project-level roles — this binding lives on the service account resource itself and is easy to miss when recreating IAM from a project-level audit. It's already set.

### Portfolio site integration

`dhruvdesai18.github.io/myportfolio` (repo: `dhruvdesai18/myportfolio`, local: `~/Downloads/DhruvDesai Portfolio`) embeds links to both services via `script.js` (`AUTOHIRE_LIVE_URL`, `CHATBOT_API_URL`). Already updated and verified live — if you ever redeploy AutoHire to yet another project, that file needs updating too, plus the `portfolio-chat` CORS allowlist (`app.py` in the Portfolio Chatbot repo) if the frontend origin ever changes.
