from codestra_document_intelligence.store import MemoryStore
from codestra_document_intelligence.middleware import MiddlewareContext
def test_store_contract():
 s=MemoryStore(); x=type("J",(),{"job_id":"j"})(); s.put_job(x); assert s.get_job("j") is x
def test_middleware_headers(): assert MiddlewareContext("t","c","o").headers()["x-operation-id"]=="o"
