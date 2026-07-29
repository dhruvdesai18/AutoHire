from google.cloud import documentai

from app.clients import documentai_client
from app.config import DOCUMENT_AI_LOCATION, DOCUMENT_AI_PROCESSOR_ID, GCP_PROJECT_ID

processor_name = documentai_client.processor_path(
    GCP_PROJECT_ID, DOCUMENT_AI_LOCATION, DOCUMENT_AI_PROCESSOR_ID
)


def extract_text(pdf_bytes: bytes) -> str:
    raw_document = documentai.RawDocument(
        content=pdf_bytes, mime_type="application/pdf"
    )
    request = documentai.ProcessRequest(
        name=processor_name, raw_document=raw_document
    )
    result = documentai_client.process_document(request=request)
    return result.document.text
