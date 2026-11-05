import os

from dotenv import load_dotenv

load_dotenv()

GCP_PROJECT_ID = os.environ["GCP_PROJECT_ID"]
GCP_REGION = os.environ["GCP_REGION"]
GCS_BUCKET_NAME = os.environ["GCS_BUCKET_NAME"]
DOCUMENT_AI_LOCATION = os.environ["DOCUMENT_AI_LOCATION"]
DOCUMENT_AI_PROCESSOR_ID = os.environ["DOCUMENT_AI_PROCESSOR_ID"]
ATS_SCORE_THRESHOLD = int(os.environ["ATS_SCORE_THRESHOLD"])
INTERVIEW_SCORE_THRESHOLD = int(os.environ["INTERVIEW_SCORE_THRESHOLD"])
BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:5000")
SECRET_KEY = os.environ["SECRET_KEY"]
GOOGLE_OAUTH_CLIENT_ID = os.environ["GOOGLE_OAUTH_CLIENT_ID"]

# How long a shortlisted candidate has to finish the assessment once the link
# is emailed.
ASSESSMENT_WINDOW_HOURS = int(os.environ.get("ASSESSMENT_WINDOW_HOURS", "48"))
# Hold the shortlist email back this many hours after the candidate applies
# (0 = send immediately). Due emails are sent by a Cloud Scheduler job that
# calls /internal/send-due-emails, authenticated as SCHEDULER_SERVICE_ACCOUNT.
SHORTLIST_EMAIL_DELAY_HOURS = float(os.environ.get("SHORTLIST_EMAIL_DELAY_HOURS", "0"))
SCHEDULER_SERVICE_ACCOUNT = os.environ.get("SCHEDULER_SERVICE_ACCOUNT", "")
