from dataclasses import dataclass
@dataclass(frozen=True)
class MiddlewareContext:
 tenant_id:str; correlation_id:str; operation_id:str|None=None
 def headers(self):
  h={"x-tenant-id":self.tenant_id,"x-correlation-id":self.correlation_id}
  if self.operation_id:h["x-operation-id"]=self.operation_id
  return h
