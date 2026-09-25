from typing import Protocol
class Store(Protocol):
 def put_job(self,job): ...
 def get_job(self,job_id,tenant_id=None): ...
 def get_by_operation(self,operation_id,tenant_id): ...
 def claim_idempotency(self,tenant_id,key,job_id): ...
 def get_idempotent_job(self,tenant_id,key): ...
 def put_result(self,job_id,result): ...
 def get_result(self,job_id): ...
class MemoryStore:
 def __init__(self): self.jobs={}; self.results={}; self.idempotency={}; self.operations={}
 def put_job(self,job): self.jobs[job.job_id]=job; self.operations[(job.tenant_id,job.operation_id)]=job.job_id
 def get_job(self,job_id,tenant_id=None):
  j=self.jobs.get(job_id); return j if j and (tenant_id is None or j.tenant_id==tenant_id) else None
 def get_by_operation(self,operation_id,tenant_id):
  jid=self.operations.get((tenant_id,operation_id)); return self.jobs.get(jid) if jid else None
 def claim_idempotency(self,tenant_id,key,job_id):
  k=(tenant_id,key)
  if k in self.idempotency:return False
  self.idempotency[k]=job_id; return True
 def get_idempotent_job(self,tenant_id,key):
  jid=self.idempotency.get((tenant_id,key)); return self.jobs.get(jid) if jid else None
 def put_result(self,job_id,result): self.results[job_id]=result
 def get_result(self,job_id): return self.results.get(job_id)
