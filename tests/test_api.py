from fastapi.testclient import TestClient
from codestra_document_intelligence.app import app
c=TestClient(app); h={"x-tenant-id":"t1","x-correlation-id":"c1","idempotency-key":"k1"}
def test_health(): assert c.get("/healthz").status_code==200
def test_idempotent_and_tenant_scoped():
 r=c.post("/v1/jobs",headers=h,json={"document_ref":"obj://a"}); assert r.status_code==202
 r2=c.post("/v1/jobs",headers=h,json={"document_ref":"obj://a"}); assert r2.json()["job_id"]==r.json()["job_id"]
 assert c.get("/v1/jobs/"+r.json()["job_id"],headers={"x-tenant-id":"t2","x-correlation-id":"c2"}).status_code==404
