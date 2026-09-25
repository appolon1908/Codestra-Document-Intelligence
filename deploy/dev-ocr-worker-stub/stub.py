"""DEVELOPMENT ONLY stand-in for Codestra-OCR-Workers.

Performs no OCR. It authenticates the service token and returns a canned,
contract-valid ``codestra.ocr.extraction-result/v1`` body so the compose
stack can be exercised end to end. Never deploy this.
"""

import hmac
import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException

TOKEN = Path(os.environ["OCR_WORKER_TOKEN_FILE"]).read_text().strip()
app = FastAPI(title="dev-ocr-worker-stub")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/v1/ocr/extract")
def extract(body: dict, authorization: str = Header(default="")):
    if not hmac.compare_digest(authorization, f"Bearer {TOKEN}"):
        raise HTTPException(401, "bad service token")
    return {
        "schema_ref": "codestra.ocr.extraction-result/v1",
        "request_id": body["request_id"],
        "worker": {"name": "dev-ocr-worker-stub", "version": "0.0.0", "engine": "none"},
        "document_type": body["document_type"],
        "country": body["country"],
        "fields": {
            "given_names": {"value": "JUAN", "confidence": 0.5, "source": "visual"},
            "surnames": {"value": "DEMO", "confidence": 0.5, "source": "visual"},
            "document_number": {"value": "000-0000000-1", "confidence": 0.5, "source": "visual"},
        },
        "image_digests": {img["side"]: img["sha256"] for img in body["images"]},
        "quality": {"overall_confidence": 0.5, "warnings": ["dev_stub_no_ocr"]},
        "qr": {"present": False, "source_lookup_url": None},
        "portrait": {"detected": False},
    }
