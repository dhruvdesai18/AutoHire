from google.api_core.client_options import ClientOptions
from google.cloud import documentai, firestore, storage

from app.config import DOCUMENT_AI_LOCATION, GCP_PROJECT_ID, GCS_BUCKET_NAME

storage_client = storage.Client(project=GCP_PROJECT_ID)
bucket = storage_client.bucket(GCS_BUCKET_NAME)

db = firestore.Client(project=GCP_PROJECT_ID)

documentai_client = documentai.DocumentProcessorServiceClient(
    client_options=ClientOptions(
        api_endpoint=f"{DOCUMENT_AI_LOCATION}-documentai.googleapis.com"
    )
)
