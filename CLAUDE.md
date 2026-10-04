# AutoHire — project context for Claude Code

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
