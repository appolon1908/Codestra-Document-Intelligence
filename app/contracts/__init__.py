"""Versioned wire contracts shared with Codestra-OCR-Workers.

The JSON Schemas in this package are the reference copies pinned by this
service. Their ``$id`` is the schema reference carried on the wire.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources

from jsonschema import Draft202012Validator

EXTRACT_REQUEST_SCHEMA_REF = "codestra.ocr.extract-request/v1"
EXTRACTION_RESULT_SCHEMA_REF = "codestra.ocr.extraction-result/v1"
FACE_ID_HANDOFF_SCHEMA_REF = "codestra.document.face-id-handoff/v1"

_FILES = {
    EXTRACT_REQUEST_SCHEMA_REF: "ocr-extract-request.v1.schema.json",
    EXTRACTION_RESULT_SCHEMA_REF: "ocr-extraction-result.v1.schema.json",
}


@cache
def load_schema(schema_ref: str) -> dict:
    name = _FILES[schema_ref]
    return json.loads(resources.files(__package__).joinpath(name).read_text(encoding="utf-8"))


@cache
def validator(schema_ref: str) -> Draft202012Validator:
    schema = load_schema(schema_ref)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def schema_errors(schema_ref: str, document: object) -> list[str]:
    """Return human-readable violations (paths only, never values)."""
    errors = sorted(validator(schema_ref).iter_errors(document), key=lambda e: list(e.absolute_path))
    return [f"/{'/'.join(str(p) for p in e.absolute_path)}: {e.validator}" for e in errors[:20]]
