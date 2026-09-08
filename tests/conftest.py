import os
from unittest.mock import MagicMock, patch

# Config values the app requires at import time — dummies are fine since
# every GCP/Gemini client is mocked below before app.main is ever imported.
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("GCP_REGION", "us-central1")
os.environ.setdefault("GCS_BUCKET_NAME", "test-bucket")
os.environ.setdefault("DOCUMENT_AI_LOCATION", "us")
os.environ.setdefault("DOCUMENT_AI_PROCESSOR_ID", "test-processor")
os.environ.setdefault("ATS_SCORE_THRESHOLD", "70")
os.environ.setdefault("INTERVIEW_SCORE_THRESHOLD", "70")
os.environ.setdefault("DASHBOARD_PASSWORD", "test-password")
os.environ.setdefault("BASE_URL", "http://testserver")

patch("google.cloud.storage.Client", MagicMock()).start()
patch("google.cloud.firestore.Client", MagicMock()).start()
patch("google.cloud.documentai.DocumentProcessorServiceClient", MagicMock()).start()
patch("google.genai.Client", MagicMock()).start()

import base64  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture
def app():
    from app.main import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_header():
    return {
        "Authorization": "Basic "
        + base64.b64encode(b"recruiter:test-password").decode()
    }
