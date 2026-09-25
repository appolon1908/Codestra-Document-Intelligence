"""Runtime configuration.

Secrets are never passed by value in the environment in production: the
environment carries a *reference* (a file path mounted from the secret store)
and the value is read from that file at startup. ``*_TOKEN`` fallbacks exist
only for local development and tests.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(RuntimeError):
    pass


def _read_secret(file_var: str, value_var: str, env: dict[str, str]) -> str | None:
    path = env.get(file_var)
    if path:
        try:
            return Path(path).read_text(encoding="utf-8").strip() or None
        except OSError as exc:
            raise ConfigError(f"{file_var} points to an unreadable file") from exc
    return env.get(value_var) or None


def _csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    database_url: str | None
    ocr_worker_url: str | None
    ocr_worker_token: str | None
    ocr_worker_timeout_seconds: float
    inbound_service_tokens: tuple[str, ...]
    allowed_workloads: tuple[str, ...]
    document_hash_pepper: str
    source_lookup_allowed_hosts: tuple[str, ...]
    max_image_bytes: int
    min_image_dimension: int
    max_image_dimension: int
    max_image_pixels: int
    environment: str = "development"
    supported_document_types: tuple[str, ...] = field(
        default=("national_id", "passport", "driver_license", "residence_permit")
    )

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        env = dict(os.environ if env is None else env)
        inbound = _read_secret("INBOUND_SERVICE_TOKENS_FILE", "INBOUND_SERVICE_TOKENS", env)
        pepper = _read_secret("DOCUMENT_HASH_PEPPER_FILE", "DOCUMENT_HASH_PEPPER", env)
        environment = env.get("APP_ENV", "development")
        if not pepper:
            if environment == "production":
                raise ConfigError("DOCUMENT_HASH_PEPPER_FILE is required in production")
            pepper = "development-only-pepper"
        return cls(
            database_url=_read_secret("DATABASE_URL_FILE", "DATABASE_URL", env),
            ocr_worker_url=(env.get("OCR_WORKER_URL") or "").rstrip("/") or None,
            ocr_worker_token=_read_secret("OCR_WORKER_TOKEN_FILE", "OCR_WORKER_TOKEN", env),
            ocr_worker_timeout_seconds=float(env.get("OCR_WORKER_TIMEOUT_SECONDS", "20")),
            inbound_service_tokens=_csv(inbound),
            allowed_workloads=_csv(env.get("ALLOWED_WORKLOADS", "middleware-v3")),
            document_hash_pepper=pepper,
            source_lookup_allowed_hosts=tuple(h.lower() for h in _csv(env.get("SOURCE_LOOKUP_ALLOWED_HOSTS", ""))),
            max_image_bytes=int(env.get("MAX_IMAGE_BYTES", str(8 * 1024 * 1024))),
            min_image_dimension=int(env.get("MIN_IMAGE_DIMENSION", "320")),
            max_image_dimension=int(env.get("MAX_IMAGE_DIMENSION", "8000")),
            max_image_pixels=int(env.get("MAX_IMAGE_PIXELS", str(40_000_000))),
            environment=environment,
        )
