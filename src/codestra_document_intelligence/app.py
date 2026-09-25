from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field
from enum import Enum
from uuid import uuid4

class JobState(str, Enum):
    queued="queued"; preprocessing="preprocessing"; extracting="extracting"; validating="validating"; review_required="review_required"; completed="completed"; failed="failed"; canceled="canceled"

class JobCreate(BaseModel):
    document_ref: str = Field(min_length=1)
    document_type: str = Field(default="generic_document", min_length=1)

class Job(BaseModel):
    job_id: str; operation_id: str; tenant_id: str; state: JobState; document_ref: str; document_type: str

app=FastAPI(title="Codestra Document Intelligence",version="0.1.0")
_jobs: dict[str,Job]={}; _idem: dict[tuple[str,str],str]={}

def context(x_tenant_id: str|None, x_correlation_id: str|None):
    if not x_tenant_id or not x_correlation_id: raise HTTPException(status_code=401,detail="trusted tenant and correlation context required")
    return x_tenant_id,x_correlation_id

@app.get("/healthz")
def health(): return {"status":"ok"}
@app.get("/readyz")
def ready(): return {"status":"ready"}
@app.post("/v1/jobs",response_model=Job,status_code=status.HTTP_202_ACCEPTED)
def create_job(body:JobCreate,x_tenant_id:str|None=Header(None),x_correlation_id:str|None=Header(None),idempotency_key:str|None=Header(None)):
    tenant,_=context(x_tenant_id,x_correlation_id)
    if not idempotency_key: raise HTTPException(400,"idempotency-key required")
    key=(tenant,idempotency_key)
    if key in _idem: return _jobs[_idem[key]]
    jid=str(uuid4()); job=Job(job_id=jid,operation_id=str(uuid4()),tenant_id=tenant,state=JobState.queued,document_ref=body.document_ref,document_type=body.document_type)
    _jobs[jid]=job; _idem[key]=jid; return job
@app.get("/v1/jobs/{job_id}",response_model=Job)
def get_job(job_id:str,x_tenant_id:str|None=Header(None),x_correlation_id:str|None=Header(None)):
    tenant,_=context(x_tenant_id,x_correlation_id); job=_jobs.get(job_id)
    if not job or job.tenant_id!=tenant: raise HTTPException(404,"job not found")
    return job
