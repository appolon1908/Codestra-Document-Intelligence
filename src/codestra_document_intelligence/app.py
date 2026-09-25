from enum import Enum
from uuid import uuid4
from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

class JobState(str, Enum):
    queued="queued"; preprocessing="preprocessing"; extracting="extracting"; validating="validating"; review_required="review_required"; completed="completed"; failed="failed"; canceled="canceled"

TERMINAL={JobState.completed,JobState.failed,JobState.canceled}
TRANSITIONS={
 JobState.queued:{JobState.preprocessing,JobState.canceled,JobState.failed},
 JobState.preprocessing:{JobState.extracting,JobState.failed,JobState.canceled},
 JobState.extracting:{JobState.validating,JobState.failed,JobState.canceled},
 JobState.validating:{JobState.completed,JobState.review_required,JobState.failed,JobState.canceled},
 JobState.review_required:{JobState.completed,JobState.failed,JobState.canceled},
}
class JobCreate(BaseModel): document_ref:str=Field(min_length=1); document_type:str=Field(default="generic_document",min_length=1)
class Transition(BaseModel): state:JobState; reason:str|None=None
class Job(BaseModel):
 job_id:str; operation_id:str; tenant_id:str; correlation_id:str; state:JobState; document_ref:str; document_type:str; failure_reason:str|None=None
class ErrorEnvelope(BaseModel): code:str; message:str; retryable:bool=False; correlation_id:str|None=None

app=FastAPI(title="Codestra Document Intelligence",version="0.2.0")
_jobs:dict[str,Job]={}; _idem:dict[tuple[str,str],str]={}

def trusted_context(tenant:str|None,correlation:str|None):
 if not tenant or not correlation: raise HTTPException(401,"trusted tenant and correlation context required")
 return tenant,correlation

def owned(job_id,tenant):
 j=_jobs.get(job_id)
 if not j or j.tenant_id!=tenant: raise HTTPException(404,"job not found")
 return j

@app.get("/healthz")
def health(): return {"status":"ok"}
@app.get("/readyz")
def ready(): return {"status":"ready"}
@app.post("/v1/jobs",response_model=Job,status_code=status.HTTP_202_ACCEPTED)
def create_job(body:JobCreate,x_tenant_id:str|None=Header(None),x_correlation_id:str|None=Header(None),idempotency_key:str|None=Header(None)):
 tenant,corr=trusted_context(x_tenant_id,x_correlation_id)
 if not idempotency_key: raise HTTPException(400,"idempotency-key required")
 key=(tenant,idempotency_key)
 if key in _idem: return _jobs[_idem[key]]
 jid=str(uuid4()); j=Job(job_id=jid,operation_id=str(uuid4()),tenant_id=tenant,correlation_id=corr,state=JobState.queued,document_ref=body.document_ref,document_type=body.document_type)
 _jobs[jid]=j; _idem[key]=jid; return j
@app.get("/v1/jobs/{job_id}",response_model=Job)
def get_job(job_id:str,x_tenant_id:str|None=Header(None),x_correlation_id:str|None=Header(None)):
 tenant,_=trusted_context(x_tenant_id,x_correlation_id); return owned(job_id,tenant)
@app.post("/v1/jobs/{job_id}/transitions",response_model=Job)
def transition(job_id:str,body:Transition,x_tenant_id:str|None=Header(None),x_correlation_id:str|None=Header(None)):
 tenant,_=trusted_context(x_tenant_id,x_correlation_id); j=owned(job_id,tenant)
 if body.state not in TRANSITIONS.get(j.state,set()): raise HTTPException(409,f"invalid transition {j.state}->{body.state}")
 j.state=body.state
 if body.state==JobState.failed: j.failure_reason=body.reason or "unspecified_failure"
 return j
@app.get("/v1/operations/{operation_id}",response_model=Job)
def operation(operation_id:str,x_tenant_id:str|None=Header(None),x_correlation_id:str|None=Header(None)):
 tenant,_=trusted_context(x_tenant_id,x_correlation_id)
 for j in _jobs.values():
  if j.operation_id==operation_id and j.tenant_id==tenant:return j
 raise HTTPException(404,"operation not found")
