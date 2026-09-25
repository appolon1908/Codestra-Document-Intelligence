from codestra_document_intelligence.store import MemoryStore
from codestra_document_intelligence.middleware import MiddlewareContext
def test_store_contract():
 s=MemoryStore(); x=type("J",(),{"job_id":"j","tenant_id":"t","operation_id":"o"})(); s.put_job(x); assert s.get_job("j") is x
def test_middleware_headers(): assert MiddlewareContext("t","c","o").headers()["x-operation-id"]=="o"

def test_idempotency_and_operation_index():
 from types import SimpleNamespace
 s=MemoryStore(); j=SimpleNamespace(job_id="j",tenant_id="t",operation_id="o"); s.put_job(j)
 assert s.claim_idempotency("t","k","j") and not s.claim_idempotency("t","k","other")
 assert s.get_idempotent_job("t","k") is j and s.get_by_operation("o","t") is j and s.get_by_operation("o","x") is None
