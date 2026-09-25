"""Sensitive value protection.

Document/personal numbers are never persisted in clear. For each protected
field we keep a tenant-scoped keyed hash (HMAC-SHA256 with a pepper held in
the secret store) and the last four characters. MRZ lines embed the document
number, so they are persisted as a keyed hash only.
"""

from __future__ import annotations

import hashlib
import hmac
import re

NUMBER_FIELDS = frozenset({"document_number", "personal_number", "national_id_number", "tax_id"})
PRIMARY_NUMBER_FIELDS = ("document_number", "personal_number", "national_id_number")
_NORMALISE_RE = re.compile(r"[^0-9A-Z]")


def is_number_field(name: str) -> bool:
    return name in NUMBER_FIELDS


def is_hash_only_field(name: str) -> bool:
    return name.startswith("mrz")


def normalise(value: str) -> str:
    return _NORMALISE_RE.sub("", value.upper())


def keyed_hash(pepper: str, tenant_id: str, country: str, document_type: str, field: str, value: str) -> str:
    message = "\x1f".join((tenant_id, country, document_type, field, normalise(value))).encode()
    digest = hmac.new(pepper.encode(), message, hashlib.sha256).hexdigest()
    return f"hmac-sha256:{digest}"


def last4(value: str) -> str:
    return normalise(value)[-4:]


def mask(value_last4: str | None) -> str | None:
    return None if value_last4 is None else f"****{value_last4}"


def protect_field(name: str, field: dict, *, pepper: str, tenant_id: str, country: str, document_type: str) -> dict:
    """Return the persistable representation of one extracted field."""
    stored = {k: v for k, v in field.items() if k != "value"}
    value = field.get("value")
    if value is None or not (is_number_field(name) or is_hash_only_field(name)):
        stored["value"] = value
        return stored
    stored["value"] = None
    stored["redacted"] = True
    stored["hash"] = keyed_hash(pepper, tenant_id, country, document_type, name, value)
    if is_number_field(name):
        stored["last4"] = last4(value)
    return stored


def protect_fields(fields: dict, **ctx) -> dict:
    return {name: protect_field(name, f, **ctx) for name, f in fields.items()}


def primary_number(fields: dict) -> tuple[str | None, str | None]:
    """(hash, last4) of the primary document number from protected fields."""
    for name in PRIMARY_NUMBER_FIELDS:
        f = fields.get(name)
        if f and f.get("redacted"):
            return f.get("hash"), f.get("last4")
    return None, None
