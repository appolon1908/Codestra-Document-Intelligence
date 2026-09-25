from fastapi.testclient import TestClient
from codestra_document_intelligence.app import app
c=TestClient(app)
def H(t="t1",k="k1"): return {"x-tenant-id":t,"x-correlation-id":"corr","idempotency-key":k}
def make(k="k1"): return c.post("/v1/jobs",headers=H(k=k),json={"document_ref":"obj://a"}).json()
def test_health_ready(): assert c.get("/healthz").status_code==200 and c.get("/readyz").status_code==200
def test_idempotent_tenant():
 a=make("idem"); b=c.post("/v1/jobs",headers=H(k="idem"),json={"document_ref":"obj://a"}).json(); assert a["job_id"]==b["job_id"]; assert c.get("/v1/jobs/"+a["job_id"],headers=H("other")).status_code==404
def test_state_machine_and_operation_readback():
 j=make("state"); url="/v1/jobs/"+j["job_id"]+"/transitions"; headers=H(k="x")
 assert c.post(url,headers=headers,json={"state":"completed"}).status_code==409
 for s in ["preprocessing","extracting","validating","completed"]: assert c.post(url,headers=headers,json={"state":s}).status_code==200
 assert c.get("/v1/operations/"+j["operation_id"],headers=headers).json()["state"]=="completed"
def test_missing_context_denied(): assert c.post("/v1/jobs",json={"document_ref":"x"}).status_code==401
