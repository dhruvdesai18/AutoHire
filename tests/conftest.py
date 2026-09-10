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
os.environ.setdefault("BASE_URL", "http://testserver")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("GOOGLE_OAUTH_CLIENT_ID", "test-client-id.apps.googleusercontent.com")

patch("google.cloud.storage.Client", MagicMock()).start()
patch("google.cloud.firestore.Client", MagicMock()).start()
patch("google.cloud.documentai.DocumentProcessorServiceClient", MagicMock()).start()
patch("google.genai.Client", MagicMock()).start()

import pytest  # noqa: E402

TEST_USER_ID = "test-user-id"
TEST_USER_EMAIL = "test@example.com"


@pytest.fixture
def app():
    from app.main import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def logged_in_client(app):
    test_client = app.test_client()
    with test_client.session_transaction() as sess:
        sess["user_id"] = TEST_USER_ID
        sess["user_email"] = TEST_USER_EMAIL
        sess["user_name"] = "Test User"
    return test_client
