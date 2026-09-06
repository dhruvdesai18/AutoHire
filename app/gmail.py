import base64
import os
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
CLIENT_SECRET_PATH = "client_secret.json"
TOKEN_PATH = os.environ.get("GMAIL_TOKEN_PATH", "token.json")


def _get_credentials() -> Credentials:
    creds = None
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    except FileNotFoundError:
        pass

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_PATH, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w") as token_file:
            token_file.write(creds.to_json())

    return creds


def send_email(to_email: str, subject: str, body: str) -> None:
    creds = _get_credentials()
    service = build("gmail", "v1", credentials=creds)

    message = MIMEText(body)
    message["to"] = to_email
    message["subject"] = subject
    message["from"] = "AutoHire <hr.autohire@gmail.com>"
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    service.users().messages().send(userId="me", body={"raw": raw}).execute()
