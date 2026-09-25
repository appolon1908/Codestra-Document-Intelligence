"""Workload identity contract.

Document Intelligence is only reachable from Middleware V3 (Caddy -> Kong ->
Middleware V3 -> this service). Middleware V3 authenticates the end user,
resolves the tenant, and calls this service with:

* ``Authorization: Bearer <service token>`` - Middleware V3's workload token
  (one of ``INBOUND_SERVICE_TOKENS``), compared in constant time;
* ``X-Codestra-Workload`` - the calling workload name, must be allowlisted;
* ``X-Tenant-ID`` - the tenant resolved by Middleware V3. Tenant is taken
  only from this header, never from request bodies or query strings.
* ``X-Codestra-Actor`` (optional) - opaque operator/actor reference for audit.
"""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import metrics

_bearer = HTTPBearer(auto_error=False, scheme_name="WorkloadToken", description="Middleware V3 workload token")

TENANT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
ACTOR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")


@dataclass(frozen=True)
class WorkloadIdentity:
    workload: str
    tenant_id: str
    actor: str | None


def _deny(status: int, reason: str, detail: str) -> HTTPException:
    metrics.AUTH_FAILURES.labels(reason=reason).inc()
    return HTTPException(status_code=status, detail={"code": reason, "message": detail})


def workload_identity(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    x_codestra_workload: str | None = Header(
        default=None, description="Required. Calling workload name (allowlisted, e.g. middleware-v3)."
    ),
    x_tenant_id: str | None = Header(
        default=None, description="Required. Tenant resolved by Middleware V3; the only tenant source."
    ),
    x_codestra_actor: str | None = Header(default=None, description="Optional opaque operator reference."),
) -> WorkloadIdentity:
    settings = request.app.state.settings
    if not settings.inbound_service_tokens:
        raise _deny(503, "auth_not_configured", "inbound workload tokens are not configured")
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise _deny(401, "missing_workload_token", "workload bearer token required")
    presented = credentials.credentials.encode()
    if not any(hmac.compare_digest(presented, t.encode()) for t in settings.inbound_service_tokens):
        raise _deny(401, "invalid_workload_token", "workload token rejected")
    if not x_codestra_workload or x_codestra_workload not in settings.allowed_workloads:
        raise _deny(403, "workload_not_allowed", "calling workload is not allowlisted")
    if not x_tenant_id:
        raise _deny(400, "tenant_required", "X-Tenant-ID is required")
    if not TENANT_RE.match(x_tenant_id):
        raise _deny(400, "tenant_invalid", "X-Tenant-ID is malformed")
    actor = x_codestra_actor if x_codestra_actor and ACTOR_RE.match(x_codestra_actor) else None
    identity = WorkloadIdentity(workload=x_codestra_workload, tenant_id=x_tenant_id, actor=actor)
    request.state.tenant_id = identity.tenant_id
    return identity


Identity = Depends(workload_identity)
